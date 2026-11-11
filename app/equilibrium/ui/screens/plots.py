"""Plots: any channel against time, or against any other channel."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QToolTip,
    QWidget,
)

from equilibrium import theme
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.widgets import button, label, pad_spin_box, screen_layout

pg.setConfigOptions(antialias=True, background=theme.BG, foreground=theme.TEXT_MUTED)

TIME = "__time__"


class PlotsScreen(Screen):
    title = "Plots"
    nav_label = "Plots"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.series: list[str] = []
        self.slots: dict[str, int] = {}  # Index into theme.SERIES, so colours follow the mode
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.x_channel = TIME
        self.window_s = 60
        self.paused = False

        box, self.header = screen_layout(self, "Plots")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.getPlotItem().getViewBox().setMenuEnabled(False)
        self.legend = self.plot.addLegend(offset=(10, 10))
        self._style_plot()
        self.plot.scene().sigMouseMoved.connect(self._hover)
        box.addWidget(self.plot, 1)
        self.empty = label("Nothing plotted yet. Add a channel from the panel, or click any value on another "
                           "screen.", "faint", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty)

        names = sorted(ctx.data.channels.values(), key=lambda c: (c.group, c.name))
        self.channel_by_name = {c.name: c.id for c in names}

        panel = self.panel
        panel.section("Add a channel")
        self.picker = QComboBox()
        self.picker.setEditable(True)
        self.picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.picker.addItems([c.name for c in names])
        self.picker.setCurrentIndex(-1)
        self.picker.lineEdit().setPlaceholderText("Search channels…")
        completer = QCompleter([c.name for c in names], self.picker)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.picker.setCompleter(completer)
        self.picker.lineEdit().returnPressed.connect(self._add_picked)
        panel.add(self.picker)
        panel.add(button("Add to plot", self._add_picked))

        panel.section("Y axis")
        self.list = QListWidget()
        self.list.setMinimumHeight(160)
        self.list.itemChanged.connect(self._toggled)
        panel.add(self.list)
        row = QWidget()
        row_box = QHBoxLayout(row)
        row_box.setContentsMargins(0, 0, 0, 0)
        row_box.addWidget(button("Remove", self._remove_selected))
        row_box.addWidget(button("Clear all", self._clear))
        panel.add(row)

        panel.section("X axis")
        self.x_picker = QComboBox()
        self.x_picker.addItem("Time", TIME)
        for c in names:
            self.x_picker.addItem(c.name, c.id)
        self.x_picker.currentIndexChanged.connect(self._x_changed)
        panel.add(self.x_picker)

        panel.section("Time window")
        self.window = QSpinBox()
        self.window.setRange(5, 600)
        self.window.setValue(self.window_s)
        self.window.setSuffix(" s")
        pad_spin_box(self.window)
        self.window.valueChanged.connect(self._window_changed)
        panel.add(self.window)
        pause = QCheckBox("Pause")
        pause.toggled.connect(self._pause)
        panel.add(pause)
        panel.note("Plotting a channel against another pairs their samples by time.")
        panel.finish()

        ctx.plotRequested.connect(self.add_channel)
        self._update_axes()

    # Colours

    def color(self, cid: str) -> str:
        return theme.SERIES[self.slots[cid] % len(theme.SERIES)]

    def _style_plot(self) -> None:
        self.plot.setBackground(theme.BG)
        for axis in ("left", "bottom"):
            self.plot.getAxis(axis).setPen(pg.mkPen(theme.BORDER))
            self.plot.getAxis(axis).setTextPen(pg.mkPen(theme.TEXT_MUTED))
        self.legend.setLabelTextColor(theme.TEXT_MUTED)

    def restyle(self) -> None:
        self._style_plot()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setForeground(theme.color(self.color(item.data(Qt.ItemDataRole.UserRole))))
        self._update_axes()
        self.refresh()

    # Series management

    def add_channel(self, cid: str) -> None:
        if cid in self.series:
            return
        used = set(self.slots.values())
        slot = next((i for i in range(len(theme.SERIES)) if i not in used), len(self.series) % len(theme.SERIES))
        self.series.append(cid)
        self.slots[cid] = slot
        color = self.color(cid)
        info = self.ctx.data.channels[cid]
        curve = self.plot.plot([], [], name=info.name, pen=pg.mkPen(color, width=1.6))
        self.curves[cid] = curve
        item = QListWidgetItem(info.name)
        item.setData(Qt.ItemDataRole.UserRole, cid)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setForeground(theme.color(color))
        item.setToolTip(f"<b>{info.name}</b><br>{info.location() or info.group}")
        self.list.addItem(item)
        self.ctx.message.emit(f"Added {info.name} to Plots")
        self._update_axes()
        self.refresh()

    def _add_picked(self) -> None:
        cid = self.channel_by_name.get(self.picker.currentText().strip())
        if cid is None:
            self.ctx.message.emit("No channel by that name")
            return
        self.add_channel(cid)
        self.picker.setCurrentIndex(-1)
        self.picker.clearEditText()

    def _remove(self, cid: str) -> None:
        self.series.remove(cid)
        self.slots.pop(cid, None)
        curve = self.curves.pop(cid)
        self.plot.removeItem(curve)
        self.legend.removeItem(curve)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == cid:
                self.list.takeItem(i)
                break
        self._update_axes()

    def _remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self._remove(item.data(Qt.ItemDataRole.UserRole))

    def _clear(self) -> None:
        for cid in list(self.series):
            self._remove(cid)

    def _toggled(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid in self.curves:
            self.curves[cid].setVisible(item.checkState() == Qt.CheckState.Checked)

    def _x_changed(self) -> None:
        self.x_channel = self.x_picker.currentData()
        self._update_axes()
        self.refresh()

    def _window_changed(self, value: int) -> None:
        self.window_s = value
        self.refresh()

    def _pause(self, on: bool) -> None:
        self.paused = on
        if not on:
            self.refresh()

    def _update_axes(self) -> None:
        channels = self.ctx.data.channels
        units = {channels[c].unit for c in self.series}
        self.plot.setLabel("left", units.pop() if len(units) == 1 else "")
        if self.x_channel == TIME:
            self.plot.setLabel("bottom", "Time", units="s")
        else:
            info = channels[self.x_channel]
            self.plot.setLabel("bottom", info.name, units=info.unit or None)
        scatter = self.x_channel != TIME  # Dots: samples of one channel against another have no order to join up.
        for cid, curve in self.curves.items():
            if scatter:
                curve.setPen(None)
                curve.setSymbol("o")
                curve.setSymbolSize(4)
                curve.setSymbolPen(None)
                curve.setSymbolBrush(pg.mkBrush(self.color(cid)))
            else:
                curve.setSymbol(None)
                curve.setPen(pg.mkPen(self.color(cid), width=1.6))
        self.empty.setVisible(not self.series)

    # Drawing

    def _xy(self, cid: str) -> tuple[np.ndarray, np.ndarray]:
        data = self.ctx.data
        t, v = data.history[cid].arrays()
        now = data.now()
        keep = t >= now - self.window_s
        t, v = t[keep], v[keep]
        if self.x_channel == TIME:
            return t - now, v
        xt, xv = data.history[self.x_channel].arrays()
        if len(xt) < 2 or len(t) == 0:
            return np.array([]), np.array([])
        inside = (t >= xt[0]) & (t <= xt[-1])
        return np.interp(t[inside], xt, xv), v[inside]

    def refresh(self) -> None:
        if self.paused:
            return
        data = self.ctx.data
        for cid, curve in self.curves.items():
            x, y = self._xy(cid)
            curve.setData(x, y)
            stale = data.is_stale(cid)
            color = theme.STALE if stale else self.color(cid)
            if self.x_channel == TIME:
                curve.setPen(pg.mkPen(color, width=1.6))
            else:
                curve.setSymbolBrush(pg.mkBrush(color))
        stale_names = [data.channels[c].name for c in self.series if data.is_stale(c)]
        self.header.summary.setText(
            f"{len(self.series)} channel{'s' if len(self.series) != 1 else ''}"
            + (f" · <span style='color:{theme.TEXT_MUTED}'>stale: {', '.join(stale_names[:4])}"
               f"{'…' if len(stale_names) > 4 else ''}</span>" if stale_names else "")
        )
        if self.x_channel == TIME:
            self.plot.setXRange(-self.window_s, 0, padding=0.01)

    def _hover(self, scene_pos: QPointF) -> None:
        vb = self.plot.getPlotItem().getViewBox()
        if not self.series or not vb.sceneBoundingRect().contains(scene_pos):
            QToolTip.hideText()
            return
        point = vb.mapSceneToView(scene_pos)
        px, py = vb.viewPixelSize()
        best = None
        for cid, curve in self.curves.items():
            if not curve.isVisible():
                continue
            x, y = curve.getData()
            if x is None or len(x) == 0:
                continue
            d2 = ((x - point.x()) / px) ** 2 + ((y - point.y()) / py) ** 2
            i = int(np.argmin(d2))
            if best is None or d2[i] < best[0]:
                best = (d2[i], cid, x[i], y[i])
        if best is None or best[0] > 15**2:
            QToolTip.hideText()
            return
        _, cid, x, y = best
        info = self.ctx.data.channels[cid]
        where = f"{x:.1f} s" if self.x_channel == TIME else self.ctx.data.channels[self.x_channel].format(x)
        text = f"<b>{info.name}</b><br>{info.location() or info.group}<br>{info.format(y)} at {where}"
        view = self.plot.mapFromScene(scene_pos)
        QToolTip.showText(self.plot.viewport().mapToGlobal(view), text, self.plot)
