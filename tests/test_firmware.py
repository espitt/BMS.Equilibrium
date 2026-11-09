"""Firmware release browser tests, against a local HTTP server standing in for GitHub. No windows are shown."""

import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "installer"), str(ROOT / "app")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from equilibrium import firmware  # noqa: E402
from equilibrium.bms import simulator  # noqa: E402
from equilibrium.firmware import FirmwareFile, FirmwareRelease  # noqa: E402
from equilibrium.ui.firmware_browser import TAG_ROLE  # noqa: E402
from equilibrium_setup import core  # noqa: E402

app = QApplication.instance() or QApplication([])

REPO = "sufst/bms-firmware"
NOV_1 = datetime(2026, 11, 1, tzinfo=timezone.utc)


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers))
        status, headers, body = self.server.routes.get(self.path, (404, {}, b'{"message": "Not Found"}'))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GitHubTest(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        self.server.routes = {}
        self.server.requests = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name) / "firmware"
        for name, value in (("API_ROOT", f"{self.base}/api"), ("REPO", REPO), ("cache_root", lambda: self.cache)):
            patcher = mock.patch.object(firmware, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.entries = []
        self.list_path = f"/api/repos/{REPO}/releases?per_page=30"

    def asset(self, tag, name, content, digest=True, served=None):
        """Attach a file. served, if given, is what the server actually sends, to fake damage."""
        self.server.routes[f"/download/{tag}/{name}"] = (200, {}, content if served is None else served)
        asset = {"name": name, "size": len(content), "browser_download_url": f"{self.base}/download/{tag}/{name}"}
        if digest:
            asset["digest"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
        return asset

    def publish(self, tag, published="2026-11-01T12:00:00Z", prerelease=False, draft=False, notes="", assets=()):
        self.entries.append({"tag_name": tag, "name": tag, "draft": draft, "prerelease": prerelease,
                             "published_at": published, "body": notes, "assets": list(assets)})
        self.server.routes[self.list_path] = (200, {}, json.dumps(self.entries).encode())

    def fail_listing(self, status, headers=None):
        self.server.routes[self.list_path] = (status, headers or {}, b'{"message": "error"}')


class ListingTests(GitHubTest):
    def test_lists_newest_first_with_notes(self):
        self.publish("v1.3.0", published="2026-10-01T09:00:00Z", notes="Older")
        self.publish("v1.4.0", published="2026-11-01T09:00:00Z", notes="Balancing **fix**")
        releases = firmware.list_releases(REPO)
        self.assertEqual([r.version for r in releases], ["1.4.0", "1.3.0"])
        self.assertEqual(releases[0].tag, "v1.4.0")
        self.assertEqual(releases[0].notes, "Balancing **fix**")
        self.assertEqual(releases[0].published, datetime(2026, 11, 1, 9, tzinfo=timezone.utc))

    def test_asks_the_github_api_for_the_firmware_repository(self):
        self.publish("v1.4.0")
        firmware.list_releases()
        [(path, headers)] = self.server.requests
        self.assertEqual(path, self.list_path)
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")

    def test_prereleases_are_listed_and_marked_but_drafts_are_not(self):
        self.publish("v1.4.0")
        self.publish("v1.5.0-rc1", published="2026-11-05T00:00:00Z", prerelease=True)
        self.publish("v1.6.0", draft=True)
        releases = firmware.list_releases(REPO)
        self.assertEqual([(r.version, r.prerelease) for r in releases], [("1.5.0-rc1", True), ("1.4.0", False)])

    def test_attached_files_and_their_checksums(self):
        self.publish("v1.4.0", assets=[self.asset("v1.4.0", "bms.bin", b"image"),
                                       self.asset("v1.4.0", "bms.elf", b"debug", digest=False),
                                       self.asset("v1.4.0", "..", b"sneaky")])
        with self.assertLogs(firmware.log, "WARNING"):
            [release] = firmware.list_releases(REPO)
        self.assertEqual([(f.name, f.size, f.sha256) for f in release.files],
                         [("bms.bin", 5, hashlib.sha256(b"image").hexdigest()), ("bms.elf", 5, None)])

    def test_a_tag_without_a_version_is_listed_by_its_name(self):
        self.publish("first-build", notes=None)
        [release] = firmware.list_releases(REPO)
        self.assertEqual((release.version, release.tag, release.notes, release.files),
                         ("first-build", "first-build", "", ()))

    def test_an_incomplete_entry_is_skipped(self):
        self.publish("v1.4.0")
        self.entries.append({"tag_name": "v1.5.0", "draft": False})  # No date
        self.server.routes[self.list_path] = (200, {}, json.dumps(self.entries).encode())
        with self.assertLogs(firmware.log, "WARNING"):
            self.assertEqual([r.version for r in firmware.list_releases(REPO)], ["1.4.0"])

    def test_versions(self):
        self.assertEqual(firmware.parse_version("v0.4.2 (simulated)"), "0.4.2")
        self.assertEqual(firmware.parse_version("v1.5.0-rc1"), "1.5.0-rc1")
        self.assertIsNone(firmware.parse_version("dev build"))


class ErrorTests(GitHubTest):
    def assert_error(self, pattern):
        with self.assertRaisesRegex(core.InstallError, pattern):
            firmware.list_releases(REPO)

    def test_missing_repository(self):
        self.assert_error(f"Could not find {REPO} on GitHub")

    def test_rate_limit_says_when_to_try_again(self):
        self.fail_listing(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 290)})
        self.assert_error("Try again in 5 minutes")

    def test_other_errors(self):
        self.fail_listing(500)
        self.assert_error(r"HTTP 500")

    def test_offline(self):
        with mock.patch.object(firmware, "API_ROOT", "http://127.0.0.1:9"):
            self.assert_error("Could not reach GitHub")

    def test_unreadable_listing(self):
        self.server.routes[self.list_path] = (200, {}, b"<html>")
        self.assert_error("could not be read")


class DownloadTests(GitHubTest):
    def release(self, *assets, tag="v1.4.0"):
        self.publish(tag, assets=assets)
        return next(r for r in firmware.list_releases(REPO) if r.tag == tag)

    def test_downloads_every_file_into_the_release_folder(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image" * 1000),
                               self.asset("v1.4.0", "bms.elf", b"debug", digest=False))
        progress = []
        folder = firmware.download(release, lambda done, total: progress.append((done, total)))
        self.assertEqual(folder, self.cache / "v1.4.0")
        self.assertEqual((folder / "bms.bin").read_bytes(), b"image" * 1000)
        self.assertEqual((folder / "bms.elf").read_bytes(), b"debug")
        self.assertEqual(progress[-1], (5005, 5005))
        self.assertTrue(firmware.is_downloaded(release))

    def test_a_good_copy_is_not_downloaded_again(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image"))
        firmware.download(release)
        self.server.requests.clear()
        firmware.download(release)
        self.assertEqual(self.server.requests, [])

    def test_a_damaged_file_is_rejected_and_removed(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image", served=b"imagf"))
        with self.assertRaisesRegex(core.InstallError, "damaged"):
            firmware.download(release)
        self.assertEqual(list((self.cache / "v1.4.0").iterdir()), [])
        self.assertFalse(firmware.is_downloaded(release))

    def test_without_a_checksum_the_size_is_still_checked(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image", digest=False, served=b"ima"))
        with self.assertRaisesRegex(core.InstallError, "damaged"):
            firmware.download(release)

    def test_a_copy_changed_on_disk_no_longer_counts(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image"))
        firmware.download(release)
        (self.cache / "v1.4.0" / "bms.bin").write_bytes(b"IMAGE")
        self.assertFalse(firmware.is_downloaded(release))

    def test_a_release_without_files(self):
        release = self.release()
        self.assertFalse(firmware.is_downloaded(release))
        with self.assertRaisesRegex(core.InstallError, "nothing to download"):
            firmware.download(release)

    def test_offline(self):
        release = self.release(self.asset("v1.4.0", "bms.bin", b"image"))
        self.server.routes.clear()
        with self.assertRaisesRegex(core.InstallError, "Could not download bms.bin"):
            firmware.download(release)

    def test_deleting_removes_only_that_release(self):
        one = self.release(self.asset("v1.4.0", "bms.bin", b"one"))
        two = self.release(self.asset("v1.5.0", "bms.bin", b"two"), tag="v1.5.0")
        firmware.download(one)
        firmware.download(two)
        firmware.delete_download(one)
        self.assertFalse((self.cache / "v1.4.0").exists())
        self.assertTrue(firmware.is_downloaded(two))
        firmware.delete_download(one)  # Already gone is fine.

    def test_folder_names_stay_inside_the_download_folder(self):
        for tag, name in [("v1.4.0", "v1.4.0"), ("release/1.4", "release_1.4"), ("..", "_.."), ("", "_")]:
            release = FirmwareRelease("1.4.0", tag, NOV_1, False, "")
            self.assertEqual(firmware.download_folder(release), self.cache / name, tag)


class BrowserTests(GitHubTest):
    def setUp(self):
        super().setUp()
        from equilibrium import theme
        from equilibrium.ui.main_window import MainWindow
        from equilibrium.ui.screens.settings import SettingsScreen

        theme.apply(app)
        self.window = MainWindow()
        self.window.resize(1400, 900)
        self.addCleanup(self.close)
        self.window._connect_simulator()
        self.window.ctx.link.stop()
        self.screen = self.window.screens[self.window.screen_index(SettingsScreen)]
        self.window.show_screen(self.window.screen_index(SettingsScreen))
        self.browser = self.screen.browser
        # Message boxes would wait for a click, so answer them here and keep what they said.
        self.messages = []
        for name, answer in (("question", QMessageBox.StandardButton.Yes), ("warning", None),
                             ("information", None)):
            patcher = mock.patch.object(QMessageBox, name, side_effect=lambda *a, answer=answer, **k:
                                        self.messages.append(a[2]) or answer)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(simulator, "FLASH_SECONDS", 0.3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def close(self):
        self.window.ctx.disconnect_link()
        self.window.ctx.config.dirty = False
        self.window.close()

    def pump(self, condition, timeout=10):
        deadline = time.time() + timeout
        while not condition():
            app.processEvents()
            time.sleep(0.01)
            self.assertLess(time.time(), deadline, "timed out")

    def check(self):
        self.browser.check()
        self.pump(lambda: not self.browser.checking)

    def rows(self):
        return [self.browser.list.itemWidget(self.browser.list.item(i)) for i in range(self.browser.list.count())]

    def tags(self):
        from equilibrium.ui.widgets import Badge

        return [[b.text() for b in row.findChildren(Badge)] for row in self.rows()]

    def descriptions(self):
        return [row.description.full for row in self.rows()]

    def select(self, tag):
        for i in range(self.browser.list.count()):
            item = self.browser.list.item(i)
            item.setSelected(item.data(TAG_ROLE) == tag)

    def test_lists_releases_from_github_on_a_worker_thread(self):
        self.publish("v1.4.0", notes="Balancing **fix**\r\nand  faster")
        self.publish("v0.4.2", published="2026-09-01T00:00:00Z")
        self.publish("v2.1.0-rc1", published="2026-11-05T00:00:00Z", prerelease=True, notes="Trying a new filter")
        self.browser.check()
        self.assertIn("Checking", self.browser.status.text())
        self.pump(lambda: not self.browser.checking)
        self.assertEqual([r.version for r in self.browser.releases], ["2.1.0-rc1", "1.4.0", "0.4.2"])
        self.assertEqual(self.tags(), [["Pre-release"], [], ["Installed"]])
        self.assertEqual(self.descriptions(), ["Trying a new filter", "Balancing fix and faster", "No description"],
                         "on one line, without Markdown")
        self.assertIn(f"3 releases in {REPO}", self.browser.status.text())
        self.screen.grab()  # Paints the screen offscreen

    def test_download_then_program_then_the_download_is_deleted(self):
        self.publish("v1.4.0", assets=[self.asset("v1.4.0", "bms-1.4.0.bin", b"image" * 100)])
        self.check()
        self.select("v1.4.0")
        self.assertIn("bms-1.4.0.bin (500 bytes)", self.browser.files.text())
        self.assertTrue(self.browser.download_button.isEnabled())
        self.assertFalse(self.browser.program.isEnabled(), "nothing to program until it is downloaded")

        self.browser.download_button.click()
        self.pump(lambda: self.browser.downloading is None)
        self.assertEqual(self.tags(), [["Downloaded"]])
        self.assertIn("Downloaded to", self.browser.files.text())
        self.assertTrue((self.cache / "v1.4.0" / "bms-1.4.0.bin").is_file())
        self.assertFalse(self.browser.download_button.isEnabled())
        self.assertTrue(self.browser.program.isEnabled())

        self.browser.program.click()
        self.assertIn("Program firmware 1.4.0", self.messages[-1])
        self.assertFalse(self.browser.program.isEnabled(), "not while programming")
        self.pump(lambda: self.browser.programming is None)
        self.assertEqual(self.window.ctx.data.device["Firmware"], "v1.4.0 (simulated)")
        self.assertEqual(self.tags(), [["Installed"]], "programmed, and no longer downloaded")
        self.assertFalse((self.cache / "v1.4.0").exists())
        self.assertTrue(self.browser.download_button.isEnabled(), "it can be downloaded again")

    def test_failed_programming_keeps_the_download(self):
        self.publish("v1.4.0", assets=[self.asset("v1.4.0", "bms.bin", b"image")])
        self.check()
        self.select("v1.4.0")
        self.browser.download_button.click()
        self.pump(lambda: self.browser.downloading is None)
        with mock.patch.object(self.window.ctx.link, "flash",
                               side_effect=lambda files, version, progress, done: done("Verify failed")):
            self.browser.program.click()
        self.assertIn("Verify failed", self.messages[-1])
        self.assertTrue(firmware.is_downloaded(self.browser.releases[0]))
        self.assertEqual(self.tags(), [["Downloaded"]])

    def test_a_release_without_files_cannot_be_downloaded(self):
        self.publish("v0.0.0", notes="First build")
        self.check()
        self.select("v0.0.0")
        self.assertIn("No files are attached to v0.0.0", self.browser.files.text())
        self.assertFalse(self.browser.download_button.isEnabled())

    def test_downloads_from_earlier_are_recognised(self):
        self.publish("v1.4.0", assets=[self.asset("v1.4.0", "bms.bin", b"image")])
        firmware.download(firmware.list_releases(REPO)[0])
        self.check()
        self.assertEqual(self.tags(), [["Downloaded"]])

    def test_failures_are_shown_in_place_of_the_list(self):
        self.fail_listing(404)
        self.check()
        self.assertEqual(self.browser.list.count(), 0)
        self.assertIn("Could not find", self.browser.status.text())

    def test_redraws_when_the_bms_or_theme_changes(self):
        from equilibrium import theme

        release = FirmwareRelease("0.4.2", "v0.4.2", NOV_1, False, "", (FirmwareFile("a.bin", "", 1, None),))
        self.browser._on_listed(self.browser._check_number, [release], {"v0.4.2"}, "")
        self.select("v0.4.2")
        self.assertEqual(self.tags(), [["Installed", "Downloaded"]])
        self.assertTrue(self.browser.program.isEnabled())

        theme.signals.changed.emit()
        self.assertEqual(self.tags(), [["Installed", "Downloaded"]])
        self.assertEqual(len(self.browser.list.selectedItems()), 1, "a redraw keeps the selection")

        self.window.ctx.disconnect_link()
        self.assertEqual(self.tags(), [["Downloaded"]], "nothing is installed without a BMS")
        self.assertFalse(self.browser.program.isEnabled(), "nothing to program without a BMS")


if __name__ == "__main__":
    unittest.main()
