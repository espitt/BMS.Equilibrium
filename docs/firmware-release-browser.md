# Firmware release browser: handover and build plan

Status as of 9 Nov 2026. This file is for picking the work up on another PC, by hand or with
Claude Code. Point Claude at this file and say "carry on with the firmware release browser".

## Where the project is

Done (see "Before you switch" below for getting it onto the new PC):

- All nine screens from *Requirements for BMS software.docx*, running against a simulated BMS.
  Start screen -> pick **Simulated BMS** -> Connect.
- Light/dark theme. Clicking the logo (top left) toggles it; the choice is saved with QSettings.
  Light mode uses SUFST navy `#00366a`, dark mode the lighter logo blue `#3a86d4`.
  All colours live in `app/equilibrium/theme.py` (two palettes, `LIGHT` and `DARK`).
- 67 tests pass (`tests/test_bms.py` builds and paints every screen offscreen).

- Browsing firmware releases (9 Nov 2026), on the Settings screen's "BMS firmware" card. It lists
  every release in `sufst/BMS-Firmware` (`firmware.REPO`), newest first: version, date,
  "Pre-release" / "Installed" tags, and the description on the same line.
  Code: `app/equilibrium/firmware.py` (no GUI) and `ui/firmware_browser.py`; tests in
  `tests/test_firmware.py`. Changed from this plan:
  - No settings (step 1): the repo is fixed in code and public, so there is no repo field and no
    token, and pre-releases are always listed, tagged "Pre-release".
  - No manifest and no compatibility checks. The hardware, bootloader, protocol and settings schema
    stay the same from version to version, so every release suits the BMS and the browser needs
    only what GitHub says about a release (tag, date, notes, attached files).
- Downloading and programming, from the same card:
  - **Download firmware** saves every file attached to the selected release into
    `QStandardPaths.AppDataLocation/firmware/<tag>/` (on Windows `%APPDATA%\Equilibrium\firmware`)
    and tags it "Downloaded". Each file is checked against the SHA-256 that GitHub publishes for
    release assets (its `digest` field), or against its size for files uploaded before GitHub kept
    checksums. A damaged file is deleted.
  - **Program…** is enabled once the selected release is downloaded and a BMS is connected. It asks
    to confirm, calls `link.flash(files, version, on_progress, on_done)`, and **once programming
    succeeds, deletes the release's downloaded files**. If it fails, they are kept.
  - Only the simulator has `flash()` so far: it pretends (about 4 s, no data meanwhile, then
    reports the new version). A link without `flash()` shows "not available yet".
  - Not done from step 5: the pre-flight safety checks (TS off, not charging, no critical
    faults), the configuration backup, and re-applying the configuration afterwards. Add them before
    a real `SerialLink.flash` exists.

Not built yet, by choice: offline listing of downloaded firmware, and the firmware repo's workflow
(step 7).

Not done, and waiting on the firmware side:

- The real serial protocol (the plan agreed so far: COBS-framed binary packets with CRC-16 over
  the USB virtual COM port, one shared schema file that generates the C header and Python decoder).
- Flashing firmware onto the BMS (needs the bootloader protocol and the microcontroller choice).

Next job: **the firmware release browser** (this document).

## Setting up on the new PC

1. Install Python 3.12 (`winget install Python.Python.3.12 --scope user`) and git.
2. Clone and set up:
   ```
   git clone https://github.com/espitt/BMS.Equilibrium.git
   cd BMS.Equilibrium
   git checkout <the branch you pushed>
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-build.txt
   python -m unittest discover -s tests -v      (expect 67 tests, all OK)
   cd app && python -m equilibrium               (run the app)
   ```

## Before you switch (on the old PC)

Everything above was **uncommitted** when this was written. Commit and push it, or it stays on
the old PC:

```
git checkout -b feature/screens
git add -A
git commit -m "Add BMS screens, simulator, light/dark theme and firmware release plan"
git push -u origin feature/screens
```

`Requirements for BMS software.docx` is untracked too. Commit it or copy it across.

---

## What the release browser does

The firmware lives in its own GitHub repository. Pushing a version tag there runs GitHub Actions,
which builds the firmware and publishes a GitHub Release with a manifest attached. The app:

1. Lists the firmware releases from that repository, newest first, including older ones so you
   can roll back.
2. Shows each one's version, date and release notes, and whether it suits the connected BMS.
3. Downloads the chosen release, checks its SHA-256, and keeps a local copy so it can be flashed
   at the track with no internet.
4. Hands the verified file to the flasher. The flasher is a stub for now: the simulator pretends
   to flash, a real BMS shows "not available yet".

This mirrors how the app already updates itself (`installer/equilibrium_setup/core.py`:
`Release`, `_open`, `download`), so reuse that code rather than writing new download logic.

## Decisions still open (ask before or while building)

| Question | Why it matters | Default if unanswered |
|---|---|---|
| Firmware repo name | The app needs to know where to look | **Answered:** `sufst/BMS-Firmware`, fixed in `firmware.REPO` |
| Is that repo public or private? | Private repos need a read-only GitHub token | **Answered:** public, so the app sends no token |
| Microcontroller on the master board | Decides the bootloader (custom serial vs STM32 USB DFU) | Not needed for the browser itself |

Recommendation already given for the bootloader: a custom bootloader over the same USB serial
link, because it needs no driver installs on team laptops.

## The release manifest (contract with the firmware repo)

**Not used (9 Nov 2026).** Everything in it except the image details stays the same from version to
version, so the browser doesn't ask for it. Kept for when downloading and programming are built:
they will still need the image's file name, size and checksums, from a manifest or elsewhere.

The planned format, for reference: each firmware release would include `firmware-manifest.json`:

```json
{
  "format": 1,
  "version": "1.4.0",
  "commit": "a1b2c3d",
  "hardware": ["master-rev-c", "master-rev-d"],
  "min_bootloader": "1.1.0",
  "protocol": 3,
  "config_schema": 5,
  "image": {
    "file": "bms-1.4.0.bin",
    "size": 183296,
    "sha256": "<64 hex chars>",
    "crc32": "<8 hex chars>",
    "address": "0x08008000"
  }
}
```

- `hardware`, `min_bootloader`: used to block incompatible releases. A board name matches what the
  BMS reports as "Hardware" once lower-cased, with "board" dropped and spaces as dashes:
  "Master board rev C" is `master-rev-c`.
- `protocol`: if it differs from what the app speaks, warn that the app may need updating too.
- `config_schema`: if it differs from the BMS's current one, warn that settings will be converted.
- `sha256`: checked after download. `crc32`: for the bootloader's own end check later.

## Build steps

Work in this order. Each step ends in something testable.

### Step 1: settings for the repo and token

- In `app/equilibrium/bms/config.py` these are **app** preferences, not BMS settings, so do not add
  them to `SETTINGS` (that list is written to the BMS). Store them with
  `QSettings("SUFST", "Equilibrium")`, keys `firmware/repo` and `firmware/prereleases`.
- Token (only if the repo is private): store it with the `keyring` package
  (`keyring.set_password("Equilibrium", "github-firmware", token)`), never in QSettings or a file.
  Add `keyring` to `requirements-build.txt`. Use a fine-grained token with read-only
  "Contents" access to the firmware repo only.
- UI: in the "BMS firmware" card on the Settings screen (`ui/screens/settings.py`), add a repo
  field, a "Show pre-releases" checkbox, and a "Set GitHub token…" button.

### Step 2: `app/equilibrium/firmware.py` (no GUI code, like `updater.py`)

```python
@dataclass(frozen=True)
class FirmwareRelease:
    version: str
    tag: str
    published: datetime
    prerelease: bool
    notes: str            # release body, markdown
    manifest: dict
    image: core.Release   # url, sha256, size, so core.download() works unchanged

def list_releases(repo: str, token: str | None, include_prereleases: bool) -> list[FirmwareRelease]
def compatibility(release, device: dict) -> list[str]   # reasons it is NOT compatible; [] = fine
def cached_path(release) -> Path | None                  # already downloaded and still verifies
def download(release, on_progress, cancel) -> Path       # into the cache, via core.download
def cached_releases() -> list[FirmwareRelease]           # for offline use
```

Details:

- Releases: `GET https://api.github.com/repos/{repo}/releases?per_page=30` with headers
  `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, and
  `Authorization: Bearer <token>` when there is one. Reuse `core._ssl_context()` (certifi) so it
  works in the frozen build.
- For each release, find the asset named `firmware-manifest.json`. Public repo: fetch its
  `browser_download_url`. Private repo: fetch the asset's API `url` with
  `Accept: application/octet-stream` and the token (the browser URL does not take a token).
  The image file is downloaded the same way.
- Skip releases with no manifest, or one that fails to parse, but log them; don't crash the list.
- Cache folder: `QStandardPaths.AppDataLocation / "firmware" / <version>/`, holding the image and
  the manifest. Not the install folder: the installer replaces that on every app update.
- `cached_path` re-hashes the file before trusting it.
- Errors: raise `core.InstallError` with a user-facing message (no internet, 404 = wrong repo name
  or no access, 401/403 = bad or missing token, rate limit = "try again in N minutes" from the
  `X-RateLimit-Reset` header).

### Step 3: run it off the GUI thread

Copy the pattern in `app/equilibrium/update_ui.py`: a `QObject` with private signals, a
`threading.Thread(daemon=True)` worker, and results passed back to the GUI thread via signals.
Never call the network from a slot directly; the screens refresh at 5 Hz and would freeze.

### Step 4: the browser UI

Replace the placeholder in `SettingsScreen._check_releases` and `_program`
(`app/equilibrium/ui/screens/settings.py`):

- Release list: version, date, "pre-release" tag, "downloaded" tag, and a compatibility badge
  (green "Compatible", red "Not for this board", amber "Needs bootloader 1.2+"). Use the colour
  tokens in `theme.py`; colour means state, so don't introduce new colours.
- Selecting a release shows its notes beneath the list.
- Buttons: "Check for releases" (refresh), "Download", "Program…". Program is enabled only for a
  compatible, downloaded release with a BMS connected.
- When offline, show the cached releases with a note "Offline: showing downloaded firmware".
- Currently installed firmware comes from `ctx.data.device["Firmware"]` (the simulator fills it).
  Mark the matching release "Installed".
- The release list in the UI must restyle on theme change: connect to `theme.signals.changed`
  like the other screens do (see `Screen.restyle`).

### Step 5: programming dialog (with a simulated flash)

A dialog that walks through the steps and shows each as a tick or cross:

1. Pre-flight: tractive system off (`ams.state` not Drive/Precharge), not charging, no critical
   faults, release compatible.
2. Back up the config (for now: save `ctx.config` to the cache folder as JSON).
3. Enter bootloader, send image (progress bar), verify, reboot.
4. Confirm the reported firmware version matches.
5. Offer to re-apply the backed-up config.

Add a `flash(path, on_progress)` method to the link interface. `Simulator.flash` fakes it with a
timer (progress over ~5 s, then sets `data.device["Firmware"]` to the new version). A future
`SerialLink.flash` does the real thing. The dialog must not care which link it has.

### Step 6: tests (`tests/test_firmware.py`)

Follow `tests/test_updates.py`, which runs a local HTTP server in place of GitHub:

- Listing parses releases, skips ones without a manifest, hides pre-releases unless asked.
- 401/404/no network give the right `InstallError` messages.
- Download verifies SHA-256 and lands in the cache; a corrupted file is rejected and removed.
- `compatibility()` blocks wrong hardware and old bootloaders.
- Cached releases are listed when the network is down.
- The Settings screen builds with releases loaded (extend `ScreenTests`).

Done when: all tests pass, and with a test repo you can list, download, and "program" via the
simulator, then see the new version on the Dashboard device panel.

### Step 7 (separate, in the firmware repo): the GitHub Actions workflow

`.github/workflows/release.yml` in the firmware repo, triggered by tags `v*.*.*`:

1. Check out, install `gcc-arm-none-eabi` and CMake.
2. Build with the version from the tag passed in (e.g. `-DFW_VERSION=${GITHUB_REF_NAME#v}`) so
   the BMS reports it.
3. Run the firmware unit tests.
4. A small script writes `firmware-manifest.json` (size, sha256, crc32 of the `.bin`; hardware
   list and versions from a checked-in `release.json`).
5. `gh release create "$GITHUB_REF_NAME" bms-*.bin bms-*.elf firmware-manifest.json --notes-from-tag`,
   adding `--prerelease` when the tag contains `-` (e.g. `v1.5.0-rc1`).

The app's own `.github/workflows/release.yml` is a working example of the build-then-publish shape.
