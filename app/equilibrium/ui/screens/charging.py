"""Charging: readiness checks, start and stop, live progress. Limits are set in the panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from equilibrium import theme
from equilibrium.bms.layout import CHARGER_STATES
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import STATE_COLORS
from equilibrium.ui.widgets import Badge, Card, SettingsForm, Tile, button, colored, label, screen_layout, write_button


class Check(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text_ = text
        self.setTextFormat(Qt.TextFormat.RichText)
        self.set(None, "")

    def set(self, ok: bool | None, detail: str) -> None:
        mark, hex_code = {True: ("✓", theme.OK), False: ("✕", theme.FAULT), None: ("–", theme.TEXT_FAINT)}[ok]
        extra = f" <span style='color:{theme.TEXT_FAINT}'>{detail}</span>" if detail else ""
        self.setText(f"<span style='color:{hex_code}; font-weight:700'>{mark}</span>&nbsp; {self.text_}{extra}")


class ChargingScreen(Screen):
    title = "Charging"
    nav_label = "Charging"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        box, self.header = screen_layout(self, "Charging")

        top = QHBoxLayout()
        top.setSpacing(12)
        box.addLayout(top)

        # Status and controls
        status = Card("Status")
        self.state_badge = Badge()
        state_row = QHBoxLayout()
        state_row.addWidget(self.state_badge)
        state_row.addStretch(1)
        status.box.addLayout(state_row)
        self.soc = label("—")
        self.soc.setStyleSheet("font-size: 40px; font-weight: 600;")
        status.box.addWidget(self.soc)
        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 1000)
        self.soc_bar.setTextVisible(False)
        self.soc_bar.setFixedHeight(8)
        status.box.addWidget(self.soc_bar)
        self.eta = label("", "muted")
        status.box.addWidget(self.eta)
        controls = QHBoxLayout()
        self.start = button("Start charging", lambda: ctx.send("charge start"), "primary")
        self.stop = button("Stop", lambda: ctx.send("charge stop"))
        self.start.setMinimumHeight(36)
        self.stop.setMinimumHeight(36)
        controls.addWidget(self.start, 2)
        controls.addWidget(self.stop, 1)
        status.box.addSpacing(6)
        status.box.addLayout(controls)
        top.addWidget(status, 3)

        # Readiness
        ready = Card("Ready to charge")
        self.checks = {
            "link": Check("BMS connected"),
            "charger": Check("Charger connected"),
            "faults": Check("No critical faults"),
            "temps": Check("Temperatures within charging limits"),
            "cells": Check("Cells below charge target"),
        }
        for check in self.checks.values():
            ready.box.addWidget(check)
        ready.box.addStretch(1)
        top.addWidget(ready, 2)

        # Live values
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = [
            Tile(ctx, "pack.voltage", "Pack voltage"),
            Tile(ctx, "pack.current", "Pack current"),
            Tile(ctx, "charger.voltage", "Charger voltage"),
            Tile(ctx, "charger.current", "Charger current"),
            Tile(ctx, "cell.max", "Max cell"),
            Tile(ctx, "temp.max", "Max temperature"),
            Tile(ctx, "bal.count", "Cells balancing"),
            Tile(ctx, "cell.delta", "Cell delta"),
        ]
        for i, tile in enumerate(self.tiles):
            grid.addWidget(tile, i // 4, i % 4)
        box.addLayout(grid)

        target_card = Card("Highest cell against charge target")
        self.target_bar = QProgressBar()
        self.target_bar.setRange(0, 1000)
        self.target_bar.setTextVisible(False)
        self.target_bar.setFixedHeight(8)
        self.target_text = label("", "muted")
        target_card.box.addWidget(self.target_bar)
        target_card.box.addWidget(self.target_text)
        box.addWidget(target_card)
        box.addStretch(1)

        panel = self.panel
        panel.section("Charge limits")
        panel.add(SettingsForm(ctx.config, ["charge_target", "charge_current_max", "charge_termination_a",
                                            "charge_soc_limit"]))
        panel.section("Temperature limits")
        panel.add(SettingsForm(ctx.config, ["charge_temp_max", "charge_temp_min"]))
        panel.section("Balancing")
        panel.add(SettingsForm(ctx.config, ["balance_enabled", "balance_threshold_mv", "balance_min_voltage"]))
        panel.section("Charger")
        panel.add(SettingsForm(ctx.config, ["charger_type"]))
        panel.add(write_button(ctx))
        panel.finish()

        ctx.data.faultsChanged.connect(self._on_data)
        ctx.config.changed.connect(lambda _key: self._on_data())

    def refresh(self) -> None:
        data = self.ctx.data
        cfg = self.ctx.config
        for tile in self.tiles:
            tile.refresh()

        state_value = data.value("charger.state")
        state = CHARGER_STATES[int(state_value)] if state_value is not None else None
        stale = data.is_stale("charger.state")
        self.state_badge.set_state(state or "—", theme.STALE if stale else
                                   STATE_COLORS["charger.state"].get(state, theme.TEXT_FAINT))
        soc = data.value("pack.soc")
        self.soc.setText(f"{soc:.1f} %" if soc is not None else "—")
        self.soc.setStyleSheet(f"font-size: 40px; font-weight: 600; color: {theme.STALE if stale else theme.TEXT};")
        self.soc_bar.setValue(int((soc or 0) * 10))

        charging = state in ("Charging", "Balancing")
        current = data.value("pack.current") or 0.0
        capacity = float(cfg["cell_capacity_ah"]) * int(cfg["parallel_count"])
        if charging and current < -0.1 and soc is not None:
            hours = (float(cfg["charge_soc_limit"]) - soc) / 100 * capacity / -current
            self.eta.setText(f"About {max(0, hours) * 60:.0f} min to {cfg['charge_soc_limit']} % at the present current")
        else:
            self.eta.setText("")

        connected = data.connected
        critical = [f for f in data.present_faults() if f.severity == "critical"]
        t_max, t_min = data.value("temp.max"), data.value("temp.min")
        cell_max = data.value("cell.max")
        temps_ok = None if t_max is None else (t_min >= cfg["charge_temp_min"] and t_max <= cfg["charge_temp_max"])
        cells_ok = None if cell_max is None else cell_max < cfg["charge_target"]
        charger_ok = None if state is None else state != "Disconnected"
        self.checks["link"].set(connected, "" if connected else "connect on the start screen")
        self.checks["charger"].set(charger_ok if connected else None, cfg["charger_type"])
        self.checks["faults"].set(not critical if connected else None,
                                  f"{len(critical)} present" if critical else "")
        self.checks["temps"].set(temps_ok if connected else None,
                                 f"{t_min:.1f} to {t_max:.1f} °C" if t_max is not None else "")
        self.checks["cells"].set(cells_ok if connected else None,
                                 f"max {cell_max:.3f} V" if cell_max is not None else "")
        ready = connected and charger_ok and not critical and temps_ok and cells_ok
        self.start.setEnabled(bool(ready) and not charging)
        self.stop.setEnabled(connected and charging)

        target = float(cfg["charge_target"])
        floor = float(cfg["cell_uv_fault"])
        if cell_max is not None:
            self.target_bar.setValue(int(max(0.0, min(1.0, (cell_max - floor) / (target - floor))) * 1000))
            self.target_text.setText(f"{cell_max:.3f} V of {target:.3f} V target "
                                     f"({(target - cell_max) * 1000:+.0f} mV to go)")
        else:
            self.target_bar.setValue(0)
            self.target_text.setText("No data")

        self.header.summary.setText(
            colored(state, STATE_COLORS["charger.state"].get(state, theme.TEXT)) if state and connected else
            "Not connected" if not connected else ""
        )
