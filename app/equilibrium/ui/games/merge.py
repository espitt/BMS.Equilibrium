"""Number merge: slide every tile one way. Two tiles with the same number join into one of twice the value."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

N = 4
SIDE = 400.0
GAP = 10.0
MOVES = {
    K.Key_Left: (-1, 0), K.Key_A: (-1, 0), K.Key_Right: (1, 0), K.Key_D: (1, 0),
    K.Key_Up: (0, -1), K.Key_W: (0, -1), K.Key_Down: (0, 1), K.Key_S: (0, 1),
}


def slide(line: list[int]) -> tuple[list[int], int]:
    """Slide a row of tiles towards its start. Returns the new row and the points earned."""
    tiles = [value for value in line if value]
    out, points, i = [], 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:  # Each tile joins only once in a move
            out.append(tiles[i] * 2)
            points += tiles[i] * 2
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    return out + [0] * (len(line) - len(out)), points


class Merge(Game):
    title = "Number merge"
    controls = "Arrow keys or WASD slide all the tiles."
    board_size = (SIDE, SIDE)
    realtime = False

    def reset(self) -> None:
        self.grid = [[0] * N for _ in range(N)]  # Rows of tile values; 0 is an empty square
        self.add_tile()
        self.add_tile()

    def add_tile(self) -> None:
        empty = [(x, y) for y in range(N) for x in range(N) if not self.grid[y][x]]
        if empty:
            x, y = self.rng.choice(empty)
            self.grid[y][x] = 4 if self.rng.random() < 0.1 else 2

    def _lines(self, dx: int, dy: int) -> list[list[tuple[int, int]]]:
        """The squares of each row or column, starting from the side the tiles slide towards."""
        order = range(N) if dx + dy < 0 else range(N - 1, -1, -1)
        if dx:
            return [[(x, y) for x in order] for y in range(N)]
        return [[(x, y) for y in order] for x in range(N)]

    def move(self, dx: int, dy: int) -> bool:
        """Slide every tile. Returns False if nothing could move."""
        moved, points = False, 0
        for squares in self._lines(dx, dy):
            before = [self.grid[y][x] for x, y in squares]
            after, earned = slide(before)
            points += earned
            moved = moved or after != before
            for (x, y), value in zip(squares, after):
                self.grid[y][x] = value
        if not moved:
            return False
        self.add_score(points)
        self.add_tile()
        if not self.can_move():
            self.end("No moves left")
        return True

    def can_move(self) -> bool:
        grid = self.grid
        return any(not grid[y][x]
                   or (x + 1 < N and grid[y][x] == grid[y][x + 1])
                   or (y + 1 < N and grid[y][x] == grid[y + 1][x])
                   for y in range(N) for x in range(N))

    def key(self, key: int) -> None:
        if key in MOVES:
            self.move(*MOVES[key])

    def draw(self, p: QPainter) -> None:
        size = (SIDE - GAP * (N + 1)) / N
        p.setPen(Qt.PenStyle.NoPen)
        for y in range(N):
            for x in range(N):
                rect = QRectF(GAP + x * (size + GAP), GAP + y * (size + GAP), size, size)
                value = self.grid[y][x]
                if not value:
                    p.setBrush(theme.color(theme.SURFACE))
                    p.drawRoundedRect(rect, 8, 8)
                    continue
                strength = min(1.0, math.log2(value) / 11)  # Full colour at 2048
                p.setBrush(theme.mix(theme.SURFACE_3, theme.ACCENT, strength))
                p.drawRoundedRect(rect, 8, 8)
                self.text(p, rect, str(value), 34 if value < 1000 else 26,
                          theme.ON_ACCENT if strength > 0.45 else theme.TEXT, bold=True)
                p.setPen(Qt.PenStyle.NoPen)
