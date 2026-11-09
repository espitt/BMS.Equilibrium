# Equilibrium

Desktop front end for battery management software, written in Python with Qt (PySide6).

## Installing

Download and run the setup program for your system from the latest GitHub Release. It fetches
the latest version of the app and installs it for your user account, with no admin rights needed.

| System  | Setup file                             | Installs to                          | To uninstall                  |
| ------- | -------------------------------------- | ------------------------------------ | ----------------------------- |
| Windows | `EquilibriumSetup-windows-x64.exe`     | `%LOCALAPPDATA%\Programs\Equilibrium`| Settings > Apps               |
| macOS   | `EquilibriumSetup-macos-arm64.zip`     | `~/Applications/Equilibrium.app`     | Move to Trash                 |
| Linux   | `EquilibriumSetup-linux-x64.tar.gz`    | `~/.local/share/Equilibrium`         | Run `uninstall` in that folder|

## Updates

A few seconds after opening, and from **Help > Check for Updates**, the app looks at the latest
release. If it is newer, the app asks before doing anything. Choosing **Install now** downloads the
setup program, closes the app, installs the update and reopens the app. If the update fails or is
cancelled, the previous version reopens.

## Project layout

- `app/equilibrium/`: the application (`updater.py` and `update_ui.py` handle updates;
  `personal.py` lists per-user splash images and startup sounds, kept in `assets/splash/`)
- `installer/equilibrium_setup/`: the setup wizard (standard library and `certifi` only, to stay small)
- `packaging/build.py`: builds release files with PyInstaller
- `.github/workflows/release.yml`: builds every platform and publishes the release
- `tests/`: installer logic tests

The install folder belongs to the installer and is replaced on update and deleted on uninstall.
**The app must keep user data and settings elsewhere**, for example in Qt's `QStandardPaths.AppDataLocation`.

## Development

Requires Python 3.12.

```
python -m venv .venv
.venv\Scripts\activate          (Windows)
source .venv/bin/activate       (macOS, Linux)
pip install -r requirements-build.txt

python -m unittest discover -s tests -v
```

## Publishing a release

Push a version tag. GitHub Actions tests and builds all three platforms, then publishes the release.

```
git tag v0.1.0
git push origin v0.1.0
```
