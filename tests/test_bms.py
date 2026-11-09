"""Tests for the pack layout, data store, configuration, simulator and screens. No windows are shown."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "installer"), str(ROOT / "app")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from equilibrium.bms.config import BY_KEY, SETTINGS, Config  # noqa: E402
from equilibrium.bms.layout import PackLayout, build_channels, cell_id, temp_id  # noqa: E402
from equilibrium.bms.store import BmsData  # noqa: E402

app = QApplication.instance() or QApplication([])


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.layout = PackLayout.load()

    def test_counts(self):
        self.assertEqual(self.layout.cell_count, 140)
        self.assertEqual(len(self.layout.thermistors), self.layout.segments * 24)

    def test_cell_position(self):
        self.assertEqual(self.layout.cell_position(1), (1, 1, 1))
        self.assertEqual(self.layout.cell_position(20), (1, 2, 20))
        self.assertEqual(self.layout.cell_position(21), (2, 1, 1))
        self.assertEqual(self.layout.cell_position(140), (7, 2, 20))

    def test_every_cell_and_thermistor_has_a_channel(self):
        channels = build_channels(self.layout)
        for n in range(1, self.layout.cell_count + 1):
            self.assertIn(cell_id(n), channels)
        for t in self.layout.thermistors:
            self.assertEqual(channels[temp_id(t.number)].segment, t.segment)

    def test_tooltip_names_location(self):
        info = build_channels(self.layout)[cell_id(47)]
        text = info.tooltip(3.9)
        self.assertIn("Cell 47", text)
        self.assertIn("Segment 3", text)
        self.assertIn("3.900 V", text)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.data = BmsData(PackLayout.load())

    def test_everything_stale_until_connected(self):
        self.assertEqual(self.data.stale, set(self.data.channels))
        self.data.set_connected(True, "test")
        self.data.update({"pack.voltage": 500.0})
        self.assertFalse(self.data.is_stale("pack.voltage"))
        self.assertTrue(self.data.is_stale("pack.current"))

    def test_goes_stale_after_timeout(self):
        self.data.set_connected(True, "test")
        self.data.update({"pack.voltage": 500.0})
        self.data.stamps["pack.voltage"] -= BmsData.STALE_AFTER + 0.5
        self.data.check_stale()
        self.assertTrue(self.data.is_stale("pack.voltage"))
        self.assertGreater(self.data.stale_for("pack.voltage"), BmsData.STALE_AFTER)

    def test_history_keeps_order_after_wrapping(self):
        history = self.data.history["pack.voltage"]
        for i in range(history.size + 10):
            history.append(float(i), float(i))
        t, v = history.arrays()
        self.assertEqual(len(t), history.size)
        self.assertEqual(t[0], 10.0)
        self.assertEqual(t[-1], history.size + 9.0)

    def test_faults_latch_until_cleared(self):
        self.data.update({"pack.voltage": 512.0})
        fault = self.data.raise_fault(1, "Test", "warning", "pack.voltage")
        self.assertEqual(fault.snapshot["pack.voltage"], 512.0)
        self.data.clear_faults()
        self.assertTrue(fault.present, "an active fault must survive a clear")
        self.data.resolve_fault(1, "pack.voltage")
        self.assertEqual(fault.status, "Latched")
        self.data.clear_faults()
        self.assertFalse(fault.present)
        self.assertIn(fault, self.data.faults, "cleared faults stay in history")

    def test_repeat_fault_counts(self):
        fault = self.data.raise_fault(1, "Test", "warning")
        self.data.resolve_fault(1)
        again = self.data.raise_fault(1, "Test", "warning")
        self.assertIs(fault, again)
        self.assertEqual(fault.count, 2)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_within_limits(self):
        for s in SETTINGS:
            if isinstance(s.default, (int, float)) and not isinstance(s.default, bool):
                self.assertGreaterEqual(s.default, s.minimum, s.key)
                self.assertLessEqual(s.default, s.maximum, s.key)
            if s.choices:
                self.assertIn(s.default, s.choices, s.key)

    def test_save_and_load(self):
        config = Config()
        config.set("charge_target", 4.1)
        self.assertTrue(config.dirty)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            config.save(path)
            self.assertFalse(config.dirty)
            other = Config()
            unknown = other.load(path)
        self.assertEqual(unknown, [])
        self.assertEqual(other["charge_target"], 4.1)
        self.assertEqual(other["cell_type"], BY_KEY["cell_type"].default)


class SimulatorTests(unittest.TestCase):
    def test_ticks_fill_every_channel(self):
        from equilibrium.bms.simulator import Simulator

        data = BmsData(PackLayout.load())
        sim = Simulator(data, Config())
        sim.start()
        sim.stop()
        sim.dropouts.clear()
        for _ in range(30):
            sim._tick()
            sim.dropouts.clear()
        missing = [cid for cid in data.channels if cid not in data.values]
        self.assertEqual(missing, [])
        self.assertAlmostEqual(data.values["cell.avg"] * 140, data.values["pack.voltage"], places=6)

    def test_commands_reply(self):
        from equilibrium.bms.simulator import Simulator

        data = BmsData(PackLayout.load())
        sim = Simulator(data, Config())
        lines = []
        sim.received.connect(lines.append)
        sim.send("help")
        sim.send("nonsense")
        self.assertTrue(any("charge start" in line for line in lines))
        self.assertTrue(lines[-1].startswith("ERR"))


class ScreenTests(unittest.TestCase):
    def test_every_screen_builds_and_refreshes(self):
        from equilibrium import theme
        from equilibrium.ui.main_window import MainWindow

        theme.apply(app)
        window = MainWindow()
        window.resize(1400, 900)
        window._connect_simulator()
        link = window.ctx.link
        link.stop()
        for _ in range(20):
            link._tick()
        for index, screen in enumerate(window.screens):
            window.show_screen(index)
            screen.refresh()
            screen.grab()  # Paints the screen offscreen
        window.ctx.plot(cell_id(1))
        window.ctx.send("faults")
        window.ctx.disconnect_link()
        self.assertFalse(window.ctx.data.connected)
        window.ctx.config.dirty = False
        window.close()


if __name__ == "__main__":
    unittest.main()
