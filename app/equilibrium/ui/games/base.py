"""What every minigame shares: scaling, the clock, pausing, keys and the notice drawn over a stopped game.

A game draws in its own fixed units (its `size`) and is scaled to whatever room the screen gives it.
It starts paused, pauses whenever it loses the keyboard or is hidden, and cannot be played at all while
`hold` says why not. The Charging screen sets that when the pack needs attention.
"""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QFont, QHideEvent, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from equilibrium import theme

K = Qt.Key
TICK_MS = 16  # Games that move
CLOCK_MS = 250  # Games that wait for the player, which only count the time
MARGIN = 8
START_KEYS = (K.Key_Space, K.Key_Return, K.Key_Enter)
PAUSE_KEYS = (K.Key_P, K.Key_Escape, K.Key_Pause)


def colours() -> list[str]:
    """Seven colours for game pieces. None is the red or amber that means a fault or a warning elsewhere."""
    series = theme.SERIES
    return [series[0], series[2], series[3], series[5], series[6], theme.BALANCE, theme.CHARGE]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Game(QWidget):
    title = ""
    controls = ""  # One line saying how to play
    score_name = "Score"  # What the score counts, where that is not points
    board_size = (400.0, 400.0)  # The board, in the game's own units
    levels: tuple[str, ...] = ()  # Names of the difficulty levels, if the game has any
    realtime = True  # False for games that wait for the player

    scoreChanged = Signal(int)
    stateChanged = Signal()  # Paused, resumed, finished or put on hold

    def __init__(self, level: int = 0, seed: int | None = None) -> None:
        super().__init__()
        self.level = level
        self.rng = random.Random(seed)
        self.score = 0
        self.over = False
        self.paused = True
        self.result = ""  # Said over a finished game, such as "Solved"
        self.notice = ""  # Why the game paused itself, if it did
        self.hold = ""  # Why the game may not be played right now
        self.elapsed = 0.0  # Seconds of play
        self.held: set[int] = set()  # Keys held down
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS if self.realtime else CLOCK_MS)
        self._timer.timeout.connect(self._on_timer)
        theme.signals.changed.connect(self.update)
        self.new_game()

    # For each game to fill in

    def reset(self) -> None:
        """Set up a fresh game."""

    def tick(self, dt: float) -> None:
        """Move the game on by dt seconds."""

    def key(self, key: int) -> None:
        """A key was pressed during play (again and again, if it is held down)."""

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        """The board was clicked during play. pos is in the game's own units."""

    def mouse(self, pos: QPointF) -> None:
        """The mouse moved over the board during play."""

    def draw(self, p: QPainter) -> None:
        """Paint the board, in the game's own units."""

    # Running

    @property
    def active(self) -> bool:
        return not self.paused and not self.over

    def new_game(self) -> None:
        self._timer.stop()
        self.score = 0
        self.over = False
        self.paused = True
        self.result = self.notice = ""
        self.elapsed = 0.0
        self.held.clear()
        self.reset()
        self.scoreChanged.emit(0)
        self.stateChanged.emit()
        self.update()

    def go(self) -> None:
        """Start, carry on, or begin again after a finished game. Does nothing while on hold."""
        if self.hold:
            return
        if self.over:
            self.new_game()
        self.set_paused(False)

    def set_paused(self, paused: bool, notice: str = "") -> None:
        if self.over or (not paused and self.hold) or paused == self.paused:
            return
        self.paused = paused
        self.notice = notice if paused else ""
        self.held.clear()
        if paused:
            self._timer.stop()
        else:
            self._timer.start()
        self.stateChanged.emit()
        self.update()

    def set_hold(self, reason: str) -> None:
        """Stop play until set_hold("") is called. The player must then choose to carry on."""
        if reason == self.hold:
            return
        self.hold = reason
        if reason:
            self.set_paused(True)
        self.stateChanged.emit()
        self.update()

    def end(self, result: str = "") -> None:
        self.over = True
        self.result = result
        self._timer.stop()
        self.stateChanged.emit()
        self.update()

    def add_score(self, points: int) -> None:
        self.set_score(self.score + points)

    def set_score(self, score: int) -> None:
        if score != self.score:
            self.score = score
            self.scoreChanged.emit(score)

    def _on_timer(self) -> None:
        if not self.active:
            return
        dt = self._timer.interval() / 1000
        self.elapsed += dt
        self.tick(dt)
        self.update()

    # Keys and mouse

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in PAUSE_KEYS:
            if self.active:
                self.set_paused(True)
            elif not self.over:
                self.go()
        elif not self.active:
            if key in START_KEYS:
                self.go()
        else:
            self.held.add(key)
            self.key(key)
            self.update()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat():
            self.held.discard(event.key())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if not self.active:
            if event.button() == Qt.MouseButton.LeftButton:
                self.go()
            return
        self.click(self.to_board(event.position()), event.button())
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.active:
            self.mouse(self.to_board(event.position()))

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.set_paused(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.set_paused(True)

    # Drawing

    def _fit(self) -> tuple[float, float, float]:
        """(scale, left, top) that centre the board in the widget."""
        width, height = self.board_size
        scale = max(0.05, min((self.width() - 2 * MARGIN) / width, (self.height() - 2 * MARGIN) / height))
        return scale, (self.width() - width * scale) / 2, (self.height() - height * scale) / 2

    def to_board(self, pos: QPointF) -> QPointF:
        scale, left, top = self._fit()
        return QPointF((pos.x() - left) / scale, (pos.y() - top) / scale)

    def text(self, p: QPainter, rect: QRectF, text: str, size: int = 13, colour: str | None = None,
             bold: bool = False, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter, wrap: bool = False) -> None:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(theme.color(colour or theme.TEXT))
        p.drawText(rect, align.value | (Qt.TextFlag.TextWordWrap.value if wrap else 0), text)

    def message(self) -> tuple[str, str, str] | None:
        """(headline, detail, headline colour) to draw over the board, or None during play."""
        how = "Press Space or click"
        if self.hold:
            # A real safety message, so it is the one thing here drawn in the warning colour.
            return "Paused for safety", f"{self.hold}. Check the charging stats.", theme.WARN
        if self.over:
            score = f"{self.score_name} {self.score}"
            return self.result or "Game over", f"{score}. {how} for a new game.", theme.TEXT
        if not self.paused:
            return None
        if self.notice:
            return self.notice, f"{how} to carry on.", theme.TEXT
        if self.elapsed == 0:
            return self.title, f"{how} to start.", theme.TEXT
        return "Paused", f"{how} to carry on.", theme.TEXT

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, left, top = self._fit()
        board = QRectF(0, 0, *self.board_size)
        p.save()
        p.translate(left, top)
        p.scale(scale, scale)
        p.setClipRect(board)
        p.fillRect(board, theme.color(theme.BG))
        self.draw(p)
        p.restore()
        p.setPen(theme.color(theme.BORDER))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(left, top, board.width() * scale, board.height() * scale))

        message = self.message()
        if message is not None:
            headline, detail, colour = message
            p.fillRect(self.rect(), theme.color(theme.BG, 215))
            middle = self.height() / 2
            self.text(p, QRectF(0, middle - 34, self.width(), 30), headline, 20, colour, bold=True)
            self.text(p, QRectF(12, middle, self.width() - 24, 60), detail, 12, theme.TEXT_MUTED,
                      align=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, wrap=True)
        p.end()
