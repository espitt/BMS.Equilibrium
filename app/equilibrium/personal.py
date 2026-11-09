"""Per-user startup touches, chosen by the Windows account folder name (C:\\Users\\<name>)."""

import sys
from pathlib import Path, PurePath

ASSETS_DIR = Path(__file__).parent / "assets" / "splash"

# Account folder name, lower case -> files in ASSETS_DIR. Either entry can be left out.
# "image" replaces the splash icon; "sound" is a WAV file played at full volume on startup.
USERS = {
    "adam": {"image": "adam.jpg", "sound": "adam.wav"},
}


def asset(kind: str, home: PurePath | None = None, platform: str = sys.platform) -> Path | None:
    """The signed-in Windows user's file of this kind ("image" or "sound"), if they have one."""
    if platform != "win32":
        return None
    name = (home or Path.home()).name.lower()
    filename = USERS.get(name, {}).get(kind)
    if filename is None or not (ASSETS_DIR / filename).is_file():
        return None
    return ASSETS_DIR / filename
