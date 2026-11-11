"""Charging: readiness checks, start and stop, live progress. Limits are set in the panel.

The Games button swaps this for a narrow column holding the same stats, hides the options panel, and
gives the rest of the screen to a game. See _game_hold for when play stops.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from equilibrium import theme
from equilibrium.bms.layout import CHARGER_STATES
from equilibrium.bms.store import SEVERITIES
from equilibrium.ui.context import AppContext
from equilibrium.ui.games.arcade import Arcade
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.states import STATE_COLORS, value_color
from equilibrium.ui.widgets import (
    Badge,
    Card,
    ReadoutGrid,
    SettingsForm,
    Tile,
    button,
    colored,
    label,
    screen_layout,
    section_label,
    write_button,
)

COMPACT_WIDTH = 300
CHECKS = {
    "link": "BMS connected",
    "charger": "Charger connected",
    "faults": "No critical faults",
    "temps": "Temperatures within charging limits",
    "cells": "Cells below charge target",
}
VALUES = [  # Channel and caption of each live value, in both the full and the condensed layout
    ("pack.voltage", "Pack voltage"),
    ("pack.current", "Pack current"),
    ("charger.voltage", "Charger voltage"),
    ("charger.current", "Charger current"),
    ("cell.max", "Max cell"),
    ("temp.max", "Max temperature"),
    ("bal.count", "Cells balancing"),
    ("cell.delta", "Cell delta"),
]


class Check(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text_ = text
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)  # The condensed column is narrow.
        self.set(None, "")

    def set(self, ok: bool | None, detail: str) -> None:
        mark, hex_code = {True: ("✓", theme.OK), False: ("✕", theme.FAULT), None: ("–", theme.TEXT_FAINT)}[ok]
        extra = f" <span style='color:{theme.TEXT_FAINT}'>{detail}</span>" if detail else ""
        self.setText(f"<span style='color:{hex_code}; font-weight:700'>{mark}</span>&nbsp; {self.text_}{extra}")


def progress_bar(height: int) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    bar.setFixedHeight(height)
    return bar


class ValueRow(QWidget):
    """One live value on a single line: a Tile, condensed. Hover says where it comes from; a click plots it."""

    def __init__(self, ctx: AppContext, cid: str, caption: str) -> None:
        super().__init__()
        self.ctx = ctx
        self.cid = cid
        self.info = ctx.data.channels[cid]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(caption, "muted"), 1)
        self.value = label("—")
        row.addWidget(self.value)

    def refresh(self) -> None:
        data = self.ctx.data
        value = data.value(self.cid)
        hex_code = value_color(self.cid, value, self.ctx.config, self.info.labels, stale=data.is_stale(self.cid))
        self.value.setText(self.info.format(value))
        self.value.setStyleSheet(f"font-weight: 600; color: {hex_code};")
        self.setToolTip(data.tooltip(self.cid))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.ctx.plot(self.cid)
        super().mouseReleaseEvent(event)


class CompactStats(Card):
    """Everything the Charging screen shows, in one narrow column, for when a game has the rest of the screen.

    It has the same parts under the same names as the full layout, so the screen fills in both alike.
    """

    soc_px = 24

    def __init__(self, ctx: AppContext) -> None:
        super().__init__("Charging")
        self.setFixedWidth(COMPACT_WIDTH)
        self.box.setSpacing(3)  # Tight, so the whole column fits the smallest window on every platform
        self.state_badge = Badge(compact=True)
        state_row = QHBoxLayout()
        state_row.addWidget(self.state_badge)
        state_row.addStretch(1)
        self.box.addLayout(state_row)
        self.soc = label("—")
        self.box.addWidget(self.soc)
        self.soc_bar = progress_bar(6)
        self.box.addWidget(self.soc_bar)
        self.eta = label("", "muted", wrap=True)
        self.box.addWidget(self.eta)
        controls = QHBoxLayout()
        self.start = button("Start charging", lambda: ctx.send("charge start"), "primary")
        self.stop = button("Stop", lambda: ctx.send("charge stop"))
        controls.addWidget(self.start, 2)
        controls.addWidget(self.stop, 1)
        self.box.addLayout(controls)

        self.box.addWidget(section_label("Ready to charge"))
        self.checks = {key: Check(text) for key, text in CHECKS.items()}
        for check in self.checks.values():
            self.box.addWidget(check)

        self.box.addWidget(section_label("Live values"))
        self.tiles = [ValueRow(ctx, cid, caption) for cid, caption in VALUES]
        for row in self.tiles:
            self.box.addWidget(row)

        self.box.addWidget(section_label("Highest cell against target"))
        self.target_bar = progress_bar(6)
        self.box.addWidget(self.target_bar)
        self.target_text = label("", "muted", wrap=True)
        self.box.addWidget(self.target_text)
        self.box.addStretch(1)


class ChargingScreen(Screen):
    title = "Charging"
    nav_label = "Charging"
    soc_px = 32

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        box, self.header = screen_layout(self, "Charging")
        self.games_button = button("Games", self._set_games,
                                   tooltip="Play a game. The charging stats move into a narrow column beside it.")
        self.games_button.setCheckable(True)
        self.header.right.addWidget(self.games_button)
        self._was_charging = False

        # Either the full layout, or the condensed column with a game beside it.
        columns = QHBoxLayout()
        columns.setSpacing(12)
        box.addLayout(columns, 1)
        self.full = QWidget()
        stats = QVBoxLayout(self.full)
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(12)
        columns.addWidget(self.full, 1)
        self.compact = CompactStats(ctx)
        self.compact.hide()
        columns.addWidget(self.compact)
        self.arcade = Arcade()
        self.arcade.hide()
        columns.addWidget(self.arcade, 1)
        self.views = (self, self.compact)  # Both are filled in by refresh()

        top = QHBoxLayout()
        top.setSpacing(12)
        stats.addLayout(top)

        # Status and controls
        status = Card("Status")
        self.state_badge = Badge()
        state_row = QHBoxLayout()
        state_row.addWidget(self.state_badge)
        state_row.addStretch(1)
        status.box.addLayout(state_row)
        self.soc = label("—")
        status.box.addWidget(self.soc)
        self.soc_bar = progress_bar(6)
        status.box.addWidget(self.soc_bar)
        self.eta = label("", "muted")
        status.box.addWidget(self.eta)
        controls = QHBoxLayout()
        self.start = button("Start charging", lambda: ctx.send("charge start"), "primary")
        self.stop = button("Stop", lambda: ctx.send("charge stop"))
        self.start.setMinimumWidth(140)
        self.stop.setMinimumWidth(80)
        controls.addWidget(self.start)
        controls.addWidget(self.stop)
        controls.addStretch(1)
        status.box.addSpacing(4)
        status.box.addLayout(controls)
        top.addWidget(status, 3)

        # Readiness
        ready = Card("Ready to charge")
        self.checks = {key: Check(text) for key, text in CHECKS.items()}
        for check in self.checks.values():
            ready.box.addWidget(check)
        ready.box.addStretch(1)
        top.addWidget(ready, 2)

        # Live values
        self.tiles = [Tile(ctx, cid, caption) for cid, caption in VALUES]
        stats.addWidget(ReadoutGrid(self.tiles, columns=4))

        target_card = Card("Highest cell against charge target")
        self.target_bar = progress_bar(6)
        self.target_text = label("", "muted")
        target_card.box.addWidget(self.target_bar)
        target_card.box.addWidget(self.target_text)
        stats.addWidget(target_card)
        stats.addStretch(1)

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

    # Games

    def _set_games(self, on: bool) -> None:
        """Swap the full layout and its options panel for the condensed stats and a game, or back."""
        self.full.setVisible(not on)
        self.compact.setVisible(on)
        self.arcade.setVisible(on)
        self.show_panel = not on
        self.panelChanged.emit()
        self.refresh()

    def _game_hold(self) -> str:
        """Why no game may be played right now, or "" when the pack needs no attention."""
        data = self.ctx.data
        if not data.connected:
            return "No BMS is connected"
        active = [f for f in data.faults if f.active and f.severity != "info"]
        if active:
            worst = min(active, key=lambda f: SEVERITIES.index(f.severity))
            return f"{worst.name} ({worst.severity})"
        if data.stale:
            return "Some BMS data has stopped updating"
        return ""

    def refresh(self) -> None:
        data = self.ctx.data
        cfg = self.ctx.config

        state_value = data.value("charger.state")
        state = CHARGER_STATES[int(state_value)] if state_value is not None else None
        stale = data.is_stale("charger.state")
        state_hex = theme.STALE if stale else STATE_COLORS["charger.state"].get(state, theme.TEXT_FAINT)
        soc = data.value("pack.soc")
        soc_hex = theme.STALE if stale else theme.TEXT

        charging = state in ("Charging", "Balancing")
        self.arcade.set_hold(self._game_hold())
        if self._was_charging and state == "Complete":
            self.arcade.pause("Charging has finished")
        self._was_charging = charging
        current = data.value("pack.current") or 0.0
        capacity = float(cfg["cell_capacity_ah"]) * int(cfg["parallel_count"])
        eta = ""
        if charging and current < -0.1 and soc is not None:
            hours = (float(cfg["charge_soc_limit"]) - soc) / 100 * capacity / -current
            eta = f"About {max(0, hours) * 60:.0f} min to {cfg['charge_soc_limit']} % at the present current"

        connected = data.connected
        critical = [f for f in data.present_faults() if f.severity == "critical"]
        t_max, t_min = data.value("temp.max"), data.value("temp.min")
        cell_max = data.value("cell.max")
        temps_ok = None if t_max is None else (t_min >= cfg["charge_temp_min"] and t_max <= cfg["charge_temp_max"])
        cells_ok = None if cell_max is None else cell_max < cfg["charge_target"]
        charger_ok = None if state is None else state != "Disconnected"
        checks = {  # What each readiness check shows: passed (None for unknown), then the detail beside it
            "link": (connected, "" if connected else "connect on the start screen"),
            "charger": (charger_ok if connected else None, cfg["charger_type"]),
            "faults": (not critical if connected else None, f"{len(critical)} present" if critical else ""),
            "temps": (temps_ok if connected else None, f"{t_min:.1f} to {t_max:.1f} °C" if t_max is not None else ""),
            "cells": (cells_ok if connected else None, f"max {cell_max:.3f} V" if cell_max is not None else ""),
        }
        ready = connected and charger_ok and not critical and temps_ok and cells_ok

        target = float(cfg["charge_target"])
        floor = float(cfg["cell_uv_fault"])
        if cell_max is not None:
            target_value = int(max(0.0, min(1.0, (cell_max - floor) / (target - floor))) * 1000)
            target_text = f"{cell_max:.3f} V of {target:.3f} V target ({(target - cell_max) * 1000:+.0f} mV to go)"
        else:
            target_value, target_text = 0, "No data"

        for view in self.views:
            for tile in view.tiles:
                tile.refresh()
            view.state_badge.set_state(state or "—", state_hex)
            view.soc.setText(f"{soc:.1f} %" if soc is not None else "—")
            view.soc.setStyleSheet(f"font-size: {view.soc_px}px; font-weight: 600; color: {soc_hex};")
            view.soc_bar.setValue(int((soc or 0) * 10))
            view.eta.setText(eta)
            for key, (ok, detail) in checks.items():
                view.checks[key].set(ok, detail)
            view.start.setEnabled(bool(ready) and not charging)
            view.stop.setEnabled(connected and charging)
            view.target_bar.setValue(target_value)
            view.target_text.setText(target_text)

        self.header.summary.setText(
            colored(state, STATE_COLORS["charger.state"].get(state, theme.TEXT)) if state and connected else
            "Not connected" if not connected else ""
        )
