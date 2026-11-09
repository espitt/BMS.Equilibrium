"""General settings: pack, CAN and precharge configuration, firmware, and config files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QListWidget, QMessageBox, QScrollArea, QWidget

from equilibrium import __version__, theme
from equilibrium.ui.context import AppContext
from equilibrium.ui.screens.base import Screen
from equilibrium.ui.widgets import Card, SettingsForm, button, label, screen_layout, write_button


class SettingsScreen(Screen):
    title = "General settings"
    nav_label = "Settings"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        box, self.header = screen_layout(body, "General settings")

        grid = QGridLayout()
        grid.setSpacing(12)
        box.addLayout(grid)

        pack = Card("Pack")
        pack.box.addWidget(SettingsForm(ctx.config, ["cell_type", "cell_capacity_ah", "parallel_count"]))
        layout = ctx.layout
        pack.box.addWidget(label(
            f"{layout.cell_count} cells in series · {layout.segments} segments of {layout.cells_per_segment} · "
            f"{len(layout.thermistors)} thermistors · {layout.board_count} slave boards", "faint", wrap=True))
        pack.box.addWidget(label("Series count and thermistor positions come from the pack layout file.", "faint",
                                 wrap=True))
        grid.addWidget(pack, 0, 0)

        can = Card("CAN bus and USB")
        can.box.addWidget(SettingsForm(ctx.config, ["can_baud", "can_base_id", "telemetry_hz"]))
        grid.addWidget(can, 0, 1)

        precharge = Card("Precharge")
        precharge.box.addWidget(SettingsForm(ctx.config, ["precharge_target_pct", "precharge_timeout_ms"]))
        grid.addWidget(precharge, 1, 0)

        about = Card("This app")
        about.box.addWidget(label(f"Equilibrium {__version__}", "muted"))
        about.box.addWidget(label("App updates are separate from BMS firmware: use Help > Check for Updates.",
                                  "faint", wrap=True))
        grid.addWidget(about, 1, 1)

        firmware = Card("BMS firmware")
        self.device = label("", "muted", wrap=True)
        self.device.setTextFormat(Qt.TextFormat.RichText)
        firmware.box.addWidget(self.device)
        firmware.box.addWidget(label("Firmware is the program on the BMS. It is separate from the configuration.",
                                     "faint", wrap=True))
        self.releases = QListWidget()
        self.releases.setMaximumHeight(130)
        firmware.box.addWidget(self.releases)
        row = QHBoxLayout()
        row.addWidget(button("Check GitHub for releases", self._check_releases))
        self.program = button("Program selected…", self._program, "primary")
        self.program.setEnabled(False)
        row.addWidget(self.program)
        row.addStretch(1)
        firmware.box.addLayout(row)
        self.releases.itemSelectionChanged.connect(
            lambda: self.program.setEnabled(bool(self.releases.selectedItems()) and ctx.connected))
        grid.addWidget(firmware, 2, 0, 1, 2)
        box.addStretch(1)

        panel = self.panel
        panel.section("Configuration file")
        self.file_label = panel.add(label("", "muted", wrap=True))
        file_row = QWidget()
        file_box = QGridLayout(file_row)
        file_box.setContentsMargins(0, 0, 0, 0)
        file_box.addWidget(button("New", self._new), 0, 0)
        file_box.addWidget(button("Open…", self.open_file), 0, 1)
        file_box.addWidget(button("Save", self._save), 1, 0)
        file_box.addWidget(button("Save as…", self._save_as), 1, 1)
        panel.add(file_row)
        panel.section("BMS")
        self.read = panel.add(button("Read from BMS", self._read_from_bms,
                                     tooltip="Replace these settings with the ones on the BMS"))
        panel.add(write_button(ctx))
        panel.note("Settings on other screens (voltage, temperature and charging limits) are part of the same "
                   "configuration and are saved with it.")
        panel.finish()

        ctx.config.fileChanged.connect(self._file_changed)
        ctx.linkChanged.connect(self._link_changed)
        ctx.data.connectionChanged.connect(self.refresh)
        self._file_changed()
        self._link_changed()

    # Config files

    def _folder(self) -> str:
        path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / "Equilibrium"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _confirm_discard(self) -> bool:
        if not self.ctx.config.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Discard the unsaved configuration changes?")
        return answer == QMessageBox.StandardButton.Yes

    def _new(self) -> None:
        if self._confirm_discard():
            self.ctx.config.reset()

    def open_file(self) -> bool:
        if not self._confirm_discard():
            return False
        path, _ = QFileDialog.getOpenFileName(self, "Open configuration", self._folder(),
                                              "Equilibrium configuration (*.json)")
        if not path:
            return False
        try:
            unknown = self.ctx.config.load(Path(path))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not open", f"{path}\n\n{error}")
            return False
        if unknown:
            QMessageBox.information(self, "Some settings ignored",
                                    "These settings are not known to this version and were ignored:\n\n"
                                    + "\n".join(unknown))
        return True

    def _save(self) -> None:
        if self.ctx.config.path is None:
            self._save_as()
        else:
            self._write(self.ctx.config.path)

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save configuration", str(Path(self._folder()) / "config.json"),
                                              "Equilibrium configuration (*.json)")
        if path:
            self._write(Path(path))

    def _write(self, path: Path) -> None:
        try:
            self.ctx.config.save(path)
            self.ctx.message.emit(f"Saved {path.name}")
        except OSError as error:
            QMessageBox.warning(self, "Could not save", f"{path}\n\n{error}")

    def _file_changed(self) -> None:
        cfg = self.ctx.config
        name = cfg.path.name if cfg.path else "Untitled"
        self.file_label.setText(f"{name}{' (unsaved changes)' if cfg.dirty else ''}")

    # BMS

    def _link_changed(self) -> None:
        self.read.setEnabled(self.ctx.connected)
        self.program.setEnabled(bool(self.releases.selectedItems()) and self.ctx.connected)

    def _read_from_bms(self) -> None:
        QMessageBox.information(self, "Not available yet",
                                "Reading the configuration from the BMS needs the serial protocol, "
                                "which is not defined yet.")

    def _check_releases(self) -> None:
        self.releases.clear()
        self.releases.addItem("Firmware releases will be listed here once the firmware repository is set.")
        self.releases.item(0).setForeground(theme.color(theme.TEXT_FAINT))
        self.releases.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _program(self) -> None:
        QMessageBox.information(
            self, "Not available yet",
            "Programming will check that the BMS is safe to program (TS off, no faults), reboot it into its "
            "bootloader, send and verify the firmware, then offer to re-apply your saved configuration.\n\n"
            "It needs the bootloader protocol, which is not defined yet.")

    def refresh(self) -> None:
        data = self.ctx.data
        if data.device:
            self.device.setText("<br>".join(f"{k}: <span style='color:{theme.TEXT}'>{v}</span>"
                                            for k, v in data.device.items()))
        else:
            self.device.setText("Connect to a BMS to see its firmware version.")
