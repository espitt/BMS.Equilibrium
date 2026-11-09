"""Thermals: a 3D heatmap of every thermistor, per segment, placed from the layout file."""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QToolTip, QWidget

from equilibrium import theme
from equilibrium.bms.layout import Thermistor, temp_id
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import LEVEL_COLORS, temp_level
from equilibrium.ui.widgets import Segmented, SettingsForm, button, colored, label, screen_layout, write_button

DEFAULT_YAW = -0.6
DEFAULT_PITCH = 0.55


class Camera(QObject):
    """View angle shared by every segment view, so they all turn together."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.yaw = DEFAULT_YAW
        self.pitch = DEFAULT_PITCH
        self.zoom = 1.0

    def rotate(self, dx: float, dy: float) -> None:
        self.yaw += dx * 0.01
        self.pitch = max(-0.2, min(1.5, self.pitch + dy * 0.01))
        self.changed.emit()

    def scale(self, factor: float) -> None:
        self.zoom = max(0.4, min(3.0, self.zoom * factor))
        self.changed.emit()

    def reset(self) -> None:
        self.yaw, self.pitch, self.zoom = DEFAULT_YAW, DEFAULT_PITCH, 1.0
        self.changed.emit()


def limits(cfg) -> tuple[float, float, float, float]:
    return (float(cfg["temp_ut_fault"]), float(cfg["temp_ut_warn"]),
            float(cfg["temp_ot_warn"]), float(cfg["temp_ot_fault"]))


class SegmentView(QWidget):
    """One segment drawn in 3D. Drag to turn, scroll to zoom, double-click to reset."""

    clicked = Signal(str)

    def __init__(self, ctx: AppContext, camera: Camera, segment: int, compact: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        self.camera = camera
        self.segment = segment
        self.compact = compact
        self.show_values = not compact
        self.thermistors: list[Thermistor] = ctx.layout.segment_thermistors(segment)
        self.hover: Thermistor | None = None
        self.projected: list[tuple[Thermistor, QPointF, float]] = []
        self._press: QPointF | None = None
        self._dragged = False
        self.setMouseTracking(True)
        self.setMinimumSize(200, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        camera.changed.connect(self.update)

    def set_segment(self, segment: int) -> None:
        self.segment = segment
        self.thermistors = self.ctx.layout.segment_thermistors(segment)
        self.hover = None
        self.update()

    def _projector(self):
        sx, sy, sz = self.ctx.layout.segment_size
        cam = self.camera
        cy, sy_ = math.cos(cam.yaw), math.sin(cam.yaw)
        cp, sp = math.cos(cam.pitch), math.sin(cam.pitch)
        size = max(sx, sy, sz)
        scale = cam.zoom * min(self.width(), self.height() * 1.6) / size * 0.78
        distance = size * 3.0
        ox, oy = self.width() / 2, self.height() / 2 + (8 if self.compact else 14)

        def project(x: float, y: float, z: float) -> tuple[QPointF, float]:
            x, y, z = x - sx / 2, y - sy / 2, z - sz / 2
            x1 = x * cy - y * sy_
            y1 = x * sy_ + y * cy
            depth = y1 * cp + z * sp
            up = z * cp - y1 * sp
            f = distance / (distance + depth)
            return QPointF(ox + x1 * scale * f, oy - up * scale * f), depth

        return project, scale

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        data = self.ctx.data
        lims = limits(self.ctx.config)
        project, scale = self._projector()
        sx, sy, sz = self.ctx.layout.segment_size

        # Segment outline
        corners = [(x, y, z) for x in (0, sx) for y in (0, sy) for z in (0, sz)]
        pts = [project(*c)[0] for c in corners]
        p.setPen(QPen(theme.color(theme.BORDER), 1.2))
        for i in range(8):
            for j in range(i + 1, 8):
                if sum(a != b for a, b in zip(corners[i], corners[j])) == 1:
                    p.drawLine(pts[i], pts[j])
        # Floor tint
        floor = [project(x, y, 0)[0] for x, y in ((0, 0), (sx, 0), (sx, sy), (0, sy))]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.SURFACE_3, 160))
        p.drawPolygon(QPolygonF(floor))

        # Thermistors, far ones first
        self.projected = []
        for t in self.thermistors:
            point, depth = project(t.x, t.y, t.z)
            self.projected.append((t, point, depth))
        self.projected.sort(key=lambda item: -item[2])
        base_r = max(5.0, min(16.0, scale * 14)) if not self.compact else max(4.0, min(10.0, scale * 12))
        small = QFont(self.font())
        small.setPointSizeF(max(6.5, small.pointSizeF() - (3 if self.compact else 2)))
        p.setFont(small)
        for t, point, depth in self.projected:
            cid = temp_id(t.number)
            value = data.value(cid)
            stale = data.is_stale(cid)
            r = base_r * (sx * 3) / (sx * 3 + depth)
            fill = theme.color(theme.STALE) if stale or value is None else theme.temperature_color(value, *lims)
            if not stale and value is not None:
                glow = QRadialGradient(point, r * 2.4)
                c = QColor(fill)
                c.setAlpha(90)
                glow.setColorAt(0, c)
                c.setAlpha(0)
                glow.setColorAt(1, c)
                p.setBrush(QBrush(glow))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(point, r * 2.4, r * 2.4)
            p.setBrush(fill)
            outline = theme.color(theme.TEXT) if t is self.hover else fill.darker(160)
            p.setPen(QPen(outline, 1.5 if t is self.hover else 1))
            p.drawEllipse(point, r, r)
            if self.show_values and value is not None and r >= 9:
                p.setPen(theme.color("#14202e") if fill.lightness() > 140 else theme.color("#ffffff"))
                p.drawText(QRectF(point.x() - r, point.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter,
                           f"{value:.0f}")

        # Title
        temps = [data.values[temp_id(t.number)] for t in self.thermistors if temp_id(t.number) in data.values]
        p.setPen(theme.color(theme.TEXT_MUTED))
        title = f"Segment {self.segment}"
        p.drawText(QRectF(8, 4, self.width() - 16, 18), Qt.AlignmentFlag.AlignLeft, title)
        if temps:
            hi = max(temps)
            level = temp_level(hi, self.ctx.config)
            p.setPen(theme.color(theme.TEXT if level == "normal" else LEVEL_COLORS[level]))
            p.drawText(QRectF(8, 4, self.width() - 16, 18), Qt.AlignmentFlag.AlignRight, f"max {hi:.1f} °C")
        p.end()

    def _hit(self, pos: QPointF) -> Thermistor | None:
        best = None
        for t, point, _depth in reversed(self.projected):  # Nearest first
            d = math.hypot(point.x() - pos.x(), point.y() - pos.y())
            if d <= 14:
                best = t
                break
        return best

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._press = event.position()
        self._dragged = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            dx, dy = pos.x() - self._press.x(), pos.y() - self._press.y()
            if self._dragged or abs(dx) + abs(dy) > 3:
                self._dragged = True
                self._press = pos
                self.camera.rotate(dx, dy)
                QToolTip.hideText()
            return
        t = self._hit(pos)
        if t is not self.hover:
            self.hover = t
            self.update()
        if t is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPosition().toPoint(), self.ctx.data.tooltip(temp_id(t.number)), self)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._dragged:
            t = self._hit(event.position())
            if t is not None:
                self.clicked.emit(temp_id(t.number))
        self._press = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.camera.reset()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.camera.scale(1.1 if event.angleDelta().y() > 0 else 1 / 1.1)

    def leaveEvent(self, event) -> None:
        self.hover = None
        self.update()
        super().leaveEvent(event)


class TempLegend(QWidget):
    """The heatmap colour scale with the four limits marked."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setFixedHeight(50)
        ctx.config.changed.connect(lambda _key: self.update())

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lims = limits(self.ctx.config)
        lo, hi = lims[0] - 5, lims[3] + 5
        bar = QRectF(60, 20, self.width() - 120, 10)
        gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
        for i in range(41):
            t = lo + (hi - lo) * i / 40
            gradient.setColorAt(i / 40, theme.temperature_color(t, *lims))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawRoundedRect(bar, 4, 4)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 2))
        p.setFont(small)
        for i, (value, name) in enumerate(zip(lims, ("UT fault", "UT warning", "OT warning", "OT fault"))):
            x = bar.left() + (value - lo) / (hi - lo) * bar.width()
            p.setPen(QPen(theme.color(theme.TEXT_MUTED), 1))
            p.drawLine(QPointF(x, bar.top() - 2), QPointF(x, bar.bottom() + 2))
            # Warnings label below the bar, faults above, so neighbouring limits never overlap.
            y = bar.bottom() + 3 if i in (1, 2) else bar.top() - 19
            p.drawText(QRectF(x - 60, y, 120, 16), Qt.AlignmentFlag.AlignCenter, f"{name} {value:g} °C")
        p.end()


class ThermalsScreen(Screen):
    title = "Thermals"
    nav_label = "Thermals"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.camera = Camera()
        box, self.header = screen_layout(self, "Thermals")

        # Segment picker, each button showing that segment's hottest reading.
        picker = QHBoxLayout()
        picker.setSpacing(6)
        self.segment_buttons: list[QPushButton] = []
        for s in range(1, ctx.layout.segments + 1):
            b = QPushButton(f"Segment {s}")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, seg=s: self._pick(seg))
            picker.addWidget(b)
            self.segment_buttons.append(b)
        picker.addStretch(1)
        box.addLayout(picker)

        self.single = SegmentView(ctx, self.camera, 1)
        self.single.clicked.connect(ctx.plot)
        box.addWidget(self.single, 1)

        self.grid_widget = QWidget()
        grid = QGridLayout(self.grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.small_views: list[SegmentView] = []
        columns = 4 if ctx.layout.segments > 4 else ctx.layout.segments
        for i in range(ctx.layout.segments):
            view = SegmentView(ctx, self.camera, i + 1, compact=True)
            view.clicked.connect(ctx.plot)
            grid.addWidget(view, i // columns, i % columns)
            self.small_views.append(view)
        box.addWidget(self.grid_widget, 1)
        self.grid_widget.hide()

        box.addWidget(TempLegend(ctx))

        panel = self.panel
        panel.section("View")
        self.view_mode = Segmented(["One segment", "All segments"])
        self.view_mode.changed.connect(self._set_view)
        panel.add(self.view_mode)
        values = QCheckBox("Show values")
        values.setChecked(True)
        values.toggled.connect(self._show_values)
        panel.add(values)
        panel.add(button("Reset view", self.camera.reset))
        panel.note("Drag to turn, scroll to zoom, double-click to reset. Positions come from the pack layout file.")

        panel.section("Temperature limits")
        panel.add(SettingsForm(ctx.config, ["temp_ot_fault", "temp_ot_warn", "temp_ut_warn", "temp_ut_fault"]))
        panel.add(write_button(ctx))
        panel.finish()
        self._pick(1)

    def _pick(self, segment: int) -> None:
        for i, b in enumerate(self.segment_buttons):
            b.setChecked(i + 1 == segment)
        self.single.set_segment(segment)
        if self.view_mode.current() == 1:
            self.view_mode.set_current(0)
            self._set_view(0)

    def _set_view(self, mode: int) -> None:
        self.single.setVisible(mode == 0)
        self.grid_widget.setVisible(mode == 1)

    def _show_values(self, on: bool) -> None:
        self.single.show_values = on
        self.single.update()

    def refresh(self) -> None:
        data = self.ctx.data
        cfg = self.ctx.config
        layout = self.ctx.layout
        self.single.update()
        for view in self.small_views:
            view.update()
        for s, b in enumerate(self.segment_buttons, start=1):
            temps = [data.values[temp_id(t.number)] for t in layout.segment_thermistors(s)
                     if temp_id(t.number) in data.values]
            stale = any(data.is_stale(temp_id(t.number)) for t in layout.segment_thermistors(s))
            if not temps:
                b.setText(f"Segment {s}")
                b.setStyleSheet("")
                continue
            hi = max(temps)
            level = temp_level(hi, cfg)
            b.setText(f"Segment {s}  ·  {hi:.0f} °C")
            hex_code = theme.STALE if stale else (None if level == "normal" else LEVEL_COLORS[level])
            b.setStyleSheet(f"QPushButton {{ color: {hex_code}; }}" if hex_code else "")

        readings = [(data.values[temp_id(t.number)], t) for t in layout.thermistors if temp_id(t.number) in data.values]
        if not readings:
            self.header.summary.setText("No data")
            return
        tmax, thmax = max(readings, key=lambda r: r[0])
        tmin, thmin = min(readings, key=lambda r: r[0])
        avg = sum(r[0] for r in readings) / len(readings)
        hot_hex = theme.TEXT if temp_level(tmax, cfg) == "normal" else LEVEL_COLORS[temp_level(tmax, cfg)]
        self.header.summary.setText(
            f"Hottest {colored(f'{tmax:.1f} °C', hot_hex)} ({thmax.label}) · "
            f"Coldest {colored(f'{tmin:.1f} °C', theme.TEXT)} ({thmin.label}) · "
            f"Average {colored(f'{avg:.1f} °C', theme.TEXT)}"
        )
