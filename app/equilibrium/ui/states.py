"""Which state colour a value should be drawn in. The one place that decides what is a warning."""

from __future__ import annotations

from equilibrium import theme
from equilibrium.bms.config import Config

# Filled in by _rebuild(), and refilled in place whenever light or dark mode is switched, so
# modules that imported these dictionaries always see the current colours.
STATE_COLORS: dict[str, dict[str, str]] = {}
SEVERITY_COLORS: dict[str, str] = {}
LEVEL_COLORS: dict[str, str] = {}


def _rebuild() -> None:
    STATE_COLORS.clear()
    STATE_COLORS.update({
        "ams.state": {"Init": theme.TEXT_MUTED, "Idle": theme.NEUTRAL, "Precharge": theme.WARN, "Drive": theme.OK,
                      "Charging": theme.CHARGE, "Fault": theme.FAULT},
        "precharge.state": {"Open": theme.NEUTRAL, "Precharging": theme.WARN, "Closed": theme.OK,
                            "Failed": theme.FAULT},
        "charger.state": {"Disconnected": theme.TEXT_MUTED, "Connected": theme.NEUTRAL, "Charging": theme.CHARGE,
                          "Balancing": theme.BALANCE, "Complete": theme.OK},
    })
    SEVERITY_COLORS.update({"critical": theme.FAULT, "warning": theme.WARN, "info": theme.TEXT_MUTED})
    LEVEL_COLORS.update({"normal": theme.NEUTRAL, "warn": theme.WARN, "fault": theme.FAULT})


_rebuild()
theme.on_change(_rebuild)


def cell_level(v: float, cfg: Config) -> str:
    if v >= cfg["cell_ov_fault"] or v <= cfg["cell_uv_fault"]:
        return "fault"
    if v >= cfg["cell_ov_warn"] or v <= cfg["cell_uv_warn"]:
        return "warn"
    return "normal"


def temp_level(t: float, cfg: Config) -> str:
    if t >= cfg["temp_ot_fault"] or t <= cfg["temp_ut_fault"]:
        return "fault"
    if t >= cfg["temp_ot_warn"] or t <= cfg["temp_ut_warn"]:
        return "warn"
    return "normal"


def level_color(level: str, normal: str | None = None) -> str:
    """The colour for a "normal", "warn" or "fault" value. `normal` defaults to the current text colour."""
    if level == "normal":
        return theme.TEXT if normal is None else normal
    return LEVEL_COLORS[level]


def value_color(cid: str, value: float | None, cfg: Config, labels: tuple[str, ...] = (),
                normal: str | None = None, stale: bool = False) -> str:
    """The colour to draw a channel's value in.

    `normal` is used when nothing needs attention. It defaults to the text colour of the mode in
    use when called, not when this module was imported.
    """
    if stale or value is None:
        return theme.TEXT_FAINT if value is None else theme.STALE
    if cid in STATE_COLORS and labels:
        index = int(round(value))
        name = labels[index] if 0 <= index < len(labels) else ""
        return STATE_COLORS[cid].get(name, level_color("normal", normal))
    if cid == "cell.delta":
        threshold = float(cfg["balance_threshold_mv"])
        level = "warn" if value > max(50.0, threshold * 5) else "normal"
    elif cid.startswith("cell."):
        level = cell_level(value, cfg)
    elif cid.startswith("temp."):
        level = temp_level(value, cfg)
    else:
        level = "normal"
    return level_color(level, normal)
