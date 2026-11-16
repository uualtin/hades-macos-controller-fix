import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hades_controller_fix as fix


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "Game.macOS.app"
        self.backups = self.root / "backups"
        self.framework = self.app / fix.FRAMEWORK
        self.make_framework(self.framework, "2.0.15", b"original SDL")
        (self.app / fix.EXECUTABLE).write_bytes(b"original executable and embedded signature")
        (self.app / fix.EXECUTABLE).chmod(0o755)
        (self.app / fix.PLIST).write_bytes(plistlib.dumps({
            "CFBundleExecutable": "Game.macOS", "CFBundleName": "Hades",
            "GCSupportedGameControllers": [{"ProfileName": "ExistingProfile"}],
        }))
        (self.app / fix.SIGNATURE).mkdir()
        (self.app / fix.SIGNATURE / "CodeResources").write_bytes(b"original outer signature")
        self.before = {str(p): fix.tree_digest(self.app / p) for p in fix.COMPONENTS}

    @staticmethod
    def make_framework(path, version, binary):
        resources = path / "Versions/A/Resources"
        resources.mkdir(parents=True)
        (resources / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleShortVersionString": version,
        }))
        (path / "Versions/A/SDL2").write_bytes(binary)
        (path / "Versions/A/SDL2").chmod(0o755)
        (path / "Versions/Current").symlink_to("A")
        (path / "SDL2").symlink_to("Versions/Current/SDL2")

    def assert_original(self):
        self.assertEqual(
            {str(p): fix.tree_digest(self.app / p) for p in fix.COMPONENTS}, self.before
        )

    def mutate_like_install(self):
        (self.app / fix.EXECUTABLE).write_bytes(b"locally re-signed executable")
        (self.app / fix.SIGNATURE / "CodeResources").write_bytes(b"new signature")

    def successful_backup(self):
        backup, data = fix.create_backup(self.app, self.backups)
        self.mutate_like_install()
        data["state"] = "installed"
        data["installed"] = {str(p): fix.tree_digest(self.app / p) for p in fix.COMPONENTS}
        fix.save_manifest(backup, data)
        return backup

    def test_backup_and_restore_preserve_original_bytes_permissions_and_symlinks(self):
        backup = self.successful_backup()
        self.assertTrue((backup / "original" / fix.FRAMEWORK / "SDL2").is_symlink())
        self.assertEqual(os.readlink(backup / "original" / fix.FRAMEWORK / "SDL2"),
                         "Versions/Current/SDL2")
        with patch.object(fix, "ensure_game_closed"):
            fix.restore(backup)
        self.assert_original()
        self.assertEqual(json.loads((backup / "manifest.json").read_text())["state"], "restored")

    def test_restore_refuses_to_overwrite_a_later_game_update(self):
        backup = self.successful_backup()
        executable = self.app / fix.EXECUTABLE
        executable.write_bytes(b"a newer game update")
        with patch.object(fix, "ensure_game_closed"), self.assertRaisesRegex(fix.FixError, "changed"):
            fix.restore(backup)
        self.assertEqual(executable.read_bytes(), b"a newer game update")

    def test_explicit_allow_changed_restores_older_components(self):
        backup = self.successful_backup()
        (self.app / fix.EXECUTABLE).write_bytes(b"updated later")
        with patch.object(fix, "ensure_game_closed"):
            fix.restore(backup, allow_changed=True)
        self.assert_original()

    def test_corrupted_backup_is_rejected_before_any_restoration(self):
        backup = self.successful_backup()
        (backup / "original" / fix.EXECUTABLE).write_bytes(b"corrupted backup")
        changed = fix.tree_digest(self.app / fix.EXECUTABLE)
        with self.assertRaisesRegex(fix.FixError, "Backup verification failed"):
            fix.restore(backup)
        self.assertEqual(fix.tree_digest(self.app / fix.EXECUTABLE), changed)

    def test_backup_inside_game_is_rejected(self):
        with self.assertRaisesRegex(fix.FixError, "outside"):
            fix.create_backup(self.app, self.app / "backup")
        self.assert_original()

    def test_dry_run_does_not_download_or_back_up(self):
        with patch.object(fix, "validate_app"), patch.object(fix, "download_dmg") as download:
            fix.install(self.app, self.backups, None, dry_run=True)
        download.assert_not_called()
        self.assertFalse(self.backups.exists())
        self.assert_original()

    def test_failed_signing_rolls_back_all_changed_components(self):
        replacement = self.root / "replacement/SDL2.framework"
        self.make_framework(replacement, fix.SDL_VERSION, b"new SDL")
        result = subprocess.CompletedProcess([], 0, "", "Signature=adhoc\nIdentifier=test.hades\n")
        with patch.object(fix, "validate_app"), patch.object(fix, "ensure_game_closed"), \
                patch.object(fix, "verify_dmg"), \
                patch.object(fix, "mounted_framework") as mounted, \
                patch.object(fix, "run", return_value=result) as runner:
            mounted.return_value.__enter__.return_value = replacement

            def fail_after_signing(*args):
                if "--force" in args:
                    self.mutate_like_install()
                    raise fix.FixError("simulated signing failure")
                return result

            runner.side_effect = fail_after_signing
            with self.assertRaisesRegex(fix.FixError, "simulated"):
                fix.install(self.app, self.backups, self.root / "official.dmg")
        self.assert_original()
        manifest = next(self.backups.glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest.read_text())["state"], "rolled-back")

    def test_successful_install_can_be_restored_and_preserves_existing_profiles(self):
        replacement = self.root / "replacement/SDL2.framework"
        self.make_framework(replacement, fix.SDL_VERSION, b"new SDL")
        result = subprocess.CompletedProcess([], 0, "", "Signature=adhoc\nIdentifier=test.hades\n")

        def sign(*args):
            if "--force" in args:
                self.mutate_like_install()
            return result

        with patch.object(fix, "validate_app"), patch.object(fix, "ensure_game_closed"), \
                patch.object(fix, "verify_dmg"), patch.object(fix, "run", side_effect=sign), \
                patch.object(fix, "mounted_framework") as mounted:
            mounted.return_value.__enter__.return_value = replacement
            fix.install(self.app, self.backups, self.root / "official.dmg")
        self.assertEqual(fix.framework_version(self.app), fix.SDL_VERSION)
        info = fix.read_plist(self.app / fix.PLIST)
        self.assertEqual(info["CFBundleName"], "Hades")
        self.assertEqual(info["CFBundleIdentifier"], "test.hades")
        self.assertEqual(info["GCSupportedGameControllers"], [
            {"ProfileName": "ExistingProfile"}, {"ProfileName": "ExtendedGamepad"},
        ])
        backup = next(self.backups.iterdir())
        with patch.object(fix, "ensure_game_closed"):
            fix.restore(backup)
        self.assert_original()

    def test_wrong_download_checksum_is_rejected(self):
        dmg = self.root / "wrong.dmg"
        dmg.write_bytes(b"not the official image")
        with self.assertRaisesRegex(fix.FixError, "checksum"):
            fix.verify_dmg(dmg)

    def test_game_running_check_includes_stuck_exit_processes(self):
        for name in ("/some/path/Game.macOS", "(Game.macOS)"):
            with self.subTest(name=name), patch.object(fix, "run", return_value=
                    subprocess.CompletedProcess([], 0, name + "\n", "")), \
                    self.assertRaisesRegex(fix.FixError, "Quit Hades"):
                fix.ensure_game_closed()

    def test_reinstall_does_not_replace_the_original_backup_with_patched_files(self):
        info = self.framework / "Versions/A/Resources/Info.plist"
        info.write_bytes(plistlib.dumps({"CFBundleShortVersionString": fix.SDL_VERSION}))
        app_info = fix.read_plist(self.app / fix.PLIST)
        app_info.update({
            "CFBundleIdentifier": "test.hades",
            "GCSupportedGameControllers": [{"ProfileName": "ExtendedGamepad"}],
            "GCSupportsControllerUserInteraction": True,
        })
        (self.app / fix.PLIST).write_bytes(plistlib.dumps(app_info))
        with patch.object(fix, "validate_app"), patch.object(fix, "create_backup") as backup:
            fix.install(self.app, self.backups, None)
        backup.assert_not_called()

    def test_future_game_update_is_not_downgraded(self):
        info = self.framework / "Versions/A/Resources/Info.plist"
        info.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "2.32.12"}))
        with patch.object(fix, "validate_app"), self.assertRaisesRegex(fix.FixError, "downgrade"):
            fix.install(self.app, self.backups, None)
        self.assertFalse(self.backups.exists())

    def test_restore_rejects_parent_symlink_outside_application(self):
        backup = self.successful_backup()
        original_contents = self.app / "Contents"
        external = self.root / "external"
        original_contents.rename(external)
        original_contents.symlink_to(external)
        with self.assertRaisesRegex(fix.FixError, "outside Hades"):
            fix.restore(backup)
        self.assertTrue((external / "MacOS/Game.macOS").exists())


if __name__ == "__main__":
    unittest.main()
