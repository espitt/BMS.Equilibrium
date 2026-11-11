"""Falling blocks: turn and stack the falling shapes to fill rows, which then clear."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from equilibrium import theme
from equilibrium.ui.games.base import Game, K, colours

COLUMNS, ROWS = 10, 18
CELL = 30.0
WELL = COLUMNS * CELL
SHAPES = [
    [(0, 0), (1, 0), (2, 0), (3, 0)],
    [(0, 0), (1, 0), (0, 1), (1, 1)],
    [(0, 0), (1, 0), (2, 0), (1, 1)],
    [(0, 0), (1, 0), (2, 0), (0, 1)],
    [(0, 0), (1, 0), (2, 0), (2, 1)],
    [(1, 0), (2, 0), (0, 1), (1, 1)],
    [(0, 0), (1, 0), (1, 1), (2, 1)],
]
ROW_POINTS = (0, 100, 300, 500, 800)  # For clearing 0 to 4 rows at once
Cells = list[tuple[int, int]]


def extent(cells: Cells) -> tuple[int, int]:
    return max(x for x, _ in cells) + 1, max(y for _, y in cells) + 1


def turned(cells: Cells) -> Cells:
    """The shape turned a quarter clockwise, still touching the top and left of its box."""
    _, height = extent(cells)
    return [(height - 1 - y, x) for x, y in cells]


class Blocks(Game):
    title = "Falling blocks"
    controls = "Left and right move, up turns, down drops a row, Space drops all the way."
    board_size = (WELL + 120, ROWS * CELL)

    def reset(self) -> None:
        self.grid: list[list[int | None]] = [[None] * COLUMNS for _ in range(ROWS)]  # The shape number in each square
        self.rows_cleared = 0
        self.upcoming = self.rng.randrange(len(SHAPES))
        self._wait = 0.0
        self._spawn()

    @property
    def speed_level(self) -> int:
        return self.rows_cleared // 10

    def _spawn(self) -> None:
        self.kind = self.upcoming
        self.upcoming = self.rng.randrange(len(SHAPES))
        self.cells = list(SHAPES[self.kind])
        self.px, self.py = (COLUMNS - extent(self.cells)[0]) // 2, 0
        if not self.fits(self.cells, self.px, self.py):
            self.end()

    def fits(self, cells: Cells, px: int, py: int) -> bool:
        return all(0 <= px + x < COLUMNS and 0 <= py + y < ROWS and self.grid[py + y][px + x] is None
                   for x, y in cells)

    def shift(self, dx: int) -> bool:
        if self.fits(self.cells, self.px + dx, self.py):
            self.px += dx
            return True
        return False

    def turn(self) -> None:
        cells = turned(self.cells)
        (old_w, old_h), (new_w, new_h) = extent(self.cells), extent(cells)
        px, py = self.px + (old_w - new_w) // 2, self.py + (old_h - new_h) // 2  # Turn about the middle
        for nudge in (0, -1, 1, -2, 2):  # Next to a wall, try a square or two sideways
            if self.fits(cells, px + nudge, py):
                self.cells, self.px, self.py = cells, px + nudge, py
                return

    def fall(self) -> bool:
        """Drop one row. Returns False if the shape landed instead."""
        if self.fits(self.cells, self.px, self.py + 1):
            self.py += 1
            return True
        self._land()
        return False

    def _land(self) -> None:
        for x, y in self.cells:
            self.grid[self.py + y][self.px + x] = self.kind
        kept = [row for row in self.grid if None in row]
        cleared = ROWS - len(kept)
        if cleared:
            self.add_score(ROW_POINTS[cleared] * (self.speed_level + 1))
            self.rows_cleared += cleared
            self.grid = [[None] * COLUMNS for _ in range(cleared)] + kept
        self._spawn()

    def key(self, key: int) -> None:
        if key in (K.Key_Left, K.Key_A):
            self.shift(-1)
        elif key in (K.Key_Right, K.Key_D):
            self.shift(1)
        elif key in (K.Key_Up, K.Key_W):
            self.turn()
        elif key in (K.Key_Down, K.Key_S):
            if self.fall():
                self.add_score(1)
            self._wait = 0.0
        elif key == K.Key_Space:
            while self.fall():
                self.add_score(2)
            self._wait = 0.0

    def tick(self, dt: float) -> None:
        self._wait += dt
        if self._wait >= max(0.08, 0.6 * 0.85 ** self.speed_level):
            self._wait = 0.0
            self.fall()

    def draw(self, p: QPainter) -> None:
        palette = colours()

        def square(x: float, y: float, kind: int) -> None:
            p.setBrush(theme.color(palette[kind]))
            p.drawRoundedRect(QRectF(x + 1, y + 1, CELL - 2, CELL - 2), 4, 4)

        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(WELL, 0, 120, ROWS * CELL), theme.color(theme.SURFACE))
        for y, row in enumerate(self.grid):
            for x, kind in enumerate(row):
                if kind is not None:
                    square(x * CELL, y * CELL, kind)
        if not self.over:
            for x, y in self.cells:
                square((self.px + x) * CELL, (self.py + y) * CELL, self.kind)
        left = WELL + 12
        self.text(p, QRectF(left, 10, 100, 20), "Next", 13, theme.TEXT_MUTED, align=Qt.AlignmentFlag.AlignLeft)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y in SHAPES[self.upcoming]:
            p.setBrush(theme.color(palette[self.upcoming]))
            p.drawRoundedRect(QRectF(left + x * 22 + 1, 40 + y * 22 + 1, 20, 20), 3, 3)
        self.text(p, QRectF(left, 110, 100, 20), f"Rows {self.rows_cleared}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignLeft)
        self.text(p, QRectF(left, 132, 100, 20), f"Speed {self.speed_level + 1}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignLeft)
