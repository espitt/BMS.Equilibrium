"""Dashboard: the pack at a glance. No configuration here."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from equilibrium import theme
from equilibrium.bms.layout import cell_id, temp_id
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import SEVERITY_COLORS, cell_level, temp_level
from equilibrium.ui.widgets import Card, Tile, colored, label, screen_layout, section_label

def level_hex(level: str) -> str:
    return {"normal": theme.TEXT, "warn": theme.WARN, "fault": theme.FAULT}[level]


class SegmentCard(Card):
    def __init__(self, segment: int) -> None:
        super().__init__(f"Segment {segment}")
        self.segment = segment
        self.voltage = label("—")
        self.voltage.setTextFormat(Qt.TextFormat.RichText)
        self.temp = label("—")
        self.temp.setTextFormat(Qt.TextFormat.RichText)
        self.box.addWidget(self.voltage)
        self.box.addWidget(self.temp)


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

        def row(title: str, specs: list[tuple[str, str | None, bool]]) -> list[Tile]:
            box.addWidget(section_label(title))
            grid = QHBoxLayout()
            grid.setSpacing(10)
            made = []
            for cid, caption, badge in specs:
                tile = Tile(ctx, cid, caption, badge)
                grid.addWidget(tile)
                made.append(tile)
            box.addLayout(grid)
            self.last_row = grid
            self.tiles.extend(made)
            return made

        row("State", [("ams.state", "AMS state", True), ("precharge.state", "Precharge", True),
                      ("charger.state", "Charger", True)])
        self.faults_card = Card()
        self.faults_card.box.setContentsMargins(14, 10, 14, 12)
        self.faults_card.box.setSpacing(2)
        self.faults_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.faults_card.box.addWidget(label("Present faults", "tileCaption"))
        self.faults_label = label("—")
        self.faults_label.setStyleSheet("font-size: 24px; font-weight: 600;")
        self.faults_card.box.addWidget(self.faults_label)
        self.faults_card.box.addWidget(label(" ", "tileSub"))
        self.last_row.addWidget(self.faults_card)

        pack = row("Pack", [("pack.voltage", "Pack voltage", False), ("pack.current", "Current", False),
                            ("pack.power", "Power", False), ("pack.soc", "State of charge", False),
                            ("ts.voltage", "TS voltage", False)])
        self.soc_tile = pack[3]
        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 1000)
        self.soc_bar.setTextVisible(False)
        self.soc_bar.setFixedHeight(6)
        self.soc_tile.layout().addWidget(self.soc_bar)

        cells = row("Cells", [("cell.max", "Max cell", False), ("cell.min", "Min cell", False),
                              ("cell.avg", "Average cell", False), ("cell.delta", "Cell delta", False)])
        self.cell_max_tile, self.cell_min_tile = cells[0], cells[1]
        temps = row("Temperatures", [("temp.max", "Max temperature", False), ("temp.min", "Min temperature", False),
                                     ("temp.avg", "Average temperature", False)])
        self.temp_max_tile, self.temp_min_tile = temps[0], temps[1]

        box.addWidget(section_label("Segments"))
        seg_grid = QGridLayout()
        seg_grid.setSpacing(10)
        self.segment_cards = []
        columns = 4 if ctx.layout.segments > 4 else ctx.layout.segments
        for i in range(ctx.layout.segments):
            card = SegmentCard(i + 1)
            seg_grid.addWidget(card, i // columns, i % columns)
            self.segment_cards.append(card)
        box.addLayout(seg_grid)
        box.addStretch(1)

        self.panel.section("Connection")
        self.connection = self.panel.add(label("", "muted", wrap=True))
        self.panel.section("Device")
        self.device = self.panel.add(label("", "muted", wrap=True))
        self.device.setTextFormat(Qt.TextFormat.RichText)
        self.panel.note("The dashboard has no settings. Hover any value to see where it comes from; "
                        "click it to add it to Plots.")
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
            vmax, nmax = max(cells)
            vmin, nmin = min(cells)
            self.cell_max_tile.set_sub(f"Cell {nmax} · segment {layout.cell_position(nmax)[0]}")
            self.cell_min_tile.set_sub(f"Cell {nmin} · segment {layout.cell_position(nmin)[0]}")
        if temps:
            tmax, thmax = max(temps, key=lambda p: p[0])
            tmin, thmin = min(temps, key=lambda p: p[0])
            self.temp_max_tile.set_sub(f"{thmax.label} · segment {thmax.segment}")
            self.temp_min_tile.set_sub(f"{thmin.label} · segment {thmin.segment}")

        present = data.present_faults()
        if not data.connected:
            self.faults_label.setText("—")
            self.faults_label.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {theme.TEXT_FAINT};")
        else:
            worst = next((s for s in ("critical", "warning", "info") if any(f.severity == s for f in present)), None)
            hex_code = SEVERITY_COLORS[worst] if worst else theme.TEXT
            self.faults_label.setText(str(len(present)) if present else "None")
            self.faults_label.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {hex_code};")

        for card in self.segment_cards:
            seg_cells = [data.values.get(cell_id(n)) for n in layout.segment_cells(card.segment)]
            seg_temps = [data.values.get(temp_id(t.number)) for t in layout.segment_thermistors(card.segment)]
            seg_cells = [v for v in seg_cells if v is not None]
            seg_temps = [v for v in seg_temps if v is not None]
            stale = any(data.is_stale(cell_id(n)) for n in layout.segment_cells(card.segment))
            if not seg_cells or stale:
                hex_code = theme.STALE if seg_cells else theme.TEXT_FAINT
                card.voltage.setText(colored("Cells —" if not seg_cells else "Cells stale", hex_code))
                card.temp.setText(colored("Temperature —" if not seg_temps else "Temperature stale", hex_code))
                continue
            lo, hi = min(seg_cells), max(seg_cells)
            worst = max((cell_level(lo, cfg), cell_level(hi, cfg)), key=["normal", "warn", "fault"].index)
            card.voltage.setText(colored(f"{lo:.3f} – {hi:.3f} V", level_hex(worst))
                                 + colored(f"  Δ {(hi - lo) * 1000:.0f} mV", theme.TEXT_MUTED))
            t_hi = max(seg_temps) if seg_temps else None
            if t_hi is not None:
                card.temp.setText(colored(f"{t_hi:.1f} °C max", level_hex(temp_level(t_hi, cfg))))

        self.connection.setText(f"Connected to {data.link_name}" if data.connected else "Not connected")
        self.device.setText("<br>".join(f"{k}: <span style='color:{theme.TEXT}'>{v}</span>"
                                        for k, v in data.device.items()) or "No device information")
