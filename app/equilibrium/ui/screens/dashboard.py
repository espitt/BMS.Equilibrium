"""Dashboard: the pack at a glance. No configuration here."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from equilibrium import theme
from equilibrium.bms.layout import cell_id, temp_id
from equilibrium.bms.store import worst_severity
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import SEVERITY_COLORS, cell_level, level_color, temp_level
from equilibrium.ui.widgets import Readout, ReadoutGrid, Tile, device_html, label, screen_layout, section_label

SEGMENT_COLUMNS = ["Segment", "Lowest cell", "Highest cell", "Cell delta", "Highest temperature"]
ROW_HEIGHT = 26


class SegmentTable(QTableWidget):
    """One row per segment: its cell range and hottest reading. For reading only, so nothing selects."""

    def __init__(self, segments: int) -> None:
        super().__init__(segments, len(SEGMENT_COLUMNS))
        self.setHorizontalHeaderLabels(SEGMENT_COLUMNS)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsClickable(False)
        header.setFixedHeight(ROW_HEIGHT + 2)
        self.setFixedHeight(header.height() + segments * ROW_HEIGHT + 2)  # Every row, with no scrolling
        for row in range(segments):
            for column in range(len(SEGMENT_COLUMNS)):
                self.setItem(row, column, QTableWidgetItem())
            self.set_row(row, [(f"Segment {row + 1}", theme.TEXT)])

    def set_row(self, row: int, cells: list[tuple[str, str]]) -> None:
        """Fill a row from the left with (text, colour) pairs."""
        for column, (text, hex_code) in enumerate(cells):
            item = self.item(row, column)
            item.setText(text)
            item.setForeground(theme.color(hex_code))


class DashboardScreen(Screen):
    title = "Dashboard"
    nav_label = "Dashboard"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        box, self.header = screen_layout(body, "Dashboard")

        self.tiles: list[Tile] = []

        def row(title: str, specs: list[tuple[str, str, bool]], extra: Readout | None = None) -> list[Tile]:
            """A headed row of live values. `extra` is a readout of something that is not a channel."""
            box.addWidget(section_label(title))
            made = [Tile(ctx, cid, caption, badge) for cid, caption, badge in specs]
            box.addWidget(ReadoutGrid(made + ([extra] if extra else [])))
            self.tiles.extend(made)
            return made

        self.faults = Readout("Present faults")
        row("State", [("ams.state", "AMS state", True), ("precharge.state", "Precharge", True),
                      ("charger.state", "Charger", True)], self.faults)

        pack = row("Pack", [("pack.voltage", "Pack voltage", False), ("pack.current", "Current", False),
                            ("pack.power", "Power", False), ("pack.soc", "State of charge", False),
                            ("ts.voltage", "TS voltage", False)])
        # The state of charge bar takes the place of the line under the value.
        soc_tile = pack[3]
        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 1000)
        self.soc_bar.setTextVisible(False)
        self.soc_bar.setFixedHeight(4)
        soc_tile.sub.hide()
        soc_tile.layout().addSpacing(5)
        soc_tile.layout().addWidget(self.soc_bar)
        soc_tile.layout().addSpacing(5)

        cells = row("Cells", [("cell.max", "Highest cell", False), ("cell.min", "Lowest cell", False),
                              ("cell.avg", "Average cell", False), ("cell.delta", "Cell delta", False)])
        self.cell_max_tile, self.cell_min_tile = cells[0], cells[1]
        temps = row("Temperatures", [("temp.max", "Highest temperature", False),
                                     ("temp.min", "Lowest temperature", False),
                                     ("temp.avg", "Average temperature", False)])
        self.temp_max_tile, self.temp_min_tile = temps[0], temps[1]

        box.addWidget(section_label("Segments"))
        self.segments = SegmentTable(ctx.layout.segments)
        box.addWidget(self.segments)
        box.addStretch(1)

        self.panel.section("Connection")
        self.connection = self.panel.add(label("", "muted", wrap=True))
        self.panel.section("Device")
        self.device = self.panel.add(label("", "muted", wrap=True))
        self.device.setTextFormat(Qt.TextFormat.RichText)
        self.panel.note("Hover a value to see where it comes from. Click it to add it to Plots.")
        self.panel.finish()
        ctx.data.faultsChanged.connect(self._on_data)
        ctx.data.connectionChanged.connect(self._on_data)

    def refresh(self) -> None:
        data = self.ctx.data
        cfg = self.ctx.config
        for tile in self.tiles:
            tile.refresh()

        soc = data.value("pack.soc")
        self.soc_bar.setValue(int((soc or 0) * 10))

        # Which cell or thermistor is the extreme, so the sub line can say where.
        layout = self.ctx.layout
        cells = [(data.values[cell_id(n)], n) for n in range(1, layout.cell_count + 1) if cell_id(n) in data.values]
        temps = [(data.values[temp_id(t.number)], t) for t in layout.thermistors if temp_id(t.number) in data.values]
        if cells:
            _, nmax = max(cells)
            _, nmin = min(cells)
            self.cell_max_tile.set_sub(f"Cell {nmax}, segment {layout.cell_position(nmax)[0]}")
            self.cell_min_tile.set_sub(f"Cell {nmin}, segment {layout.cell_position(nmin)[0]}")
        if temps:
            _, thmax = max(temps, key=lambda p: p[0])
            _, thmin = min(temps, key=lambda p: p[0])
            self.temp_max_tile.set_sub(f"{thmax.label}, segment {thmax.segment}")
            self.temp_min_tile.set_sub(f"{thmin.label}, segment {thmin.segment}")

        present = data.present_faults()
        if not data.connected:
            self.faults.set_value("—", theme.TEXT_FAINT)
        else:
            worst = worst_severity(present)
            self.faults.set_value(str(len(present)) if present else "None",
                                  SEVERITY_COLORS[worst] if worst else theme.TEXT)

        for segment in range(1, layout.segments + 1):
            seg_cells = [data.values.get(cell_id(n)) for n in layout.segment_cells(segment)]
            seg_temps = [data.values.get(temp_id(t.number)) for t in layout.segment_thermistors(segment)]
            seg_cells = [v for v in seg_cells if v is not None]
            seg_temps = [v for v in seg_temps if v is not None]
            stale = any(data.is_stale(cell_id(n)) for n in layout.segment_cells(segment))
            name = (f"Segment {segment}", theme.TEXT)
            if not seg_cells or stale:
                gap = ("Stale", theme.STALE) if seg_cells else ("—", theme.TEXT_FAINT)
                self.segments.set_row(segment - 1, [name, gap, gap, gap, gap])
                continue
            lo, hi = min(seg_cells), max(seg_cells)
            t_hi = max(seg_temps) if seg_temps else None
            self.segments.set_row(segment - 1, [
                name,
                (f"{lo:.3f} V", level_color(cell_level(lo, cfg))),
                (f"{hi:.3f} V", level_color(cell_level(hi, cfg))),
                (f"{(hi - lo) * 1000:.0f} mV", theme.TEXT_MUTED),
                ("—", theme.TEXT_FAINT) if t_hi is None else (f"{t_hi:.1f} °C", level_color(temp_level(t_hi, cfg))),
            ])

        self.connection.setText(f"Connected to {data.link_name}" if data.connected else "Not connected")
        self.device.setText(device_html(data.device) or "No device information")
