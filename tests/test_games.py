"""Tests for the minigames on the Charging screen, and for stopping them when the pack needs attention."""

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "installer"), str(ROOT / "app")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from equilibrium.ui.games import arcade, blocks, merge, mines, rocks, runner, snake, solitaire, sudoku  # noqa: E402
from equilibrium.ui.games.arcade import GAMES, Arcade  # noqa: E402
from equilibrium.ui.games.blocks import Blocks  # noqa: E402
from equilibrium.ui.games.bricks import Bricks  # noqa: E402
from equilibrium.ui.games.merge import Merge  # noqa: E402
from equilibrium.ui.games.mines import Mines  # noqa: E402
from equilibrium.ui.games.rocks import Rocks  # noqa: E402
from equilibrium.ui.games.runner import Runner  # noqa: E402
from equilibrium.ui.games.snake import Snake  # noqa: E402
from equilibrium.ui.games.solitaire import Solitaire  # noqa: E402
from equilibrium.ui.games.sudoku import Sudoku  # noqa: E402
from equilibrium.ui.games.tennis import Tennis  # noqa: E402

app = QApplication.instance() or QApplication([])
K = Qt.Key
DT = 0.016


def press(game, key) -> None:
    """Press a key the way Qt delivers it, as a plain number."""
    QApplication.sendEvent(game, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def release(game, key) -> None:
    QApplication.sendEvent(game, QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier))


def run(game, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        if game.over:
            break
        game.tick(DT)


class GameTest(unittest.TestCase):
    def setUp(self):
        # Scores and the last game played are saved, so point the settings at a file of the test's own.
        ini = str(Path(tempfile.mkdtemp()) / "settings.ini")
        patch = mock.patch.object(arcade, "_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))
        patch.start()
        self.addCleanup(patch.stop)


class PlayingTests(GameTest):
    def test_starts_paused_and_keys_start_and_pause_it(self):
        game = Snake(seed=1)
        self.assertTrue(game.paused)
        self.assertIn("to start", game.message()[1])
        press(game, K.Key_Up)
        self.assertEqual(game.turns, [], "keys do nothing until the game starts")
        press(game, K.Key_Space)
        self.assertTrue(game.active)
        self.assertIsNone(game.message())
        press(game, K.Key_Up)
        self.assertEqual(game.turns, [(0, -1)])
        press(game, K.Key_P)
        self.assertTrue(game.paused)
        press(game, K.Key_P)
        self.assertTrue(game.active)

    def test_held_keys_are_tracked_until_released_or_paused(self):
        game = Bricks(seed=1)
        game.go()
        press(game, K.Key_Right)
        self.assertIn(K.Key_Right, game.held)
        before = game.paddle
        game.tick(DT)
        self.assertGreater(game.paddle, before)
        release(game, K.Key_Right)
        self.assertNotIn(K.Key_Right, game.held)
        press(game, K.Key_Left)
        game.set_paused(True)
        self.assertEqual(game.held, set())

    def test_a_hidden_game_pauses(self):
        game = Snake(seed=1)
        game.show()
        game.go()
        game.hide()
        self.assertTrue(game.paused)

    def test_a_finished_game_starts_afresh(self):
        game = Snake(seed=1)
        game.go()
        game.add_score(30)
        game.end()
        self.assertIn("Score 30", game.message()[1])
        press(game, K.Key_Space)
        self.assertTrue(game.active)
        self.assertEqual(game.score, 0)

    def test_every_game_paints_in_every_state(self):
        for cls in GAMES:
            for level in range(max(1, len(cls.levels))):
                game = cls(level, seed=3)
                game.resize(420, 380)
                game.grab()
                game.go()
                game.tick(0.25)
                game.grab()
                game.click(QPointF(100, 100), Qt.MouseButton.LeftButton)
                game.mouse(QPointF(120, 140))
                game.end()
                game.grab()
                game.set_hold("Overtemperature (critical)")
                game.grab()

    def test_no_game_uses_the_fault_or_warning_colours(self):
        from equilibrium import theme
        from equilibrium.ui.games.base import colours

        for mode in theme.PALETTES.values():
            with mock.patch.multiple(theme, SERIES=mode["SERIES"], BALANCE=mode["BALANCE"], CHARGE=mode["CHARGE"]):
                self.assertFalse({mode["FAULT"], mode["WARN"]} & set(colours()))


class HoldTests(GameTest):
    def test_a_hold_stops_play_until_it_is_lifted_and_the_player_carries_on(self):
        game = Snake(seed=1)
        game.go()
        game.set_hold("Overtemperature (critical)")
        self.assertTrue(game.paused)
        headline, detail, _ = game.message()
        self.assertEqual(headline, "Paused for safety")
        self.assertIn("Overtemperature (critical). Check the charging stats.", detail)
        press(game, K.Key_Space)
        game.go()
        self.assertTrue(game.paused, "nothing starts a game on hold")
        game.set_hold("")
        self.assertTrue(game.paused, "lifting the hold does not start play by itself")
        game.go()
        self.assertTrue(game.active)

    def test_the_arcade_holds_whichever_game_is_chosen(self):
        card = Arcade()
        card.set_hold("No BMS is connected")
        self.assertFalse(card.pause_button.isEnabled())
        card.picker.setCurrentIndex(3)
        self.assertIsInstance(card.game, GAMES[3])
        self.assertEqual(card.game.hold, "No BMS is connected")
        card.set_hold("")
        self.assertTrue(card.pause_button.isEnabled())
        card.game.go()
        card.pause("Charging has finished")
        self.assertEqual(card.game.message()[0], "Charging has finished")

    def test_best_scores_are_kept_for_each_game_and_level(self):
        card = Arcade()
        card.picker.setCurrentIndex(GAMES.index(Mines))
        self.assertEqual([card.level.itemText(i) for i in range(card.level.count())], list(Mines.levels))
        card.game.add_score(40)
        self.assertEqual(card.score.text(), "Score 40 · Best 40")
        card.level.setCurrentIndex(2)
        self.assertEqual(card.game.level, 2)
        self.assertEqual(card.score.text(), "Score 0 · Best 0")
        card.level.setCurrentIndex(0)
        self.assertEqual(card.score.text(), "Score 0 · Best 40")
        card.game.add_score(10)
        self.assertEqual(card.score.text(), "Score 10 · Best 40")
        self.assertEqual(Arcade().picker.currentIndex(), GAMES.index(Mines), "opens on the game played last")

    def test_the_charging_screen_stops_games_when_the_pack_needs_attention(self):
        from equilibrium import theme
        from equilibrium.ui.main_window import MainWindow
        from equilibrium.ui.screens.charging import ChargingScreen

        theme.apply(app)
        window = MainWindow()
        window.resize(1100, 700)  # The smallest the window goes
        window._connect_simulator()
        data, link = window.ctx.data, window.ctx.link
        link.stop()
        link.dropouts.clear()
        link._tick()
        for code in [f.code for f in data.faults if f.active]:
            for fault in [f for f in data.faults if f.code == code]:
                data.resolve_fault(code, fault.location)
        index = window.screen_index(ChargingScreen)
        screen = window.screens[index]
        window.show_screen(index)
        window.show()
        app.processEvents()

        self.assertTrue(screen.arcade.isHidden())
        self.assertTrue(screen.compact.isHidden())
        self.assertTrue(window.side.isVisible())
        screen.games_button.click()
        app.processEvents()
        self.assertTrue(screen.arcade.isVisible())
        self.assertTrue(screen.compact.isVisible(), "the condensed stats take the place of the full layout")
        self.assertTrue(screen.full.isHidden())
        self.assertFalse(window.side.isVisible(), "the options panel makes room for the game")
        self.assertGreaterEqual(screen.arcade.game.width(), 400)
        self.assertLessEqual(screen.compact.sizeHint().height(), screen.compact.height(), "nothing is squeezed")
        for view in screen.views:  # Both layouts show the same numbers
            self.assertEqual(view.soc.text(), f"{data.value('pack.soc'):.1f} %")
            self.assertEqual(view.state_badge.text(), "Connected")
            self.assertEqual([row.cid for row in view.tiles], [row.cid for row in screen.tiles])
            self.assertIn("BMS connected", view.checks["link"].text())
            self.assertIn("V of", view.target_text.text())
        self.assertEqual(screen.compact.tiles[0].value.text(), data.channels["pack.voltage"].format(
            data.value("pack.voltage")))

        window.show_screen(0)
        self.assertTrue(window.side.isVisible(), "other screens keep their panels")
        self.assertTrue(screen.arcade.game.paused)
        window.show_screen(index)
        self.assertFalse(window.side.isVisible())
        game = screen.arcade.game
        self.assertEqual(game.hold, "")
        game.go()
        self.assertTrue(game.active)

        data.raise_fault(0x0105, "Cell imbalance", "info", "cell.delta")
        self.assertTrue(game.active, "an info fault does not stop play")
        data.raise_fault(0x0202, "Overtemperature warning", "warning", "temp.1")
        self.assertEqual(game.hold, "Overtemperature warning (warning)")
        self.assertTrue(game.paused)
        data.raise_fault(0x0201, "Overtemperature", "critical", "temp.1")
        self.assertEqual(game.hold, "Overtemperature (critical)", "the worst fault is the one named")
        data.resolve_fault(0x0201, "temp.1")
        data.resolve_fault(0x0202, "temp.1")
        self.assertEqual(game.hold, "")
        self.assertTrue(game.paused)
        game.go()

        data.stamps["cell.1"] = -100.0  # One channel stops updating
        data.check_stale()
        self.assertEqual(game.hold, "Some BMS data has stopped updating")

        window.ctx.disconnect_link()
        self.assertEqual(game.hold, "No BMS is connected")
        self.assertIn("✕", screen.compact.checks["link"].text())

        screen.games_button.click()  # Back to the full layout
        self.assertTrue(screen.full.isVisible())
        self.assertTrue(screen.arcade.isHidden())
        self.assertTrue(screen.compact.isHidden())
        self.assertTrue(window.side.isVisible())
        window.ctx.config.dirty = False
        window.close()

    def test_finishing_the_charge_pauses_the_game(self):
        from equilibrium.bms.layout import CHARGER_STATES
        from equilibrium.ui.context import AppContext
        from equilibrium.ui.screens.charging import ChargingScreen

        ctx = AppContext()
        screen = ChargingScreen(ctx)
        ctx.data.set_connected(True, "test")
        everything = dict.fromkeys(ctx.data.channels, 1.0)
        ctx.data.update({**everything, "charger.state": CHARGER_STATES.index("Charging")})
        screen.refresh()
        game = screen.arcade.game
        game.go()
        self.assertTrue(game.active)
        ctx.data.update({**everything, "charger.state": CHARGER_STATES.index("Complete")})
        screen.refresh()
        self.assertTrue(game.paused)
        self.assertEqual(game.message()[0], "Charging has finished")
        game.go()
        screen.refresh()
        self.assertTrue(game.active, "it pauses once, not for as long as the charge stays complete")


class SnakeTests(GameTest):
    def test_eats_grows_and_dies_at_the_wall(self):
        game = Snake(seed=1)
        game.go()
        head = game.body[0]
        game.food = (head[0] + 1, head[1])
        game.step()
        self.assertEqual((len(game.body), game.score), (4, 10))
        self.assertNotIn(game.food, game.body)
        game.key(K.Key_Left)
        self.assertEqual(game.turns, [], "it cannot turn straight back on itself")
        game.food = (0, 0)
        for _ in range(snake.N):
            game.step()
        self.assertTrue(game.over)

    def test_dies_on_its_own_tail_but_may_follow_it(self):
        game = Snake(seed=1)
        game.go()
        game.food = (0, 0)
        game.body = [(5, 5), (5, 6), (6, 6), (6, 5)]  # A closed square: the head is about to follow the tail
        game.direction = (1, 0)
        game.step()
        self.assertFalse(game.over)
        game.body = [(5, 5), (5, 6), (6, 6), (6, 5), (7, 5)]
        game.direction = (1, 0)
        game.step()
        self.assertTrue(game.over)


class BricksTests(GameTest):
    def test_a_well_placed_paddle_breaks_bricks_and_a_missed_ball_costs_a_life(self):
        game = Bricks(seed=2)
        game.go()
        self.assertTrue(game.stuck)
        game.key(K.Key_Space)
        self.assertFalse(game.stuck)
        bricks = len(game.bricks)
        for _ in range(4000):
            game.paddle = min(max(game.ball_x, 35.0), 365.0)  # Always under the ball
            game.tick(DT)
        self.assertGreater(game.score, 0)
        self.assertEqual(game.lives, 3)
        self.assertTrue(game.stage > 1 or len(game.bricks) < bricks)

        game.launch()
        game.ball_x, game.ball_y, game.vx, game.vy = 20.0, 499.0, 0.0, 300.0
        game.paddle = 300.0
        run(game, 0.2)
        self.assertEqual(game.lives, 2)
        self.assertTrue(game.stuck)
        game.lives = 1
        game.launch()
        game.ball_x, game.ball_y, game.vx, game.vy = 20.0, 499.0, 0.0, 300.0
        run(game, 0.2)
        self.assertTrue(game.over)


class TennisTests(GameTest):
    def test_each_player_has_their_own_keys(self):
        game = Tennis(seed=2)
        game.go()
        game.vx = game.vy = 0.0  # Hold the ball still
        press(game, K.Key_W)
        press(game, K.Key_Down)
        run(game, 0.1)
        left, right = game.paddles
        self.assertLess(left, 160.0, "W moves the left paddle up")
        self.assertGreater(right, 160.0, "the down arrow moves the right paddle down")
        release(game, K.Key_W)
        release(game, K.Key_Down)
        press(game, K.Key_S)
        press(game, K.Key_Up)
        run(game, 0.2)
        self.assertGreater(game.paddles[0], left)
        self.assertLess(game.paddles[1], right)
        release(game, K.Key_S)
        release(game, K.Key_Up)
        still = list(game.paddles)
        run(game, 0.2)
        self.assertEqual(game.paddles, still, "nothing moves a paddle but its player")
        self.assertIn("2 players", game.title)

    def test_points_are_scored_and_eleven_wins(self):
        game = Tennis(seed=2)
        game.go()
        game.ball_x, game.vx, game.vy = 499.0, 300.0, 0.0
        game.ball_y, game.paddles[1] = 300.0, 40.0  # Out of the right player's reach
        run(game, 0.2)
        self.assertEqual(game.points, [1, 0])
        self.assertGreater(game.vx, 0, "the serve goes to whoever lost the point")
        game.points = [7, 10]
        game.ball_x, game.vx, game.vy = 1.0, -300.0, 0.0
        game.ball_y, game.paddles[0] = 300.0, 40.0
        run(game, 0.2)
        self.assertTrue(game.over)
        self.assertEqual((game.points, game.result), ([7, 11], "Right wins 11–7"))

    def test_both_paddles_return_the_ball_and_the_longest_rally_is_the_score(self):
        game = Tennis(seed=2)
        game.go()
        game.ball_x, game.ball_y, game.vx, game.vy = 60.0, 160.0, -300.0, 0.0
        run(game, 0.3)
        self.assertGreater(game.vx, 300.0, "it comes back off the left paddle, a little faster")
        for _ in range(400):
            game.paddles[1] = game.ball_y  # The right player keeps up; the left stands still
            game.tick(DT)
            if game.rally == 2:
                break
        self.assertEqual((game.rally, game.score), (2, 2))
        self.assertLess(game.vx, 0)
        self.assertEqual(game.points, [0, 0])
        game.paddles[0] = 400.0  # The left player misses
        game.ball_y, game.vy = 30.0, 0.0
        while game.points == [0, 0]:
            game.tick(DT)
        self.assertEqual((game.points, game.rally, game.score), ([0, 1], 0, 2))
        game.end(game.result)
        self.assertIn("Longest rally 2", game.message()[1])


class BlocksTests(GameTest):
    def test_a_full_row_clears_and_scores(self):
        game = Blocks(seed=4)
        game.go()
        game.grid[-1] = [None] * 4 + [1] * 6
        game.grid[-2][9] = 2
        game.kind, game.cells, game.px, game.py = 0, list(blocks.SHAPES[0]), 3, 0
        for _ in range(3):
            game.key(K.Key_Left)
        self.assertEqual(game.px, 0)
        game.key(K.Key_Left)
        self.assertEqual(game.px, 0, "the wall stops it")
        game.key(K.Key_Space)
        self.assertEqual(game.rows_cleared, 1)
        self.assertGreaterEqual(game.score, 100)
        self.assertEqual(game.grid[-1], [None] * 9 + [2], "the rows above move down")
        self.assertFalse(game.over)

    def test_turning_and_the_end(self):
        self.assertEqual(sorted(blocks.turned(blocks.SHAPES[0])), [(0, 0), (0, 1), (0, 2), (0, 3)])
        for shape in blocks.SHAPES:
            cells = shape
            for _ in range(4):
                cells = blocks.turned(cells)
            self.assertEqual(sorted(cells), sorted(shape), "four quarter turns come back round")
        game = Blocks(seed=4)
        game.go()
        game.kind, game.cells, game.px, game.py = 0, list(blocks.SHAPES[0]), 7, 5
        game.turn()
        self.assertTrue(game.fits(game.cells, game.px, game.py))
        self.assertEqual(blocks.extent(game.cells), (1, 4))
        game.grid[0] = [1] * 9 + [None]
        game._spawn()
        self.assertTrue(game.over, "no room for a new shape ends the game")

    def test_shapes_fall_by_themselves(self):
        game = Blocks(seed=4)
        game.go()
        run(game, 0.7)
        self.assertEqual(game.py, 1)


class RocksTests(GameTest):
    def test_shots_split_rocks_and_rocks_cost_lives(self):
        game = Rocks(seed=5)
        game.go()
        self.assertEqual(len(game.rocks), 3)
        game.rocks = [rocks.Rock(250.0, 120.0, 0.0, 0.0, 3, [1.0] * 10)]
        game.safe = 0.0
        game.shoot()
        game.shoot()
        self.assertEqual(len(game.shots), 1, "it has to reload between shots")
        run(game, 0.4)
        self.assertEqual(game.score, 20)
        self.assertEqual([rock.size for rock in game.rocks], [2, 2])

        game.rocks = [rocks.Rock(game.ship_x, game.ship_y, 0.0, 0.0, 1, [1.0] * 10)]
        game.shots = []
        game.tick(DT)
        self.assertEqual(game.lives, 2)
        self.assertGreater(game.safe, 0)
        game.tick(DT)
        self.assertEqual(game.lives, 2, "nothing can hit the ship straight after it loses a life")

        game.rocks = []
        game.tick(DT)
        self.assertEqual(game.wave, 2)
        self.assertEqual(len(game.rocks), 4)

    def test_keys_fly_the_ship(self):
        game = Rocks(seed=5)
        game.go()
        game.rocks = [rocks.Rock(20.0, 20.0, 0.0, 0.0, 1, [1.0] * 10)]
        press(game, K.Key_Right)
        press(game, K.Key_Up)
        run(game, 0.5)
        self.assertGreater(game.angle, 0)
        self.assertGreater(game.vx, 0)


class RunnerTests(GameTest):
    def test_jumping_clears_a_block_and_running_into_one_ends_the_game(self):
        game = Runner(seed=6)
        game.go()
        game.gap = 1e9
        game.blocks = [[runner.RUNNER_X + 70, 28.0, 36.0]]
        game.key(K.Key_Space)
        run(game, 0.9)
        self.assertFalse(game.over)
        self.assertEqual(game.lift, 0.0, "it has landed again")
        self.assertGreater(game.score, 0)

        game.blocks = [[runner.RUNNER_X + 70, 28.0, 36.0]]
        run(game, 0.9)
        self.assertTrue(game.over)

    def test_blocks_keep_coming(self):
        game = Runner(seed=6)
        game.go()
        seen = 0
        for _ in range(600):
            before = len(game.blocks)
            game.lift = 100.0  # Flying over everything
            game.tick(DT)
            seen += len(game.blocks) > before
        self.assertGreater(seen, 3)
        self.assertGreater(game.speed, runner.START_SPEED)


class MinesTests(GameTest):
    def test_the_first_click_is_safe_and_clearing_the_field_wins(self):
        for level, (n, count) in enumerate(mines.SIZES):
            game = Mines(level, seed=7)
            game.go()
            first = (n // 2, n // 2)
            game.uncover(first)
            self.assertEqual(len(game.mines), count)
            self.assertFalse(game.mines & {first, *game.around(first)})
            self.assertGreater(len(game.shown), 1, "an empty square opens its neighbours")
            self.assertEqual(game.score, len(game.shown))
            for x in range(n):
                for y in range(n):
                    if (x, y) not in game.mines:
                        game.uncover((x, y))
            self.assertTrue(game.over)
            self.assertEqual(game.result, "Field cleared")
            self.assertEqual(game.score, n * n - count + mines.TIME_BONUS)

    def test_flags_protect_and_mines_end_the_game(self):
        game = Mines(0, seed=7)
        game.go()
        game.uncover((4, 4))
        mine = next(iter(game.mines))
        game.flag(mine)
        game.uncover(mine)
        self.assertFalse(game.over, "a flagged square cannot be uncovered")
        game.flag(mine)
        game.uncover(mine)
        self.assertTrue(game.over)
        self.assertEqual((game.result, game.hit), ("You hit a mine", mine))

    def test_clicking_a_number_uncovers_around_it_once_its_mines_are_flagged(self):
        game = Mines(0, seed=7)
        game.go()
        game.mines = {(0, 0)}
        game.count = 1
        game.shown = {(1, 1)}
        game.uncover_around((1, 1))
        self.assertEqual(game.shown, {(1, 1)}, "not until the flag is down")
        size = mines.SIDE / game.n
        game.click(QPointF(size / 2, size / 2), Qt.MouseButton.RightButton)
        self.assertEqual(game.flags, {(0, 0)})
        game.click(QPointF(size * 1.5, size * 1.5), Qt.MouseButton.LeftButton)
        self.assertTrue(game.over)
        self.assertEqual(game.result, "Field cleared")


class MergeTests(GameTest):
    def test_sliding_a_row(self):
        self.assertEqual(merge.slide([2, 2, 2, 2]), ([4, 4, 0, 0], 8))
        self.assertEqual(merge.slide([2, 0, 2, 4]), ([4, 4, 0, 0], 4))
        self.assertEqual(merge.slide([4, 4, 8, 0]), ([8, 8, 0, 0], 8), "a new tile does not join again that move")
        self.assertEqual(merge.slide([2, 4, 8, 16]), ([2, 4, 8, 16], 0))

    def test_moves_in_each_direction(self):
        game = Merge(seed=8)
        game.go()
        start = [[2, 0, 0, 2], [0, 0, 0, 0], [4, 0, 0, 0], [4, 0, 0, 0]]
        for key, row, column, value in [(K.Key_Left, 0, 0, 4), (K.Key_Right, 0, 3, 4), (K.Key_Up, 0, 0, 2),
                                        (K.Key_Down, 3, 0, 8)]:
            game.grid = [list(line) for line in start]
            game.score = 0
            game.key(key)
            self.assertEqual(game.grid[row][column], value, key)
            self.assertEqual(sum(1 for line in game.grid for tile in line if tile), 4, "two joined, one arrived")
        self.assertEqual(game.score, 8)

    def test_a_move_that_moves_nothing_adds_no_tile_and_a_full_board_ends_the_game(self):
        game = Merge(seed=8)
        game.go()
        game.grid = [[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        self.assertFalse(game.move(-1, 0))
        self.assertEqual(sum(1 for line in game.grid for tile in line if tile), 4)
        game.grid = [[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [2, 4, 2, 0]]
        with mock.patch.object(game.rng, "random", return_value=0.05):  # The new tile is a 4
            game.move(1, 0)
        self.assertEqual(game.grid[3], [4, 2, 4, 2])
        self.assertTrue(game.over)
        self.assertEqual(game.result, "No moves left")


class SolitaireTests(GameTest):
    def setUp(self):
        super().setUp()
        self.game = Solitaire(seed=9)
        self.game.go()

    def test_the_deal(self):
        game = self.game
        self.assertEqual([len(pile) for pile in game.piles], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(game.hidden, [0, 1, 2, 3, 4, 5, 6])
        cards = [card for pile in game.piles for card in pile] + game.pack
        self.assertEqual(len(set(cards)), 52)
        game.turn_pack()
        self.assertEqual((len(game.pack), len(game.turned)), (23, 1))
        order = list(game.pack) + game.turned
        for _ in range(23):
            game.turn_pack()
        game.turn_pack()
        self.assertEqual((len(game.pack), game.turned), (24, []))
        self.assertEqual(game.pack + [], order[:23] + order[23:], "the pack comes round in the same order")

    def test_cards_build_up_by_suit_and_stack_down_in_turn(self):
        game = self.game
        game.piles = [[(13, 0)], [(5, 3), (12, 1)], [], [(9, 0)], [], [], []]
        game.hidden = [0, 1, 0, 0, 0, 0, 0]
        game.turned = [(2, 0), (1, 0)]
        self.assertTrue(game.play_turned())
        self.assertTrue(game.play_turned())
        self.assertEqual((game.built[0], game.score), ([(1, 0), (2, 0)], 20))

        self.assertTrue(game.play_pile(1, 1))
        self.assertEqual(game.piles[0], [(13, 0), (12, 1)])
        self.assertEqual((game.hidden[1], game.score), (0, 25), "the card it uncovered is turned over")
        self.assertFalse(game.play_pile(1, 0), "a five has nowhere to go")
        self.assertFalse(game.play_pile(3, 0), "nor a nine")

        game.piles[3] = [(11, 0), (10, 1)]
        self.assertTrue(game.play_pile(3, 0), "a run moves together")
        self.assertEqual(game.piles[0], [(13, 0), (12, 1), (11, 0), (10, 1)])
        self.assertFalse(game.play_pile(0, 0), "a king alone in its column stays where it is")
        game.piles[5] = [(4, 2), (13, 2)]
        game.hidden[5] = 1
        self.assertTrue(game.play_pile(5, 1), "a king moves to a gap when that uncovers a card")
        self.assertEqual(game.piles[2], [(13, 2)])

    def test_hidden_cards_cannot_be_moved_and_a_click_finds_the_card(self):
        game = self.game
        self.assertFalse(game.play_pile(6, 0))
        before = len(game.pack)
        game.click(QPointF(solitaire.LEFT + 5, solitaire.TOP + 5), Qt.MouseButton.LeftButton)
        self.assertEqual(len(game.pack), before - 1)
        game.piles[0], game.hidden[0] = [(1, 3)], 0
        game.click(QPointF(solitaire.LEFT + 5, solitaire.PILES_Y + 5), Qt.MouseButton.LeftButton)
        self.assertEqual(game.built[3], [(1, 3)])

    def test_solving_it(self):
        game = self.game
        game.built = [[(rank, suit) for rank in range(1, 14)] for suit in range(4)]
        game.built[3].pop()
        game.piles = [[] for _ in range(7)]
        game.hidden = [0] * 7
        game.pack, game.turned = [], [(13, 3)]
        game.play_turned()
        self.assertTrue(game.over)
        self.assertEqual(game.result, "Solved")


class SudokuTests(GameTest):
    def assert_valid(self, grid):
        lines = [[r * 9 + c for c in range(9)] for r in range(9)] + [[r * 9 + c for r in range(9)] for c in range(9)]
        lines += [[(br + r) * 9 + bc + c for r in range(3) for c in range(3)] for br in (0, 3, 6) for bc in (0, 3, 6)]
        for line in lines:
            self.assertEqual(sorted(grid[i] for i in line), list(range(1, 10)))

    def test_every_puzzle_has_exactly_one_solution(self):
        for level, blanks in enumerate(sudoku.BLANKS):
            for seed in range(3):
                puzzle, solution = sudoku.make_puzzle(random.Random(seed), blanks)
                self.assert_valid(solution)
                self.assertEqual(sudoku.count_solutions(list(puzzle)), 1)
                self.assertTrue(all(p in (0, s) for p, s in zip(puzzle, solution)))
                self.assertGreaterEqual(puzzle.count(0), blanks - 6, (level, seed))
        self.assertEqual(sudoku.count_solutions([0] * 81), 2, "an empty grid has many, counted no further than two")

    def test_playing_with_the_keys_and_solving(self):
        game = Sudoku(0, seed=10)
        game.go()
        blank = game.cells.index(0)
        given = game.given.index(True)
        row, column = divmod(blank, 9)
        game.click(QPointF((column + 0.5) * sudoku.CELL, (row + 0.5) * sudoku.CELL), Qt.MouseButton.LeftButton)
        self.assertEqual(game.selected, blank)
        right = game.solution[blank]
        wrong = right % 9 + 1
        press(game, K.Key_0 + wrong)
        self.assertEqual((game.cells[blank], game.score), (wrong, 0))
        press(game, K.Key_Backspace)
        self.assertEqual(game.cells[blank], 0)
        press(game, K.Key_0 + right)
        self.assertEqual((game.cells[blank], game.score), (right, 10))

        game.enter(given, game.solution[given] % 9 + 1)
        self.assertEqual(game.cells[given], game.solution[given], "the squares given at the start cannot be changed")
        game.selected = 0
        press(game, K.Key_Left)
        press(game, K.Key_Up)
        self.assertEqual(game.selected, 0, "the arrows stop at the edges")
        press(game, K.Key_Down)
        press(game, K.Key_Right)
        self.assertEqual(game.selected, 10)

        blanks = [i for i in range(81) if not game.given[i]]
        for i in blanks:
            game.enter(i, game.solution[i])
        self.assertTrue(game.over)
        self.assertEqual(game.result, "Solved")
        self.assertEqual(game.score, 10 * len(blanks) + sudoku.TIME_BONUS)


if __name__ == "__main__":
    unittest.main()
