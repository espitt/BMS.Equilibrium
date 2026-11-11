"""Communications: the daisy chain of slave boards, their health, and identifying them."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QWidget,
)

from equilibrium import theme
from equilibrium.bms.layout import PackLayout, Thermistor, board_id
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.widgets import button, colored, label, screen_layout

RECENT_ERRORS_S = 10.0
COLUMNS = ["Board", "Chain address", "Cells", "Thermistors", "PEC errors", "Die temperature", "Status"]


def board_members(layout: PackLayout, board: tuple[int, int]) -> tuple[list[int], list[Thermistor]]:
    """The cell numbers and the thermistors that one slave board reads."""
    segment, slave = board
    cells = [n for n in layout.segment_cells(segment) if layout.cell_position(n)[1] == slave]
    thermistors = [t for t in layout.segment_thermistors(segment) if t.slave == slave]
    return cells, thermistors


class BoardHealth:
    """Tracks when each board's PEC error count last went up."""

    def __init__(self) -> None:
        self.last_count: dict[tuple[int, int], float] = {}
        self.last_rise: dict[tuple[int, int], float] = {}

    def status(self, ctx: AppContext, board: tuple[int, int]) -> tuple[str, str]:
        data = ctx.data
        cid = board_id(*board, "pec")
        count = data.value(cid)
        if count is None:
            return "No data", theme.TEXT_FAINT
        if data.is_stale(cid):
            return "Not responding", theme.STALE
        if board in self.last_count and count > self.last_count[board]:
            self.last_rise[board] = data.now()
        self.last_count[board] = count
        if data.now() - self.last_rise.get(board, -1e9) < RECENT_ERRORS_S:
            return "PEC errors", theme.WARN
        return "OK", theme.OK


class ChainView(QWidget):
    boardClicked = Signal(object)

    def __init__(self, ctx: AppContext, health: BoardHealth) -> None:
        super().__init__()
        self.ctx = ctx
        self.health = health
        self.selected: tuple[int, int] | None = None
        self.hover: tuple[int, int] | None = None
        self.rects: dict[tuple[int, int], QRectF] = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(60 + 52 * ctx.layout.segments)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = self.ctx.layout
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))

        master = QRectF(10, 10, 120, 40)
        row_h = 52
        board_w = min(170.0, (self.width() - 300) / max(1, layout.slaves_per_segment) - 30)
        start_x = 170.0
        self.rects = {}
        for s, b in layout.boards():
            # Snake: left to right on odd segments, right to left on even ones, like a real harness.
            column = b - 1 if s % 2 == 1 else layout.slaves_per_segment - b
            x = start_x + column * (board_w + 30)
            y = 10 + (s - 1) * row_h
            self.rects[(s, b)] = QRectF(x, y, board_w, 40)

        # Links, in chain order
        chain = [None] + layout.boards()
        for prev, board in zip(chain, chain[1:]):
            a = master if prev is None else self.rects[prev]
            r = self.rects[board]
            _status, hex_code = self.health.status(self.ctx, board)
            pen = QPen(theme.color(hex_code if hex_code != theme.OK else theme.BORDER), 2)
            if hex_code == theme.STALE:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            if prev is None:
                p.drawLine(QPointF(a.right(), a.center().y()), QPointF(r.left(), r.center().y()))
            elif abs(a.center().y() - r.center().y()) < 1:
                left, right = (a, r) if a.left() < r.left() else (r, a)
                p.drawLine(QPointF(left.right(), left.center().y()), QPointF(right.left(), right.center().y()))
            else:
                p.drawLine(QPointF(a.center().x(), a.bottom()), QPointF(r.center().x(), r.top()))

        # Master
        p.setPen(QPen(theme.color(theme.ACCENT if self.ctx.data.connected else theme.BORDER), 1))
        p.setBrush(theme.color(theme.ACCENT_TINT))
        p.drawRoundedRect(master, theme.RADIUS, theme.RADIUS)
        p.setPen(theme.color(theme.ACCENT))
        p.drawText(master, Qt.AlignmentFlag.AlignCenter, "Master")

        # Segment labels and boards
        p.setFont(small)
        for s in range(1, layout.segments + 1):
            y = 10 + (s - 1) * row_h
            p.setPen(theme.color(theme.TEXT_FAINT))
            label_x = start_x + layout.slaves_per_segment * (board_w + 30) - 14
            p.drawText(QRectF(label_x, y, 90, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"Segment {s}")
        data = self.ctx.data
        for board, rect in self.rects.items():
            status, hex_code = self.health.status(self.ctx, board)
            # A healthy board is outlined like any other box; only trouble and selection are coloured.
            quiet = theme.BORDER if hex_code == theme.OK else hex_code
            border = theme.ACCENT if board == self.selected else quiet
            p.setPen(QPen(theme.color(border), 2 if board == self.selected else 1))
            p.setBrush(theme.color(theme.SURFACE_3 if board == self.hover else theme.SURFACE_2))
            p.drawRoundedRect(rect, theme.RADIUS, theme.RADIUS)
            p.setBrush(theme.color(hex_code))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(rect.left() + 12, rect.top() + 13), 4, 4)
            p.setPen(theme.color(theme.TEXT))
            p.drawText(QRectF(rect.left() + 22, rect.top() + 4, rect.width() - 26, 18), Qt.AlignmentFlag.AlignLeft,
                       f"Slave {board[0]}.{board[1]}")
            pec = data.value(board_id(*board, "pec"))
            die = data.value(board_id(*board, "die"))
            if pec is None:
                detail = "—"
            else:
                detail = f"PEC {pec:.0f}, {die:.0f} °C" if die is not None else f"PEC {pec:.0f}"
            p.setPen(theme.color(theme.TEXT_MUTED))
            p.drawText(QRectF(rect.left() + 10, rect.top() + 21, rect.width() - 14, 16), Qt.AlignmentFlag.AlignLeft,
                       detail)
        p.end()

    def _board_at(self, pos: QPointF) -> tuple[int, int] | None:
        return next((b for b, r in self.rects.items() if r.contains(pos)), None)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        board = self._board_at(event.position())
        if board != self.hover:
            self.hover = board
            self.update()
        if board is None:
            QToolTip.hideText()
            return
        status, hex_code = self.health.status(self.ctx, board)
        address = self.ctx.layout.boards().index(board) + 1
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"<b>Slave board {board[0]}.{board[1]}</b><br>Segment {board[0]}, chain address "
                          f"{address}<br>{colored(status, hex_code)}<br>"
                          f"{colored('Click to select', theme.TEXT_FAINT)}", self)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        board = self._board_at(event.position())
        if board is not None:
            self.selected = board
            self.boardClicked.emit(board)
            self.update()

    def leaveEvent(self, event) -> None:
        self.hover = None
        self.update()
        super().leaveEvent(event)


class CommsScreen(Screen):
    title = "Communications"
    nav_label = "Communications"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.health = BoardHealth()
        box, self.header = screen_layout(self, "Communications")
        self.view = ChainView(ctx, self.health)
        self.view.boardClicked.connect(self._select)
        box.addWidget(self.view)

        boards = ctx.layout.boards()
        self.table = QTableWidget(len(boards), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.table.cellDoubleClicked.connect(lambda row, _c: ctx.plot(board_id(*boards[row], "pec")))
        box.addWidget(self.table, 1)

        panel = self.panel
        panel.section("Chain")
        self.chain_summary = panel.add(label("", "muted", wrap=True))
        self.chain_summary.setTextFormat(Qt.TextFormat.RichText)
        self.scan = panel.add(button("Re-scan chain", lambda: ctx.send("chain scan"),
                                     tooltip="Ask the BMS to enumerate the slave boards again"))
        panel.section("Selected board")
        self.selected_label = panel.add(label("Click a board to select it.", "muted", wrap=True))
        self.selected_label.setTextFormat(Qt.TextFormat.RichText)
        self.identify = panel.add(button("Identify (blink LED)", self._identify,
                                         tooltip="Blink the LED on the selected board so you can find it"))
        self.identify.setEnabled(False)
        panel.note("A board that stops answering is shown grey and dashed. Amber means PEC errors in the last "
                   f"{RECENT_ERRORS_S:.0f} s. Double-click a row to plot its PEC count.")
        panel.finish()
        ctx.linkChanged.connect(self._link_changed)
        self._link_changed()

    def _link_changed(self) -> None:
        self.scan.setEnabled(self.ctx.connected)
        self.identify.setEnabled(self.ctx.connected and self.view.selected is not None)

    def _select(self, board: tuple[int, int]) -> None:
        self.view.selected = board
        row = self.ctx.layout.boards().index(board)
        self.table.blockSignals(True)
        self.table.selectRow(row)
        self.table.blockSignals(False)
        self.identify.setEnabled(self.ctx.connected)
        self.view.update()
        self._describe()

    def _table_selected(self) -> None:
        row = self.table.currentRow()
        boards = self.ctx.layout.boards()
        if 0 <= row < len(boards):
            self._select(boards[row])

    def _identify(self) -> None:
        if self.view.selected is not None:
            s, b = self.view.selected
            self.ctx.send(f"identify {s}.{b}")

    def _describe(self) -> None:
        board = self.view.selected
        if board is None:
            return
        layout = self.ctx.layout
        s, b = board
        cells, therms = board_members(layout, board)
        status, hex_code = self.health.status(self.ctx, board)
        self.selected_label.setText(
            "<br>".join([
                f"<b style='color:{theme.TEXT}'>Slave board {s}.{b}</b>",
                f"Chain address {layout.boards().index(board) + 1}",
                f"Cells {cells[0]}–{cells[-1]}" if cells else "No cells",
                f"Thermistors {therms[0].label}–{therms[-1].label}" if therms else "No thermistors",
                colored(status, hex_code),
            ])
        )

    def refresh(self) -> None:
        self.view.update()
        data = self.ctx.data
        layout = self.ctx.layout
        responding = 0
        total_pec = 0
        for row, board in enumerate(layout.boards()):
            s, b = board
            status, hex_code = self.health.status(self.ctx, board)
            responding += status in ("OK", "PEC errors")
            pec = data.value(board_id(s, b, "pec"))
            die = data.value(board_id(s, b, "die"))
            total_pec += int(pec or 0)
            cells, therms = board_members(layout, board)
            texts = [
                (f"Slave {s}.{b}", theme.TEXT),
                (str(row + 1), theme.TEXT_MUTED),
                (f"{cells[0]}–{cells[-1]}" if cells else "—", theme.TEXT_MUTED),
                (str(len(therms)), theme.TEXT_MUTED),
                ("—" if pec is None else f"{pec:.0f}", theme.TEXT_MUTED),
                ("—" if die is None else f"{die:.1f} °C", theme.TEXT_MUTED),
                (status, hex_code),
            ]
            for col, (text, hex_) in enumerate(texts):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(text)
                item.setForeground(theme.color(hex_))
        boards = layout.board_count
        hex_code = theme.OK if responding == boards else theme.WARN if responding else theme.TEXT_FAINT
        summary = f"{colored(f'{responding} of {boards}', hex_code)} boards responding · {total_pec} PEC errors total"
        self.chain_summary.setText(summary if data.connected else "Not connected")
        self.header.summary.setText(summary if data.connected else "Not connected")
        self._describe()
