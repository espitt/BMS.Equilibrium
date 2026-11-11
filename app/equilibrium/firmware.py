"""BMS firmware releases: list the ones published on GitHub, and download their files. No GUI code.

Every release suits the BMS: the hardware, bootloader, protocol and settings format stay the same
from version to version, so a release needs nothing beyond what GitHub already says about it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import math
import os
import re
import shutil
import sys
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QStandardPaths

try:
    from equilibrium_setup import core
except ImportError:  # A source run: the installer package sits beside the app rather than on the path.
    sys.path.append(str(Path(__file__).resolve().parents[2] / "installer"))
    from equilibrium_setup import core

log = logging.getLogger(__name__)

REPO = "espitt/BMS.Firmware"  # Public, so no GitHub token is needed
API_ROOT = "https://api.github.com"
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
PER_PAGE = 30

_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?")
_FILE_NAME = re.compile(r'[^./\\:*?"<>|][^/\\:*?"<>|]*')  # One file, never hidden and never a path
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class FirmwareFile:
    """A file attached to a release."""

    name: str
    url: str
    size: int
    sha256: Optional[str]  # GitHub's checksum. Files uploaded before GitHub kept checksums have none.


@dataclass(frozen=True)
class FirmwareRelease:
    version: str
    tag: str
    published: datetime
    prerelease: bool
    notes: str  # The release description, in Markdown
    files: tuple[FirmwareFile, ...] = ()


def parse_version(text: str) -> Optional[str]:
    """The first version number in text: "v0.4.2 (simulated)" gives "0.4.2"."""
    match = _VERSION.search(text or "")
    return match.group(0) if match else None


def installed_version(device: dict) -> Optional[str]:
    return parse_version(str(device.get("Firmware", "")))


# Listing

def _http_error(error: urllib.error.HTTPError, repo: str) -> core.InstallError:
    code = error.code
    headers = error.headers
    if code == 429 or (code == 403 and (headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After"))):
        wait = None
        try:
            if headers.get("Retry-After"):
                wait = float(headers["Retry-After"])
            elif headers.get("X-RateLimit-Reset"):
                wait = float(headers["X-RateLimit-Reset"]) - time.time()
        except ValueError:
            pass
        if wait is None:
            when = "Try again later."
        else:
            minutes = max(1, math.ceil(wait / 60))
            when = f"Try again in {minutes} minute{'s' if minutes != 1 else ''}."
        return core.InstallError(f"GitHub's limit on requests has been reached. {when}")
    if code == 404:
        return core.InstallError(f"Could not find {repo} on GitHub. It may have been renamed or made private.")
    return core.InstallError(f"GitHub returned an error (HTTP {code}).")


def _timestamp(text) -> datetime:
    stamp = datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _files(entry: dict) -> tuple[FirmwareFile, ...]:
    files = []
    for asset in entry.get("assets") or []:
        try:
            name = str(asset["name"])
            if not _FILE_NAME.fullmatch(name):
                raise ValueError(f"{name!r} is not a file name this app will save")
            digest = str(asset.get("digest") or "").lower()
            sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else None
            if sha256 is not None and not _SHA256.fullmatch(sha256):
                raise ValueError(f"{name} has an unreadable checksum")
            files.append(FirmwareFile(name, str(asset["browser_download_url"]), int(asset["size"]), sha256))
        except (ValueError, KeyError, TypeError) as error:
            log.warning("Ignoring a file attached to %s: %s", entry.get("tag_name", "?"), error)
    return tuple(files)


def list_releases(repo: Optional[str] = None) -> list[FirmwareRelease]:
    """The firmware releases in repo (normally REPO), pre-releases included, newest first. No drafts."""
    repo = repo or REPO
    url = f"{API_ROOT}/repos/{repo}/releases?per_page={PER_PAGE}"
    try:
        with core._open(url, API_HEADERS) as response:
            entries = json.load(response)
    except urllib.error.HTTPError as error:
        raise _http_error(error, repo) from error
    except (http.client.HTTPException, OSError) as error:  # OSError covers URLError and timeouts.
        raise core.InstallError("Could not reach GitHub. Check the internet connection.") from error
    except ValueError as error:
        raise core.InstallError("GitHub's list of releases could not be read.") from error
    if not isinstance(entries, list):
        raise core.InstallError("GitHub's list of releases could not be read.")

    releases = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        try:
            tag = str(entry["tag_name"])
            releases.append(FirmwareRelease(
                version=parse_version(tag) or tag,
                tag=tag,
                published=_timestamp(entry["published_at"]),
                prerelease=bool(entry.get("prerelease")),
                notes=str(entry.get("body") or ""),
                files=_files(entry),
            ))
        except (ValueError, KeyError, TypeError) as error:  # GitHub's entry itself is incomplete.
            log.warning("Skipping firmware release %s: %s", entry.get("tag_name", "?"), error)
    releases.sort(key=lambda r: r.published, reverse=True)
    return releases


# Downloading. Kept beside the app's other data, not in the install folder, which updates replace.

def cache_root() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "firmware"


def download_folder(release: FirmwareRelease) -> Path:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", release.tag)
    # Never "", "." or "..": deleting a release's folder must only ever delete that release.
    return cache_root() / (f"_{name}" if not name or name.startswith(".") else name)


def delete_download(release: FirmwareRelease) -> None:
    """Delete the release's downloaded files. Done once they have been programmed into the BMS."""
    folder = download_folder(release)
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise core.InstallError(f"Could not delete the downloaded firmware in {folder}: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(core.CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _is_good(path: Path, file: FirmwareFile) -> bool:
    try:
        if path.stat().st_size != file.size:
            return False
        return file.sha256 is None or _sha256(path) == file.sha256
    except OSError:
        return False


def is_downloaded(release: FirmwareRelease) -> bool:
    """Whether every file of the release is on this computer and still matches GitHub's checksum."""
    folder = download_folder(release)
    return bool(release.files) and all(_is_good(folder / f.name, f) for f in release.files)


def download(release: FirmwareRelease, on_progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    """Download the release's files into its folder, checking each, and return the folder.

    Files already there and intact are kept. A file that arrives damaged is deleted.
    """
    if not release.files:
        raise core.InstallError(f"No files are attached to {release.tag}, so there is nothing to download.")
    folder = download_folder(release)
    total = sum(f.size for f in release.files)
    done = 0
    for file in release.files:
        target = folder / file.name
        if not _is_good(target, file):
            _fetch(file, target, lambda got: on_progress(done + got, total))
        done += file.size
        on_progress(done, total)
    return folder


def _fetch(file: FirmwareFile, target: Path, on_progress: Callable[[int], None]) -> None:
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    got = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with core._open(file.url) as response, open(partial, "wb") as output:
            while chunk := response.read(core.CHUNK_SIZE):
                output.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                on_progress(got)
        if got != file.size or (file.sha256 is not None and digest.hexdigest() != file.sha256):
            raise core.InstallError(f"{file.name} was damaged on the way (it doesn't match GitHub's checksum). "
                                    "Please try again.")
        os.replace(partial, target)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as error:
        raise core.InstallError(f"Could not download {file.name}. Check the internet connection and try "
                                "again.") from error
    except OSError as error:
        raise core.InstallError(f"Could not save {file.name} in {target.parent}: {error}") from error
    finally:
        partial.unlink(missing_ok=True)
