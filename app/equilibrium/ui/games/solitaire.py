"""Solitaire (Klondike): build each suit up from the ace. A click moves a card to the best place for it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from equilibrium import theme
from equilibrium.ui.games.base import Game, colours

WIDTH, HEIGHT = 560.0, 540.0
CARD_W, CARD_H = 64.0, 90.0
LEFT, TOP, PITCH = 14.0, 12.0, 78.0  # Of the top row, and from one pile to the next
PILES_Y = 120.0
DOWN_STEP, UP_STEP = 10.0, 26.0  # How much of a covered card shows
SUITS = "♠♥♦♣"
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
Card = tuple[int, int]  # Rank 1 (ace) to 13 (king), then suit 0 to 3


def is_red(card: Card) -> bool:
    return card[1] in (1, 2)


class Solitaire(Game):
    title = "Solitaire"
    controls = "Click a card to move it. Click the pack to turn a card over."
    board_size = (WIDTH, HEIGHT)
    realtime = False

    def reset(self) -> None:
        deck = [(rank, suit) for suit in range(4) for rank in range(1, 14)]
        self.rng.shuffle(deck)
        self.piles: list[list[Card]] = []  # The seven columns, each from the back card to the front
        self.hidden: list[int] = []  # How many cards at the back of each pile are face down
        for i in range(7):
            self.piles.append([deck.pop() for _ in range(i + 1)])
            self.hidden.append(i)
        self.pack = deck  # Face down; the last card is on top
        self.turned: list[Card] = []  # Turned over from the pack
        self.built: list[list[Card]] = [[] for _ in range(4)]  # One for each suit, built up from its ace

    # Rules

    def can_build(self, card: Card) -> bool:
        return len(self.built[card[1]]) == card[0] - 1

    def can_stack(self, card: Card, pile: list[Card]) -> bool:
        if not pile:
            return card[0] == 13
        return pile[-1][0] == card[0] + 1 and is_red(pile[-1]) != is_red(card)

    def _home_for(self, card: Card, source: int | None = None, whole_pile: bool = False) -> int | None:
        """The pile a card can move onto. Piles holding cards come first, to keep the gaps for kings."""
        choices = [i for i, pile in enumerate(self.piles) if i != source and self.can_stack(card, pile)]
        if whole_pile:  # A king with nothing under it gains nothing by moving to another gap.
            choices = [i for i in choices if self.piles[i]]
        return min(choices, key=lambda i: not self.piles[i], default=None)

    # Moves

    def turn_pack(self) -> None:
        if self.pack:
            self.turned.append(self.pack.pop())
        else:
            self.pack, self.turned = self.turned[::-1], []

    def play_turned(self) -> bool:
        if not self.turned:
            return False
        card = self.turned[-1]
        if self.can_build(card):
            self.built[card[1]].append(self.turned.pop())
            self.add_score(10)
        else:
            home = self._home_for(card)
            if home is None:
                return False
            self.piles[home].append(self.turned.pop())
        self._check_solved()
        return True

    def play_pile(self, source: int, index: int) -> bool:
        """Move the card at index in a pile, with every card in front of it."""
        pile = self.piles[source]
        if index < self.hidden[source] or index >= len(pile):
            return False
        run = pile[index:]
        if len(run) == 1 and self.can_build(run[0]):
            self.built[run[0][1]].append(pile.pop())
            self.add_score(10)
        else:
            home = self._home_for(run[0], source, whole_pile=index == 0)
            if home is None:
                return False
            del pile[index:]
            self.piles[home] += run
        if pile and self.hidden[source] == len(pile):  # Turn over the card this uncovered
            self.hidden[source] -= 1
            self.add_score(5)
        self._check_solved()
        return True

    def _check_solved(self) -> None:
        if all(len(built) == 13 for built in self.built):
            self.end("Solved")

    # Layout

    def _slot(self, column: int) -> QRectF:
        return QRectF(LEFT + column * PITCH, TOP, CARD_W, CARD_H)

    def _pile_rects(self, i: int) -> list[QRectF]:
        pile, hidden = self.piles[i], self.hidden[i]
        showing = len(pile) - hidden
        room = HEIGHT - 8 - PILES_Y - CARD_H - hidden * DOWN_STEP
        step = min(UP_STEP, room / max(1, showing - 1))  # A long pile closes up to stay on the board
        rects, y = [], PILES_Y
        for index in range(len(pile)):
            rects.append(QRectF(LEFT + i * PITCH, y, CARD_W, CARD_H))
            y += DOWN_STEP if index < hidden else step
        return rects

    def click(self, pos: QPointF, button: Qt.MouseButton) -> None:
        if self._slot(0).contains(pos):
            self.turn_pack()
        elif self._slot(1).contains(pos):
            self.play_turned()
        else:
            for i in range(7):
                rects = self._pile_rects(i)
                for index in range(len(rects) - 1, -1, -1):  # The front card first
                    if rects[index].contains(pos):
                        self.play_pile(i, index)
                        return

    # Drawing

    def _draw_slot(self, p: QPainter, rect: QRectF, mark: str = "") -> None:
        p.setPen(QPen(theme.color(theme.BORDER), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        if mark:
            self.text(p, rect, mark, 28, theme.TEXT_FAINT)

    def _draw_back(self, p: QPainter, rect: QRectF) -> None:
        p.setPen(QPen(theme.color(theme.ACCENT), 1))
        p.setBrush(theme.color(theme.ACCENT_TINT))
        p.drawRoundedRect(rect, 6, 6)

    def _draw_card(self, p: QPainter, rect: QRectF, card: Card) -> None:
        p.setPen(QPen(theme.color(theme.BORDER), 1))
        p.setBrush(theme.color(theme.SURFACE_2))
        p.drawRoundedRect(rect, 6, 6)
        colour = colours()[2] if is_red(card) else theme.TEXT  # Pink, not red: red means a fault in this app
        self.text(p, QRectF(rect.left() + 6, rect.top() + 3, CARD_W - 12, 22),
                  f"{RANKS[card[0] - 1]}{SUITS[card[1]]}", 16, colour, bold=True,
                  align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text(p, QRectF(rect.left(), rect.top() + 26, CARD_W, CARD_H - 30), SUITS[card[1]], 34, colour)

    def draw(self, p: QPainter) -> None:
        if self.pack:
            self._draw_back(p, self._slot(0))
            self.text(p, self._slot(0), str(len(self.pack)), 14, theme.ACCENT)
        else:
            self._draw_slot(p, self._slot(0), "↻" if self.turned else "")
        if self.turned:
            self._draw_card(p, self._slot(1), self.turned[-1])
        else:
            self._draw_slot(p, self._slot(1))
        for suit, built in enumerate(self.built):
            if built:
                self._draw_card(p, self._slot(3 + suit), built[-1])
            else:
                self._draw_slot(p, self._slot(3 + suit), SUITS[suit])
        for i, pile in enumerate(self.piles):
            rects = self._pile_rects(i)
            if not pile:
                self._draw_slot(p, QRectF(LEFT + i * PITCH, PILES_Y, CARD_W, CARD_H))
            for index, card in enumerate(pile):
                if index < self.hidden[i]:
                    self._draw_back(p, rects[index])
                else:
                    self._draw_card(p, rects[index], card)
