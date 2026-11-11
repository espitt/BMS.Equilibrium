"""The main window: start screen, then navigation rail, configuration panel and the screens."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from equilibrium import ICON_PATH, theme
from equilibrium.bms.store import worst_severity
from equilibrium.ui.connection import ConnectionPage
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.charging import ChargingScreen
from equilibrium.ui.screens.comms import CommsScreen
from equilibrium.ui.screens.dashboard import DashboardScreen
from equilibrium.ui.screens.faults import FaultsScreen
from equilibrium.ui.screens.plots import PlotsScreen
from equilibrium.ui.screens.settings import SettingsScreen
from equilibrium.ui.screens.terminal import TerminalScreen
from equilibrium.ui.screens.thermals import ThermalsScreen
from equilibrium.ui.screens.voltages import VoltagesScreen
from equilibrium.ui.states import SEVERITY_COLORS
from equilibrium.ui.widgets import Badge, button, label

SCREENS = [DashboardScreen, VoltagesScreen, ThermalsScreen, PlotsScreen, FaultsScreen, ChargingScreen,
           SettingsScreen, CommsScreen, TerminalScreen]


class NavButton(QPushButton):
    """A navigation entry with an optional count badge on the right."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.badge = QLabel(self)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.hide()

    def set_badge(self, count: int, hex_code: str) -> None:
        self.badge.setVisible(count > 0)
        if count:
            self.badge.setText(str(count))
            self.badge.setStyleSheet(f"background: {hex_code}; color: {theme.ON_ACCENT}; border-radius: 8px; "
                                     f"font-size: 11px; font-weight: 600; padding: 0 5px;")
            self.badge.adjustSize()
            self._place_badge()

    def _place_badge(self) -> None:
        w = max(18, self.badge.sizeHint().width())
        self.badge.setGeometry(self.width() - w - 10, (self.height() - 16) // 2, w, 16)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_badge()


class Banner(QFrame):
    """Shown above every screen when data is stale or nothing is connected."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 5, 12, 5)
        self.text = label("")
        self.text.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.text, 1)
        self.action = button("Connect…")
        row.addWidget(self.action)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        ctx.data.staleChanged.connect(self.refresh)
        ctx.linkChanged.connect(self.refresh)

    def _style(self, hex_code: str) -> None:
        self.setStyleSheet(f"Banner {{ background: {theme.rgba(hex_code, 28)}; "
                           f"border-bottom: 1px solid {theme.BORDER}; }}")

    def refresh(self) -> None:
        data = self.ctx.data
        if not self.ctx.connected:
            self._style(theme.NEUTRAL)
            self.text.setText(f"<b>Offline</b>&nbsp;&nbsp; <span style='color:{theme.TEXT_MUTED}'>Editing the "
                              "configuration without a BMS. Live values are unavailable.</span>")
            self.action.show()
            self.show()
            return
        self.action.hide()
        stale = data.stale
        if not stale:
            self.hide()
            return
        ages = [a for cid in stale if (a := data.stale_for(cid)) is not None and a != float("inf")]
        age = f" for {min(ages):.1f} s" if ages else ""
        if len(stale) == len(data.channels):
            what = "No data from the BMS"
        else:
            segments = sorted({data.channels[c].segment for c in stale if data.channels[c].segment is not None})
            where = f" in segment{'s' if len(segments) > 1 else ''} {', '.join(map(str, segments))}" if segments else ""
            what = f"{len(stale)} channel{'s' if len(stale) != 1 else ''}{where} not updating"
        self._style(theme.WARN)
        self.text.setText(f"<b style='color:{theme.WARN}'>Stale data</b>&nbsp;&nbsp; "
                          f"<span style='color:{theme.TEXT_MUTED}'>{what}{age}. Affected values are greyed "
                          f"out.</span>")
        self.show()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext | None = None) -> None:
        super().__init__()
        self.ctx = ctx or AppContext(self)
        self.setWindowTitle("Equilibrium")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)

        self.connection = ConnectionPage()
        self.connection.connectSimulator.connect(self._connect_simulator)
        self.connection.openConfig.connect(self._open_offline)
        self.connection.newConfig.connect(self._new_offline)
        self.pages.addWidget(self.connection)

        self.workspace = QWidget()
        self.pages.addWidget(self.workspace)
        row = QHBoxLayout(self.workspace)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.screens = [cls(self.ctx) for cls in SCREENS]

        # Navigation rail
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(172)
        rail_box = QVBoxLayout(rail)
        rail_box.setContentsMargins(0, 10, 0, 12)
        rail_box.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(11, 0, 12, 10)
        brand.setSpacing(6)
        # The logo doubles as the light/dark mode switch.
        self.logo = QToolButton()
        self.logo.setObjectName("logoToggle")
        self.logo.setIcon(QIcon(str(ICON_PATH)))
        self.logo.setIconSize(QSize(22, 22))
        self.logo.setAutoRaise(True)
        self.logo.clicked.connect(theme.toggle)
        brand.addWidget(self.logo)
        brand.addWidget(label("Equilibrium", "brand"), 1)
        rail_box.addLayout(brand)
        self.nav: list[NavButton] = []
        for i, screen in enumerate(self.screens):
            b = NavButton(screen.nav_label)
            b.setToolTip(f"{screen.title} (Ctrl+{i + 1})")
            b.clicked.connect(lambda _checked=False, index=i: self.show_screen(index))
            rail_box.addWidget(b)
            self.nav.append(b)
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            shortcut.activated.connect(lambda index=i: self.show_screen(index))
        rail_box.addStretch(1)
        link_box = QVBoxLayout()
        link_box.setContentsMargins(12, 0, 12, 0)
        link_box.setSpacing(8)
        self.link_state = Badge()  # A dot for connected or not, then what to
        link_box.addWidget(self.link_state)
        self.link_button = button("Disconnect", self._toggle_link)
        link_box.addWidget(self.link_button)
        rail_box.addLayout(link_box)
        row.addWidget(rail)

        # Configuration panel for the current screen
        self.side = QFrame()
        self.side.setObjectName("sidePanel")
        self.side.setFixedWidth(288)
        side_box = QVBoxLayout(self.side)
        side_box.setContentsMargins(0, 0, 0, 0)
        self.panels = QStackedWidget()
        for screen in self.screens:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(screen.panel)
            self.panels.addWidget(scroll)
            screen.panelChanged.connect(self._place_panel)
        side_box.addWidget(self.panels)
        row.addWidget(self.side)

        # Content
        content = QWidget()
        content_box = QVBoxLayout(content)
        content_box.setContentsMargins(0, 0, 0, 0)
        content_box.setSpacing(0)
        self.banner = Banner(self.ctx)
        self.banner.action.clicked.connect(self._go_to_connection)
        content_box.addWidget(self.banner)
        self.stack = QStackedWidget()
        for screen in self.screens:
            self.stack.addWidget(screen)
        content_box.addWidget(self.stack, 1)
        row.addWidget(content, 1)

        self.statusBar().setSizeGripEnabled(False)
        self.ctx.message.connect(lambda text: self.statusBar().showMessage(text, 4000))
        self.ctx.linkChanged.connect(self._link_changed)
        self.ctx.data.faultsChanged.connect(self._update_fault_badge)
        self.ctx.data.connectionChanged.connect(self._link_changed)

        theme.signals.changed.connect(self._restyle)
        self._restyle()
        self.show_screen(0)
        self._link_changed()
        self.pages.setCurrentWidget(self.connection)
        self.statusBar().hide()

    def show_screen(self, index: int) -> None:
        if self.pages.currentWidget() is not self.workspace:
            return
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)
        self.stack.setCurrentIndex(index)
        self.panels.setCurrentIndex(index)
        self._place_panel()

    def _place_panel(self) -> None:
        """Show the sidebar unless the screen on show has asked for its room."""
        self.side.setVisible(self.screens[self.stack.currentIndex()].show_panel)

    def screen_index(self, cls) -> int:
        return next(i for i, s in enumerate(self.screens) if isinstance(s, cls))

    def _enter_workspace(self, screen_cls=DashboardScreen) -> None:
        self.pages.setCurrentWidget(self.workspace)
        self.statusBar().show()
        self.show_screen(self.screen_index(screen_cls))

    def _connect_simulator(self) -> None:
        self.ctx.connect_simulator()
        self._enter_workspace()

    def _open_offline(self) -> None:
        settings = self.screens[self.screen_index(SettingsScreen)]
        if settings.open_file():
            self._enter_workspace(SettingsScreen)

    def _new_offline(self) -> None:
        self.ctx.config.reset()
        self._enter_workspace(SettingsScreen)

    def _go_to_connection(self) -> None:
        self.statusBar().hide()
        self.pages.setCurrentWidget(self.connection)

    def _toggle_link(self) -> None:
        if self.ctx.connected:
            self.ctx.disconnect_link()
        else:
            self._go_to_connection()

    def _link_changed(self) -> None:
        if self.ctx.connected:
            self.link_state.set_state(self.ctx.data.link_name, theme.OK)
            self.link_button.setText("Disconnect")
        else:
            self.link_state.set_state("Offline", theme.TEXT_FAINT)
            self.link_button.setText("Connect…")
        self._update_fault_badge()

    def _restyle(self) -> None:
        other = "light" if theme.mode == "dark" else "dark"
        self.logo.setToolTip(f"Switch to {other} mode")
        self.banner.refresh()
        self._link_changed()

    def _update_fault_badge(self) -> None:
        present = self.ctx.data.present_faults()
        worst = worst_severity(present) or "info"
        self.nav[self.screen_index(FaultsScreen)].set_badge(len(present), SEVERITY_COLORS[worst])

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.ctx.config.dirty:
            answer = QMessageBox.question(
                self, "Unsaved configuration", "The configuration has unsaved changes. Quit anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.ctx.disconnect_link()
        super().closeEvent(event)
