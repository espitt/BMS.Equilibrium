"""Terminal: send commands by hand and watch the BMS's status and debug messages."""

from __future__ import annotations

import time
from html import escape

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPlainTextEdit

from equilibrium import theme
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.widgets import button, screen_layout

QUICK_COMMANDS = ["help", "status", "version", "faults"]
MAX_LINES = 5000


class TerminalScreen(Screen):
    title = "Terminal"
    nav_label = "Terminal"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.history: list[str] = []
        self.history_index = 0
        self.show_status = True
        self.show_debug = True
        self.timestamps = True
        self.autoscroll = True
        self.lines: list[tuple[str, str, str]] = []  # (time, text, colour token)

        box, self.header = screen_layout(self, "Terminal")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(theme.mono_font(10))
        self.output.setMaximumBlockCount(MAX_LINES)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        box.addWidget(self.output, 1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setFont(theme.mono_font(10))
        self.input.returnPressed.connect(self._send)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        self.send_button = button("Send", self._send, "primary")
        row.addWidget(self.send_button)
        box.addLayout(row)

        panel = self.panel
        panel.section("Show")
        for text, attr in [("Status stream (STAT)", "show_status"), ("Debug messages (DBG)", "show_debug"),
                           ("Timestamps", "timestamps"), ("Auto-scroll", "autoscroll")]:
            check = QCheckBox(text)
            check.setChecked(True)
            check.toggled.connect(lambda on, a=attr: setattr(self, a, on))
            panel.add(check)
        panel.add(button("Clear", self._clear))
        panel.section("Quick commands")
        for command in QUICK_COMMANDS:
            panel.add(button(command, lambda _=False, c=command: self._run(c)))
        panel.note("Up and down arrows recall earlier commands. Type 'help' for the full list.")
        panel.finish()

        ctx.received.connect(self._received)
        ctx.commandSent.connect(self._sent)
        ctx.linkChanged.connect(self._link_changed)
        self._link_changed()

    def _link_changed(self) -> None:
        connected = self.ctx.connected
        self.input.setEnabled(connected)
        self.send_button.setEnabled(connected)
        self.input.setPlaceholderText("Type a command and press Enter" if connected
                                      else "Connect to a BMS to send commands")
        self.header.summary.setText(f"Connected to {self.ctx.data.link_name}" if connected else "Not connected")
        if connected:
            self._append(f"Connected to {self.ctx.data.link_name}", "ACCENT")
        elif self.output.blockCount() > 1:
            self._append("Disconnected", "TEXT_FAINT")

    def _run(self, command: str) -> None:
        self.ctx.send(command)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
        self.history_index = len(self.history)
        self.input.clear()
        self.ctx.send(text)

    def _sent(self, text: str) -> None:
        self._append(f"> {text}", "ACCENT")

    def _received(self, line: str) -> None:
        if line.startswith("STAT"):
            if not self.show_status:
                return
            token = "TEXT_MUTED"
        elif line.startswith("DBG"):
            if not self.show_debug:
                return
            token = "TEXT_FAINT"
        elif line.startswith("ERR"):
            token = "FAULT"
        elif line.startswith("WARN"):
            token = "WARN"
        elif line.startswith("OK"):
            token = "OK"
        else:
            token = "TEXT"
        self._append(line, token)

    def _html(self, stamp: str, text: str, token: str) -> str:
        prefix = f"<span style='color:{theme.TEXT_FAINT}'>{stamp}  </span>" if self.timestamps else ""
        return f"{prefix}<span style='color:{getattr(theme, token)}; white-space:pre'>{escape(text)}</span>"

    def _append(self, text: str, token: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.lines.append((stamp, text, token))
        del self.lines[:-MAX_LINES]
        bar = self.output.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.output.appendHtml(self._html(stamp, text, token))
        if self.autoscroll and at_end:
            bar.setValue(bar.maximum())

    def _clear(self) -> None:
        self.lines.clear()
        self.output.clear()

    def restyle(self) -> None:
        """Redraw the whole log in the new mode's colours."""
        self.output.clear()
        for line in self.lines:
            self.output.appendHtml(self._html(*line))
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.input and event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Up and self.history:
                self.history_index = max(0, self.history_index - 1)
                self.input.setText(self.history[self.history_index])
                return True
            if event.key() == Qt.Key.Key_Down and self.history:
                self.history_index = min(len(self.history), self.history_index + 1)
                self.input.setText(self.history[self.history_index] if self.history_index < len(self.history) else "")
                return True
        return super().eventFilter(obj, event)
