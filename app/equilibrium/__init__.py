"""Equilibrium: desktop front end for battery management software."""

from pathlib import Path

__version__ = "0.0.0-dev"  # Stamped from the release tag by packaging/build.py.

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
