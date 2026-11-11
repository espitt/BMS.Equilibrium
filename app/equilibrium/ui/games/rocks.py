"""Rock shooter: fly a small ship, and break up the drifting rocks before they hit you."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

SIDE = 500.0
RADIUS = {3: 36.0, 2: 22.0, 1: 12.0}  # By rock size
POINTS = {3: 20, 2: 50, 1: 100}
SHIP_RADIUS = 10.0
TURN, THRUST, DRAG = 3.5, 220.0, 0.4
SHOT_SPEED, SHOT_LIFE, RELOAD = 420.0, 1.0, 0.25
SAFE_SECONDS = 2.0  # After losing a life, nothing can hit the ship for this long


@dataclass
class Rock:
    x: float
    y: float
    vx: float
    vy: float
    size: int
    shape: list[float]  # How far each corner is from the middle, as a share of the radius


class Rocks(Game):
    title = "Rock shooter"
    controls = "Left and right turn, up fires the engine, Space shoots."
    board_size = (SIDE, SIDE)

    def reset(self) -> None:
        self.lives = 3
        self.wave = 0
        self.shots: list[list[float]] = []  # x, y, vx, vy, seconds left
        self.rocks: list[Rock] = []
        self.reload = 0.0
        self._centre_ship()
        self.safe = 0.0
        self._next_wave()

    def _centre_ship(self) -> None:
        self.ship_x = self.ship_y = SIDE / 2
        self.vx = self.vy = 0.0
        self.angle = 0.0  # Radians clockwise from straight up
        self.safe = SAFE_SECONDS

    def _rock(self, x: float, y: float, size: int, speed: float) -> Rock:
        heading = self.rng.uniform(0, math.tau)
        shape = [self.rng.uniform(0.75, 1.15) for _ in range(10)]
        return Rock(x, y, speed * math.cos(heading), speed * math.sin(heading), size, shape)

    def _next_wave(self) -> None:
        self.wave += 1
        for _ in range(2 + self.wave):
            while True:  # Not on top of the ship
                x, y = self.rng.uniform(0, SIDE), self.rng.uniform(0, SIDE)
                if math.hypot(x - self.ship_x, y - self.ship_y) > 150:
                    break
            self.rocks.append(self._rock(x, y, 3, self.rng.uniform(30, 70)))

    def shoot(self) -> None:
        if self.reload > 0:
            return
        self.reload = RELOAD
        dx, dy = math.sin(self.angle), -math.cos(self.angle)
        self.shots.append([self.ship_x + dx * SHIP_RADIUS, self.ship_y + dy * SHIP_RADIUS,
                           self.vx + dx * SHOT_SPEED, self.vy + dy * SHOT_SPEED, SHOT_LIFE])

    def tick(self, dt: float) -> None:
        held = self.held
        self.angle += ((K.Key_Right in held or K.Key_D in held) - (K.Key_Left in held or K.Key_A in held)) * TURN * dt
        if K.Key_Up in held or K.Key_W in held:
            self.vx += math.sin(self.angle) * THRUST * dt
            self.vy -= math.cos(self.angle) * THRUST * dt
        self.vx *= 1 - DRAG * dt
        self.vy *= 1 - DRAG * dt
        self.ship_x, self.ship_y = (self.ship_x + self.vx * dt) % SIDE, (self.ship_y + self.vy * dt) % SIDE
        self.reload = max(0.0, self.reload - dt)
        self.safe = max(0.0, self.safe - dt)
        if K.Key_Space in held:
            self.shoot()

        for shot in self.shots:
            shot[0], shot[1] = (shot[0] + shot[2] * dt) % SIDE, (shot[1] + shot[3] * dt) % SIDE
            shot[4] -= dt
        self.shots = [shot for shot in self.shots if shot[4] > 0]
        for rock in self.rocks:
            rock.x, rock.y = (rock.x + rock.vx * dt) % SIDE, (rock.y + rock.vy * dt) % SIDE
        self._collide()

    def _collide(self) -> None:
        for shot in list(self.shots):
            rock = next((r for r in self.rocks if math.hypot(r.x - shot[0], r.y - shot[1]) < RADIUS[r.size]), None)
            if rock is not None:
                self.shots.remove(shot)
                self.split(rock)
        if self.safe == 0 and any(math.hypot(r.x - self.ship_x, r.y - self.ship_y) < RADIUS[r.size] + SHIP_RADIUS
                                  for r in self.rocks):
            self.lives -= 1
            if self.lives == 0:
                self.end()
                return
            self._centre_ship()
        if not self.rocks:
            self.add_score(200)
            self._next_wave()

    def split(self, rock: Rock) -> None:
        self.rocks.remove(rock)
        self.add_score(POINTS[rock.size])
        if rock.size > 1:
            speed = math.hypot(rock.vx, rock.vy) * 1.4
            self.rocks += [self._rock(rock.x, rock.y, rock.size - 1, speed) for _ in range(2)]

    def draw(self, p: QPainter) -> None:
        p.setBrush(theme.color(theme.SURFACE_3))
        p.setPen(QPen(theme.color(theme.TEXT_MUTED), 1.5))
        for rock in self.rocks:
            corners = len(rock.shape)
            p.drawPolygon(QPolygonF([
                QPointF(rock.x + RADIUS[rock.size] * share * math.cos(math.tau * i / corners),
                        rock.y + RADIUS[rock.size] * share * math.sin(math.tau * i / corners))
                for i, share in enumerate(rock.shape)]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.CHARGE))
        for shot in self.shots:
            p.drawEllipse(QPointF(shot[0], shot[1]), 2.5, 2.5)
        if not self.over and int(self.safe * 8) % 2 == 0:  # Blinks while nothing can hit it
            p.save()
            p.translate(self.ship_x, self.ship_y)
            p.rotate(math.degrees(self.angle))
            p.setBrush(theme.color(theme.ACCENT))
            p.drawPolygon(QPolygonF([QPointF(0, -13), QPointF(9, 10), QPointF(0, 5), QPointF(-9, 10)]))
            p.restore()
        self.text(p, QRectF(10, 8, SIDE - 20, 24), f"Wave {self.wave}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text(p, QRectF(10, 8, SIDE - 20, 24), f"Lives {self.lives}", 13, theme.TEXT_MUTED,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
