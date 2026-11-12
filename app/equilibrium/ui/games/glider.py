"""Gap glider: each tap lifts the glider, which otherwise falls. Thread it through the gaps in the walls."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPolygonF

from equilibrium import theme
from equilibrium.ui.games.base import Game, K

WIDTH, HEIGHT = 400.0, 500.0
GLIDER_X, RADIUS = 110.0, 11.0
LIFT, GRAVITY = 370.0, 1250.0  # Upward speed given by a tap, and the pull back down
WALL_W, SPACING = 54.0, 215.0  # Width of a wall, and the distance from one wall to the next
START_GAP, SMALLEST_GAP = 150.0, 112.0  # The gaps narrow as the score rises
START_SPEED, TOP_SPEED = 150.0, 215.0
EDGE = 50.0  # A gap is never closer than this to the top or bottom
TAP_KEYS = (K.Key_Space, K.Key_Up, K.Key_W)


class Glider(Game):
    title = "Gap glider"
    controls = "Space, the up arrow or a click lifts the glider. Fly through the gaps."
    board_size = (WIDTH, HEIGHT)

    def reset(self) -> None:
        self.altitude = HEIGHT / 2  # The glider's centre, measured down from the top like everything drawn
        self.vy = -LIFT * 0.6  # A small hop to begin, so it does not drop at once
        self.walls: list[list[float]] = []  # Left edge, top of the gap, height of the gap
        self.next_wall = 0.0  # Distance to go before another wall appears
        self.passed = 0

    @property
    def speed(self) -> float:
        return min(TOP_SPEED, START_SPEED + 3 * self.passed)

    def tap(self) -> None:
        self.vy = -LIFT

    def key(self, key: int) -> None:
        if key in TAP_KEYS:
            self.tap()

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        self.tap()

    def tick(self, dt: float) -> None:
        self.vy += GRAVITY * dt
        self.altitude += self.vy * dt
        travel = self.speed * dt
        for wall in self.walls:
            before = wall[0] + WALL_W
            wall[0] -= travel
            if before >= GLIDER_X - RADIUS > wall[0] + WALL_W:  # The glider has just cleared it
                self.passed += 1
                self.add_score(1)
        self.walls = [wall for wall in self.walls if wall[0] + WALL_W > 0]
        self.next_wall -= travel
        if self.next_wall <= 0:
            gap = max(SMALLEST_GAP, START_GAP - 2 * self.passed)
            self.walls.append([WIDTH, self.rng.uniform(EDGE, HEIGHT - EDGE - gap), gap])
            self.next_wall = SPACING
        if self.crashed():
            self.end()

    def crashed(self) -> bool:
        if self.altitude < RADIUS or self.altitude > HEIGHT - RADIUS:
            return True
        for left, top, gap in self.walls:
            if left - RADIUS < GLIDER_X < left + WALL_W + RADIUS:
                if self.altitude - RADIUS < top or self.altitude + RADIUS > top + gap:
                    return True
        return False

    def draw(self, p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.SURFACE_3))
        for left, top, gap in self.walls:
            p.drawRoundedRect(QRectF(left, -8, WALL_W, top + 8), 6, 6)
            p.drawRoundedRect(QRectF(left, top + gap, WALL_W, HEIGHT - top - gap + 8), 6, 6)
        p.setBrush(theme.color(theme.TEXT_MUTED))
        for left, top, gap in self.walls:  # A darker lip at each end of a gap
            p.drawRoundedRect(QRectF(left - 3, top - 10, WALL_W + 6, 10), 3, 3)
            p.drawRoundedRect(QRectF(left - 3, top + gap, WALL_W + 6, 10), 3, 3)

        # A paper dart, nose up when rising and down when falling
        p.save()
        p.translate(GLIDER_X, self.altitude)
        p.rotate(max(-25.0, min(55.0, self.vy / 9)))
        p.setBrush(theme.color(theme.ACCENT))
        p.drawPolygon(QPolygonF([QPointF(15, 0), QPointF(-12, -10), QPointF(-6, 0), QPointF(-12, 10)]))
        p.setBrush(theme.color(theme.CHARGE))
        p.drawPolygon(QPolygonF([QPointF(15, 0), QPointF(-6, 0), QPointF(-12, 10)]))
        p.restore()
        self.text(p, QRectF(0, 14, WIDTH, 44), str(self.score), 34, theme.TEXT_FAINT, bold=True)
