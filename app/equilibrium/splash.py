"""Startup splash screen, shown while the app starts and checks for updates."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen

from equilibrium import personal

MIN_DURATION_MS = 2500  # Always shown at least this long, so it never just flickers.
MAX_DURATION_MS = 8000  # Never held longer than this; a slow check finishes behind the window.
ICON_SIZE = 320  # Logical pixels; images are rendered at the screen's full resolution.
PHOTO_HEIGHT = 480
PHOTO_CORNER_RADIUS = 16

# The icon's three cells charge from empty to full while the splash is up. They are full a little
# before the minimum time, so a full charge is seen before the window replaces the splash.
CHARGE_TIME = 0.85  # Share of MIN_DURATION_MS spent charging.
FRAME_MS = 16

# Where the cell fills sit in assets/icon.png, in its own pixels. Each fill is a parallelogram
# leaning to the right: its sides move CELL_SLANT pixels left for every pixel down.
ICON_ART_SIZE = 1024
ICON_BACKGROUND = "#00366a"
CELL_FILLS = ((538.7, 344.0), (513.2, 495.5), (487.7, 647.0))  # Top-left corner of each fill.
CELL_WIDTH = 159.0
CELL_HEIGHT = 33.0
CELL_SLANT = 1 / 6
CELL_MARGIN = 6.0  # How far the cover overlaps the gap between a fill and its outline.


def _ratio() -> float:
    screen = QApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def _icon_pixmap(icon: QIcon) -> QPixmap:
    ratio = _ratio()
    pixmap = icon.pixmap(ICON_SIZE, ICON_SIZE).scaled(
        round(ICON_SIZE * ratio),
        round(ICON_SIZE * ratio),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _photo_pixmap(path: Path) -> QPixmap | None:
    photo = QPixmap(str(path))
    if photo.isNull():
        return None
    ratio = _ratio()
    photo = photo.scaledToHeight(round(PHOTO_HEIGHT * ratio), Qt.TransformationMode.SmoothTransformation)
    # Rounded corners, drawn onto a transparent background.
    rounded = QPixmap(photo.size())
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    radius = PHOTO_CORNER_RADIUS * ratio
    clip.addRoundedRect(QRectF(rounded.rect()), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, photo)
    painter.end()
    rounded.setDevicePixelRatio(ratio)
    return rounded


def _charged(icon: QPixmap, charge: float) -> QPixmap:
    """The icon with its cells filled from the left up to charge (0 = empty, 1 = full)."""
    charge = min(max(charge, 0.0), 1.0)
    pixmap = QPixmap(icon)
    if charge >= 1.0:
        return pixmap
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ICON_SIZE / ICON_ART_SIZE, ICON_SIZE / ICON_ART_SIZE)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ICON_BACKGROUND))
    # Paint the background colour over the part of each fill that is not charged yet.
    above = CELL_MARGIN * CELL_SLANT
    below = (CELL_HEIGHT + CELL_MARGIN) * CELL_SLANT
    for x, y in CELL_FILLS:
        left = x - CELL_MARGIN + charge * (CELL_WIDTH + 2 * CELL_MARGIN)
        right = x + CELL_WIDTH + CELL_MARGIN
        top, bottom = y - CELL_MARGIN, y + CELL_HEIGHT + CELL_MARGIN
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(left + above, top),
                    QPointF(right + above, top),
                    QPointF(right - below, bottom),
                    QPointF(left - below, bottom),
                ]
            )
        )
    painter.end()
    return pixmap


class Splash:
    """Shows the icon until the startup work is done, then swaps it for the window.

    Call ready() when the startup work finishes. The window appears once ready() has been
    called and MIN_DURATION_MS has passed, or at MAX_DURATION_MS, whichever comes first.
    """

    def __init__(self, icon: QIcon, window: QMainWindow) -> None:
        self.window = window
        self.revealed = False
        self._ready = False
        self._min_passed = False
        self._pending: list[Callable[[], None]] = []
        # The current user's own image if they have one, otherwise the app icon, charging up.
        path = personal.asset("image")
        photo = _photo_pixmap(path) if path is not None else None
        self._icon = _icon_pixmap(icon) if photo is None else None
        self._elapsed = QElapsedTimer()
        self._charge_ms = 1.0
        self._frames = QTimer()
        self._frames.setInterval(FRAME_MS)
        self._frames.timeout.connect(self._draw_charge)
        first = photo if photo is not None else _charged(self._icon, 0.0)
        self.screen = QSplashScreen(first, Qt.WindowType.WindowStaysOnTopHint)
        # Draw only the icon itself, with no box around its transparent corners.
        self.screen.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def show(self) -> None:
        self.screen.show()
        if self._icon is not None:
            self._charge_ms = max(MIN_DURATION_MS * CHARGE_TIME, 1.0)
            self._elapsed.start()
            self._frames.start()
        QTimer.singleShot(MIN_DURATION_MS, self._on_min_passed)
        QTimer.singleShot(MAX_DURATION_MS, self.reveal)

    def _draw_charge(self) -> None:
        charge = self._elapsed.elapsed() / self._charge_ms
        self.screen.setPixmap(_charged(self._icon, charge))
        if charge >= 1.0:
            self._frames.stop()

    def ready(self) -> None:
        self._ready = True
        if self._min_passed:
            self.reveal()

    def _on_min_passed(self) -> None:
        self._min_passed = True
        if self._ready:
            self.reveal()

    def after_reveal(self, action: Callable[[], None]) -> None:
        """Run action once the window is showing (now, if it already is)."""
        if self.revealed:
            action()
        else:
            self._pending.append(action)

    def reveal(self) -> None:
        if self.revealed:
            return
        self.revealed = True
        self._frames.stop()
        self.window.showMaximized()  # The app opens filling the screen.
        self.screen.finish(self.window)
        pending, self._pending = self._pending, []
        for action in pending:
            action()
