"""Paddle tennis for two players at one keyboard: W and S on the left, the arrows on the right. First to 11."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from equilibrium import theme
from equilibrium.ui.games.base import Game, K, clamp

WIDTH, HEIGHT = 500.0, 320.0
PADDLE_W, PADDLE_H = 8.0, 60.0
PADDLE_X = (16.0, WIDTH - 16.0 - PADDLE_W)  # Left edge of each player's paddle
PADDLE_SPEED = 300.0
KEYS = ((K.Key_W, K.Key_S), (K.Key_Up, K.Key_Down))  # Up and down, for each player
NAMES = ("Left", "Right")
RADIUS = 6.0
SERVE_SPEED, TOP_SPEED = 240.0, 520.0
WIN = 11


class Tennis(Game):
    title = "Paddle tennis (2 players)"
    controls = "Two players. Left: W and S. Right: up and down arrows. First to 11 wins."
    score_name = "Longest rally"  # There is no one player to score, so the best kept is the longest rally.
    board_size = (WIDTH, HEIGHT)

    def reset(self) -> None:
        self.points = [0, 0]  # Left, right
        self.paddles = [HEIGHT / 2, HEIGHT / 2]  # Their centres
        self.rally = 0  # Hits since the serve
        self._serve(1)

    def _serve(self, direction: int) -> None:
        self.rally = 0
        self.ball_x, self.ball_y = WIDTH / 2, HEIGHT / 2
        angle = self.rng.uniform(-0.4, 0.4)
        self.vx, self.vy = direction * SERVE_SPEED * math.cos(angle), SERVE_SPEED * math.sin(angle)

    def tick(self, dt: float) -> None:
        for player, (up, down) in enumerate(KEYS):
            move = (down in self.held) - (up in self.held)
            self.paddles[player] = clamp(self.paddles[player] + move * PADDLE_SPEED * dt,
                                         PADDLE_H / 2, HEIGHT - PADDLE_H / 2)
        steps = max(1, math.ceil(math.hypot(self.vx, self.vy) * dt / 4))
        for _ in range(steps):
            if self._advance(dt / steps):
                break

    def _advance(self, dt: float) -> bool:
        """Move the ball. Returns True when the point is over."""
        self.ball_x += self.vx * dt
        self.ball_y += self.vy * dt
        if self.ball_y < RADIUS:
            self.ball_y, self.vy = RADIUS, abs(self.vy)
        elif self.ball_y > HEIGHT - RADIUS:
            self.ball_y, self.vy = HEIGHT - RADIUS, -abs(self.vy)

        left, right = PADDLE_X
        if self.vx < 0 and left <= self.ball_x - RADIUS <= left + PADDLE_W:
            self._hit(0, 1, left + PADDLE_W + RADIUS)
        elif self.vx > 0 and right <= self.ball_x + RADIUS <= right + PADDLE_W:
            self._hit(1, -1, right - RADIUS)

        if -RADIUS <= self.ball_x <= WIDTH + RADIUS:
            return False
        winner = 0 if self.ball_x > WIDTH else 1
        self.points[winner] += 1
        if self.points[winner] == WIN:
            self.end(f"{NAMES[winner]} wins {max(self.points)}–{min(self.points)}")
        else:
            self._serve(1 if winner == 0 else -1)  # Towards whoever lost the point
        return True

    def _hit(self, player: int, direction: int, x: float) -> None:
        reach = PADDLE_H / 2 + RADIUS
        offset = self.ball_y - self.paddles[player]
        if abs(offset) > reach:
            return
        # Where the ball meets the paddle decides the angle it leaves at, and each hit is a little faster.
        speed = min(TOP_SPEED, math.hypot(self.vx, self.vy) * 1.05)
        angle = offset / reach * 0.9
        self.vx, self.vy = direction * speed * math.cos(angle), speed * math.sin(angle)
        self.ball_x = x
        self.rally += 1
        self.set_score(max(self.score, self.rally))

    def draw(self, p: QPainter) -> None:
        colours = (theme.ACCENT, theme.CHARGE)  # One for each player
        p.setPen(QPen(theme.color(theme.BORDER), 2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(WIDTH / 2, 0), QPointF(WIDTH / 2, HEIGHT))
        self.text(p, QRectF(0, 10, WIDTH / 2 - 20, 40), str(self.points[0]), 32, colours[0], bold=True,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.text(p, QRectF(WIDTH / 2 + 20, 10, WIDTH / 2 - 20, 40), str(self.points[1]), 32, colours[1], bold=True,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.text(p, QRectF(PADDLE_X[0] + 16, HEIGHT - 24, 120, 18), "W / S", 12, theme.TEXT_FAINT,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text(p, QRectF(PADDLE_X[1] - 128, HEIGHT - 24, 120, 18), "↑ / ↓", 12, theme.TEXT_FAINT,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.setPen(Qt.PenStyle.NoPen)
        for player, centre in enumerate(self.paddles):
            p.setBrush(theme.color(colours[player]))
            p.drawRoundedRect(QRectF(PADDLE_X[player], centre - PADDLE_H / 2, PADDLE_W, PADDLE_H), 3, 3)
        p.setBrush(theme.color(theme.TEXT))
        p.drawEllipse(QPointF(self.ball_x, self.ball_y), RADIUS, RADIUS)
