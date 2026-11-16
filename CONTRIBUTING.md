# Contributing

Reports from other setups are useful. Please distinguish a successful menu test from a successful gameplay test, and mention rumble separately.

Include your macOS version, Intel or Apple Silicon, Hades storefront, controller model, connection type, and the SDL version printed by `inspect`. A short relevant log excerpt is enough. Remove usernames and local paths; do not attach saves, account files, or game binaries.

For code changes, keep the installer dependency-free and preserve the ability to restore the original components. Add tests when changing backup, restore, download verification, or file handling. Never run a test that changes a contributor's real Hades installation.

```sh
python3 -m unittest discover -s tests -v
```

Please do not add untested controllers to the confirmed compatibility table or redistribute Hades/SDL binaries. SDL remains a separate download from its official release.
