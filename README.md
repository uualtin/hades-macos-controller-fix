# Hades macOS Controller Fix

My Logitech F710 worked in Steam's menus and in Safari, but Hades would not respond to it. At one point I could move around the menu, yet the face buttons still did nothing.

What finally worked was updating the SDL framework bundled with Hades, declaring GameController support in the app, and letting Hades use SDL input with Steam Input disabled. After that, the menus, sticks, and buttons worked in-game.

This repo packages that workaround into a small, reversible installer. It is an unofficial fix for **the original Hades on Steam for macOS**.

## What has actually been tested

| Setup | Result |
| --- | --- |
| Apple Silicon Mac, macOS 26.5, Logitech F710 in **D** mode, Steam edition of Hades | Menus and gameplay confirmed working by the player |
| Rumble on that setup | Hades reported no haptic device; vibration is not supported by this tested path |
| Other controllers, macOS versions, Intel Macs, or storefronts | Not tested by this project |

The game used SDL **2.0.15**. The working replacement is the official SDL **2.32.10** macOS framework. This is a pinned, tested version, not a request to install whichever SDL version is newest. **SDL 3 is not a drop-in replacement.**

## Before you start

- Quit Hades. Closing just its window may leave it running.
- You need Python **3.9 or newer** (`python3 --version`). If it is missing, install it from [python.org](https://www.python.org/downloads/macos/).
- Use your normal macOS account. The installer does not need `sudo` for a normal Steam library owned by you.
- The tool changes files inside the game app and replaces its ad-hoc code signature. A Steam update or **Verify integrity of game files** can undo the fix.

Your save files are outside the application and are not modified. The installer also leaves your Steam account files, controller profiles, browser settings, and system drivers alone.

## Install

### 1. Download this repo

Click **Code → Download ZIP** on this page, unzip it, then open Terminal and enter `cd ` with a trailing space. Drag the extracted folder into Terminal and press Return.

If you use Git, you can instead run:

```sh
git clone https://github.com/uualtin/hades-macos-controller-fix.git
cd hades-macos-controller-fix
```

### 2. Preview the change

```sh
python3 hades_controller_fix.py install --dry-run
```

This checks the expected game layout and prints the plan. It does not download or change anything.

The default installation location is:

```text
~/Library/Application Support/Steam/steamapps/common/Hades/Game.macOS.app
```

For another Steam library, use `--app` with the full path to `Game.macOS.app`, both for the preview and the install:

```sh
python3 hades_controller_fix.py install --dry-run --app "/Volumes/Games/SteamLibrary/steamapps/common/Hades/Game.macOS.app"
```

You can find the game folder through **Steam → Hades → Properties → Installed Files → Browse**.

### 3. Apply the fix

```sh
python3 hades_controller_fix.py install
```

The installer:

1. Downloads the pinned macOS disk image from the [official SDL release](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10) and checks its SHA-256.
2. Opens it read-only and checks the framework version and Intel architecture required by Hades.
3. Backs up the original framework, app metadata, game executable, and outer signature. It verifies the backup before changing the game.
4. Replaces the bundled framework and declares `ExtendedGamepad` support in `Info.plist`.
5. Re-signs the outer app locally and verifies it. The replacement framework keeps its own signature.

If installation fails after changes begin, it attempts to restore the backed-up components automatically. Keep the backup path printed by the tool even after a successful install.

The download is about 2 MB. Signing and verification may take a little while; let the command finish before opening the game.

### 4. Set these two options in Steam

Open **Hades → Properties**:

| Setting | Value |
| --- | --- |
| Controller → Override for Hades | **Disable Steam Input** |
| General → Launch Options | The line below |

```text
/UseNativeGaInput=false /UseNativeGaInputNoControllers=false
```

Replace previous controller troubleshooting launch options with this line. The installer intentionally leaves this step to you rather than editing Steam's account configuration.

### 5. Connect and test

For the Logitech F710, set the physical **D/X switch to D before launching Hades**. It normally appears on macOS as **Logitech Cordless RumblePad 2**. That name is expected.

Start the game through Steam. Try moving around the menu with the left stick, selecting with A, and going back with B. Then load a save and test movement, attacks, dash, and the shoulder buttons.

The F710's **MODE** button swaps the left stick and D-pad behavior. If they seem reversed, press MODE once; it is a different control from the D/X switch.

## Undo the fix

Quit Hades and run the restore command printed after installation:

```sh
python3 hades_controller_fix.py restore "/full/path/to/the/printed/backup"
```

Backups normally live in:

```text
~/Library/Application Support/HadesControllerFix/backups/
```

The restore command checks the backup before using it. It also checks whether the installed components have changed since the fix, so it will not silently overwrite a later game update. If that happens, use Steam's file verification to return to the current official game files. `restore --allow-changed` is available if you deliberately want to put back the older components from your backup.

The two Steam settings are manual, so restore their previous values yourself if needed. If the installer was interrupted or its backup is unavailable, **Steam → Hades → Properties → Installed Files → Verify integrity of game files** is the fallback for the official game files.

## Why this helped

The controller was sending input to macOS. The problem was in the game's older input stack: its original SDL framework could see the physical device in a separate test, but did not provide a usable controller setup in Hades. Adding a button mapping alone did not fix gameplay.

With SDL 2.32.10 and the app's controller declarations in place, Hades registered the controller through the newer GameController path. Its log then contained:

```text
InputSystemSDL Initialized
Gamepad added: Index = 1, Name = Logitech Cordless RumblePad 2, ...
```

The player then confirmed that the game worked correctly. These observations support an old-input-stack compatibility problem; we have not isolated a single upstream SDL bug or proven which individual change is sufficient on every machine.

You do not need a system-wide F710 driver for this workaround. It updates the copy of SDL inside Hades.

## If it still does not work

- Confirm the two Steam settings above, and restart Hades after changing them.
- Check the F710's D/X switch and reconnect the receiver before starting the game.
- Disconnect other controllers while testing.
- Run `python3 hades_controller_fix.py inspect` to check the installed SDL version.
- Look for `Gamepad added` in `~/Library/Application Support/Supergiant Games/Hades/Hades.log`.
- If the tool says the game is still running, quit it through its menu. If macOS has a stuck process that will not exit, restart the Mac before retrying.
- If you use `--dmg` and mounting reports that the image is busy, eject any copy of that SDL disk image already mounted in Finder, then retry.
- If the app fails to launch, restore the backup or verify the game files in Steam. Do not disable Gatekeeper or SIP to make this fix work.

If you open an issue, include your macOS version, Mac architecture, controller model, connection type, and whether menus and gameplay work. A few relevant log lines are enough; remove usernames and local paths. Do not upload saves, Steam account configuration, or the game app.

## More detail

- [Manual procedure](docs/manual-install.md)
- [Technical notes and limits](docs/technical-notes.md)
- [Contributing and reporting results](CONTRIBUTING.md)

To run the automated checks:

```sh
python3 -m unittest discover -s tests -v
```

## Credits and license

Thanks to the [SDL project](https://github.com/libsdl-org/SDL) for the actual input library. This installer and documentation are MIT licensed. SDL is distributed separately under its [own license](https://github.com/libsdl-org/SDL/blob/release-2.32.10/LICENSE.txt); no SDL or Hades binaries are included here.

Zadera's [Steam Community write-up for the Xbox Elite Series 2](https://steamcommunity.com/app/1145360/discussions/1/585057730992118344/) described the same framework update and app declaration approach. It helped guide the final working F710 fix documented here. This repo adds an installer with verified backups and rollback, and reports our own confirmed setup.

Also see [Supergiant's Hades troubleshooting guide](https://www.supergiantgames.com/faqs/hades/). This project is not affiliated with Supergiant Games, Valve, Logitech, or SDL.
