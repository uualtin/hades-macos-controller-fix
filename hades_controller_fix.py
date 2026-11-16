#!/usr/bin/env python3
"""Back up and update the SDL framework in the Steam macOS build of Hades."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

SDL_VERSION = "2.32.10"
SDL_URL = (
    "https://github.com/libsdl-org/SDL/releases/download/"
    f"release-{SDL_VERSION}/SDL2-{SDL_VERSION}.dmg"
)
SDL_SHA256 = "4a7ac31640d70214e848f994be8a12849c0f97918a7e6c2e27a40036166d1a7f"
DEFAULT_APP = Path.home() / (
    "Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app"
)
DEFAULT_BACKUPS = Path.home() / "Library/Application Support/HadesControllerFix/backups"
FRAMEWORK = Path("Contents/MacOS/SDL2.framework")
PLIST = Path("Contents/Info.plist")
EXECUTABLE = Path("Contents/MacOS/Game.macOS")
SIGNATURE = Path("Contents/_CodeSignature")
COMPONENTS = (FRAMEWORK, PLIST, EXECUTABLE, SIGNATURE)
LAUNCH_OPTIONS = "/UseNativeGaInput=false /UseNativeGaInputNoControllers=false"


class FixError(Exception):
    """An expected problem that should be explained without a traceback."""


def run(*args):
    result = subprocess.run(
        [str(a) for a in args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FixError(f"{args[0]} failed: {detail}")
    return result


def read_plist(path):
    with path.open("rb") as stream:
        return plistlib.load(stream)


def framework_version(app):
    path = app / FRAMEWORK / "Versions/A/Resources/Info.plist"
    return read_plist(path).get("CFBundleShortVersionString", "unknown")


def validate_app(app):
    if app.name != "Game.macOS.app":
        raise FixError("Select the Game.macOS.app bundle inside the Hades installation.")
    if app.is_symlink():
        raise FixError("Pass the real Game.macOS.app path, rather than a symlink.")
    if not all((app / part).exists() for part in COMPONENTS):
        raise FixError("This is not the expected signed Hades macOS application layout.")
    if read_plist(app / PLIST).get("CFBundleExecutable") != "Game.macOS":
        raise FixError("The selected application does not identify itself as Game.macOS.")
    # Do not follow an unexpected link outside the selected game application.
    for part in COMPONENTS:
        try:
            (app / part).resolve().relative_to(app.resolve())
        except ValueError as exc:
            raise FixError(f"Unexpected link outside the game: {part}") from exc
    if "x86_64" not in run("/usr/bin/file", "-b", app / EXECUTABLE).stdout:
        raise FixError("This tool targets the Intel macOS build of Hades.")


def ensure_game_closed():
    names = run("/bin/ps", "-axo", "comm=").stdout.splitlines()
    if any(Path(name.strip()).name in {"Game.macOS", "(Game.macOS)"} for name in names):
        raise FixError("Quit Hades completely before installing or restoring.")


def verify_dmg(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SDL_SHA256:
        raise FixError("SDL download checksum does not match the pinned official release.")


def download_dmg(path):
    print(f"Downloading official SDL {SDL_VERSION}...")
    request = urllib.request.Request(SDL_URL, headers={"User-Agent": "HadesControllerFix/1.0"})
    with urllib.request.urlopen(request, timeout=60) as source, path.open("wb") as dest:
        shutil.copyfileobj(source, dest)
    verify_dmg(path)


@contextmanager
def mounted_framework(dmg, workspace):
    mount = workspace / "mounted-sdl"
    mount.mkdir()
    run("/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, dmg)
    try:
        framework = mount / "SDL2.framework"
        version = read_plist(framework / "Versions/A/Resources/Info.plist")
        if version.get("CFBundleShortVersionString") != SDL_VERSION:
            raise FixError("The disk image contains an unexpected SDL version.")
        if "x86_64" not in run(
            "/usr/bin/file", "-b", framework / "Versions/A/SDL2"
        ).stdout:
            raise FixError("The replacement SDL framework has no Intel architecture.")
        yield framework
    finally:
        run("/usr/bin/hdiutil", "detach", mount)


def copy_component(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)


def remove_component(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def tree_digest(root):
    """Fingerprint names, contents, symlink targets, and permission bits."""
    digest = hashlib.sha256()
    entries = [root] + (sorted(root.rglob("*")) if root.is_dir() else [])
    for item in entries:
        relative = "." if item == root else item.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0")
        digest.update(str(item.lstat().st_mode & 0o7777).encode() + b"\0")
        if item.is_symlink():
            digest.update(b"link\0" + os.readlink(item).encode() + b"\0")
        elif item.is_file():
            digest.update(b"file\0")
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"dir\0")
    return digest.hexdigest()


def save_manifest(backup, data):
    temp = backup / "manifest.json.tmp"
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(backup / "manifest.json")


def create_backup(app, backup_root):
    # A sibling/outside backup survives replacing the framework and re-signing the app.
    try:
        backup_root.resolve().relative_to(app.resolve())
    except ValueError:
        pass
    else:
        raise FixError("The backup directory must be outside the Hades application.")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(
        prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=backup_root
    ))
    for part in COMPONENTS:
        copy_component(app / part, backup / "original" / part)
    original = {str(p): tree_digest(backup / "original" / p) for p in COMPONENTS}
    for part in COMPONENTS:
        if tree_digest(app / part) != original[str(part)]:
            raise FixError("A game file changed while creating the backup. Nothing was installed.")
    data = {
        "format": 1, "app": str(app.resolve()), "state": "backed-up",
        "original_sdl": framework_version(app), "replacement_sdl": SDL_VERSION,
        "original": original,
    }
    save_manifest(backup, data)
    return backup, data


def load_backup(backup):
    data = json.loads((backup / "manifest.json").read_text())
    expected = {str(part) for part in COMPONENTS}
    if data.get("format") != 1 or set(data.get("original", {})) != expected:
        raise FixError("Unrecognized or incomplete backup manifest.")
    app = Path(data["app"])
    if not app.is_absolute() or app.name != "Game.macOS.app" or app.is_symlink():
        raise FixError("The backup does not point to an expected Hades application.")
    try:
        backup.resolve().relative_to(app.resolve())
    except ValueError:
        pass
    else:
        raise FixError("The backup must be outside the game application.")
    for part in COMPONENTS:
        if tree_digest(backup / "original" / part) != data["original"][str(part)]:
            raise FixError(f"Backup verification failed for {part}. No files were restored.")
        try:
            (app / part).parent.resolve().relative_to(app.resolve())
        except ValueError as exc:
            raise FixError("Unexpected destination link outside Hades.") from exc
    return app, data


def restore_components(app, backup):
    for part in COMPONENTS:
        remove_component(app / part)
        copy_component(backup / "original" / part, app / part)


def patch_app(app, replacement, identifier):
    remove_component(app / FRAMEWORK)
    copy_component(replacement, app / FRAMEWORK)
    data = read_plist(app / PLIST)
    data.setdefault("CFBundleIdentifier", identifier)
    profiles = data.setdefault("GCSupportedGameControllers", [])
    if not any(p.get("ProfileName") == "ExtendedGamepad" for p in profiles):
        profiles.append({"ProfileName": "ExtendedGamepad"})
    data["GCSupportsControllerUserInteraction"] = True
    (app / PLIST).write_bytes(plistlib.dumps(data))
    # The tested game has an ad-hoc signature. Only re-sign the outer app;
    # keep the official replacement framework's nested signature intact.
    run("/usr/bin/codesign", "--force", "--sign", "-", "--identifier", identifier, app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)


def install(app, backup_root, dmg, dry_run=False):
    validate_app(app)
    current = framework_version(app)
    info = read_plist(app / PLIST)
    declared = any(p.get("ProfileName") == "ExtendedGamepad"
                   for p in info.get("GCSupportedGameControllers", []))
    if (current == SDL_VERSION and declared and info.get("CFBundleIdentifier")
            and info.get("GCSupportsControllerUserInteraction") is True):
        print(f"SDL {SDL_VERSION} and controller declarations are already installed. Check the Steam settings in README.md.")
        return
    try:
        newer = tuple(map(int, current.split("."))) > tuple(map(int, SDL_VERSION.split(".")))
    except ValueError as exc:
        raise FixError("Cannot identify the existing SDL version. Nothing was changed.") from exc
    if newer:
        raise FixError("The game already has a newer SDL version. Refusing to downgrade it.")
    if dry_run:
        print(f"Would update: {app}")
        print(f"Current SDL: {framework_version(app)}; replacement: {SDL_VERSION}")
        print(f"Backups: {backup_root}")
        print("No files changed; nothing downloaded.")
        return
    ensure_game_closed()
    signature = run("/usr/bin/codesign", "-dv", "--verbose=2", app).stderr
    if "Signature=adhoc" not in signature:
        raise FixError("This installer only modifies the tested ad-hoc-signed Steam build.")
    match = re.search(r"^Identifier=(.+)$", signature, re.MULTILINE)
    if not match:
        raise FixError("Could not read the game's signing identifier.")
    with tempfile.TemporaryDirectory(prefix="hades-controller-fix-") as temporary:
        workspace = Path(temporary)
        image = dmg if dmg else workspace / f"SDL2-{SDL_VERSION}.dmg"
        if dmg:
            verify_dmg(image)
        else:
            download_dmg(image)
        with mounted_framework(image, workspace) as replacement:
            ensure_game_closed()
            backup, data = create_backup(app, backup_root)
            print(f"Verified backup: {backup}", flush=True)
            ensure_game_closed()
            data["state"] = "installing"
            save_manifest(backup, data)
            try:
                patch_app(app, replacement, match.group(1))
                data["installed"] = {str(p): tree_digest(app / p) for p in COMPONENTS}
                data["state"] = "installed"
                save_manifest(backup, data)
            except BaseException:
                print("Installation did not finish. Restoring the backed-up components...", file=sys.stderr)
                restore_components(app, backup)
                data["state"] = "rolled-back"
                save_manifest(backup, data)
                raise
    print("Installed. Finish these two settings in Steam → Hades → Properties:")
    print("  Controller: Disable Steam Input")
    print(f"  General → Launch Options: {LAUNCH_OPTIONS}")
    print("For F710, leave the physical switch in D mode before launching Hades.")
    print(f'Undo: python3 hades_controller_fix.py restore "{backup}"')


def restore(backup, allow_changed=False, dry_run=False):
    app, data = load_backup(backup)
    if data["state"] in {"restored", "rolled-back"}:
        print("This backup has already been restored.")
        return
    if not dry_run:
        ensure_game_closed()
    installed = data.get("installed", {})
    if not allow_changed:
        if not installed:
            raise FixError("Interrupted install: inspect the backup, then use --allow-changed if needed.")
        for part in COMPONENTS:
            if tree_digest(app / part) != installed.get(str(part)):
                raise FixError(
                    "Hades changed since installation, possibly after an update. "
                    "Use Steam's file verification, or --allow-changed to restore the older components."
                )
    if dry_run:
        print(f"Would restore verified components from {backup} to {app}. No files changed.")
        return
    restore_components(app, backup)
    for part in COMPONENTS:
        if tree_digest(app / part) != data["original"][str(part)]:
            raise FixError(f"Restored file verification failed: {part}")
    data["state"] = "restored"
    save_manifest(backup, data)
    print("Original application components restored. Undo the two Steam settings manually if desired.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "install"):
        sub = commands.add_parser(command)
        sub.add_argument("--app", type=Path, default=DEFAULT_APP)
        if command == "install":
            sub.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUPS)
            sub.add_argument("--dmg", type=Path, help="Use a local copy of the pinned official DMG")
            sub.add_argument("--dry-run", action="store_true")
    undo = commands.add_parser("restore")
    undo.add_argument("backup", type=Path)
    undo.add_argument("--allow-changed", action="store_true", help="Restore even if a game update changed these components")
    undo.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if platform.system() != "Darwin":
            raise FixError("This tool is for macOS only.")
        if args.command == "inspect":
            app = args.app.expanduser().absolute()
            validate_app(app)
            print(f"Hades: {app}\nBundled SDL: {framework_version(app)}")
            print("Controller declaration:", read_plist(app / PLIST).get("GCSupportedGameControllers", []))
        elif args.command == "install":
            install(args.app.expanduser().absolute(), args.backup_root.expanduser().absolute(),
                    args.dmg.expanduser().absolute() if args.dmg else None, args.dry_run)
        else:
            restore(args.backup.expanduser().absolute(), args.allow_changed, args.dry_run)
    except (FixError, OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
