# Technical notes

## What we observed

The confirmed setup was an Apple Silicon Mac running macOS 26.5 with a Logitech F710 connected through its USB receiver in DirectInput (**D**) mode.

- macOS identified the physical device as **Logitech Cordless RumblePad 2**, USB VID `046d`, PID `c219`.
- Steam's interface accepted input, and Safari's Gamepad API worked. Brave did not detect it in the user's test; we did not investigate that browser issue after narrowing the task to Hades.
- A separate diagnostic received stick, D-pad, and button values through IOKit. Apple's GameController API also exposed an extended gamepad profile.
- Hades's original SDL library was version 2.0.15. A diagnostic using that library saw the raw joystick but reported that it had no controller mapping.
- Adding a device mapping and selecting Hades's SDL input path did not produce working controls in the game.
- After updating to the official SDL 2.32.10 framework and declaring controller support in the app, a diagnostic recognized a mapped controller through the GameController path. Hades then logged the controller being added, and the player confirmed working menus and gameplay.

This is enough to document the workaround. It does not identify a particular SDL commit as the root cause, prove that the metadata change alone is necessary, or demonstrate compatibility with every controller.

## The working combination

```text
Bundled framework: SDL 2.32.10 (official macOS runtime)
GCSupportedGameControllers: ExtendedGamepad
GCSupportsControllerUserInteraction: true
Steam Input override: Disabled for Hades
Launch options: /UseNativeGaInput=false /UseNativeGaInputNoControllers=false
F710 physical switch: D
```

The application remains Intel code running under Rosetta on Apple Silicon. This does not port Hades to ARM. The replacement framework includes the Intel slice the game needs.

## Scope of the installer

The installer changes four components: the SDL framework, `Info.plist`, the executable's embedded signature, and the outer `_CodeSignature` directory. It downloads the pinned official SDL disk image over HTTPS and compares it to a hard-coded SHA-256 before mounting it read-only.

It backs up the components it will replace, including the executable affected by re-signing, and fingerprints the backup. It keeps framework symlinks and preserves file permission bits. A failed patch triggers restoration. An interrupted process or a failed restoration may need the printed backup path or Steam's file verification.

It does not edit Steam configuration. Those files mix unrelated account and application settings, so the two Hades-specific choices stay explicit in the README. No save data, account tokens, diagnostic logs, game assets, or third-party binaries are shipped in this repository.

Only the original game's Intel macOS app layout and an ad-hoc-signed Steam build are accepted. This is not an installer for Hades II, Windows, CrossOver, consoles, or a system driver.

## Tradeoffs

- This changes the local game app. Steam updates and file verification can restore the older framework.
- Re-signing is local and ad-hoc. It does not create an Apple-notarized release.
- The tested GameController path did not expose a haptic device. Working controls do not imply working rumble.
- Restore checks the four modified components for later changes, rather than guaranteeing that every asset in the game is unchanged. After a Steam update, prefer file verification.
- The installer automates the file operations; the successful gameplay test was performed with the same underlying operations during troubleshooting. See the repository tests for automated coverage of backup, rollback, checksum, and restore behavior.
- Before publication, the installer was also exercised on a disposable macOS app fixture using the pinned disk image, real mounting and signing commands, signature verification after installation, and a byte-for-byte comparison after restoration. That check did not modify the working game installation.

## References

- [SDL 2.32.10 release](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10)
- [SDL macOS documentation](https://wiki.libsdl.org/SDL2/README-macos)
- [Apple: GCSupportedGameControllers](https://developer.apple.com/documentation/bundleresources/information-property-list/gcsupportedgamecontrollers)
- [Supergiant: Hades technical support](https://www.supergiantgames.com/faqs/hades/)
- [Zadera's related Steam Community fix](https://steamcommunity.com/app/1145360/discussions/1/585057730992118344/)
