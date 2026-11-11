"""The start screen: connect to a BMS, or work offline on a saved or blank configuration."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from equilibrium import ICON_PATH, __version__, theme
from equilibrium.ui.widgets import button, label, section_label

SIMULATOR = "__simulator__"


def serial_ports() -> list[tuple[str, str]]:
    """(port name, description) for each serial port. Empty if Qt's serial module is not installed."""
    try:
        from PySide6.QtSerialPort import QSerialPortInfo
    except ImportError:
        return []
    ports = []
    for info in QSerialPortInfo.availablePorts():
        description = info.description() or info.manufacturer() or "Serial port"
        ports.append((info.portName(), description))
    return ports


class ConnectionPage(QWidget):
    connectSimulator = Signal()
    openConfig = Signal()
    newConfig = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("startPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # So the style sheet's background is drawn
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(420)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

        box = QVBoxLayout(card)
        box.setContentsMargins(24, 22, 24, 24)
        box.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        icon = QLabel()
        pixmap = QPixmap(str(ICON_PATH))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF()
            pixmap = pixmap.scaled(round(40 * ratio), round(40 * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            icon.setPixmap(pixmap)
        brand.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("Equilibrium", "startTitle"))
        titles.addWidget(label(f"Battery management system tool, version {__version__}", "faint"))
        brand.addLayout(titles)
        brand.addStretch(1)
        box.addLayout(brand)
        box.addSpacing(6)

        box.addWidget(section_label("Connect to a BMS"))
        self.ports = QListWidget()
        self.ports.setMinimumHeight(170)
        self.ports.itemDoubleClicked.connect(lambda _item: self._connect())
        self.ports.itemSelectionChanged.connect(self._selection_changed)
        box.addWidget(self.ports)
        actions = QHBoxLayout()
        actions.addWidget(button("Refresh", self.refresh))
        actions.addStretch(1)
        self.connect_button = button("Connect", self._connect, "primary")
        self.connect_button.setMinimumWidth(96)
        actions.addWidget(self.connect_button)
        box.addLayout(actions)

        box.addSpacing(6)
        box.addWidget(section_label("Work offline"))
        offline = QHBoxLayout()
        offline.addWidget(button("Open saved configuration…", self.openConfig.emit))
        offline.addWidget(button("New blank configuration", self.newConfig.emit))
        box.addLayout(offline)
        self.refresh()
        theme.signals.changed.connect(self.refresh)

    def refresh(self) -> None:
        self.ports.clear()
        sim = QListWidgetItem("Simulated BMS\nDemo data, no hardware needed")
        sim.setData(Qt.ItemDataRole.UserRole, SIMULATOR)
        self.ports.addItem(sim)
        ports = serial_ports()
        for name, description in ports:
            item = QListWidgetItem(f"{name}\n{description}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.ports.addItem(item)
        if not ports:
            item = QListWidgetItem("No USB serial ports found")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(theme.color(theme.TEXT_FAINT))
            self.ports.addItem(item)
        self.ports.setCurrentRow(0)

    def _selection_changed(self) -> None:
        self.connect_button.setEnabled(bool(self.ports.selectedItems()))

    def _connect(self) -> None:
        item = self.ports.currentItem()
        if item is None:
            return
        port = item.data(Qt.ItemDataRole.UserRole)
        if port == SIMULATOR:
            self.connectSimulator.emit()
        elif port:
            QMessageBox.information(self, "Not available yet",
                                    f"Connecting to {port} needs the BMS serial protocol, which is not defined "
                                    "yet. Use the simulated BMS for now.")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
