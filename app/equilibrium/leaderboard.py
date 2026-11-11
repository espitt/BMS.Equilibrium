"""The minigame leaderboard shared by everyone with the app. No GUI code.

The scores are one small JSON file in a public GitHub repository, so anyone can read them and nobody
needs a GitHub account. Writing needs an access token, which release builds carry (see TOKEN). A copy
without one shows the leaderboard but cannot add to it. docs/leaderboard.md has the setup.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from equilibrium_setup import core
except ImportError:  # A source run: the installer package sits beside the app rather than on the path.
    sys.path.append(str(Path(__file__).resolve().parents[2] / "installer"))
    from equilibrium_setup import core

REPO = "espitt/BMS.Scores"  # Public. It holds nothing but the scores file.
BRANCH = "main"
FILE = "scores.json"
API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

# A fine-grained token that can write to REPO's contents and nothing else. packaging/build.py stamps it
# into release builds from the LEADERBOARD_TOKEN secret; it is never committed. Anyone determined can
# dig it out of a release, which is why it must be able to do nothing beyond changing the scores.
TOKEN = ""
TOKEN_VARIABLE = "EQUILIBRIUM_LEADERBOARD_TOKEN"  # Lets a source run post scores too

FORMAT = 1
TOP = 10  # Places kept on each board
NAME_LENGTH = 20
ATTEMPTS = 4  # Another player may save a score at the same moment; then read the file and try again


@dataclass(frozen=True)
class Entry:
    name: str
    score: int
    date: str  # The day it was set, as 2026-11-11


Boards = dict[str, list[Entry]]  # By board: a game and its level, such as "snake/0"


def token() -> str:
    return TOKEN or os.environ.get(TOKEN_VARIABLE, "")


def clean_name(text: str) -> str:
    """A player's name made fit to publish: one line, no odd characters, not too long."""
    text = re.sub(r"[^\w .'-]", "", " ".join(str(text).split()))
    return text[:NAME_LENGTH].strip()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ranked(entries: list[Entry]) -> list[Entry]:
    """Best first. Equal scores go in the order they were set."""
    return sorted(entries, key=lambda e: (-e.score, e.date))[:TOP]


def merged(entries: list[Entry], entry: Entry) -> Optional[list[Entry]]:
    """The board with a score added, or None if the score changes nothing.

    Each player has one place, their best. Names differing only in capitals are the same player.
    """
    if entry.score <= 0 or not entry.name:
        return None
    mine = next((e for e in entries if e.name.casefold() == entry.name.casefold()), None)
    if mine is not None and mine.score >= entry.score:
        return None
    board = ranked([e for e in entries if e is not mine] + [entry])
    return board if entry in board else None


def parse(document: object) -> Boards:
    """The boards in a scores file. Anything malformed is left out: the file can be edited by hand."""
    boards: Boards = {}
    scores = document.get("scores") if isinstance(document, dict) else None
    if not isinstance(scores, dict):
        return boards
    for board, rows in scores.items():
        entries = []
        for row in rows if isinstance(rows, list) else []:
            try:
                name, score = clean_name(row["name"]), int(row["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if name and score > 0:
                entries.append(Entry(name, score, str(row.get("date", ""))[:10]))
        boards[str(board)] = ranked(entries)
    return boards


def dump(boards: Boards) -> bytes:
    scores = {board: [{"name": e.name, "score": e.score, "date": e.date} for e in entries]
              for board, entries in sorted(boards.items())}
    return (json.dumps({"format": FORMAT, "scores": scores}, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


# Talking to GitHub

def _request(url: str, method: str = "GET", body: Optional[dict] = None, authorised: bool = False):
    headers = {"User-Agent": core.USER_AGENT, **API_HEADERS}
    if authorised:
        headers["Authorization"] = f"Bearer {token()}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    # Plain http:// is only reachable from the tests, via a loopback server.
    context = core._ssl_context() if url.startswith("https://") else None
    return urllib.request.urlopen(request, timeout=core.TIMEOUT_SECONDS, context=context)


def _failure(error: Exception) -> core.InstallError:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return core.InstallError("The leaderboard turned this copy of the app away. Its access may have expired.")
        return core.InstallError(f"The leaderboard returned an error (HTTP {error.code}).")
    if isinstance(error, ValueError):
        return core.InstallError("The leaderboard could not be read.")
    return core.InstallError("Could not reach the leaderboard. Check the internet connection.")


def _load() -> tuple[Boards, Optional[str]]:
    """The boards, and the version of the file they came from (needed to replace it).

    With a token the file is read through GitHub's API, which is always up to date. Without one it is
    read as a plain download, which has no hourly limit but can lag a few minutes behind.
    """
    try:
        if token():
            with _request(f"{API_ROOT}/repos/{REPO}/contents/{FILE}?ref={BRANCH}", authorised=True) as response:
                reply = json.load(response)
            return parse(json.loads(base64.b64decode(reply["content"]))), str(reply["sha"])
        with _request(f"{RAW_ROOT}/{REPO}/{BRANCH}/{FILE}") as response:
            return parse(json.load(response)), None
    except urllib.error.HTTPError as error:
        if error.code == 404:  # Nobody has set a score yet.
            return {}, None
        raise _failure(error) from error
    except (http.client.HTTPException, OSError, ValueError, KeyError, TypeError) as error:
        raise _failure(error) from error


def fetch() -> Boards:
    """Every board. Raises InstallError, with a message fit to show, if they cannot be had."""
    return _load()[0]


def can_post() -> bool:
    return bool(token())


def post(board: str, name: str, score: int) -> Boards:
    """Add a score to a board, if it earns a place, and return every board as it then stands."""
    if not can_post():
        raise core.InstallError("This copy of the app can show the leaderboard but not add to it.")
    entry = Entry(clean_name(name), int(score), today())
    for _attempt in range(ATTEMPTS):
        boards, version = _load()
        board_now = merged(boards.get(board, []), entry)
        if board_now is None:
            return boards
        boards[board] = board_now
        body = {"message": f"{entry.name}: {entry.score} on {board}", "branch": BRANCH,
                "content": base64.b64encode(dump(boards)).decode("ascii")}
        if version is not None:
            body["sha"] = version
        try:
            with _request(f"{API_ROOT}/repos/{REPO}/contents/{FILE}", "PUT", body, authorised=True):
                return boards
        except urllib.error.HTTPError as error:
            if error.code not in (409, 422):  # Not "the file changed since it was read"
                raise _failure(error) from error
        except (http.client.HTTPException, OSError) as error:
            raise _failure(error) from error
    raise core.InstallError("The leaderboard is busy. The score will be sent again later.")
