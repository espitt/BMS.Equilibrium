"""Mine sweeper: uncover every square that has no mine. A number says how many mines touch that square."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPolygonF

from equilibrium import theme
from equilibrium.ui.games.base import Game, colours

SIDE = 480.0
SIZES = ((9, 10), (12, 22), (16, 40))  # Squares along a side, mines
TIME_BONUS = 300  # Points for clearing the field at once, less one for each second taken
Cell = tuple[int, int]


class Mines(Game):
    title = "Mine sweeper"
    controls = "Click to uncover a square. Right-click to flag a mine. Click a number to uncover around it."
    board_size = (SIDE, SIDE)
    levels = ("Small", "Medium", "Large")
    realtime = False

    def reset(self) -> None:
        self.n, self.count = SIZES[self.level]
        self.mines: set[Cell] | None = None  # Laid at the first click, so that click is always safe
        self.shown: set[Cell] = set()
        self.flags: set[Cell] = set()
        self.hit: Cell | None = None  # The mine that ended the game

    def around(self, cell: Cell) -> list[Cell]:
        x, y = cell
        return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and 0 <= x + dx < self.n and 0 <= y + dy < self.n]

    def number(self, cell: Cell) -> int:
        return sum(1 for other in self.around(cell) if other in self.mines)

    def lay(self, first: Cell) -> None:
        clear = {first, *self.around(first)}
        free = [(x, y) for x in range(self.n) for y in range(self.n) if (x, y) not in clear]
        self.mines = set(self.rng.sample(free, self.count))

    def uncover(self, cell: Cell) -> None:
        if cell in self.flags or cell in self.shown:
            return
        if self.mines is None:
            self.lay(cell)
        if cell in self.mines:
            self.hit = cell
            self.end("You hit a mine")
            return
        before = len(self.shown)
        waiting = [cell]
        while waiting:
            cell = waiting.pop()
            if cell in self.shown:
                continue
            self.shown.add(cell)
            if self.number(cell) == 0:  # Nothing near: its neighbours are safe too
                waiting += [other for other in self.around(cell) if other not in self.shown | self.flags]
        self.add_score(len(self.shown) - before)
        if len(self.shown) == self.n * self.n - self.count:
            self.add_score(max(0, TIME_BONUS - int(self.elapsed)))
            self.end("Field cleared")

    def uncover_around(self, cell: Cell) -> None:
        """Uncover a number's other neighbours, once as many flags as its number are around it."""
        around = self.around(cell)
        if self.number(cell) and self.number(cell) == sum(1 for other in around if other in self.flags):
            for other in around:
                if not self.over:
                    self.uncover(other)

    def flag(self, cell: Cell) -> None:
        if cell not in self.shown:
            self.flags ^= {cell}

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        size = SIDE / self.n
        cell = (int(pos.x() // size), int(pos.y() // size))
        if not (0 <= cell[0] < self.n and 0 <= cell[1] < self.n):
            return
        if button == Qt.MouseButton.RightButton:
            self.flag(cell)
        elif cell in self.shown:
            self.uncover_around(cell)
        else:
            self.uncover(cell)

    def draw(self, p: QPainter) -> None:
        size = SIDE / self.n
        palette = colours()
        for x in range(self.n):
            for y in range(self.n):
                cell = (x, y)
                rect = QRectF(x * size + 1, y * size + 1, size - 2, size - 2)
                p.setPen(Qt.PenStyle.NoPen)
                if cell in self.shown:
                    number = self.number(cell)
                    if number:
                        self.text(p, rect, str(number), int(size * 0.55), palette[(number - 1) % len(palette)],
                                  bold=True)
                    continue
                p.setBrush(theme.color(theme.SURFACE_3))
                p.drawRoundedRect(rect, 3, 3)
                if self.over and self.mines and cell in self.mines:
                    p.setBrush(theme.color(theme.TEXT if cell == self.hit else theme.TEXT_MUTED))
                    p.drawEllipse(rect.center(), size * 0.22, size * 0.22)
                elif cell in self.flags:
                    p.setBrush(theme.color(theme.ACCENT))
                    left, top = rect.left() + size * 0.3, rect.top() + size * 0.2
                    p.drawPolygon(QPolygonF([QPointF(left, top), QPointF(left + size * 0.4, top + size * 0.2),
                                             QPointF(left, top + size * 0.4)]))
                    p.drawRect(QRectF(left - 2, top, 2, size * 0.6))
