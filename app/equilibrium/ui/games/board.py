"""The shared leaderboard beside a game: the top scores from everyone with the app, and the player's name.

The scores are fetched and sent on worker threads, so a slow connection never freezes a game.
"""

from __future__ import annotations

import html
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from equilibrium import leaderboard, theme
from equilibrium.leaderboard import Entry
from equilibrium.ui.widgets import button, label, section_label
from equilibrium_setup import core

WIDTH = 200


class LeaderboardPanel(QWidget):
    nameChanged = Signal(str)  # The player's name, cleaned, for the caller to remember

    # The worker thread reports back through this, which Qt delivers on the GUI thread.
    _done = Signal(int, object, str)  # Request number, the boards (None if they could not be had), error

    def __init__(self, name: str = "") -> None:
        super().__init__()
        self.setFixedWidth(WIDTH)
        self.board = ""  # Which board is on show, such as "snake/0"
        self.best = 0  # The player's own best on it, sent whenever it would earn a place
        self.boards: leaderboard.Boards | None = None  # None until they have been fetched once
        self.error = ""
        self.busy = False
        self._number = 0
        self._waiting = False  # A sync was asked for while hidden; do it when next shown

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addWidget(section_label("Leaderboard"))
        self.title = label("", "muted")  # The game whose board this is
        box.addWidget(self.title)
        self.rows = label("", wrap=True)
        self.rows.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.rows)
        self.status = label("", "faint", wrap=True)
        box.addWidget(self.status)
        box.addStretch(1)
        self.name = QLineEdit(leaderboard.clean_name(name))
        self.name.setPlaceholderText("Your name")
        self.name.setMaxLength(leaderboard.NAME_LENGTH)
        self.name.setToolTip("Shown to everyone on the leaderboard beside your scores")
        self.name.editingFinished.connect(self._name_edited)
        box.addWidget(self.name)
        row = QHBoxLayout()
        self.refresh_button = button("Refresh", self.sync)
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        box.addLayout(row)

        self._done.connect(self._on_done)
        theme.signals.changed.connect(self._render)
        self._render()

    def player(self) -> str:
        return leaderboard.clean_name(self.name.text())

    def show_board(self, board: str, title: str, best: int) -> None:
        """Change to another game's board, and bring it up to date."""
        self.board = board
        self.best = best
        self.title.setText(title)
        self._render()
        self.sync()

    def set_best(self, best: int) -> None:
        """The player has a new best on this board: send it."""
        if best > self.best:
            self.best = best
            self.sync()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._waiting or self.boards is None:
            self.sync()

    def _name_edited(self) -> None:
        name = self.player()
        self.name.setText(name)
        self.nameChanged.emit(name)
        self.sync()

    # Fetching and sending

    def sync(self, _checked: bool = False) -> None:
        """Fetch the boards, first sending the player's best if it would earn a place."""
        if not self.isVisible():
            self._waiting = True
            return
        self._waiting = False
        self._number += 1
        self.busy = True
        self._render()
        work = threading.Thread(target=self._work, args=(self._number, self.board, self.player(), self.best),
                                daemon=True)
        work.start()

    def _work(self, number: int, board: str, name: str, best: int) -> None:
        try:
            boards = leaderboard.fetch()
            mine = Entry(name, best, leaderboard.today())
            if leaderboard.can_post() and leaderboard.merged(boards.get(board, []), mine) is not None:
                boards = leaderboard.post(board, name, best)
            self._done.emit(number, boards, "")
        except core.InstallError as error:
            self._done.emit(number, None, str(error))
        except Exception as error:  # A failed leaderboard must never disturb a game.
            self._done.emit(number, None, f"The leaderboard failed ({error}).")

    def _on_done(self, number: int, boards: object, error: str) -> None:
        if number != self._number:  # Overtaken by a later request
            return
        self.busy = False
        self.error = error
        if boards is not None:
            self.boards = boards
        self._render()

    # Showing

    def _render(self) -> None:
        entries = (self.boards or {}).get(self.board, [])
        me = self.player().casefold()
        lines = []
        for place, entry in enumerate(entries, start=1):
            mine = entry.name.casefold() == me
            colour = theme.ACCENT if mine else theme.TEXT
            weight = "600" if mine else "400"
            lines.append(
                f"<tr style='color:{colour}; font-weight:{weight}'>"
                f"<td style='color:{theme.TEXT_FAINT}' align='right'>{place}&nbsp;</td>"
                f"<td width='100%'>{html.escape(entry.name, quote=False)}</td>"
                f"<td align='right'>&nbsp;{entry.score}</td></tr>")
        if lines:
            self.rows.setText(f"<table width='100%' cellspacing='0' cellpadding='2'>{''.join(lines)}</table>")
        elif self.boards is None:
            self.rows.setText("")
        else:
            self.rows.setText(f"<span style='color:{theme.TEXT_MUTED}'>No scores yet. Set the first.</span>")
        self.rows.setVisible(bool(self.rows.text()))

        if self.busy:
            status = "Updating…"
        elif self.error:
            status = self.error
        elif not leaderboard.can_post():
            status = "This copy of the app shows the leaderboard but cannot add scores to it."
        elif not self.player():
            status = "Enter a name to put your scores on the leaderboard. Everyone with the app will see it."
        else:
            status = f"Your best scores are shared as {self.player()}."
        self.status.setText(status)
