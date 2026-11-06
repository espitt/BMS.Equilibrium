#!/usr/bin/env python3
"""Build release files.

    python packaging/build.py build --version 1.2.3 --repo owner/name
    python packaging/build.py manifest --version 1.2.3 --repo owner/name --dir release

``build`` creates, in ./release, this platform's app archive and setup program.
``manifest`` hashes the app archives from every platform into manifest.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
RELEASE = ROOT / "release"
WORK = ROOT / "build"
DIST = ROOT / "dist"
APP_INIT = ROOT / "app" / "equilibrium" / "__init__.py"
SETUP_INIT = ROOT / "installer" / "equilibrium_setup" / "__init__.py"
SETUP_NAME = "EquilibriumSetup"

sys.path.insert(0, str(ROOT / "installer"))
from equilibrium_setup.core import MANIFEST_NAME, platform_key  # noqa: E402


def pyinstaller(name: str, entry: str, paths: str, *options: str) -> None:
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--windowed",
            "--name", name,
            "--paths", str(ROOT / paths),
            "--distpath", str(DIST),
            "--workpath", str(WORK),
            "--specpath", str(WORK),
            *options,
            str(PACKAGING / entry),
        ],
        check=True,
    )


def stamp(path: Path, pattern: str, replacement: str) -> None:
    text, count = re.subn(pattern, replacement, path.read_text(encoding="utf-8"), flags=re.M)
    if count != 1:
        raise SystemExit(f"Could not stamp {path}")
    path.write_text(text, encoding="utf-8")


def build(version: str, repo: str) -> None:
    key = platform_key()
    originals = {path: path.read_text(encoding="utf-8") for path in (APP_INIT, SETUP_INIT)}
    shutil.rmtree(RELEASE, ignore_errors=True)
    RELEASE.mkdir()
    try:
        stamp(APP_INIT, r"^__version__ = .*$", f'__version__ = "{version}"')
        stamp(SETUP_INIT, r"^GITHUB_REPO = .*$", f'GITHUB_REPO = "{repo}"')
        pyinstaller("Equilibrium", "entry_app.py", "app", "--onedir")
        # A single file everywhere except macOS, where the .app bundle is the unit.
        # --hidden-import because certifi is imported inside a function.
        pyinstaller(
            SETUP_NAME, "entry_setup.py", "installer",
            "--onedir" if key.startswith("macos") else "--onefile",
            "--hidden-import", "certifi", "--collect-data", "certifi",
            "--exclude-module", "PySide6",
        )
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")

    smoke_test(key)
    package_app(version, key)
    package_setup(key)


def smoke_test(key: str) -> None:
    if key.startswith("windows"):
        app, setup = DIST / "Equilibrium" / "Equilibrium.exe", DIST / f"{SETUP_NAME}.exe"
    elif key.startswith("macos"):
        app = DIST / "Equilibrium.app" / "Contents" / "MacOS" / "Equilibrium"
        setup = DIST / f"{SETUP_NAME}.app" / "Contents" / "MacOS" / SETUP_NAME
    else:
        app, setup = DIST / "Equilibrium" / "Equilibrium", DIST / SETUP_NAME
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for program in (app, setup):
        subprocess.run([str(program), "--smoke-test"], check=True, timeout=120, env=environment)


def package_app(version: str, key: str) -> None:
    archive = RELEASE / f"Equilibrium-{version}-{key}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        if key.startswith("macos"):
            # The extraction folder itself becomes Equilibrium.app.
            source = DIST / "Equilibrium.app"
        else:
            source = DIST / "Equilibrium"
        for child in sorted(source.iterdir()):
            tar.add(child, arcname=child.name)


def package_setup(key: str) -> None:
    if key.startswith("windows"):
        shutil.copy2(DIST / f"{SETUP_NAME}.exe", RELEASE / f"{SETUP_NAME}-{key}.exe")
    elif key.startswith("macos"):
        # ditto preserves the symlinks and metadata that a macOS bundle relies on.
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(DIST / f"{SETUP_NAME}.app"),
             str(RELEASE / f"{SETUP_NAME}-{key}.zip")],
            check=True,
        )
    else:
        # A tarball, because browsers strip the executable bit from a bare binary.
        with tarfile.open(RELEASE / f"{SETUP_NAME}-{key}.tar.gz", "w:gz") as tar:
            tar.add(DIST / SETUP_NAME, arcname=SETUP_NAME)


def manifest(version: str, repo: str, directory: Path) -> None:
    prefix = f"Equilibrium-{version}-"
    assets = {}
    for archive in sorted(directory.glob(f"{prefix}*.tar.gz")):
        key = archive.name[len(prefix):-len(".tar.gz")]
        assets[key] = {
            "name": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "size": archive.stat().st_size,
        }
    if not assets:
        raise SystemExit(f"No app archives found in {directory}")
    document = {
        "version": version,
        "base_url": f"https://github.com/{repo}/releases/download/v{version}",
        "assets": assets,
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(document, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "manifest"])
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dir", type=Path, default=RELEASE)
    args = parser.parse_args()
    if args.command == "build":
        build(args.version, args.repo)
    else:
        manifest(args.version, args.repo, args.dir)


if __name__ == "__main__":
    main()
