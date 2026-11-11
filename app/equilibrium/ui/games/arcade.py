"""The games card on the Charging screen: choose a game, see the score, and stop play when the pack needs attention.

The player's best scores go on the leaderboard shared by everyone with the app (see board.py).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QHBoxLayout

from equilibrium.ui.games.base import Game
from equilibrium.ui.games.blocks import Blocks
from equilibrium.ui.games.board import LeaderboardPanel
from equilibrium.ui.games.bricks import Bricks
from equilibrium.ui.games.merge import Merge
from equilibrium.ui.games.mines import Mines
from equilibrium.ui.games.rocks import Rocks
from equilibrium.ui.games.runner import Runner
from equilibrium.ui.games.snake import Snake
from equilibrium.ui.games.solitaire import Solitaire
from equilibrium.ui.games.sudoku import Sudoku
from equilibrium.ui.games.tennis import Tennis
from equilibrium.ui.widgets import Card, button, label

GAMES: list[type[Game]] = [Snake, Bricks, Blocks, Tennis, Rocks, Runner, Mines, Merge, Solitaire, Sudoku]


def _settings() -> QSettings:
    return QSettings("SUFST", "Equilibrium")


def _number(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Arcade(Card):
    def __init__(self) -> None:
        super().__init__("Games")
        self.game: Game | None = None
        self.hold = ""  # Why no game may be played right now

        row = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.addItems([game.title for game in GAMES])
        row.addWidget(self.picker)
        self.level = QComboBox()
        row.addWidget(self.level)
        row.addStretch(1)
        self.board_button = button("Leaderboard", self._show_board, tooltip="Show or hide the shared leaderboard")
        self.board_button.setCheckable(True)
        self.board_button.setChecked(True)
        row.addWidget(self.board_button)
        self.new_button = button("New game", self._new_game)
        row.addWidget(self.new_button)
        self.pause_button = button("Pause", self._toggle_pause)
        row.addWidget(self.pause_button)
        self.box.addLayout(row)
        self.score = label("", "muted")
        self.box.addWidget(self.score)
        self.stage = QHBoxLayout()  # The game, with the leaderboard to its right
        self.stage.setSpacing(12)
        self.box.addLayout(self.stage, 1)
        self.board = LeaderboardPanel(str(_settings().value("games/player") or ""))
        self.board.nameChanged.connect(self._name_changed)
        self.stage.addWidget(self.board)
        self.hint = label("", "faint", wrap=True)

        last = _number(_settings().value("games/last"))
        self.picker.setCurrentIndex(last if 0 <= last < len(GAMES) else 0)
        self.picker.currentIndexChanged.connect(self._picked)
        # A method, not a lambda holding self: that would keep the card alive until Python shuts down,
        # after Qt has gone, which crashes on exit.
        self.level.currentIndexChanged.connect(self._level_picked)
        self._load()
        self.box.addWidget(self.hint)

    # Choosing a game

    def _picked(self, index: int) -> None:
        _settings().setValue("games/last", index)  # Opens on the same game next time
        self._load()

    def _level_picked(self, _index: int) -> None:
        self._load(keep_level=True)

    def _load(self, keep_level: bool = False) -> None:
        cls = GAMES[self.picker.currentIndex()]
        level = self.level.currentIndex() if keep_level else 0
        if not keep_level:
            self.level.blockSignals(True)
            self.level.clear()
            self.level.addItems(cls.levels)
            self.level.setVisible(bool(cls.levels))
            self.level.blockSignals(False)
        if self.game is not None:
            self.stage.removeWidget(self.game)
            self.game.hide()
            self.game.deleteLater()
        self.game = cls(max(0, level))
        self.game.scoreChanged.connect(self._on_score)
        self.game.stateChanged.connect(self._on_state)
        self.game.set_hold(self.hold)
        self.stage.insertWidget(0, self.game, 1)
        self.hint.setText(cls.controls)
        self.board.show_board(self._board_key(), cls.title, self.best())
        self._on_score(0)
        self._on_state()
        self.game.setFocus()

    def _new_game(self) -> None:
        self.game.new_game()
        self.game.setFocus()

    def _toggle_pause(self) -> None:
        if self.game.active:
            self.game.set_paused(True)
        else:
            self.game.go()
            self.game.setFocus()

    # Scores. The best is kept for each game and level, and shared on that game and level's leaderboard.

    def _board_key(self) -> str:
        return f"{type(self.game).__name__.lower()}/{self.game.level}"

    def _best_key(self) -> str:
        return f"games/{self._board_key()}/best"

    def _show_board(self, on: bool) -> None:
        self.board.setVisible(on)

    def _name_changed(self, name: str) -> None:
        _settings().setValue("games/player", name)

    def best(self) -> int:
        return _number(_settings().value(self._best_key()))

    def _on_score(self, score: int) -> None:
        best = self.best()
        if score > best:
            best = score
            _settings().setValue(self._best_key(), best)
        self.score.setText(f"{self.game.score_name} {score} · Best {best}")

    def _on_state(self) -> None:
        game = self.game
        self.pause_button.setText("Pause" if game.active else "Resume")
        self.pause_button.setEnabled(not game.hold and not game.over)
        if game.over:  # A finished game is the moment to share a new best.
            self.board.set_best(self.best())

    # Safety

    def set_hold(self, reason: str) -> None:
        """Stop play while reason says the pack needs attention. "" lets the player carry on."""
        self.hold = reason
        self.game.set_hold(reason)

    def pause(self, notice: str = "") -> None:
        """Pause, saying why over the game. The player can carry on at once."""
        self.game.set_paused(True, notice)
