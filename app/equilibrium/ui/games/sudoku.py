"""Sudoku: fill the grid so every row, column and box holds each of 1 to 9 once."""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

CELL = 50.0
SIDE = 9 * CELL
BLANKS = (36, 46, 52)  # Squares left empty at each level
TIME_BONUS = 1800  # Points for finishing at once, less one for each second taken
STEPS = {K.Key_Left: -1, K.Key_Right: 1, K.Key_Up: -9, K.Key_Down: 9}
CLEAR_KEYS = (K.Key_0, K.Key_Backspace, K.Key_Delete)


def _peers(i: int) -> set[int]:
    row, column = divmod(i, 9)
    box = [(row // 3 * 3 + r) * 9 + column // 3 * 3 + c for r in range(3) for c in range(3)]
    return {*(row * 9 + c for c in range(9)), *(r * 9 + column for r in range(9)), *box} - {i}


PEERS = [_peers(i) for i in range(81)]  # The squares that may not repeat each square's number


def count_solutions(grid: list[int], limit: int = 2) -> int:
    """How many ways the grid (0 for an empty square) can be finished, counting no further than limit."""
    best: tuple[int, list[int]] | None = None
    for i in range(81):
        if grid[i]:
            continue
        used = {grid[peer] for peer in PEERS[i]}
        choices = [digit for digit in range(1, 10) if digit not in used]
        if not choices:
            return 0
        if best is None or len(choices) < len(best[1]):  # Try the most constrained square first
            best = (i, choices)
    if best is None:
        return 1
    i, choices = best
    total = 0
    for digit in choices:
        grid[i] = digit
        total += count_solutions(grid, limit - total)
        grid[i] = 0
        if total >= limit:
            break
    return total


def solved_grid(rng: random.Random) -> list[int]:
    """A complete valid grid: a regular pattern with its rows, columns and digits shuffled."""
    def shuffled(items: range) -> list[int]:
        return rng.sample(items, len(items))

    rows = [band * 3 + row for band in shuffled(range(3)) for row in shuffled(range(3))]
    columns = [stack * 3 + column for stack in shuffled(range(3)) for column in shuffled(range(3))]
    digits = shuffled(range(1, 10))
    return [digits[(3 * (row % 3) + row // 3 + column) % 9] for row in rows for column in columns]


def make_puzzle(rng: random.Random, blanks: int) -> tuple[list[int], list[int]]:
    """(puzzle, solution). Squares are emptied only while the puzzle keeps exactly one solution."""
    solution = solved_grid(rng)
    puzzle = list(solution)
    removed = 0
    for i in rng.sample(range(81), 81):
        if removed == blanks:
            break
        puzzle[i] = 0
        if count_solutions(puzzle) == 1:
            removed += 1
        else:
            puzzle[i] = solution[i]
    return puzzle, solution


class Sudoku(Game):
    title = "Sudoku"
    controls = "Click a square, then type 1 to 9. Backspace clears it. Arrow keys move."
    board_size = (SIDE, SIDE)
    levels = ("Easy", "Medium", "Hard")
    realtime = False

    def reset(self) -> None:
        puzzle, self.solution = make_puzzle(self.rng, BLANKS[self.level])
        self.cells = puzzle
        self.given = [bool(value) for value in puzzle]
        self.selected: int | None = None

    def enter(self, i: int, digit: int) -> None:
        """Put a digit in a square, or 0 to empty it. Squares given at the start stay as they are."""
        if self.given[i]:
            return
        self.cells[i] = digit
        right = sum(1 for j in range(81) if not self.given[j] and self.cells[j] == self.solution[j])
        self.set_score(10 * right)
        if self.cells == self.solution:
            self.add_score(max(0, TIME_BONUS - int(self.elapsed)))
            self.end("Solved")

    def key(self, key: int) -> None:
        if self.selected is None:
            self.selected = 0
            return
        if key in STEPS:
            column = self.selected % 9
            if (key == K.Key_Left and column == 0) or (key == K.Key_Right and column == 8):
                return
            if 0 <= self.selected + STEPS[key] < 81:
                self.selected += STEPS[key]
        elif key in CLEAR_KEYS:
            self.enter(self.selected, 0)
        elif K.Key_1 <= key <= K.Key_9:
            self.enter(self.selected, key - K.Key_0)

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        column, row = int(pos.x() // CELL), int(pos.y() // CELL)
        if 0 <= column < 9 and 0 <= row < 9:
            self.selected = row * 9 + column

    def draw(self, p: QPainter) -> None:
        chosen = self.cells[self.selected] if self.selected is not None else 0
        for i, value in enumerate(self.cells):
            row, column = divmod(i, 9)
            rect = QRectF(column * CELL, row * CELL, CELL, CELL)
            if i == self.selected:
                p.fillRect(rect, theme.color(theme.ACCENT_TINT))
            elif self.selected is not None and (i in PEERS[self.selected] or (value and value == chosen)):
                p.fillRect(rect, theme.color(theme.SURFACE))
            if not value:
                continue
            if self.given[i]:
                self.text(p, rect, str(value), 24, theme.TEXT, bold=True)
            else:  # A wrong number is purple, not red: red means a fault in this app
                self.text(p, rect, str(value), 24, theme.ACCENT if value == self.solution[i] else theme.BALANCE)
        for line in range(10):
            heavy = line % 3 == 0
            p.setPen(QPen(theme.color(theme.TEXT_MUTED if heavy else theme.BORDER), 2 if heavy else 1))
            p.drawLine(QPointF(line * CELL, 0), QPointF(line * CELL, SIDE))
            p.drawLine(QPointF(0, line * CELL), QPointF(SIDE, line * CELL))
