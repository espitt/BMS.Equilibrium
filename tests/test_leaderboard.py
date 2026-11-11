"""Tests for the shared minigame leaderboard, against a pretend GitHub on this computer."""

import base64
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "installer"), str(ROOT / "app")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from equilibrium import leaderboard  # noqa: E402
from equilibrium.leaderboard import Entry  # noqa: E402
from equilibrium.ui.games import arcade  # noqa: E402
from equilibrium.ui.games.arcade import GAMES, Arcade  # noqa: E402
from equilibrium.ui.games.snake import Snake  # noqa: E402
from equilibrium_setup import core  # noqa: E402

app = QApplication.instance() or QApplication([])
REPO = "team/scores"
TOKEN = "github_pat_test"
RAW_PATH = f"/{REPO}/main/scores.json"
API_PATH = f"/repos/{REPO}/contents/scores.json"


def document(**boards) -> bytes:
    scores = {board.replace("_", "/"): [{"name": n, "score": s, "date": d} for n, s, d in rows]
              for board, rows in boards.items()}
    return json.dumps({"format": 1, "scores": scores}).encode()


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    """Serves and stores one scores file, the way GitHub's contents API does."""

    def log_message(self, *args):
        pass

    def reply(self, status: int, body: object) -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def allowed(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    def do_GET(self):
        server = self.server
        server.requests.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == RAW_PATH and server.file is not None:
            self.reply(200, server.file)
        elif self.path == f"{API_PATH}?ref=main" and not self.allowed():
            self.reply(401, {"message": "Bad credentials"})
        elif self.path == f"{API_PATH}?ref=main" and server.file is not None:
            self.reply(200, {"content": base64.encodebytes(server.file).decode(), "sha": server.version()})
        else:
            self.reply(404, {"message": "Not Found"})

    def do_PUT(self):
        server = self.server
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        server.requests.append(("PUT", self.path, self.headers.get("Authorization")))
        if self.path != API_PATH or not self.allowed():
            self.reply(401, {"message": "Bad credentials"})
            return
        if server.rivals:  # Someone else saves a score between this player's read and write
            server.file = server.rivals.pop(0)
        if body.get("sha") != server.version():
            self.reply(409, {"message": "scores.json does not match"})
            return
        server.file = base64.b64decode(body["content"])
        server.messages.append(body["message"])
        self.reply(200 if body.get("sha") else 201, {"content": {}})


class Server(http.server.ThreadingHTTPServer):
    def version(self):
        return hashlib.sha1(self.file).hexdigest() if self.file is not None else None


class LeaderboardTest(unittest.TestCase):
    def setUp(self):
        self.server = Server(("127.0.0.1", 0), FakeGitHub)
        self.server.file = None
        self.server.token = TOKEN
        self.server.requests, self.server.messages, self.server.rivals = [], [], []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        root = f"http://127.0.0.1:{self.server.server_address[1]}"
        ini = str(Path(tempfile.mkdtemp()) / "settings.ini")
        for patch in (
            mock.patch.multiple(leaderboard, API_ROOT=root, RAW_ROOT=root, REPO=REPO, TOKEN=TOKEN),
            mock.patch.dict(os.environ, {leaderboard.TOKEN_VARIABLE: ""}),
            mock.patch.object(leaderboard, "today", return_value="2026-11-11"),
            mock.patch.object(arcade, "_settings", lambda: QSettings(ini, QSettings.Format.IniFormat)),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def puts(self) -> int:
        return sum(1 for method, *_ in self.server.requests if method == "PUT")

    def stored(self) -> leaderboard.Boards:
        return leaderboard.parse(json.loads(self.server.file))


class RulesTests(unittest.TestCase):
    def test_each_player_keeps_one_place_their_best(self):
        board = [Entry("Ana", 50, "2026-11-01"), Entry("Ben", 30, "2026-11-02")]
        self.assertEqual(leaderboard.merged(board, Entry("Cy", 40, "2026-11-03")),
                         [board[0], Entry("Cy", 40, "2026-11-03"), board[1]])
        self.assertIsNone(leaderboard.merged(board, Entry("ben", 30, "2026-11-03")), "no better than before")
        self.assertEqual(leaderboard.merged(board, Entry("BEN", 60, "2026-11-03")),
                         [Entry("BEN", 60, "2026-11-03"), board[0]], "capitals do not make a new player")
        self.assertIsNone(leaderboard.merged(board, Entry("Cy", 0, "2026-11-03")))
        self.assertIsNone(leaderboard.merged(board, Entry("", 99, "2026-11-03")), "a score needs a name")

    def test_only_the_top_ten_are_kept_and_ties_go_to_whoever_was_first(self):
        board = [Entry(f"P{i}", 100 - i, "2026-11-01") for i in range(leaderboard.TOP)]
        late = Entry("Late", 91, "2026-11-05")
        self.assertIsNone(leaderboard.merged(board, late), "level with last place, but later")
        better = leaderboard.merged(board, Entry("New", 95, "2026-11-05"))
        self.assertEqual(len(better), leaderboard.TOP)
        self.assertEqual([e.name for e in better[4:7]], ["P4", "P5", "New"])
        self.assertNotIn("P9", [e.name for e in better])

    def test_names_are_made_fit_to_publish(self):
        self.assertEqual(leaderboard.clean_name("  Ethan \n S. "), "Ethan S.")
        self.assertEqual(leaderboard.clean_name("<b>Zoë</b> O'Neil-Jones"), "bZoëb O'Neil-Jones")
        self.assertEqual(len(leaderboard.clean_name("x" * 80)), leaderboard.NAME_LENGTH)
        self.assertEqual(leaderboard.clean_name("  \t "), "")

    def test_a_damaged_file_loses_only_its_bad_rows(self):
        boards = leaderboard.parse({"scores": {
            "snake/0": [{"name": "Ana", "score": 50, "date": "2026-11-01T10:00:00Z"}, {"name": "Ben"}, "junk",
                        {"name": "", "score": 9}, {"name": "Cy", "score": "70"}, {"name": "Di", "score": -4}],
            "mines/1": "junk",
        }})
        self.assertEqual(boards, {"snake/0": [Entry("Cy", 70, ""), Entry("Ana", 50, "2026-11-01")], "mines/1": []})
        for junk in (None, [], "text", {"scores": []}):
            self.assertEqual(leaderboard.parse(junk), {})
        self.assertEqual(leaderboard.parse(json.loads(leaderboard.dump(boards))), boards)

    def test_no_token_is_ever_committed(self):
        source = (ROOT / "app" / "equilibrium" / "leaderboard.py").read_text(encoding="utf-8")
        self.assertIn('\nTOKEN = ""\n', source, "release builds stamp the token in; the repository never holds it")


class GitHubTests(LeaderboardTest):
    def test_anyone_can_read_without_an_account(self):
        self.server.file = document(snake_0=[("Ana", 50, "2026-11-01")])
        with mock.patch.object(leaderboard, "TOKEN", ""):
            self.assertFalse(leaderboard.can_post())
            self.assertEqual(leaderboard.fetch(), {"snake/0": [Entry("Ana", 50, "2026-11-01")]})
            with self.assertRaisesRegex(core.InstallError, "cannot add|not add"):
                leaderboard.post("snake/0", "Ben", 60)
        self.assertEqual(self.server.requests, [("GET", RAW_PATH, None)], "a plain download, with no token")

    def test_an_empty_leaderboard_and_failures(self):
        with mock.patch.object(leaderboard, "TOKEN", ""):
            self.assertEqual(leaderboard.fetch(), {}, "no file yet means no scores yet")
            self.server.file = b"not json"
            with self.assertRaisesRegex(core.InstallError, "could not be read"):
                leaderboard.fetch()
            with mock.patch.object(leaderboard, "RAW_ROOT", "http://127.0.0.1:9"):
                with self.assertRaisesRegex(core.InstallError, "internet connection"):
                    leaderboard.fetch()
        self.server.token = "a different one"
        with self.assertRaisesRegex(core.InstallError, "turned this copy of the app away"):
            leaderboard.fetch()

    def test_the_first_score_makes_the_file_and_later_ones_add_to_it(self):
        self.assertEqual(leaderboard.post("snake/0", " Ana ", 50), {"snake/0": [Entry("Ana", 50, "2026-11-11")]})
        leaderboard.post("mines/2", "Ana", 300)
        boards = leaderboard.post("snake/0", "Ben", 80)
        self.assertEqual(boards["snake/0"], [Entry("Ben", 80, "2026-11-11"), Entry("Ana", 50, "2026-11-11")])
        self.assertEqual(self.stored(), boards)
        self.assertEqual(set(boards), {"snake/0", "mines/2"})
        self.assertEqual(self.server.messages, ["Ana: 50 on snake/0", "Ana: 300 on mines/2", "Ben: 80 on snake/0"])
        self.assertTrue(all(sent == f"Bearer {TOKEN}" for _, _, sent in self.server.requests))

    def test_a_score_that_earns_no_place_is_not_sent(self):
        leaderboard.post("snake/0", "Ana", 50)
        self.assertEqual(leaderboard.post("snake/0", "Ana", 40), self.stored())
        self.assertEqual(self.puts(), 1)

    def test_two_players_saving_at_once_both_keep_their_scores(self):
        leaderboard.post("snake/0", "Ana", 50)
        self.server.rivals = [document(snake_0=[("Ana", 50, "2026-11-11"), ("Cy", 70, "2026-11-11")])]
        boards = leaderboard.post("snake/0", "Ben", 60)
        self.assertEqual([(e.name, e.score) for e in boards["snake/0"]], [("Cy", 70), ("Ben", 60), ("Ana", 50)])
        self.assertEqual(self.stored(), boards)
        self.assertEqual(self.puts(), 3, "Ana's, Ben's that clashed, and Ben's again")

        self.server.rivals = [document(snake_0=[("R", n, "2026-11-11")]) for n in range(1, 9)]
        with self.assertRaisesRegex(core.InstallError, "busy"):
            leaderboard.post("snake/0", "Di", 90)


class PanelTests(LeaderboardTest):
    def wait(self, panel) -> None:
        deadline = time.time() + 10
        app.processEvents()
        while panel.busy and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
        self.assertFalse(panel.busy)

    def card(self) -> Arcade:
        card = Arcade()
        card.resize(700, 500)
        card.show()
        self.addCleanup(card.close)
        self.wait(card.board)
        return card

    def test_a_finished_game_puts_the_players_best_on_the_board(self):
        self.server.file = document(snake_0=[("Ana", 50, "2026-11-01")], mines_0=[("Cy", 9, "2026-11-01")])
        card = self.card()
        panel = card.board
        self.assertIsInstance(card.game, Snake)
        self.assertEqual(panel.title.text(), "Snake")
        self.assertIn("Ana", panel.rows.text())
        self.assertNotIn("Cy", panel.rows.text(), "only this game's board is shown")
        self.assertIn("Enter a name", panel.status.text())

        card.game.go()
        card.game.add_score(70)
        card.game.end()
        self.wait(panel)
        self.assertEqual(self.puts(), 0, "nothing is published without a name")

        panel.name.setText("  Ben<> ")
        panel.name.editingFinished.emit()
        self.wait(panel)
        self.assertEqual(panel.name.text(), "Ben")
        self.assertEqual(self.stored()["snake/0"], [Entry("Ben", 70, "2026-11-11"), Entry("Ana", 50, "2026-11-01")])
        self.assertLess(panel.rows.text().index("Ben"), panel.rows.text().index("Ana"))
        self.assertIn("shared as Ben", panel.status.text())
        self.assertEqual(arcade._settings().value("games/player"), "Ben")

        card.game.go()
        card.game.add_score(30)  # Worse than their best
        card.game.end()
        self.wait(panel)
        self.assertEqual(self.puts(), 1)

        card.picker.setCurrentIndex(6)  # Mine sweeper
        self.wait(panel)
        self.assertEqual(panel.title.text(), "Mine sweeper")
        self.assertIn("Cy", panel.rows.text())
        self.assertNotIn("Ana", panel.rows.text())
        card.level.setCurrentIndex(1)
        self.wait(panel)
        self.assertIn("No scores yet", panel.rows.text(), "each level has a board of its own")

        again = self.card()
        self.assertEqual(again.board.name.text(), "Ben", "the name is remembered")

    def test_a_best_set_while_offline_is_sent_later(self):
        card = self.card()
        panel = card.board
        panel.name.setText("Ana")
        panel.name.editingFinished.emit()
        self.wait(panel)
        with mock.patch.multiple(leaderboard, API_ROOT="http://127.0.0.1:9"):
            card.game.go()
            card.game.add_score(40)
            card.game.end()
            self.wait(panel)
            self.assertIn("internet connection", panel.status.text())
        self.assertIsNone(self.server.file)
        panel.refresh_button.click()
        self.wait(panel)
        self.assertEqual(self.stored(), {"snake/0": [Entry("Ana", 40, "2026-11-11")]})

    def test_a_copy_without_a_token_shows_the_board_but_sends_nothing(self):
        self.server.file = document(snake_0=[("Ana", 50, "2026-11-01")])
        with mock.patch.object(leaderboard, "TOKEN", ""):
            card = self.card()
            panel = card.board
            panel.name.setText("Ben")
            panel.name.editingFinished.emit()
            card.game.go()
            card.game.add_score(70)
            card.game.end()
            self.wait(panel)
            self.assertIn("Ana", panel.rows.text())
            self.assertIn("cannot add scores", panel.status.text())
        self.assertEqual(self.puts(), 0)

    def test_a_hidden_board_asks_for_nothing_and_can_be_put_away(self):
        card = Arcade()
        card.picker.setCurrentIndex(GAMES.index(Snake) + 1)
        app.processEvents()
        self.assertEqual(self.server.requests, [])
        card.show()
        self.addCleanup(card.close)
        self.wait(card.board)
        self.assertEqual(len(self.server.requests), 1)
        card.board_button.click()
        self.assertTrue(card.board.isHidden())
        self.assertTrue(card.game.isVisible())
        card.board_button.click()
        self.assertTrue(card.board.isVisible())


if __name__ == "__main__":
    unittest.main()
