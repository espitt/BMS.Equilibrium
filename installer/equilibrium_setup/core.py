"""Find, download, verify and unpack a release. Contains no GUI or OS integration."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import shutil
import ssl
import sys
import tarfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

APP_NAME = "Equilibrium"
MARKER_NAME = ".equilibrium-install.json"
MANIFEST_NAME = "manifest.json"
USER_AGENT = "EquilibriumSetup"
TIMEOUT_SECONDS = 30
CHUNK_SIZE = 64 * 1024


class InstallError(Exception):
    """A failure with a message that is suitable to show to the user."""


class Cancelled(Exception):
    """The user cancelled the operation."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int


def platform_key() -> str:
    """Return the manifest key for this machine, for example ``windows-x64``."""
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{arch}"


def _ssl_context() -> ssl.SSLContext:
    # Frozen builds cannot rely on the system's CA paths, so certifi is bundled.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Plain http:// is only reachable from the tests, via a loopback server.
    context = _ssl_context() if url.startswith("https://") else None
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context)


def manifest_url(repo: str) -> str:
    # The /latest/download/ route does not use the rate-limited GitHub API.
    return f"https://github.com/{repo}/releases/latest/download/{MANIFEST_NAME}"


def fetch_release(url: str, key: Optional[str] = None) -> Release:
    """Download the release manifest and pick the entry for this platform."""
    key = key or platform_key()
    try:
        with _open(url) as response:
            manifest = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise InstallError("No published release of Equilibrium was found.") from error
        raise InstallError(f"GitHub returned an error (HTTP {error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise InstallError(
            "Could not reach GitHub. Check your internet connection and try again."
        ) from error
    except ValueError as error:
        raise InstallError("The release information could not be read.") from error

    try:
        version = manifest["version"]
        base_url = manifest["base_url"]
        assets = manifest["assets"]
        if key not in assets:
            available = ", ".join(sorted(assets))
            raise InstallError(
                f"Equilibrium {version} is not available for {key}. "
                f"Available: {available}."
            )
        asset = assets[key]
        return Release(
            version=version,
            url=f"{base_url}/{urllib.parse.quote(asset['name'])}",
            sha256=asset["sha256"].lower(),
            size=int(asset["size"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise InstallError("The release information is incomplete.") from error


def download(
    release: Release,
    destination: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    cancel: Optional[threading.Event] = None,
) -> None:
    """Stream the release archive to ``destination`` and verify its checksum."""
    digest = hashlib.sha256()
    done = 0
    try:
        with _open(release.url) as response, open(destination, "wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                output.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                on_progress(done, release.size)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as error:
        raise InstallError("The download failed. Please try again.") from error

    if digest.hexdigest() != release.sha256:
        destination.unlink(missing_ok=True)
        raise InstallError("The download was corrupted (checksum mismatch). Please try again.")


def check_target(install_dir: Path) -> None:
    """Refuse a folder that holds anything other than a previous Equilibrium install.

    Installing replaces the whole folder and uninstalling deletes it, so this
    check is what stops a mistyped path from destroying someone's files.
    """
    if not install_dir.exists():
        return
    if not install_dir.is_dir():
        raise InstallError(f"{install_dir} is a file, not a folder.")
    if (install_dir / MARKER_NAME).is_file():
        return
    # macOS bundles carry no marker, because extra files would break code signing.
    if (install_dir / "Contents" / "MacOS" / APP_NAME).is_file():
        return
    if any(install_dir.iterdir()):
        raise InstallError(
            f"{install_dir} already contains other files. Please choose an empty folder."
        )


def read_marker(install_dir: Path) -> dict:
    try:
        return json.loads((install_dir / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def install_archive(
    archive: Path,
    install_dir: Path,
    version: str,
    uninstaller: Optional[Path] = None,
    uninstaller_name: str = "",
    write_marker: bool = True,
) -> None:
    """Unpack ``archive`` beside ``install_dir``, then swap it into place.

    Any failure before the swap leaves an existing installation untouched.
    """
    check_target(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = install_dir.with_name(f"{install_dir.name}.new-{os.getpid()}")
    retired = install_dir.with_name(f"{install_dir.name}.old-{os.getpid()}")

    try:
        staging.mkdir()
        extract_archive(archive, staging)
        if uninstaller is not None:
            shutil.copy2(uninstaller, staging / uninstaller_name)
        if write_marker:
            # Keep earlier shortcuts on record so that uninstalling still removes them.
            shortcuts = read_marker(install_dir).get("shortcuts", [])
            marker = {"version": version, "shortcuts": shortcuts}
            (staging / MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")

        had_previous = install_dir.exists()
        if had_previous:
            try:
                install_dir.rename(retired)
            except PermissionError as error:
                raise InstallError(
                    f"{APP_NAME} appears to be running. Close it and try again."
                ) from error
        try:
            staging.rename(install_dir)
        except OSError:
            if had_previous:
                retired.rename(install_dir)
            raise
    except OSError as error:
        raise InstallError(f"Could not write to {install_dir}: {error}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    shutil.rmtree(retired, ignore_errors=True)


def extract_archive(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # The "data" filter rejects paths that escape the destination.
            tar.extractall(destination, filter="data")
    except (tarfile.TarError, EOFError) as error:
        raise InstallError("The downloaded archive could not be unpacked.") from error


def add_shortcuts_to_marker(install_dir: Path, shortcuts: list[str]) -> None:
    marker = read_marker(install_dir)
    marker["shortcuts"] = sorted({*marker.get("shortcuts", []), *shortcuts})
    (install_dir / MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
