"""Endless runner: jump the blocks as the ground speeds up."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

WIDTH, HEIGHT = 600.0, 240.0
GROUND = 200.0
RUNNER_X, RUNNER_W, RUNNER_H = 80.0, 24.0, 30.0
JUMP, GRAVITY = 560.0, 1500.0
START_SPEED, TOP_SPEED = 240.0, 520.0
JUMP_KEYS = (K.Key_Space, K.Key_Up, K.Key_W)


class Runner(Game):
    title = "Endless runner"
    controls = "Space, the up arrow or a click jumps."
    board_size = (WIDTH, HEIGHT)

    def reset(self) -> None:
        self.lift = 0.0  # How far the runner's feet are above the ground
        self.vy = 0.0
        self.distance = 0.0
        self.blocks: list[list[float]] = []  # Left edge, width, height
        self.gap = 400.0  # Distance until the next block appears

    @property
    def speed(self) -> float:
        return min(TOP_SPEED, START_SPEED + self.distance / 40)

    def jump(self) -> None:
        if self.lift == 0:
            self.vy = JUMP

    def key(self, key: int) -> None:
        if key in JUMP_KEYS:
            self.jump()

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        self.jump()

    def tick(self, dt: float) -> None:
        speed = self.speed
        self.distance += speed * dt
        self.set_score(int(self.distance / 20))
        if self.lift > 0 or self.vy > 0:
            self.vy -= GRAVITY * dt
            self.lift = max(0.0, self.lift + self.vy * dt)
            if self.lift == 0:
                self.vy = 0.0

        for block in self.blocks:
            block[0] -= speed * dt
        self.blocks = [block for block in self.blocks if block[0] + block[1] > 0]
        self.gap -= speed * dt
        if self.gap <= 0:
            self.blocks.append([WIDTH, self.rng.choice((18.0, 28.0, 44.0)), self.rng.choice((24.0, 36.0, 46.0))])
            self.gap = speed * self.rng.uniform(0.9, 1.6)  # Always time to land and jump again

        if any(left < RUNNER_X + RUNNER_W and left + width > RUNNER_X and self.lift < height
               for left, width, height in self.blocks):
            self.end()

    def draw(self, p: QPainter) -> None:
        p.setPen(QPen(theme.color(theme.BORDER), 2))
        p.drawLine(QPointF(0, GROUND), QPointF(WIDTH, GROUND))
        p.setPen(QPen(theme.color(theme.BORDER), 1))
        offset = self.distance % 60
        for i in range(12):  # Marks on the ground, so it is seen to move
            x = i * 60 - offset
            p.drawLine(QPointF(x, GROUND + 10), QPointF(x + 18, GROUND + 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.TEXT_MUTED))
        for left, width, height in self.blocks:
            p.drawRoundedRect(QRectF(left, GROUND - height, width, height), 3, 3)
        p.setBrush(theme.color(theme.ACCENT))
        p.drawRoundedRect(QRectF(RUNNER_X, GROUND - self.lift - RUNNER_H, RUNNER_W, RUNNER_H), 5, 5)
