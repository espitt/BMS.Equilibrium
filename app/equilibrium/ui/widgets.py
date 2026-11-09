"""Small building blocks shared by the screens."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from equilibrium import theme
from equilibrium.bms.config import BY_KEY, Config, Setting
from equilibrium.ui.context import AppContext
from equilibrium.ui.states import value_color


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def section_label(text: str) -> QLabel:
    return label(text.upper(), "sectionLabel")


def button(text: str, on_click: Callable | None = None, name: str = "", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if on_click is not None:
        widget.clicked.connect(on_click)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class Panel(QWidget):
    """The contents of the left configuration panel for one screen."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 16, 16, 16)
        self.box.setSpacing(8)
        self.box.addWidget(label(title, "panelTitle"))

    def section(self, title: str) -> None:
        self.box.addWidget(section_label(title))

    def add(self, widget: QWidget) -> QWidget:
        self.box.addWidget(widget)
        return widget

    def note(self, text: str) -> QLabel:
        widget = label(text, "faint", wrap=True)
        self.box.addWidget(widget)
        return widget

    def finish(self) -> None:
        self.box.addStretch(1)


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 12, 14, 14)
        self.box.setSpacing(8)
        if title:
            self.box.addWidget(label(title, "cardTitle"))


class ScreenHeader(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(title, "screenTitle"))
        row.addSpacing(16)
        self.summary = label("", "screenSummary")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.summary, 1)
        self.right = QHBoxLayout()
        row.addLayout(self.right)


def screen_layout(widget: QWidget, title: str) -> tuple[QVBoxLayout, ScreenHeader]:
    box = QVBoxLayout(widget)
    box.setContentsMargins(20, 16, 20, 16)
    box.setSpacing(12)
    header = ScreenHeader(title)
    box.addWidget(header)
    return box, header


def colored(text: str, hex_code: str) -> str:
    return f"<span style='color:{hex_code}'>{text}</span>"


class Badge(QLabel):
    """A pill showing a named state in its state colour."""

    def __init__(self, text: str = "—", compact: bool = False) -> None:
        super().__init__(text)
        self.compact = compact  # Smaller, for tags inside a list row
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_state(text, theme.TEXT_FAINT)

    def set_state(self, text: str, hex_code: str) -> None:
        self.setText(text)
        c = theme.color(hex_code)
        size = "border-radius: 9px; padding: 1px 8px; font-size: 11px;" if self.compact else \
            "border-radius: 11px; padding: 3px 12px;"
        self.setStyleSheet(
            f"QLabel {{ color: {hex_code}; background: rgba({c.red()},{c.green()},{c.blue()},38);"
            f" border: 1px solid rgba({c.red()},{c.green()},{c.blue()},110); {size} font-weight: 600; }}"
        )


class Tile(QFrame):
    """One live value on the dashboard: caption, big value, optional sub line.

    Hover shows where the value comes from; clicking adds it to Plots.
    """

    def __init__(self, ctx: AppContext, cid: str, caption: str | None = None, badge: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        self.cid = cid
        self.info = ctx.data.channels[cid]
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(2)
        box.addWidget(label(caption or self.info.name, "tileCaption"))
        self.badge = Badge() if badge else None
        self.value = QLabel("—")
        if self.badge is not None:
            row = QHBoxLayout()
            row.addWidget(self.badge)
            row.addStretch(1)
            box.addSpacing(4)
            box.addLayout(row)
        else:
            self.value.setStyleSheet("font-size: 24px; font-weight: 600;")
            box.addWidget(self.value)
        self.sub = label(" ", "tileSub")  # Always present, so every tile in a row is the same height
        box.addWidget(self.sub)

    def refresh(self) -> None:
        data = self.ctx.data
        value = data.value(self.cid)
        stale = data.is_stale(self.cid)
        hex_code = value_color(self.cid, value, self.ctx.config, self.info.labels, stale=stale)
        if self.badge is not None:
            self.badge.set_state(self.info.format(value), hex_code)
        else:
            self.value.setText(self.info.format(value))
            self.value.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {hex_code};")
        self.setToolTip(data.tooltip(self.cid))

    def set_sub(self, text: str) -> None:
        self.sub.setText(text or " ")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.ctx.plot(self.cid)
        super().mouseReleaseEvent(event)


class Segmented(QWidget):
    """A row of exclusive buttons, like a segmented control."""

    changed = Signal(int)

    def __init__(self, options: list[str], current: int = 0) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setChecked(i == current)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b, i)
            row.addWidget(b)
        self.group.idClicked.connect(self.changed)

    def current(self) -> int:
        return self.group.checkedId()

    def set_current(self, index: int) -> None:
        button_ = self.group.button(index)
        if button_ is not None:
            button_.setChecked(True)


class SettingsForm(QWidget):
    """Editors for a list of settings, kept in step with the shared configuration."""

    def __init__(self, config: Config, keys: list[str]) -> None:
        super().__init__()
        self.config = config
        self.editors: dict[str, QWidget] = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key in keys:
            setting = BY_KEY[key]
            editor = self._editor(setting)
            if setting.help:
                editor.setToolTip(setting.help)
            self.editors[key] = editor
            if isinstance(editor, QCheckBox):
                form.addRow(editor)
            else:
                caption = label(setting.label, "muted")
                if setting.help:
                    caption.setToolTip(setting.help)
                form.addRow(caption, editor)
        config.changed.connect(self._refresh)

    def _editor(self, s: Setting) -> QWidget:
        value = self.config[s.key]
        if isinstance(s.default, bool):
            editor = QCheckBox(s.label)
            editor.setChecked(bool(value))
            editor.toggled.connect(lambda v, k=s.key: self.config.set(k, bool(v)))
        elif s.choices:
            editor = QComboBox()
            editor.addItems(list(s.choices))
            editor.setCurrentText(str(value))
            editor.currentTextChanged.connect(lambda v, k=s.key: self.config.set(k, v))
        elif isinstance(s.default, float):
            editor = QDoubleSpinBox()
            editor.setDecimals(s.decimals)
            editor.setRange(s.minimum, s.maximum)
            editor.setSingleStep(s.step)
            editor.setValue(float(value))
            editor.valueChanged.connect(lambda v, k=s.key: self.config.set(k, float(v)))
        elif isinstance(s.default, int):
            editor = QSpinBox()
            editor.setRange(int(s.minimum), int(s.maximum))
            editor.setSingleStep(int(s.step))
            if s.hex:
                editor.setDisplayIntegerBase(16)
                editor.setPrefix("0x")
            editor.setValue(int(value))
            editor.valueChanged.connect(lambda v, k=s.key: self.config.set(k, int(v)))
        else:
            editor = QLineEdit(str(value))
            editor.editingFinished.connect(lambda e=editor, k=s.key: self.config.set(k, e.text()))
        if s.unit and isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.setSuffix(f" {s.unit}")
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.setKeyboardTracking(False)
            editor.setMinimumWidth(96)
        return editor

    def _refresh(self, key: str) -> None:
        keys = self.editors if key == "" else [key] if key in self.editors else []
        for k in keys:
            editor = self.editors[k]
            value = self.config[k]
            editor.blockSignals(True)
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                editor.setValue(value)
            elif isinstance(editor, QLineEdit):
                editor.setText(str(value))
            editor.blockSignals(False)


def write_button(ctx: AppContext) -> QPushButton:
    def write() -> None:
        if ctx.send("config write"):
            ctx.message.emit("Configuration written to the BMS")

    b = button("Write to BMS", write, "primary", "Send the configuration to the connected BMS")
    b.setEnabled(ctx.connected)
    ctx.linkChanged.connect(lambda: b.setEnabled(ctx.connected))
    return b


class LegendRow(QWidget):
    """A colour swatch and its meaning. `token` names a theme colour, such as "WARN"."""

    def __init__(self, token: str, text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.token = token
        self.swatch = QLabel()
        self.swatch.setFixedSize(12, 12)
        row.addWidget(self.swatch)
        row.addWidget(label(text, "muted"), 1)
        self.restyle()
        theme.signals.changed.connect(self.restyle)

    def restyle(self) -> None:
        self.swatch.setStyleSheet(f"background: {getattr(theme, self.token)}; border-radius: 3px;")
