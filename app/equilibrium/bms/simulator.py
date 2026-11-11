"""A simulated BMS, so every screen can be built and tried without hardware.

It behaves like a link to a real BMS: it pushes channel values into the data store, raises and
resolves faults, prints console lines and answers text commands. The real serial link will
offer the same interface (send(), received, start(), stop(), and flash() once there is a bootloader
protocol).
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from equilibrium.bms.config import Config
from equilibrium.bms.layout import AMS_STATES, CHARGER_STATES, PRECHARGE_STATES, balance_id, board_id, cell_id, temp_id
from equilibrium.bms.store import BmsData

TICK_S = 0.2
FLASH_SECONDS = 4.0  # How long pretend programming takes
SOC_POINTS = [0.0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0]
OCV_POINTS = [3.00, 3.30, 3.45, 3.55, 3.68, 3.85, 4.00, 4.08, 4.18]
CHARGE_SPEEDUP = 25  # Charging is sped up so a demo reaches the target in minutes, not hours.

HELP = """Commands:
  help                 this list
  version              firmware and hardware versions
  status               pack summary
  faults               list present faults
  faults clear         clear latched faults
  stream on|off        periodic status lines
  charge start|stop    start or stop charging
  identify <seg>.<n>   blink the LED on a slave board
  chain scan           re-enumerate the daisy chain
  config write         write the app's configuration to the BMS
  sim dropout [seg]    (simulator) stop one segment's data for 3 s
  sim usb              (simulator) stop all data for 2 s
  sim fault            (simulator) inject a cell overvoltage fault"""


class Simulator(QObject):
    received = Signal(str)
    name = "Simulated BMS"

    def __init__(self, data: BmsData, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.config = config
        self.layout = layout = data.layout
        rng = self.rng = random.Random(7)

        n = layout.cell_count
        self.soc_offset = [rng.gauss(0, 0.004) for _ in range(n)]
        self.soc_offset[rng.randrange(n)] -= 0.03  # One weak cell
        self.soc_offset[rng.randrange(n)] += 0.015  # One high cell
        self.resistance = [0.0025 * (1 + rng.gauss(0, 0.08)) for _ in range(n)]
        self.balancing = [False] * n

        sx, sy, sz = layout.segment_size
        self.heat_factor = []
        for t in layout.thermistors:
            # Thermistors near the middle of a segment run hotter.
            d = math.sqrt(((t.x - sx / 2) / sx) ** 2 + ((t.y - sy / 2) / sy) ** 2 + ((t.z - sz / 2) / sz) ** 2)
            self.heat_factor.append(0.6 + 0.9 * max(0.0, 1 - 1.6 * d) + rng.gauss(0, 0.05))
        self.temp_offset = [rng.gauss(0, 0.4) for _ in layout.thermistors]
        self.hot = min(len(layout.thermistors) - 1, 3 * len(layout.thermistors) // layout.segments + 9)

        self.soc = 0.78
        self.heat = 0.0
        self.t = 0.0
        self.state = "Init"
        self.ts_voltage = 0.0
        self.current = 0.0
        self.charge_requested = False
        self.charge_complete = False
        self.stream = True
        self.dropouts: dict[int, float] = {}
        self.usb_drop_until = 0.0
        self.injected_until = 0.0
        self.pec = {board: 0 for board in layout.boards()}
        self._last_stream = 0.0
        self.firmware = "v0.4.2 (simulated)"
        self._flash: tuple[QTimer, Callable[[str], None]] | None = None  # Programming in progress

        self.timer = QTimer(self)
        self.timer.setInterval(int(TICK_S * 1000))
        self.timer.timeout.connect(self._tick)

    # Link interface

    def start(self) -> None:
        self.data.device.update(
            {
                "Firmware": self.firmware,
                "Bootloader": "v1.1.0",
                "Hardware": "Master board rev C",
                "Serial number": "EQ-SIM-0001",
            }
        )
        self.data.set_connected(True, self.name)
        # Something in the history list from an earlier session.
        old = self.data.raise_fault(0x0301, "CAN bus timeout", "warning", "")
        old.first_seen -= 3600
        old.last_seen = old.first_seen + 2
        self.data.resolve_fault(0x0301, "")
        old.latched = False
        self.timer.start()
        self.received.emit(self._banner())

    def _banner(self) -> str:
        """What the BMS prints when it starts."""
        return f"Equilibrium BMS {self.firmware}. Type 'help' for commands."

    def stop(self) -> None:
        self.timer.stop()
        if self._flash is not None:
            timer, on_done = self._flash
            timer.stop()
            self._flash = None
            on_done("The connection to the BMS closed while programming.")

    def flash(self, files: list[Path], version: str, on_progress: Callable[[float], None],
              on_done: Callable[[str], None]) -> None:
        """Pretend to program firmware: drop into the bootloader, take the files, restart.

        Returns at once. Reports progress from 0 to 1, then calls on_done with "" for success or a
        message saying what went wrong. A real BMS reports its new version itself; the simulator is
        told it.
        """
        if self._flash is not None:
            on_done("The BMS is already being programmed.")
            return
        missing = [f.name for f in files if not f.is_file()]
        if missing:
            on_done(f"Missing firmware file: {', '.join(missing)}")
            return
        self.timer.stop()  # A BMS in its bootloader sends no data.
        self.received.emit("BOOT entering bootloader")
        started = time.monotonic()
        timer = QTimer(self)
        timer.setInterval(100)

        def step() -> None:
            fraction = (time.monotonic() - started) / FLASH_SECONDS
            if fraction < 1:
                on_progress(fraction)
                return
            timer.stop()
            timer.deleteLater()
            self._flash = None
            self.firmware = f"v{version} (simulated)"
            self.data.device["Firmware"] = self.firmware
            self.state = "Init"
            self.received.emit("BOOT image verified, restarting")
            self.received.emit(self._banner())
            self.timer.start()
            on_progress(1.0)
            on_done("")

        timer.timeout.connect(step)
        self._flash = (timer, on_done)
        timer.start()

    def send(self, text: str) -> None:
        words = text.strip().split()
        if not words:
            return
        if self._flash is not None:
            self.received.emit("ERR in bootloader: wait for programming to finish")
            return
        cmd, args = words[0].lower(), [w.lower() for w in words[1:]]
        reply = self.received.emit
        if cmd == "help":
            for line in HELP.splitlines():
                reply(line)
        elif cmd == "version":
            for key, value in self.data.device.items():
                reply(f"{key}: {value}")
        elif cmd == "status":
            v = self.data.values
            reply(f"State {self.state}, SOC {self.soc * 100:.1f} %, pack {v.get('pack.voltage', 0):.1f} V, "
                  f"{self.current:.1f} A")
            reply(f"Cells {v.get('cell.min', 0):.3f}-{v.get('cell.max', 0):.3f} V, "
                  f"temps {v.get('temp.min', 0):.1f}-{v.get('temp.max', 0):.1f} °C")
        elif cmd == "faults" and args[:1] == ["clear"]:
            reply(f"OK cleared {self.data.clear_faults()} fault(s)")
        elif cmd == "faults":
            present = self.data.present_faults()
            if not present:
                reply("No faults present")
            for f in present:
                reply(f"0x{f.code:04X} {f.severity.upper():8} {f.name} [{f.status}]")
        elif cmd == "stream" and args[:1] in (["on"], ["off"]):
            self.stream = args[0] == "on"
            reply(f"OK stream {args[0]}")
        elif cmd == "charge" and args[:1] == ["start"]:
            if any(f.severity == "critical" and f.present for f in self.data.faults):
                reply("ERR cannot charge with critical faults present")
            else:
                self.charge_requested = True
                self.charge_complete = False
                reply("OK charging started")
        elif cmd == "charge" and args[:1] == ["stop"]:
            self.charge_requested = False
            reply("OK charging stopped")
        elif cmd == "identify" and args:
            reply(f"OK slave board {args[0]} LED blinking for 10 s")
        elif cmd == "chain" and args[:1] == ["scan"]:
            reply(f"OK found {self.layout.board_count} of {self.layout.board_count} slave boards")
        elif cmd == "config" and args[:1] == ["write"]:
            reply(f"OK wrote {len(self.config.values)} settings")
        elif cmd == "sim" and args[:1] == ["dropout"]:
            segment = int(args[1]) if len(args) > 1 and args[1].isdigit() else self.rng.randint(1, self.layout.segments)
            self.dropouts[segment] = self.t + 3
            reply(f"OK segment {segment} dropping out for 3 s")
        elif cmd == "sim" and args[:1] == ["usb"]:
            self.usb_drop_until = self.t + 2
            reply("OK pausing all data for 2 s")
        elif cmd == "sim" and args[:1] == ["fault"]:
            self.injected_until = self.t + 2
            reply("OK injecting cell overvoltage fault")
        else:
            reply(f"ERR unknown command '{text.strip()}'. Type 'help' for commands.")

    # Simulation

    def _ocv(self, soc: float) -> float:
        return float(np.interp(soc, SOC_POINTS, OCV_POINTS))

    def _tick(self) -> None:
        self.t += TICK_S
        cfg = self.config
        layout = self.layout
        rng = self.rng

        # Random daisy chain hiccups, about once every two minutes.
        if rng.random() < TICK_S / 120:
            self.dropouts[rng.randint(1, layout.segments)] = self.t + 3
        for segment, until in list(self.dropouts.items()):
            if until < self.t:
                del self.dropouts[segment]

        self._step_state()
        capacity = max(float(cfg["cell_capacity_ah"]) * int(cfg["parallel_count"]), 20.0)
        speed = CHARGE_SPEEDUP if self.state == "Charging" else 1
        self.soc = min(1.0, max(0.0, self.soc - self.current * TICK_S * speed / 3600 / capacity))

        cells = [
            self._ocv(self.soc + self.soc_offset[i]) - self.current * self.resistance[i] + rng.gauss(0, 0.0006)
            for i in range(layout.cell_count)
        ]
        self._balance(cells)

        self.heat += ((self.current**2) * 0.012 - self.heat) * TICK_S / 40
        temps = []
        for i, factor in enumerate(self.heat_factor):
            t = 26 + self.heat * factor + self.temp_offset[i] + rng.gauss(0, 0.05)
            if i == self.hot:
                t += 12 + 8 * math.sin(self.t / 25)
            temps.append(t)

        pack_v = sum(cells)
        target_ts = pack_v if self.state in ("Precharge", "Drive", "Charging") else 0.0
        self.ts_voltage += (target_ts - self.ts_voltage) * (0.3 if self.state == "Precharge" else 0.6)

        values: dict[str, float] = {
            "pack.voltage": pack_v,
            "pack.current": self.current,
            "pack.power": pack_v * self.current / 1000,
            "pack.soc": self.soc * 100,
            "ts.voltage": self.ts_voltage,
            "cell.max": max(cells),
            "cell.min": min(cells),
            "cell.avg": pack_v / len(cells),
            "cell.delta": (max(cells) - min(cells)) * 1000,
            "temp.max": max(temps),
            "temp.min": min(temps),
            "temp.avg": sum(temps) / len(temps),
            "ams.state": AMS_STATES.index(self.state),
            "precharge.state": PRECHARGE_STATES.index(self._precharge_state()),
            "charger.state": CHARGER_STATES.index(self._charger_state()),
            "charger.voltage": pack_v + 1.5 if self.state == "Charging" else 0.0,
            "charger.current": -self.current if self.state == "Charging" else 0.0,
            "bal.count": sum(self.balancing),
        }
        for number in range(1, layout.cell_count + 1):
            segment, _, _ = layout.cell_position(number)
            if segment in self.dropouts:
                continue
            values[cell_id(number)] = cells[number - 1]
            values[balance_id(number)] = 1.0 if self.balancing[number - 1] else 0.0
        for th in layout.thermistors:
            if th.segment not in self.dropouts:
                values[temp_id(th.number)] = temps[th.number - 1]
        for segment, slave in layout.boards():
            if rng.random() < 0.002 or (segment in self.dropouts and rng.random() < 0.3):
                self.pec[(segment, slave)] += 1
            if segment in self.dropouts:
                continue
            seg_temps = [temps[th.number - 1] for th in layout.segment_thermistors(segment) if th.slave == slave]
            values[board_id(segment, slave, "pec")] = self.pec[(segment, slave)]
            values[board_id(segment, slave, "die")] = sum(seg_temps) / max(1, len(seg_temps)) + 6

        if self.t >= self.usb_drop_until:
            self.data.update(values)
        self._check_faults(cells, temps, values)
        self._emit_stream(values)

    def _step_state(self) -> None:
        critical = any(f.severity == "critical" and f.active for f in self.data.faults)
        if critical:
            self.state = "Fault"
            self.current = 0.0
            self.charge_requested = False
            return
        if self.state == "Fault":
            self.state = "Idle"
        if self.state == "Init" and self.t > 1.0:
            self.state = "Idle"
        elif self.state == "Idle" and self.t > 2.5 and not self.charge_requested:
            self.state = "Precharge"
            self.received.emit("INFO precharge started")
        elif self.state == "Precharge":
            pct = float(self.config["precharge_target_pct"]) / 100
            pack = self.data.values.get("pack.voltage", 1.0)
            if self.ts_voltage >= pct * pack:
                self.state = "Drive"
                self.received.emit("INFO precharge complete, AIRs closed")

        if self.charge_requested and self.state in ("Idle", "Drive", "Precharge"):
            self.state = "Charging"
        if not self.charge_requested and self.state == "Charging":
            self.state = "Idle"

        if self.state == "Drive":
            t = self.t
            self.current = (14 + 30 * math.sin(0.33 * t) + 16 * math.sin(1.7 * t) + 10 * math.sin(0.09 * t)
                            + self.rng.gauss(0, 1.5))
        elif self.state == "Charging":
            target = float(self.config["charge_target"])
            max_cell = self.data.values.get("cell.max", 0.0)
            taper = max(0.0, min(1.0, (target - max_cell) / 0.04))
            amps = float(self.config["charge_current_max"]) * taper
            soc_limit = float(self.config["charge_soc_limit"]) / 100
            if amps < float(self.config["charge_termination_a"]) or self.soc >= soc_limit:
                self.charge_requested = False
                self.charge_complete = True
                self.state = "Idle"
                self.current = 0.0
                self.received.emit("INFO charge complete")
            else:
                self.current = -amps
        else:
            self.current = 0.3 + self.rng.gauss(0, 0.05)

    def _precharge_state(self) -> str:
        return {"Precharge": "Precharging", "Drive": "Closed", "Charging": "Closed"}.get(self.state, "Open")

    def _charger_state(self) -> str:
        if self.state == "Charging":
            return "Balancing" if any(self.balancing) and abs(self.current) < 2 else "Charging"
        return "Complete" if self.charge_complete else "Connected"

    def _balance(self, cells: list[float]) -> None:
        cfg = self.config
        active = bool(cfg["balance_enabled"]) and self.state == "Charging"
        floor = min(cells) + float(cfg["balance_threshold_mv"]) / 1000
        minimum = float(cfg["balance_min_voltage"])
        for i, v in enumerate(cells):
            self.balancing[i] = active and v > floor and v > minimum
            if self.balancing[i]:
                self.soc_offset[i] -= 0.00004 * CHARGE_SPEEDUP / 5

    def _check_faults(self, cells: list[float], temps: list[float], values: dict[str, float]) -> None:
        cfg = self.config
        data = self.data
        hot = temps[self.hot]
        location = temp_id(self.hot + 1)
        if hot >= float(cfg["temp_ot_fault"]):
            data.raise_fault(0x0201, "Overtemperature", "critical", location)
        elif hot >= float(cfg["temp_ot_warn"]):
            data.raise_fault(0x0202, "Overtemperature warning", "warning", location)
        if hot < float(cfg["temp_ot_warn"]) - 1:
            data.resolve_fault(0x0202, location)
        if hot < float(cfg["temp_ot_fault"]) - 1:
            data.resolve_fault(0x0201, location)

        delta_mv = values["cell.delta"]
        if delta_mv > 60:
            data.raise_fault(0x0105, "Cell imbalance", "info", "cell.delta")
        elif delta_mv < 50:
            data.resolve_fault(0x0105, "cell.delta")

        if self.injected_until > self.t:
            data.raise_fault(0x0101, "Cell overvoltage", "critical", cell_id(cells.index(max(cells)) + 1))
        else:
            for fault in data.faults:
                if fault.code == 0x0101 and fault.active:
                    data.resolve_fault(0x0101, fault.location)

        for segment in range(1, self.layout.segments + 1):
            where = f"Segment {segment} daisy chain"
            if segment in self.dropouts:
                data.raise_fault(0x0401, "Daisy chain timeout", "warning", where)
            else:
                data.resolve_fault(0x0401, where)

    def _emit_stream(self, values: dict[str, float]) -> None:
        if not self.stream or self.t - self._last_stream < 1.0 or self.t < self.usb_drop_until:
            return
        self._last_stream = self.t
        self.received.emit(
            f"STAT t={self.t:7.1f} {self.state:<9} V={values['pack.voltage']:6.1f} I={self.current:6.1f} "
            f"SOC={self.soc * 100:5.1f} Vmin={values['cell.min']:.3f} Vmax={values['cell.max']:.3f} "
            f"Tmax={values['temp.max']:.1f}"
        )
        if self.rng.random() < 0.15:
            self.received.emit(f"DBG isoSPI loop {self.rng.randint(180, 240)} us, {sum(self.pec.values())} PEC total")
