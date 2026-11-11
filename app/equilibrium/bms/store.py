"""The live data store: latest value, update time and recent history of every channel, plus faults.

Whatever is connected (the simulator now, the real serial link later) pushes values in with
update(). Screens only read from here.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from equilibrium.bms.layout import PackLayout, build_channels

SEVERITIES = ("critical", "warning", "info")  # Worst first


class History:
    """A fixed-size ring buffer of (time, value) samples for one channel."""

    def __init__(self, size: int) -> None:
        self.t = np.zeros(size)
        self.v = np.zeros(size)
        self.size = size
        self.count = 0
        self.head = 0

    def append(self, t: float, v: float) -> None:
        self.t[self.head] = t
        self.v[self.head] = v
        self.head = (self.head + 1) % self.size
        self.count = min(self.count + 1, self.size)

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Samples in time order, oldest first."""
        if self.count < self.size:
            return self.t[: self.count].copy(), self.v[: self.count].copy()
        return np.roll(self.t, -self.head), np.roll(self.v, -self.head)

    def clear(self) -> None:
        self.count = 0
        self.head = 0


@dataclass(eq=False)  # Compared by identity: each fault is one occurrence
class Fault:
    code: int
    name: str
    severity: str  # One of SEVERITIES
    location: str  # A channel id, or plain text when the fault is not tied to one channel
    first_seen: float  # Wall clock, time.time()
    last_seen: float
    active: bool = True  # The condition is present right now
    latched: bool = True  # Stays present until cleared, even once the condition goes away
    count: int = 1
    snapshot: dict[str, float] = field(default_factory=dict)  # Freeze frame of every channel

    @property
    def present(self) -> bool:
        return self.active or self.latched

    @property
    def status(self) -> str:
        if self.active:
            return "Active"
        return "Latched" if self.latched else "Cleared"


def worst_severity(faults: Iterable[Fault]) -> str | None:
    """The most serious severity among the faults, or None when there are none."""
    found = {fault.severity for fault in faults}
    return next((severity for severity in SEVERITIES if severity in found), None)


class BmsData(QObject):
    updated = Signal()
    staleChanged = Signal()
    faultsChanged = Signal()
    connectionChanged = Signal()

    STALE_AFTER = 1.0  # Seconds without an update before a channel is shown as stale
    HISTORY_SAMPLES = 3000

    def __init__(self, layout: PackLayout, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.layout = layout
        self.channels = build_channels(layout)
        self.values: dict[str, float] = {}
        self.stamps: dict[str, float] = {}
        self.history = {cid: History(self.HISTORY_SAMPLES) for cid in self.channels}
        self.faults: list[Fault] = []
        self.device: dict[str, str] = {}
        self.connected = False
        self.link_name = ""
        self.stale: set[str] = set(self.channels)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.check_stale)
        self._timer.start()

    # Time is seconds since the app started, so history and plots share one clock.
    def now(self) -> float:
        return time.monotonic() - self._t0

    def update(self, values: dict[str, float]) -> None:
        t = self.now()
        for cid, value in values.items():
            self.values[cid] = value
            self.stamps[cid] = t
            history = self.history.get(cid)
            if history is not None:
                history.append(t, value)
        self.check_stale()
        self.updated.emit()

    def value(self, cid: str) -> float | None:
        return self.values.get(cid)

    def is_stale(self, cid: str) -> bool:
        return cid in self.stale

    def stale_for(self, cid: str) -> float | None:
        """Seconds since the channel last updated, or None when it is fresh."""
        if cid not in self.stale:
            return None
        stamp = self.stamps.get(cid)
        return float("inf") if stamp is None else self.now() - stamp

    def tooltip(self, cid: str, extra: str = "") -> str:
        info = self.channels[cid]
        return info.tooltip(self.values.get(cid), self.stale_for(cid), extra)

    def check_stale(self) -> None:
        if self.connected:
            limit = self.now() - self.STALE_AFTER
            stale = {cid for cid in self.channels if self.stamps.get(cid, -1e9) < limit}
        else:
            stale = set(self.channels)
        if stale != self.stale:
            self.stale = stale
            self.staleChanged.emit()

    def set_connected(self, connected: bool, name: str = "") -> None:
        self.connected = connected
        self.link_name = name if connected else ""
        self.check_stale()
        self.connectionChanged.emit()

    def reset(self) -> None:
        """Forget everything from the previous connection."""
        self.values.clear()
        self.stamps.clear()
        for history in self.history.values():
            history.clear()
        self.faults.clear()
        self.device.clear()
        self.set_connected(False)
        self.faultsChanged.emit()
        self.updated.emit()

    # Faults

    def present_faults(self) -> list[Fault]:
        return [f for f in self.faults if f.present]

    def raise_fault(self, code: int, name: str, severity: str, location: str = "") -> Fault:
        now = time.time()
        for fault in self.faults:
            if fault.code == code and fault.location == location and fault.present:
                fault.last_seen = now
                if not fault.active:
                    fault.active = True
                    fault.count += 1
                    self.faultsChanged.emit()
                return fault
        fault = Fault(code, name, severity, location, now, now, snapshot=dict(self.values))
        self.faults.append(fault)
        self.faultsChanged.emit()
        return fault

    def resolve_fault(self, code: int, location: str = "") -> None:
        for fault in self.faults:
            if fault.code == code and fault.location == location and fault.active:
                fault.active = False
                fault.last_seen = time.time()
                self.faultsChanged.emit()

    def clear_faults(self) -> int:
        """Unlatch every fault whose condition has gone. Returns how many were cleared."""
        cleared = 0
        for fault in self.faults:
            if fault.latched and not fault.active:
                fault.latched = False
                cleared += 1
        self.faultsChanged.emit()
        return cleared
