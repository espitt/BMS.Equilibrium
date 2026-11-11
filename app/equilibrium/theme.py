"""Colours, fonts and the application stylesheet.

Colour means state. Everything else stays a neutral grey (light or dark), with SUFST blue kept
for selection and branding. Screens take colours from here and never define their own.
"""

from collections.abc import Callable

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from equilibrium import ASSETS_DIR

# Two palettes with the same names. set_mode() copies one into the module globals below, so
# code reads theme.TEXT and so on at the moment it draws and always gets the current mode.
LIGHT = {
    # Surfaces and text. Plain greys with no tint, so the only colour on screen is state.
    "BG": "#ffffff",
    "SURFACE": "#f3f3f3",  # Rail, side panel, table headers
    "SURFACE_2": "#ffffff",  # Inputs and buttons
    "SURFACE_3": "#e7e7e7",  # Hover and selection
    "BORDER": "#d1d1d1",
    "TEXT": "#1a1a1a",
    "TEXT_MUTED": "#5c5c5c",
    "TEXT_FAINT": "#8a8a8a",
    "TOOLTIP_BG": "#ffffff",
    # SUFST blue. Selection and branding only, never pack state.
    "ACCENT": "#00366a",
    "ACCENT_HOVER": "#0d4f8f",
    "ACCENT_TINT": "#e2eaf3",  # Selected backgrounds
    "ON_ACCENT": "#ffffff",  # Text on an accent background
    "DANGER_BORDER": "#e0a3a7",
    "DANGER_HOVER": "#fbeced",
    # Pack state, dark enough to read on white
    "NEUTRAL": "#8f959c",  # A healthy value that needs no attention.
    "OK": "#1a7f37",
    "WARN": "#b9770e",
    "FAULT": "#c62828",
    "STALE": "#c4c4c4",
    "BALANCE": "#7a4fc9",
    "CHARGE": "#0f7f90",
    # Plot series, where colour tells lines apart rather than showing state.
    "SERIES": ["#2f6fdb", "#e8710a", "#12a090", "#c2399b", "#8a6d00", "#6f42c1", "#0b8bb8", "#d6453d"],
}

DARK = {
    "BG": "#1b1b1b",
    "SURFACE": "#232323",
    "SURFACE_2": "#2a2a2a",
    "SURFACE_3": "#353535",
    "BORDER": "#3e3e3e",
    "TEXT": "#e4e4e4",
    "TEXT_MUTED": "#a3a3a3",
    "TEXT_FAINT": "#707070",
    "TOOLTIP_BG": "#2a2a2a",
    # SUFST navy is too dark to see on black, so dark mode uses the lighter blue from the logo.
    "ACCENT": "#4c94dc",
    "ACCENT_HOVER": "#6aa8e6",
    "ACCENT_TINT": "#1f3044",
    "ON_ACCENT": "#ffffff",
    "DANGER_BORDER": "#6b3333",
    "DANGER_HOVER": "#332021",
    "NEUTRAL": "#8b9199",
    "OK": "#3fb950",
    "WARN": "#e0a93a",
    "FAULT": "#f2554d",
    "STALE": "#555555",
    "BALANCE": "#b592f5",
    "CHARGE": "#3fbcc7",
    "SERIES": ["#5fa8ff", "#f0883e", "#56d4a8", "#e86fbf", "#d4c35a", "#9d8cff", "#6fd0e8", "#ff8f8f"],
}

PALETTES = {"light": LIGHT, "dark": DARK}
mode = "light"

BG = SURFACE = SURFACE_2 = SURFACE_3 = BORDER = TEXT = TEXT_MUTED = TEXT_FAINT = TOOLTIP_BG = ""
ACCENT = ACCENT_HOVER = ACCENT_TINT = ON_ACCENT = DANGER_BORDER = DANGER_HOVER = ""
NEUTRAL = OK = WARN = FAULT = STALE = BALANCE = CHARGE = ""
SERIES: list[str] = []
globals().update(LIGHT)

RADIUS = 3  # Corner radius of every box, in pixels. Small, like a native desktop app.


class _Signals(QObject):
    changed = Signal()  # The mode switched; anything holding colours should redraw.


signals = _Signals()
_hooks: list[Callable[[], None]] = []  # Run before `changed`, for modules caching colours


def on_change(hook: Callable[[], None]) -> None:
    _hooks.append(hook)


MONO_FAMILIES = ["Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "monospace"]


def color(hex_code: str, alpha: int = 255) -> QColor:
    c = QColor(hex_code)
    c.setAlpha(alpha)
    return c


def rgba(hex_code: str, alpha: int) -> str:
    """The colour as style sheet text, see-through by alpha (0 clear to 255 solid)."""
    c = QColor(hex_code)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def mix(a: str | QColor, b: str | QColor, f: float) -> QColor:
    """Blend from a (f=0) to b (f=1)."""
    ca, cb = QColor(a), QColor(b)
    f = max(0.0, min(1.0, f))
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * f),
        round(ca.green() + (cb.green() - ca.green()) * f),
        round(ca.blue() + (cb.blue() - ca.blue()) * f),
    )


def mono_font(size: int = 12) -> QFont:
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(size)
    return font


def temperature_color(t: float, ut_fault: float, ut_warn: float, ot_warn: float, ot_fault: float) -> QColor:
    """Heatmap colour, anchored to the limits so warning and fault colours mean the same as elsewhere.

    Cold faults are blue, the normal range runs from a cool slate to a warm sand, and the
    warning and fault limits turn amber and red.
    """
    stops = [
        (ut_fault, QColor("#2f6fdb")),
        (ut_warn, QColor("#5a8ac0")),
        (ut_warn + 0.01, QColor("#7f97b0")),
        (ot_warn - 0.01, QColor("#c4a56c")),
        (ot_warn, QColor(WARN)),
        (ot_fault, QColor(FAULT)),
    ]
    if t <= stops[0][0]:
        return QColor(stops[0][1])
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return mix(c0, c1, (t - t0) / (t1 - t0) if t1 > t0 else 1.0)
    return QColor(stops[-1][1])


def _settings() -> QSettings:
    return QSettings("SUFST", "Equilibrium")


def saved_mode() -> str:
    value = _settings().value("theme", "light")
    return value if value in PALETTES else "light"


def _use(new_mode: str, app: QApplication | None) -> None:
    """Make new_mode's palette the current one, restyle the app and run the hooks."""
    global mode
    mode = new_mode if new_mode in PALETTES else "light"
    globals().update(PALETTES[mode])
    if app is not None:
        _apply_style(app)
    for hook in _hooks:
        hook()


def set_mode(new_mode: str, app: QApplication | None = None) -> None:
    """Switch between "light" and "dark", remember the choice, and tell everything to redraw."""
    _use(new_mode, app or QApplication.instance())
    _settings().setValue("theme", mode)
    signals.changed.emit()


def toggle() -> None:
    set_mode("dark" if mode == "light" else "light")


def apply(app: QApplication) -> None:
    """Style the app in the mode chosen last time."""
    _use(saved_mode(), app)


def _apply_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE_2,
        QPalette.ColorRole.AlternateBase: SURFACE,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE_2,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: ON_ACCENT,
        QPalette.ColorRole.ToolTipBase: SURFACE_3,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_FAINT,
        QPalette.ColorRole.Light: SURFACE_3,
        QPalette.ColorRole.Midlight: SURFACE_3,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BORDER,
        QPalette.ColorRole.Shadow: TEXT_FAINT,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_FAINT))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet() + _spin_buttons())


def stylesheet() -> str:
    r = RADIUS
    return f"""
QToolTip {{
    background: {TOOLTIP_BG}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px;
}}

/* Navigation rail */
#navRail {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#navRail QPushButton#navButton {{
    background: transparent; border: none; border-radius: 0; border-left: 3px solid transparent;
    color: {TEXT_MUTED}; text-align: left; padding: 7px 14px 7px 13px;
}}
#navRail QPushButton#navButton:hover {{ color: {TEXT}; background: {SURFACE_3}; }}
#navRail QPushButton#navButton:checked {{
    color: {TEXT}; background: {SURFACE_3}; border-left: 3px solid {ACCENT}; font-weight: 600;
}}
#logoToggle {{ border: none; border-radius: {r}px; padding: 3px; background: transparent; }}
#logoToggle:hover {{ background: {SURFACE_3}; }}
#logoToggle:pressed {{ background: {BORDER}; }}
#brand {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}

/* Per-screen configuration panel */
#sidePanel {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#sidePanel QScrollArea, #sidePanel QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#sectionLabel {{ color: {TEXT}; font-weight: 600; }}
QFrame#rule {{ background: {BORDER}; border: none; }}
#muted {{ color: {TEXT_MUTED}; }}
#faint {{ color: {TEXT_FAINT}; }}

/* Content */
#startPage {{ background: {SURFACE}; }}
#startTitle {{ font-size: 20px; font-weight: 600; color: {TEXT}; }}
#screenTitle {{ font-size: 16px; font-weight: 600; color: {TEXT}; }}
#screenSummary {{ color: {TEXT_MUTED}; }}
QFrame#card {{ background: {BG}; border: 1px solid {BORDER}; border-radius: {r}px; }}
#cardTitle {{ color: {TEXT}; font-weight: 600; }}

/* Live values, side by side in one box and split by hairlines */
QFrame#readouts {{ background: {BG}; border: 1px solid {BORDER}; border-radius: {r}px; }}
QFrame#readout {{
    background: transparent; border: none;
    border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
}}
QFrame#readout[lastColumn="true"] {{ border-right: none; }}
QFrame#readout[lastRow="true"] {{ border-bottom: none; }}
#tileCaption {{ color: {TEXT_MUTED}; }}
#tileValue {{ font-size: 20px; font-weight: 600; }}
#tileSub {{ color: {TEXT_FAINT}; font-size: 11px; }}

/* Controls */
QPushButton {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: {r}px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}
QPushButton:checked {{ background: {ACCENT_TINT}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {TEXT_FAINT}; }}
QPushButton#danger {{ color: {FAULT}; border-color: {DANGER_BORDER}; }}
QPushButton#danger:hover {{ background: {DANGER_HOVER}; }}
QPushButton#danger:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
QPushButton#segmentPick {{ padding: 5px 4px; }}

/* Segmented control: buttons joined into one box, the chosen one filled */
QPushButton#segment {{ border-radius: 0; border-left: none; padding: 4px 10px; }}
QPushButton#segment[edge="first"] {{
    border-left: 1px solid {BORDER}; border-top-left-radius: {r}px; border-bottom-left-radius: {r}px;
}}
QPushButton#segment[edge="last"] {{ border-top-right-radius: {r}px; border-bottom-right-radius: {r}px; }}
QPushButton#segment:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; }}

QLineEdit, QAbstractSpinBox, QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {r}px; padding: 4px 6px;
    color: {TEXT}; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ background: {SURFACE}; color: {TEXT_FAINT}; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; outline: none;
    selection-background-color: {ACCENT_TINT}; selection-color: {TEXT};
}}
QCheckBox {{ spacing: 8px; }}

QTableWidget, QListWidget, QPlainTextEdit, QTextEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: {r}px; gridline-color: {BORDER};
    outline: none;
}}
QTableWidget::item {{ padding: 2px 6px; }}
QListWidget::item {{ padding: 5px 8px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT_TINT}; color: {TEXT}; }}
QHeaderView {{ background: {SURFACE}; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 5px 6px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_MUTED}; padding: 6px 2px; margin-right: 20px; border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QSplitter::handle {{ background: {BG}; }}
QProgressBar {{ background: {SURFACE_3}; border: none; border-radius: 2px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ border-radius: 2px; background: {NEUTRAL}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {BORDER}; border-radius: 3px; min-height: 24px; min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {TEXT_FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {SURFACE}; color: {TEXT_MUTED}; border-top: 1px solid {BORDER}; }}
QMenuBar {{ background: {SURFACE}; color: {TEXT}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {SURFACE_3}; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 3px 0; }}
QMenu::item {{ padding: 5px 24px; }}
QMenu::item:selected {{ background: {ACCENT_TINT}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 3px 0; }}
"""


def _spin_buttons() -> str:
    """Spin box arrows. Styling a spin box's frame hides Fusion's own arrows, so draw them here."""
    assets = ASSETS_DIR.as_posix()
    r = RADIUS - 1
    return f"""
QAbstractSpinBox {{ padding-right: 20px; }}

QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; border: none; border-left: 1px solid {BORDER}; background: {SURFACE};
}}
QAbstractSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: {r}px; margin: 1px 1px 0 0;
}}
QAbstractSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: {r}px; margin: 0 1px 1px 0;
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {SURFACE_3}; }}
QAbstractSpinBox::up-arrow {{ image: url({assets}/arrow_up.svg); width: 8px; height: 5px; }}
QAbstractSpinBox::down-arrow {{ image: url({assets}/arrow_down.svg); width: 8px; height: 5px; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url({assets}/arrow_down.svg); width: 8px; height: 5px; }}
"""
