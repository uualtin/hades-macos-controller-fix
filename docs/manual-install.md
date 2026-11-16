# Manual installation

Use this if you want to understand or perform the changes without the installer. The script is the easier option because it checks the download, verifies its backups, and can restore the exact components it changed.

## 1. Quit Hades

Do not modify the application while it is running. Steam can remain open for the file changes; you will change its Hades settings afterward.

## 2. Get the tested SDL release

Download **SDL2-2.32.10.dmg** from the [official 2.32.10 release](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10). Check the downloaded file:

```sh
shasum -a 256 "$HOME/Downloads/SDL2-2.32.10.dmg"
```

Expected SHA-256 for the disk image used by this project:

```text
4a7ac31640d70214e848f994be8a12849c0f97918a7e6c2e27a40036166d1a7f
```

This checksum pins the release asset tested here. It is not a separate vendor attestation. Do not substitute SDL 3 or a framework from an unrelated download site.

Open the disk image. It contains `SDL2.framework`.

## 3. Back up the original components

Locate `Game.macOS.app` in Hades's Steam installation folder. Choose **Show Package Contents** in Finder to inspect it.

Copy these items into a new backup folder **outside the app**, retaining their relative paths:

```text
Contents/MacOS/SDL2.framework
Contents/MacOS/Game.macOS
Contents/Info.plist
Contents/_CodeSignature
```

Keep the framework's symlinks intact. A whole-app backup is also an option if you have enough disk space. The game executable must be included because re-signing changes its embedded signature.

## 4. Replace SDL and update the app metadata

Replace `Contents/MacOS/SDL2.framework` with the framework from the disk image. Copy the entire framework, preserving its structure, rather than just its library file.

In `Contents/Info.plist`, preserve existing fields and add or merge:

```xml
<key>GCSupportedGameControllers</key>
<array>
    <dict>
        <key>ProfileName</key>
        <string>ExtendedGamepad</string>
    </dict>
</array>
<key>GCSupportsControllerUserInteraction</key>
<true/>
```

If `CFBundleIdentifier` is absent, use the existing code-signing identifier. You can read it with:

```sh
codesign -dv --verbose=2 "/full/path/to/Game.macOS.app"
```

Use the value after `Identifier=`. The automated tool preserves this value and any existing controller profiles.

## 5. Re-sign the outer application

The tested Steam build is ad-hoc signed. After modifying its framework and metadata, re-sign the outer app and verify it:

```sh
codesign --force --sign - --identifier "THE_EXISTING_IDENTIFIER" "/full/path/to/Game.macOS.app"
codesign --verify --deep --strict "/full/path/to/Game.macOS.app"
```

Replace both placeholders. The first command signs the outer app without recursively re-signing its nested libraries. The second verifies nested code too. The installer refuses to replace a developer-signed build, because that is outside the setup tested here.

Do not change macOS security settings or remove quarantine attributes globally.

## 6. Configure Steam and test

In **Hades → Properties → Controller**, choose **Disable Steam Input**. Set **General → Launch Options** to:

```text
/UseNativeGaInput=false /UseNativeGaInputNoControllers=false
```

For an F710, select **D** on its physical D/X switch before launching the game. Test menus and gameplay. Hades should log `Gamepad added` in:

```text
~/Library/Application Support/Supergiant Games/Hades/Hades.log
```

## Restore

Quit Hades and copy all four original components back to their exact locations. Do not re-sign the restored originals: the backed-up executable and `_CodeSignature` contain their original signatures. This assumes no other game files changed since the backup. After a game update, Steam's file verification is generally the better way to restore a consistent official installation.

Restore your previous Steam launch and controller settings separately if desired.
