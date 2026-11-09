"""BMS configuration settings: what they are, their limits, and saving them to a file.

PROVISIONAL: this list is a stand-in until the firmware's real configuration schema exists.
Screens build their forms from it, so changing a setting here changes it everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

CONFIG_FORMAT = 1


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    default: object
    unit: str = ""
    minimum: float = 0
    maximum: float = 100
    step: float = 1
    decimals: int = 0
    choices: tuple[str, ...] = ()
    hex: bool = False
    help: str = ""


SETTINGS: list[Setting] = [
    # Cell voltage
    Setting("cell_ov_fault", "Overvoltage fault", 4.25, "V", 3.0, 4.5, 0.005, 3),
    Setting("cell_ov_warn", "Overvoltage warning", 4.20, "V", 3.0, 4.5, 0.005, 3),
    Setting("cell_uv_warn", "Undervoltage warning", 3.00, "V", 2.0, 4.0, 0.005, 3),
    Setting("cell_uv_fault", "Undervoltage fault", 2.80, "V", 2.0, 4.0, 0.005, 3),
    Setting("charge_target", "Charge target", 4.15, "V", 3.5, 4.4, 0.005, 3,
            help="Cell voltage at which charging stops"),
    # Balancing
    Setting("balance_enabled", "Balancing enabled", True),
    Setting("balance_threshold_mv", "Balance threshold", 10, "mV", 1, 200,
            help="A cell balances when it is this far above the lowest cell"),
    Setting("balance_min_voltage", "Balance above", 3.60, "V", 2.5, 4.4, 0.01, 2,
            help="No cell balances below this voltage"),
    # Temperature
    Setting("temp_ot_fault", "Overtemperature fault", 60.0, "°C", 0, 100, 0.5, 1),
    Setting("temp_ot_warn", "Overtemperature warning", 55.0, "°C", 0, 100, 0.5, 1),
    Setting("temp_ut_warn", "Undertemperature warning", 0.0, "°C", -40, 40, 0.5, 1),
    Setting("temp_ut_fault", "Undertemperature fault", -20.0, "°C", -40, 40, 0.5, 1),
    # Charging
    Setting("charge_current_max", "Max charge current", 15.0, "A", 0.5, 100, 0.5, 1),
    Setting("charge_termination_a", "Termination current", 1.0, "A", 0.1, 20, 0.1, 1,
            help="Charging ends once the current tapers below this"),
    Setting("charge_soc_limit", "Stop at SOC", 100, "%", 10, 100),
    Setting("charge_temp_max", "Max charging temperature", 45.0, "°C", 0, 80, 0.5, 1),
    Setting("charge_temp_min", "Min charging temperature", 0.0, "°C", -20, 40, 0.5, 1),
    Setting("charger_type", "Charger", "Elcon (CAN)", choices=("Elcon (CAN)", "Generic CAN", "None")),
    # Pack
    Setting("cell_type", "Cell type", "Molicel P45B",
            choices=("Molicel P45B", "Molicel P42A", "Samsung 40T", "LG M50LT", "Generic NMC", "Generic LFP")),
    Setting("cell_capacity_ah", "Cell capacity", 4.5, "Ah", 0.5, 100, 0.1, 1),
    Setting("parallel_count", "Cells in parallel", 1, "", 1, 20),
    # Communication
    Setting("can_baud", "CAN baud rate", "500 kbit/s", choices=("125 kbit/s", "250 kbit/s", "500 kbit/s", "1 Mbit/s")),
    Setting("can_base_id", "CAN base ID", 0x100, "", 0, 0x7FF, hex=True),
    Setting("telemetry_hz", "USB telemetry rate", 10, "Hz", 1, 50),
    # Precharge
    Setting("precharge_target_pct", "Precharge complete at", 95, "%", 50, 100,
            help="Tractive system voltage as a share of pack voltage"),
    Setting("precharge_timeout_ms", "Precharge timeout", 3000, "ms", 500, 20000, 100),
]

BY_KEY = {s.key: s for s in SETTINGS}


class Config(QObject):
    """The configuration being edited. It may come from a file, the BMS, or defaults."""

    changed = Signal(str)  # The key that changed, or "" when everything did
    fileChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.values: dict[str, object] = {s.key: s.default for s in SETTINGS}
        self.path: Path | None = None
        self.dirty = False

    def __getitem__(self, key: str):
        return self.values[key]

    def set(self, key: str, value) -> None:
        if self.values.get(key) == value:
            return
        self.values[key] = value
        self.dirty = True
        self.changed.emit(key)
        self.fileChanged.emit()

    def reset(self) -> None:
        self.values = {s.key: s.default for s in SETTINGS}
        self.path = None
        self.dirty = False
        self.changed.emit("")
        self.fileChanged.emit()

    def to_json(self) -> str:
        return json.dumps({"format": CONFIG_FORMAT, "settings": self.values}, indent=2)

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")
        self.path = Path(path)
        self.dirty = False
        self.fileChanged.emit()

    def load(self, path: Path) -> list[str]:
        """Load settings from a file. Returns the keys it did not recognise."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = raw.get("settings", {})
        unknown = [key for key in settings if key not in BY_KEY]
        self.values = {s.key: settings.get(s.key, s.default) for s in SETTINGS}
        self.path = Path(path)
        self.dirty = False
        self.changed.emit("")
        self.fileChanged.emit()
        return unknown
