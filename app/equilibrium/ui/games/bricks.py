"""Brick breaker: keep the ball in play with the paddle and clear every brick."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter

from equilibrium import theme
from equilibrium.ui.games.base import Game, K, clamp, colours

WIDTH, HEIGHT = 400.0, 500.0
PADDLE_W, PADDLE_H, PADDLE_Y = 70.0, 10.0, 470.0
PADDLE_SPEED = 380.0
RADIUS = 6.0
COLUMNS = 8
BRICK_H, GAP, TOP = 16.0, 4.0, 50.0


class Bricks(Game):
    title = "Brick breaker"
    controls = "Left and right arrows or the mouse move the paddle. Space or a click launches the ball."
    board_size = (WIDTH, HEIGHT)

    def reset(self) -> None:
        self.lives = 3
        self.stage = 1
        self.paddle = WIDTH / 2  # Its centre
        self._build()
        self._serve()

    def _build(self) -> None:
        rows = min(4 + self.stage, 8)
        width = (WIDTH - GAP * (COLUMNS + 1)) / COLUMNS
        self.bricks = [(QRectF(GAP + c * (width + GAP), TOP + r * (BRICK_H + GAP), width, BRICK_H), r)
                       for r in range(rows) for c in range(COLUMNS)]

    def _serve(self) -> None:
        self.stuck = True  # Resting on the paddle until launched
        self.ball_x, self.ball_y = self.paddle, PADDLE_Y - RADIUS
        self.vx = self.vy = 0.0

    def launch(self) -> None:
        if not self.stuck:
            return
        self.stuck = False
        speed = 240 + 20 * self.stage
        angle = self.rng.uniform(-0.5, 0.5)
        self.vx, self.vy = speed * math.sin(angle), -speed * math.cos(angle)

    def key(self, key: int) -> None:
        if key == K.Key_Space:
            self.launch()

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        self.launch()

    def mouse(self, pos: QPointF) -> None:
        self.paddle = clamp(pos.x(), PADDLE_W / 2, WIDTH - PADDLE_W / 2)

    def tick(self, dt: float) -> None:
        move = (K.Key_Right in self.held or K.Key_D in self.held) - (K.Key_Left in self.held or K.Key_A in self.held)
        self.paddle = clamp(self.paddle + move * PADDLE_SPEED * dt, PADDLE_W / 2, WIDTH - PADDLE_W / 2)
        if self.stuck:
            self.ball_x = self.paddle
            return
        # Small steps, so a fast ball cannot pass through a brick between two frames.
        steps = max(1, math.ceil(math.hypot(self.vx, self.vy) * dt / 4))
        for _ in range(steps):
            self._advance(dt / steps)
            if self.stuck or self.over:
                break

    def _advance(self, dt: float) -> None:
        self.ball_x += self.vx * dt
        self.ball_y += self.vy * dt
        if self.ball_x < RADIUS:
            self.ball_x, self.vx = RADIUS, abs(self.vx)
        elif self.ball_x > WIDTH - RADIUS:
            self.ball_x, self.vx = WIDTH - RADIUS, -abs(self.vx)
        if self.ball_y < RADIUS:
            self.ball_y, self.vy = RADIUS, abs(self.vy)

        reach = PADDLE_W / 2 + RADIUS
        level = PADDLE_Y - RADIUS <= self.ball_y <= PADDLE_Y + PADDLE_H
        if self.vy > 0 and level and abs(self.ball_x - self.paddle) <= reach:
            # Where the ball lands on the paddle decides the angle it leaves at.
            speed = math.hypot(self.vx, self.vy)
            angle = (self.ball_x - self.paddle) / reach * 1.1
            self.vx, self.vy = speed * math.sin(angle), -speed * math.cos(angle)
            self.ball_y = PADDLE_Y - RADIUS
        if self.ball_y > HEIGHT + RADIUS:
            self.lives -= 1
            if self.lives == 0:
                self.end()
            else:
                self._serve()
            return

        for i, (rect, _row) in enumerate(self.bricks):
            dx = self.ball_x - clamp(self.ball_x, rect.left(), rect.right())
            dy = self.ball_y - clamp(self.ball_y, rect.top(), rect.bottom())
            if dx * dx + dy * dy > RADIUS * RADIUS:
                continue
            del self.bricks[i]
            self.add_score(10)
            if abs(dx) > abs(dy):
                self.vx = math.copysign(self.vx, dx)
            elif dy:
                self.vy = math.copysign(self.vy, dy)
            else:
                self.vy = -self.vy
            break
        if not self.bricks:
            self.add_score(100)
            self.stage += 1
            self._build()
            self._serve()

    def draw(self, p: QPainter) -> None:
        palette = colours()
        p.setPen(Qt.PenStyle.NoPen)
        for rect, row in self.bricks:
            p.setBrush(theme.color(palette[row % len(palette)]))
            p.drawRoundedRect(rect, 3, 3)
        p.setBrush(theme.color(theme.ACCENT))
        p.drawRoundedRect(QRectF(self.paddle - PADDLE_W / 2, PADDLE_Y, PADDLE_W, PADDLE_H), 5, 5)
        p.setBrush(theme.color(theme.TEXT))
        p.drawEllipse(QPointF(self.ball_x, self.ball_y), RADIUS, RADIUS)
        self.text(p, QRectF(10, 8, WIDTH - 20, 24), f"Stage {self.stage}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text(p, QRectF(10, 8, WIDTH - 20, 24), f"Lives {self.lives}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
