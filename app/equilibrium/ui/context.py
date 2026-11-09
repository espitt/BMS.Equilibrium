"""Shared state for every screen: the pack layout, live data, configuration and the BMS link."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from equilibrium.bms.config import Config
from equilibrium.bms.layout import PackLayout
from equilibrium.bms.store import BmsData


class AppContext(QObject):
    plotRequested = Signal(str)  # A channel id someone clicked, to add to the Plots screen
    commandSent = Signal(str)  # Text sent to the BMS, so the terminal can show it
    received = Signal(str)  # A console line from the BMS
    linkChanged = Signal()
    message = Signal(str)  # A short status bar message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.layout = PackLayout.load()
        self.data = BmsData(self.layout, self)
        self.config = Config(self)
        self.link = None

    @property
    def connected(self) -> bool:
        return self.link is not None

    def connect_simulator(self) -> None:
        from equilibrium.bms.simulator import Simulator

        self.disconnect_link()
        self.link = Simulator(self.data, self.config, self)
        self.link.received.connect(self.received)
        self.link.start()
        self.linkChanged.emit()

    def disconnect_link(self) -> None:
        if self.link is None:
            return
        self.link.stop()
        self.link.blockSignals(True)
        self.link.deleteLater()
        self.link = None
        self.data.reset()
        self.linkChanged.emit()

    def send(self, text: str) -> bool:
        """Send a command to the BMS. Returns False when nothing is connected."""
        if self.link is None:
            self.message.emit("Not connected to a BMS")
            return False
        self.commandSent.emit(text)
        self.link.send(text)
        return True

    def plot(self, cid: str) -> None:
        if cid in self.data.channels:
            self.plotRequested.emit(cid)
