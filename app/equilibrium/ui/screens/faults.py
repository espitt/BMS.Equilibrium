"""Faults: present and historic faults, their severity, and the freeze frame from when each happened."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from equilibrium import theme
from equilibrium.bms.layout import temp_id
from equilibrium.bms.store import SEVERITIES, Fault, worst_severity
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.screens.voltages import VoltageChart
from equilibrium.ui.states import SEVERITY_COLORS, value_color
from equilibrium.ui.widgets import Card, button, colored, label, screen_layout

COLUMNS = ["Severity", "Code", "Fault", "Location", "First seen", "Count", "Status"]
FREEZE_FRAME = ["ams.state", "pack.voltage", "pack.current", "pack.soc", "cell.max", "cell.min", "cell.delta",
                "temp.max", "temp.min", "precharge.state"]


def when(stamp: float) -> str:
    local = time.localtime(stamp)
    if time.strftime("%Y-%m-%d", local) == time.strftime("%Y-%m-%d"):
        return time.strftime("%H:%M:%S", local)
    return time.strftime("%d %b %H:%M", local)


class FaultsScreen(Screen):
    title = "Faults"
    nav_label = "Faults"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.shown: list[Fault] = []
        self.severities = set(SEVERITIES)
        box, self.header = screen_layout(self, "Faults")

        self.tabs = QTabBar()
        self.tabs.addTab("Present")
        self.tabs.addTab("History")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)  # Tabs as wide as their names, at the left
        self.tabs.currentChanged.connect(lambda _i: self._rebuild())
        box.addWidget(self.tabs)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        box.addWidget(splitter, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.cellDoubleClicked.connect(self._plot_location)
        splitter.addWidget(self.table)

        # Freeze frame
        self.detail = Card()
        self.detail_title = label("Select a fault to see the pack as it was when the fault happened.", "muted",
                                  wrap=True)
        self.detail_title.setTextFormat(Qt.TextFormat.RichText)
        self.detail_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail.box.addWidget(self.detail_title)
        self.frame_values = QWidget()
        self.frame_grid = QGridLayout(self.frame_values)
        self.frame_grid.setContentsMargins(0, 0, 0, 0)
        self.frame_grid.setHorizontalSpacing(24)
        self.frame_labels: dict[str, QLabel] = {}
        for i, cid in enumerate(FREEZE_FRAME):
            info = ctx.data.channels[cid]
            caption = label(info.name, "tileCaption")
            value = label("—")
            value.setStyleSheet("font-size: 14px; font-weight: 600;")
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(caption)
            cell.addWidget(value)
            self.frame_grid.addLayout(cell, i // 5, i % 5)
            self.frame_labels[cid] = value
        self.detail.box.addWidget(self.frame_values)
        self.hottest = label("", "muted", wrap=True)
        self.hottest.setTextFormat(Qt.TextFormat.RichText)
        self.detail.box.addWidget(self.hottest)
        self.chart = VoltageChart(ctx.layout, ctx.config, compact=True)
        self.detail.box.addWidget(self.chart, 1)
        self.frame_values.hide()
        self.chart.hide()
        splitter.addWidget(self.detail)
        splitter.setSizes([300, 360])

        panel = self.panel
        panel.section("Actions")
        self.clear = panel.add(button("Clear faults", self._clear, "danger",
                                      "Clear latched faults whose condition has gone. Active faults stay."))
        panel.section("Show")
        self.filters: dict[str, QCheckBox] = {}
        for severity in SEVERITIES:
            box_ = QCheckBox(severity.capitalize())
            box_.setChecked(True)
            box_.toggled.connect(lambda on, s=severity: self._filter(s, on))
            panel.add(box_)
            self.filters[severity] = box_
        panel.section("Summary")
        self.summary = panel.add(label("", "muted", wrap=True))
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        panel.note("Active: the condition is present now. Latched: it has gone but has not been cleared. "
                   "Double-click a fault to plot its location.")
        panel.finish()

        ctx.data.faultsChanged.connect(self._rebuild)
        ctx.linkChanged.connect(lambda: self.clear.setEnabled(ctx.connected))
        self.clear.setEnabled(ctx.connected)
        self._rebuild()

    def restyle(self) -> None:
        self._rebuild()
        self.chart.update()

    def _clear(self) -> None:
        self.ctx.send("faults clear")

    def _filter(self, severity: str, on: bool) -> None:
        if on:
            self.severities.add(severity)
        else:
            self.severities.discard(severity)
        self._rebuild()

    def _location_text(self, fault: Fault) -> str:
        info = self.ctx.data.channels.get(fault.location)
        if info is None:
            return fault.location or "Pack"
        where = info.location()
        return f"{info.name} ({where})" if where else info.name

    def _rebuild(self) -> None:
        data = self.ctx.data
        selected = self.shown[self.table.currentRow()] if 0 <= self.table.currentRow() < len(self.shown) else None
        source = data.present_faults() if self.tabs.currentIndex() == 0 else list(data.faults)
        self.shown = sorted((f for f in source if f.severity in self.severities),
                            key=lambda f: (not f.active, SEVERITIES.index(f.severity), -f.first_seen))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.shown))
        for row, fault in enumerate(self.shown):
            status_hex = {"Active": SEVERITY_COLORS[fault.severity], "Latched": theme.TEXT,
                          "Cleared": theme.TEXT_FAINT}[fault.status]
            cells = [
                (fault.severity.capitalize(), SEVERITY_COLORS[fault.severity]),
                (f"0x{fault.code:04X}", theme.TEXT_MUTED),
                (fault.name, theme.TEXT),
                (self._location_text(fault), theme.TEXT_MUTED),
                (when(fault.first_seen), theme.TEXT_MUTED),
                (str(fault.count), theme.TEXT_MUTED),
                (fault.status, status_hex),
            ]
            for col, (text, hex_code) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(theme.color(hex_code))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if selected in self.shown:
            self.table.selectRow(self.shown.index(selected))
        else:
            self.table.clearSelection()
            self._show_selected()

        present = data.present_faults()
        self.tabs.setTabText(0, f"Present ({len(present)})")
        self.tabs.setTabText(1, f"History ({len(data.faults)})")
        counts = {s: sum(1 for f in present if f.severity == s) for s in SEVERITIES}
        lines = [colored(f"{n} {s}", SEVERITY_COLORS[s] if n else theme.TEXT_FAINT) for s, n in counts.items()]
        self.summary.setText("<br>".join(lines) if data.connected else "Not connected")
        worst = worst_severity(present)
        self.header.summary.setText(
            colored(f"{len(present)} present", SEVERITY_COLORS[worst]) if worst else "No faults present"
        )

    def _show_selected(self) -> None:
        row = self.table.currentRow()
        if not self.table.selectedItems() or not 0 <= row < len(self.shown):
            self.detail_title.setText("Select a fault to see the pack as it was when the fault happened.")
            self.frame_values.hide()
            self.chart.hide()
            self.hottest.setText("")
            return
        fault = self.shown[row]
        snap = fault.snapshot
        cfg = self.ctx.config
        self.detail_title.setText(
            f"<span style='color:{theme.TEXT}; font-weight:600'>Freeze frame</span> "
            f"&nbsp;{colored(fault.name, SEVERITY_COLORS[fault.severity])} at "
            f"{time.strftime('%H:%M:%S', time.localtime(fault.first_seen))}"
        )
        for cid, widget in self.frame_labels.items():
            info = self.ctx.data.channels[cid]
            value = snap.get(cid)
            widget.setText(info.format(value))
            widget.setStyleSheet(f"font-size: 14px; font-weight: 600; "
                                 f"color: {value_color(cid, value, cfg, info.labels)};")
        layout = self.ctx.layout
        temps = sorted(((snap[temp_id(t.number)], t) for t in layout.thermistors if temp_id(t.number) in snap),
                       key=lambda p: -p[0])[:3]
        self.hottest.setText(
            "Hottest: " + ", ".join(f"{t.label} {colored(f'{v:.1f} °C', value_color(temp_id(t.number), v, cfg))}"
                                    for v, t in temps) if temps else "")
        self.chart.set_data(snap, set())
        self.frame_values.setVisible(bool(snap))
        self.chart.setVisible(bool(snap))

    def _plot_location(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.shown):
            self.ctx.plot(self.shown[row].location)

    def refresh(self) -> None:
        pass  # Fault changes arrive through faultsChanged.
