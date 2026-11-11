"""Small building blocks shared by the screens."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
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


def section_label(text: str) -> QWidget:
    """A group heading with a rule under it."""
    widget = QWidget()
    box = QVBoxLayout(widget)
    box.setContentsMargins(0, 8, 0, 2)
    box.setSpacing(4)
    box.addWidget(label(text, "sectionLabel"))
    rule = QFrame()
    rule.setObjectName("rule")
    rule.setFixedHeight(1)
    box.addWidget(rule)
    return widget


def pad_spin_box(spin: QAbstractSpinBox) -> None:
    """Keep a spin box's text off its left edge. Style sheet padding does not reach the text inside one."""
    editor = spin.findChild(QLineEdit)
    if editor is not None:
        editor.setTextMargins(4, 0, 0, 0)


def button(text: str, on_click: Callable | None = None, name: str = "", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if on_click is not None:
        widget.clicked.connect(on_click)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


class Panel(QWidget):
    """The contents of the left configuration panel for one screen."""

    def __init__(self) -> None:
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 8, 14, 14)
        self.box.setSpacing(8)

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
    """A bordered group of related controls, with an optional heading."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(12, 10, 12, 12)
        self.box.setSpacing(8)
        if title:
            self.box.addWidget(label(title, "cardTitle"))


class ScreenHeader(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(title, "screenTitle"))
        row.addSpacing(14)
        self.summary = label("", "screenSummary")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.summary, 1)
        self.right = QHBoxLayout()
        row.addLayout(self.right)


def screen_layout(widget: QWidget, title: str) -> tuple[QVBoxLayout, ScreenHeader]:
    box = QVBoxLayout(widget)
    box.setContentsMargins(18, 12, 18, 14)
    box.setSpacing(10)
    header = ScreenHeader(title)
    header.setMinimumHeight(28)  # The same with or without buttons on the right
    box.addWidget(header)
    return box, header


def colored(text: str, hex_code: str) -> str:
    return f"<span style='color:{hex_code}'>{text}</span>"


def device_html(device: dict[str, str]) -> str:
    """What the BMS says about itself (firmware, hardware and so on), one line each."""
    return "<br>".join(f"{key}: {colored(value, theme.TEXT)}" for key, value in device.items())


class Badge(QLabel):
    """A named state: a dot in the state's colour, then its name. Without the dot, a small outlined tag."""

    DOT = 8

    def __init__(self, text: str = "—", compact: bool = False, dot: bool = True, px: int = 0) -> None:
        super().__init__(text)
        self.compact = compact  # Smaller, for tags inside a list row
        self.dot = dot
        self.px = px or (11 if compact else 12)
        self.hex_code = theme.TEXT_FAINT
        self.set_state(text, theme.TEXT_FAINT)

    def set_state(self, text: str, hex_code: str) -> None:
        self.setText(text)
        self.hex_code = hex_code
        if self.dot:
            style = f"color: {theme.TEXT}; padding-left: {self.DOT + 6}px; font-weight: 600;"
        else:
            style = (f"color: {hex_code}; border: 1px solid {theme.BORDER}; border-radius: 2px;"
                     f" padding: 0 5px;")
        self.setStyleSheet(f"QLabel {{ {style} font-size: {self.px}px; }}")
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.dot:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(self.hex_code))
        p.drawEllipse(QRectF(0.5, (self.height() - self.DOT) / 2 + 0.5, self.DOT, self.DOT))
        p.end()


def value_html(text: str, hex_code: str) -> str:
    """A formatted value as rich text: the number in its state colour, the unit smaller and muted."""
    number, space, unit = text.rpartition(" ")
    try:
        float(number)
    except ValueError:
        return colored(escape(text), hex_code)
    return (f"{colored(escape(number), hex_code)}<span style='font-size:12px; font-weight:400; "
            f"color:{theme.TEXT_MUTED}'>{space}{escape(unit)}</span>")


class Readout(QFrame):
    """One value in a ReadoutGrid: caption, large value or state, and an optional line beneath."""

    def __init__(self, caption: str, badge: bool = False) -> None:
        super().__init__()
        self.setObjectName("readout")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(1)
        box.addWidget(label(caption, "tileCaption"))
        self.badge = Badge(px=18) if badge else None
        self.value = label("—", "tileValue")
        self.value.setTextFormat(Qt.TextFormat.RichText)
        self.value.setMinimumHeight(28)
        if self.badge is not None:
            self.badge.setMinimumHeight(28)
        box.addWidget(self.value if self.badge is None else self.badge)
        self.sub = label(" ", "tileSub")  # Always present, so every readout in a row is the same height
        box.addWidget(self.sub)

    def set_value(self, text: str, hex_code: str) -> None:
        if self.badge is not None:
            self.badge.set_state(text, hex_code)
        else:
            self.value.setText(value_html(text, hex_code))

    def set_sub(self, text: str) -> None:
        self.sub.setText(text or " ")


class Tile(Readout):
    """A Readout showing one live channel. Hover shows where the value comes from; clicking adds it to Plots."""

    def __init__(self, ctx: AppContext, cid: str, caption: str | None = None, badge: bool = False) -> None:
        info = ctx.data.channels[cid]
        super().__init__(caption or info.name, badge)
        self.info = info
        self.ctx = ctx
        self.cid = cid

    def refresh(self) -> None:
        data = self.ctx.data
        value = data.value(self.cid)
        stale = data.is_stale(self.cid)
        hex_code = value_color(self.cid, value, self.ctx.config, self.info.labels, stale=stale)
        self.set_value(self.info.format(value), hex_code)
        self.setToolTip(data.tooltip(self.cid))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.ctx.plot(self.cid)
        super().mouseReleaseEvent(event)


class ReadoutGrid(QFrame):
    """Readouts in one bordered box with hairlines between them, like an instrument panel.

    `columns` is how many go on a row; 0 puts them all on one row.
    """

    def __init__(self, readouts: list[Readout], columns: int = 0) -> None:
        super().__init__()
        self.setObjectName("readouts")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        columns = columns or len(readouts)
        last_row = (len(readouts) - 1) // columns
        for i, readout in enumerate(readouts):
            row, column = divmod(i, columns)
            # The style sheet leaves the dividing line off the outer edges.
            readout.setProperty("lastColumn", column == columns - 1)
            readout.setProperty("lastRow", row == last_row)
            grid.addWidget(readout, row, column)
        for column in range(columns):
            grid.setColumnStretch(column, 1)


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
            b.setProperty("edge", "first" if i == 0 else "last" if i == len(options) - 1 else "")
            b.setCheckable(True)
            b.setChecked(i == current)
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
        form.setVerticalSpacing(6)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
            pad_spin_box(editor)
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
        self.swatch.setFixedSize(10, 10)
        row.addWidget(self.swatch)
        row.addWidget(label(text, "muted"), 1)
        self.restyle()
        theme.signals.changed.connect(self.restyle)

    def restyle(self) -> None:
        self.swatch.setStyleSheet(f"background: {getattr(theme, self.token)}; border-radius: 1px;")
