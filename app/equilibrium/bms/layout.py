"""The accumulator's physical layout and the list of channels it produces.

A channel is any single value the BMS reports: one cell voltage, one thermistor, the pack
current, the AMS state and so on. Every screen refers to data by channel id, so hover text,
stale greying and click-to-plot work the same way everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

LAYOUT_FILE = Path(__file__).resolve().parent.parent / "assets" / "pack_layout.json"

AMS_STATES = ("Init", "Idle", "Precharge", "Drive", "Charging", "Fault")
PRECHARGE_STATES = ("Open", "Precharging", "Closed", "Failed")
CHARGER_STATES = ("Disconnected", "Connected", "Charging", "Balancing", "Complete")
ON_OFF = ("Off", "On")


@dataclass(frozen=True)
class Thermistor:
    number: int  # 1-based across the whole pack
    segment: int  # 1-based
    local_id: int  # The id within its segment, from the layout file
    slave: int  # 1-based within the segment
    x: float  # mm within the segment
    y: float
    z: float

    @property
    def label(self) -> str:
        return f"T{self.segment}.{self.local_id}"


@dataclass(frozen=True)
class ChannelInfo:
    id: str
    name: str
    unit: str = ""
    decimals: int = 2
    group: str = "Pack"
    segment: int | None = None
    slave: int | None = None
    detail: str = ""  # Extra location line for hover text
    labels: tuple[str, ...] = ()  # Names for an enumerated state

    def format(self, value: float | None, unit: bool = True) -> str:
        if value is None:
            return "—"
        if self.labels:
            index = int(round(value))
            return self.labels[index] if 0 <= index < len(self.labels) else str(index)
        text = f"{value:.{self.decimals}f}"
        return f"{text} {self.unit}" if unit and self.unit else text

    def location(self) -> str:
        parts = []
        if self.segment is not None:
            parts.append(f"Segment {self.segment}")
        if self.slave is not None:
            parts.append(f"Slave board {self.segment}.{self.slave}")
        return " · ".join(parts)

    def tooltip(self, value: float | None, stale_for: float | None = None, extra: str = "") -> str:
        lines = [f"<b>{escape(self.name)}</b>"]
        if self.location():
            lines.append(escape(self.location()))
        if self.detail:
            lines.append(escape(self.detail))
        lines.append(f"<span style='font-size:14px'>{escape(self.format(value))}</span>")
        if extra:
            lines.append(extra)
        if stale_for is not None:
            age = "no data yet" if stale_for == float("inf") else f"not updated for {stale_for:.1f} s"
            lines.append(f"<i>Stale: {age}</i>")
        lines.append("<span style='color:#5d6474'>Click to add to Plots</span>")
        return "<br>".join(lines)


@dataclass
class PackLayout:
    segments: int
    cells_per_segment: int
    slaves_per_segment: int
    segment_size: tuple[float, float, float]
    thermistors: list[Thermistor]

    @property
    def cell_count(self) -> int:
        return self.segments * self.cells_per_segment

    @property
    def cells_per_slave(self) -> int:
        return self.cells_per_segment // self.slaves_per_segment

    @property
    def board_count(self) -> int:
        return self.segments * self.slaves_per_segment

    def cell_position(self, number: int) -> tuple[int, int, int]:
        """(segment, slave, index within segment) for a 1-based cell number, all 1-based."""
        index = number - 1
        segment = index // self.cells_per_segment + 1
        in_segment = index % self.cells_per_segment
        slave = min(in_segment // self.cells_per_slave, self.slaves_per_segment - 1) + 1
        return segment, slave, in_segment + 1

    def segment_cells(self, segment: int) -> range:
        start = (segment - 1) * self.cells_per_segment + 1
        return range(start, start + self.cells_per_segment)

    def segment_thermistors(self, segment: int) -> list[Thermistor]:
        return [t for t in self.thermistors if t.segment == segment]

    def boards(self) -> list[tuple[int, int]]:
        """(segment, slave) for every slave board, in daisy chain order."""
        return [(s, b) for s in range(1, self.segments + 1) for b in range(1, self.slaves_per_segment + 1)]

    @classmethod
    def load(cls, path: Path = LAYOUT_FILE) -> PackLayout:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        segments = int(raw["segments"])
        thermistors = []
        number = 1
        for segment in range(1, segments + 1):
            for entry in raw["thermistors"]:
                thermistors.append(
                    Thermistor(
                        number=number,
                        segment=segment,
                        local_id=int(entry["id"]),
                        slave=int(entry["slave"]),
                        x=float(entry["x"]),
                        y=float(entry["y"]),
                        z=float(entry["z"]),
                    )
                )
                number += 1
        return cls(
            segments=segments,
            cells_per_segment=int(raw["cells_per_segment"]),
            slaves_per_segment=int(raw["slaves_per_segment"]),
            segment_size=tuple(float(v) for v in raw["segment_size_mm"]),
            thermistors=thermistors,
        )


def cell_id(number: int) -> str:
    return f"cell.{number}"


def balance_id(number: int) -> str:
    return f"bal.{number}"


def temp_id(number: int) -> str:
    return f"temp.{number}"


def board_id(segment: int, slave: int, field: str) -> str:
    return f"board.{segment}.{slave}.{field}"


def build_channels(layout: PackLayout) -> dict[str, ChannelInfo]:
    channels: list[ChannelInfo] = [
        ChannelInfo("pack.voltage", "Pack voltage", "V", 1),
        ChannelInfo("pack.current", "Pack current", "A", 1, detail="Positive = discharge"),
        ChannelInfo("pack.power", "Pack power", "kW", 2),
        ChannelInfo("pack.soc", "State of charge", "%", 1),
        ChannelInfo("ts.voltage", "Tractive system voltage", "V", 1, detail="Measured after the AIRs"),
        ChannelInfo("cell.max", "Max cell voltage", "V", 3, "Cells"),
        ChannelInfo("cell.min", "Min cell voltage", "V", 3, "Cells"),
        ChannelInfo("cell.avg", "Average cell voltage", "V", 3, "Cells"),
        ChannelInfo("cell.delta", "Cell delta", "mV", 0, "Cells", detail="Max cell minus min cell"),
        ChannelInfo("temp.max", "Max temperature", "°C", 1, "Thermals"),
        ChannelInfo("temp.min", "Min temperature", "°C", 1, "Thermals"),
        ChannelInfo("temp.avg", "Average temperature", "°C", 1, "Thermals"),
        ChannelInfo("ams.state", "AMS state", labels=AMS_STATES),
        ChannelInfo("precharge.state", "Precharge state", labels=PRECHARGE_STATES),
        ChannelInfo("charger.state", "Charger state", group="Charging", labels=CHARGER_STATES),
        ChannelInfo("charger.voltage", "Charger output voltage", "V", 1, "Charging"),
        ChannelInfo("charger.current", "Charger output current", "A", 1, "Charging"),
        ChannelInfo("bal.count", "Cells balancing", "", 0, "Cells"),
    ]
    for number in range(1, layout.cell_count + 1):
        segment, slave, local = layout.cell_position(number)
        detail = f"Cell {local} of segment {segment}"
        channels.append(ChannelInfo(cell_id(number), f"Cell {number}", "V", 3, "Cells", segment, slave, detail))
        channels.append(
            ChannelInfo(balance_id(number), f"Cell {number} balancing", "", 0, "Balancing", segment, slave,
                        detail, ON_OFF)
        )
    for t in layout.thermistors:
        detail = f"Thermistor {t.local_id} of segment {t.segment} · x {t.x:g}, y {t.y:g}, z {t.z:g} mm"
        channels.append(
            ChannelInfo(temp_id(t.number), f"Thermistor {t.label}", "°C", 1, "Thermals", t.segment, t.slave, detail)
        )
    for segment, slave in layout.boards():
        channels.append(
            ChannelInfo(board_id(segment, slave, "pec"), f"Slave {segment}.{slave} PEC errors", "", 0,
                        "Communications", segment, slave)
        )
        channels.append(
            ChannelInfo(board_id(segment, slave, "die"), f"Slave {segment}.{slave} die temperature", "°C", 1,
                        "Communications", segment, slave)
        )
    return {c.id: c for c in channels}
