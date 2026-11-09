"""Startup splash screen, shown while the app starts and checks for updates."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen

from equilibrium import personal

MIN_DURATION_MS = 2500  # Always shown at least this long, so it never just flickers.
MAX_DURATION_MS = 8000  # Never held longer than this; a slow check finishes behind the window.
ICON_SIZE = 320  # Logical pixels; images are rendered at the screen's full resolution.
PHOTO_HEIGHT = 480
PHOTO_CORNER_RADIUS = 16


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


def _pixmap(icon: QIcon) -> QPixmap:
    """The current user's own image if they have one, otherwise the app icon."""
    path = personal.asset("image")
    photo = _photo_pixmap(path) if path is not None else None
    return photo if photo is not None else _icon_pixmap(icon)


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
        self.screen = QSplashScreen(_pixmap(icon), Qt.WindowType.WindowStaysOnTopHint)
        # Draw only the icon itself, with no box around its transparent corners.
        self.screen.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def show(self) -> None:
        self.screen.show()
        QTimer.singleShot(MIN_DURATION_MS, self._on_min_passed)
        QTimer.singleShot(MAX_DURATION_MS, self.reveal)

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
        self.window.show()
        self.screen.finish(self.window)
        pending, self._pending = self._pending, []
        for action in pending:
            action()
