"""Snake: steer to the food, grow, and avoid the walls and your own tail."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

N = 20  # Squares along each side
CELL = 20.0
TURNS = {
    K.Key_Left: (-1, 0), K.Key_A: (-1, 0), K.Key_Right: (1, 0), K.Key_D: (1, 0),
    K.Key_Up: (0, -1), K.Key_W: (0, -1), K.Key_Down: (0, 1), K.Key_S: (0, 1),
}


class Snake(Game):
    title = "Snake"
    controls = "Arrow keys or WASD to steer."
    board_size = (N * CELL, N * CELL)

    def reset(self) -> None:
        middle = N // 2
        self.body = [(middle - i, middle) for i in range(3)]  # Head first
        self.direction = (1, 0)
        self.turns: list[tuple[int, int]] = []  # Turns asked for but not yet made
        self.interval = 0.14  # Seconds a step
        self._wait = 0.0
        self.food = self._place_food()

    def _place_food(self) -> tuple[int, int] | None:
        free = [(x, y) for x in range(N) for y in range(N) if (x, y) not in self.body]
        return self.rng.choice(free) if free else None

    def key(self, key: int) -> None:
        turn = TURNS.get(key)
        if turn is None or len(self.turns) >= 2:
            return
        last = self.turns[-1] if self.turns else self.direction
        if turn != last and (turn[0] + last[0], turn[1] + last[1]) != (0, 0):  # No turning straight back
            self.turns.append(turn)

    def tick(self, dt: float) -> None:
        self._wait += dt
        while self._wait >= self.interval and not self.over:
            self._wait -= self.interval
            self.step()

    def step(self) -> None:
        if self.turns:
            self.direction = self.turns.pop(0)
        head = (self.body[0][0] + self.direction[0], self.body[0][1] + self.direction[1])
        eating = head == self.food
        solid = self.body if eating else self.body[:-1]  # The tail's square is free: it moves on this step.
        if not (0 <= head[0] < N and 0 <= head[1] < N) or head in solid:
            self.end()
            return
        self.body.insert(0, head)
        if not eating:
            self.body.pop()
            return
        self.add_score(10)
        self.interval = max(0.06, self.interval * 0.97)
        self.food = self._place_food()
        if self.food is None:
            self.end("You filled the board")

    def draw(self, p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        if self.food is not None:
            p.setBrush(theme.color(theme.CHARGE))
            p.drawEllipse(QRectF(self.food[0] * CELL + 3, self.food[1] * CELL + 3, CELL - 6, CELL - 6))
        for i, (x, y) in enumerate(self.body):
            p.setBrush(theme.color(theme.ACCENT_HOVER if i == 0 else theme.ACCENT))
            p.drawRoundedRect(QRectF(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2), 4, 4)
