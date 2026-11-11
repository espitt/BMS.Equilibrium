"""Voltages: every cell as a bar, grouped by segment, with the voltage limits drawn across."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QToolTip, QWidget

from equilibrium import theme
from equilibrium.bms.config import Config
from equilibrium.bms.layout import PackLayout, balance_id, build_channels, cell_id
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import LEVEL_COLORS, cell_level
from equilibrium.ui.widgets import LegendRow, Segmented, SettingsForm, colored, screen_layout, write_button


def nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = math.ceil(lo / step) * step
    ticks = []
    v = first
    while v <= hi + step * 1e-6:
        ticks.append(round(v, 10))
        v += step
    return ticks


class VoltageChart(QWidget):
    """Bar chart of all cells. Works from live data or from a fault's freeze frame."""

    cellClicked = Signal(int)

    ABSOLUTE, DEVIATION = 0, 1

    def __init__(self, layout: PackLayout, config: Config, compact: bool = False) -> None:
        super().__init__()
        self.pack = layout
        self.config = config
        self.compact = compact
        self.channels = build_channels(layout)
        self.values: dict[str, float] = {}
        self.stale: set[str] = set()
        self.stale_age: dict[str, float] = {}
        self.mode = self.ABSOLUTE
        self.zoom = False
        self.hover: int | None = None
        self.bars: list[tuple[int, QRectF]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(160 if compact else 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        config.changed.connect(lambda _key: self.update())

    def set_data(self, values: dict[str, float], stale: set[str]) -> None:
        self.values = values
        self.stale = stale
        self.update()

    def cell_values(self) -> list[float | None]:
        return [self.values.get(cell_id(n)) for n in range(1, self.pack.cell_count + 1)]

    def _range(self, cells: list[float]) -> tuple[float, float]:
        cfg = self.config
        if self.mode == self.DEVIATION:
            mean = sum(cells) / len(cells) if cells else 0
            extent = max([abs(v - mean) * 1000 for v in cells] + [float(cfg["balance_threshold_mv"]) * 1.5, 5.0])
            return -extent * 1.15, extent * 1.15
        if self.zoom and cells:
            pad = max(0.01, (max(cells) - min(cells)) * 0.2)
            return min(cells) - pad, max(cells) + pad
        return float(cfg["cell_uv_fault"]) - 0.15, float(cfg["cell_ov_fault"]) + 0.05

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cfg = self.config
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 2))
        p.setFont(small)

        left, right, top, bottom = 52, 12, 26 if not self.compact else 18, 8
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        values = self.cell_values()
        known = [v for v in values if v is not None]
        lo, hi = self._range(known)
        mean = sum(known) / len(known) if known else 0.0

        def y_of(v: float) -> float:
            return plot.bottom() - (v - lo) / (hi - lo) * plot.height()

        # Grid and axis labels
        unit = "mV" if self.mode == self.DEVIATION else "V"
        for tick in nice_ticks(lo, hi, 4 if self.compact else 6):
            y = y_of(tick)
            p.setPen(QPen(theme.color(theme.BORDER), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(theme.color(theme.TEXT_FAINT))
            text = f"{tick:+.0f}" if self.mode == self.DEVIATION else f"{tick:.2f}"
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       text)
        p.setPen(theme.color(theme.TEXT_FAINT))
        p.drawText(QRectF(0, 0, left - 8, top - 6), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, unit)

        # Bars, grouped by segment
        segs = self.pack.segments
        per = self.pack.cells_per_segment
        group_gap = 10.0
        bar_gap = 2.0 if plot.width() / self.pack.cell_count > 6 else 1.0
        group_w = (plot.width() - group_gap * (segs - 1)) / segs
        bar_w = max(1.0, (group_w - bar_gap * (per - 1)) / per)
        base_v = 0.0 if self.mode == self.DEVIATION else lo
        self.bars = []
        for s in range(segs):
            gx = plot.left() + s * (group_w + group_gap)
            p.fillRect(QRectF(gx - 3, plot.top(), group_w + 6, plot.height()), theme.color(theme.SURFACE))
            p.setPen(theme.color(theme.TEXT_MUTED))
            name = f"Segment {s + 1}" if group_w > 90 else f"S{s + 1}"
            p.drawText(QRectF(gx, 0, group_w, top - 6), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom,
                       name)
            for i in range(per):
                n = s * per + i + 1
                v = values[n - 1]
                x = gx + i * (bar_w + bar_gap)
                if v is None:
                    continue
                shown = (v - mean) * 1000 if self.mode == self.DEVIATION else v
                y0, y1 = y_of(max(lo, min(hi, base_v))), y_of(max(lo, min(hi, shown)))
                rect = QRectF(x, min(y0, y1), bar_w, max(1.0, abs(y1 - y0)))
                self.bars.append((n, QRectF(x, plot.top(), bar_w + bar_gap, plot.height())))
                stale = cell_id(n) in self.stale
                fill = theme.color(theme.STALE) if stale else theme.color(LEVEL_COLORS[cell_level(v, cfg)])
                if n == self.hover:
                    fill = fill.lighter(140)
                p.fillRect(rect, fill)
                if not stale and self.values.get(balance_id(n), 0) >= 0.5:
                    cap_y = rect.top() if shown >= base_v else rect.bottom() - 3
                    p.fillRect(QRectF(x, cap_y, bar_w, 3), theme.color(theme.BALANCE))

        # Limit lines
        lines: list[tuple[float, str, str]] = []
        if self.mode == self.ABSOLUTE:
            lines = [
                (float(cfg["cell_ov_fault"]), "OV fault", theme.FAULT),
                (float(cfg["cell_ov_warn"]), "OV warning", theme.WARN),
                (float(cfg["charge_target"]), "Charge target", theme.CHARGE),
                (float(cfg["cell_uv_warn"]), "UV warning", theme.WARN),
                (float(cfg["cell_uv_fault"]), "UV fault", theme.FAULT),
            ]
        elif known:
            floor = (min(known) - mean) * 1000 + float(cfg["balance_threshold_mv"])
            lines = [(floor, "Balance threshold", theme.BALANCE), (0.0, "Mean", theme.TEXT_MUTED)]
        for value, name, hex_code in lines:
            if not lo <= value <= hi:
                continue
            y = y_of(value)
            pen = QPen(theme.color(hex_code, 200), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if not self.compact:
                text = f"{name} {value:.3f} V" if self.mode == self.ABSOLUTE else name
                width = p.fontMetrics().horizontalAdvance(text) + 10
                box = QRectF(plot.right() - width, y - 15, width, 14)
                p.fillRect(box, theme.color(theme.BG, 220))
                p.setPen(theme.color(hex_code))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def _cell_at(self, x: float, y: float) -> int | None:
        for n, rect in self.bars:
            if rect.contains(QPointF(x, y)):
                return n
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        n = self._cell_at(pos.x(), pos.y())
        if n != self.hover:
            self.hover = n
            self.update()
        if n is None:
            QToolTip.hideText()
            return
        cid = cell_id(n)
        info = self.channels[cid]
        known = [v for v in self.cell_values() if v is not None]
        v = self.values.get(cid)
        extra = ""
        if v is not None and known:
            mean = sum(known) / len(known)
            extra = f"{(v - mean) * 1000:+.1f} mV from mean"
            if self.values.get(balance_id(n), 0) >= 0.5:
                extra += f"<br>{colored('Balancing', theme.BALANCE)}"
        stale_for = self.stale_age.get(cid) if cid in self.stale else None
        if cid in self.stale and stale_for is None:
            stale_for = float("inf")
        QToolTip.showText(event.globalPosition().toPoint(), info.tooltip(v, stale_for, extra), self)

    def leaveEvent(self, event) -> None:
        self.hover = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            n = self._cell_at(event.position().x(), event.position().y())
            if n is not None:
                self.cellClicked.emit(n)


class VoltagesScreen(Screen):
    title = "Voltages"
    nav_label = "Voltages"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        box, self.header = screen_layout(self, "Cell voltages")
        self.chart = VoltageChart(ctx.layout, ctx.config)
        self.chart.cellClicked.connect(lambda n: ctx.plot(cell_id(n)))
        box.addWidget(self.chart, 1)

        panel = self.panel
        panel.section("View")
        self.mode = Segmented(["Absolute", "Deviation"])
        self.mode.changed.connect(self._set_mode)
        panel.add(self.mode)
        self.zoom = QCheckBox("Zoom to cell range")
        self.zoom.setToolTip("In absolute mode, fit the axis to the cells instead of the limits")
        self.zoom.toggled.connect(self._set_zoom)
        panel.add(self.zoom)

        panel.section("Voltage limits")
        panel.add(SettingsForm(ctx.config, ["cell_ov_fault", "cell_ov_warn", "charge_target",
                                            "cell_uv_warn", "cell_uv_fault"]))
        panel.section("Balancing")
        panel.add(SettingsForm(ctx.config, ["balance_enabled", "balance_threshold_mv", "balance_min_voltage"]))
        panel.add(write_button(ctx))

        panel.section("Colours")
        for token, text in [("NEUTRAL", "Within limits"), ("WARN", "Past a warning limit"),
                            ("FAULT", "Past a fault limit"), ("BALANCE", "Balancing (bar cap)"),
                            ("STALE", "Stale, not updating")]:
            panel.add(LegendRow(token, text))
        panel.finish()

    def _set_mode(self, mode: int) -> None:
        self.chart.mode = mode
        self.zoom.setEnabled(mode == VoltageChart.ABSOLUTE)
        self.chart.update()

    def _set_zoom(self, on: bool) -> None:
        self.chart.zoom = on
        self.chart.update()

    def refresh(self) -> None:
        data = self.ctx.data
        self.chart.stale_age = {cid: age for cid in data.stale if (age := data.stale_for(cid)) is not None}
        self.chart.set_data(data.values, data.stale)
        layout = self.ctx.layout
        cells = [(data.values[cell_id(n)], n) for n in range(1, layout.cell_count + 1) if cell_id(n) in data.values]
        if not cells:
            self.header.summary.setText("No data")
            return
        (vmax, nmax), (vmin, nmin) = max(cells), min(cells)
        balancing = sum(1 for n in range(1, layout.cell_count + 1) if data.values.get(balance_id(n), 0) >= 0.5)
        parts = [
            f"Max {colored(f'{vmax:.3f} V', theme.TEXT)} (cell {nmax})",
            f"Min {colored(f'{vmin:.3f} V', theme.TEXT)} (cell {nmin})",
            f"Δ {colored(f'{(vmax - vmin) * 1000:.0f} mV', theme.TEXT)}",
        ]
        if balancing:
            parts.append(colored(f"{balancing} balancing", theme.BALANCE))
        self.header.summary.setText(" · ".join(parts))
