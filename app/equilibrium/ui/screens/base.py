"""The common shape of a screen: main content plus a panel for the left sidebar."""

from __future__ import annotations

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from equilibrium import theme
from equilibrium.ui.context import AppContext
from equilibrium.ui.widgets import Panel


class Screen(QWidget):
    title = ""
    nav_label = ""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.panel = Panel(self.title)
        ctx.data.updated.connect(self._on_data)
        ctx.data.staleChanged.connect(self._on_data)
        theme.signals.changed.connect(self.restyle)

    def _on_data(self) -> None:
        # Hidden screens skip the work and catch up when shown.
        if self.isVisible():
            self.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Redraw from the latest data."""

    def restyle(self) -> None:
        """Light or dark mode changed. Screens that keep colours of their own override this."""
        self.refresh()
        self.update()
