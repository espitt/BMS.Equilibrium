"""The firmware release browser on the Settings screen.

Lists the releases in the firmware repository on GitHub, newest first, each with its description,
and downloads the selected one's files. GitHub is asked on worker threads, so the screens never freeze.
"""

from __future__ import annotations

import html
import threading

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from equilibrium import firmware, theme
from equilibrium.firmware import FirmwareRelease
from equilibrium.ui.context import AppContext
from equilibrium.ui.widgets import Badge, button, colored, label
from equilibrium_setup import core

TAG_ROLE = Qt.ItemDataRole.UserRole  # Tags are unique in a repository; versions might not be


def _date(release: FirmwareRelease) -> str:
    local = release.published.astimezone()
    return f"{local.day} {local:%b %Y}"


def _size(size: int) -> str:
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def plain_notes(notes: str) -> str:
    """The release description without its Markdown formatting."""
    document = QTextDocument()
    document.setMarkdown(notes)
    return document.toPlainText().strip()


class ElidedLabel(QLabel):
    """One line of text that ends in "…" when there isn't room for it all. Hovering shows it all."""

    def __init__(self, text: str, name: str = "") -> None:
        super().__init__()
        self.full = " ".join(text.split())
        if name:
            self.setObjectName(name)
        self.setToolTip(text)
        # Ignored, so the row's width decides the label's, not the length of the text.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(self.full)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, self.width()))


class ReleaseRow(QWidget):
    """One release in the list: version, date, tags and description."""

    def __init__(self, release: FirmwareRelease, installed: bool, downloaded: bool) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(8)
        version = label(release.version)
        version.setStyleSheet("font-weight: 600;")
        row.addWidget(version)
        row.addWidget(label(_date(release), "faint"))
        if installed:
            row.addWidget(self._badge("Installed", theme.TEXT))
        if release.prerelease:
            row.addWidget(self._badge("Pre-release", theme.TEXT_MUTED))
        if downloaded:
            row.addWidget(self._badge("Downloaded", theme.TEXT_MUTED))
        notes = plain_notes(release.notes)
        self.description = ElidedLabel(notes, "muted") if notes else ElidedLabel("No description", "faint")
        row.addWidget(self.description, 1)

    @staticmethod
    def _badge(text: str, hex_code: str) -> Badge:
        badge = Badge(compact=True)
        badge.set_state(text, hex_code)
        return badge


class ReleaseBrowser(QWidget):
    # Worker threads report back through these, which Qt delivers on the GUI thread.
    _listed = Signal(int, object, object, str)  # Check number, releases, downloaded tags, error ("" if none)
    _progress = Signal(int, int)  # Bytes done, bytes in all
    _downloaded = Signal(str, object)  # Tag, folder
    _download_failed = Signal(str, str)  # Tag, message

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.releases: list[FirmwareRelease] = []
        self.downloaded: set[str] = set()  # Tags whose files are all on this computer
        self.downloading: str | None = None  # The tag being downloaded
        self.programming: str | None = None  # The tag being programmed into the BMS
        self.error = ""
        self.checking = False
        self.checked = False  # The first time the browser is shown, it checks by itself
        self._check_number = 0
        self._installed: str | None = None

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        self.list = QListWidget()
        # Each row is a widget with margins of its own; the theme's item padding would squash it.
        self.list.setStyleSheet("QListWidget::item { padding: 0; }")
        self.list.setFixedHeight(180)
        self.list.itemSelectionChanged.connect(self._show_selected)
        box.addWidget(self.list)
        self.status = label("", "faint", wrap=True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.status)
        self.files = label("", "muted", wrap=True)  # The selected release's files
        self.files.setTextFormat(Qt.TextFormat.RichText)
        self.files.setOpenExternalLinks(True)
        box.addWidget(self.files)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        box.addWidget(self.progress)

        row = QHBoxLayout()
        self.check_button = button("Check for releases", self.check)
        row.addWidget(self.check_button)
        self.download_button = button("Download firmware", self._download)
        row.addWidget(self.download_button)
        self.program = button("Program…", self._program, "primary")
        row.addWidget(self.program)
        row.addStretch(1)
        box.addLayout(row)

        self._listed.connect(self._on_listed)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        self._download_failed.connect(self._on_download_failed)
        theme.signals.changed.connect(self._render)
        ctx.linkChanged.connect(self.device_changed)
        self._render()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self.checked:
            self.check()

    # Asking GitHub

    def check(self) -> None:
        """List the releases again. A check still running is overtaken: its answer is ignored."""
        self.checked = True
        self.checking = True
        self._check_number += 1
        self.check_button.setEnabled(False)
        self._render_status()
        threading.Thread(target=self._list_worker, args=(self._check_number, firmware.REPO), daemon=True).start()

    def _list_worker(self, number: int, repo: str) -> None:
        try:
            releases = firmware.list_releases(repo)
            downloaded = {r.tag for r in releases if firmware.is_downloaded(r)}
            self._listed.emit(number, releases, downloaded, "")
        except core.InstallError as error:
            self._listed.emit(number, [], set(), str(error))
        except Exception as error:  # A failed check must never disturb the app.
            self._listed.emit(number, [], set(), f"Could not list the firmware releases ({error}).")

    def _on_listed(self, number: int, releases: list, downloaded: set, error: str) -> None:
        if number != self._check_number:
            return
        self.checking = False
        self.checked = True
        self.check_button.setEnabled(True)
        self.releases = releases
        self.downloaded = downloaded
        self.error = error
        self._render()

    @property
    def busy(self) -> bool:
        return self.downloading is not None or self.programming is not None

    # Downloading

    def _download(self) -> None:
        release = self._selected()
        if release is None or self.busy:
            return
        self.downloading = release.tag
        self.progress.setRange(0, max(1, sum(f.size for f in release.files)))
        self.progress.setValue(0)
        self.progress.show()
        self._show_selected()
        threading.Thread(target=self._download_worker, args=(release,), daemon=True).start()

    def _download_worker(self, release: FirmwareRelease) -> None:
        try:
            folder = firmware.download(release, lambda done, total: self._progress.emit(done, total))
            self._downloaded.emit(release.tag, folder)
        except core.InstallError as error:
            self._download_failed.emit(release.tag, str(error))
        except Exception as error:  # A failed download must never disturb the app.
            self._download_failed.emit(release.tag, f"The download failed ({error}).")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(min(done, total))

    def _on_downloaded(self, tag: str, folder) -> None:
        self.downloading = None
        self.progress.hide()
        self.downloaded.add(tag)
        self._render()
        self.ctx.message.emit(f"Downloaded firmware {tag} to {folder}")

    def _on_download_failed(self, tag: str, message: str) -> None:
        self.downloading = None
        self.progress.hide()
        self._show_selected()
        QMessageBox.warning(self, "Download failed", message)

    # Showing the list

    def device_changed(self) -> None:
        """Redraw if the BMS reports different firmware, to move the "Installed" tag. Cheap to call often."""
        if self._installed_now() != self._installed:
            self._render()
        else:
            self._update_buttons()

    def _installed_now(self) -> str | None:
        return firmware.installed_version(self.ctx.data.device) if self.ctx.connected else None

    def _selected(self) -> FirmwareRelease | None:
        items = self.list.selectedItems()
        tag = items[0].data(TAG_ROLE) if items else None
        return next((r for r in self.releases if r.tag == tag), None)

    def _render(self) -> None:
        self._installed = self._installed_now()
        selected = self._selected()
        self.list.blockSignals(True)
        self.list.clear()
        for release in self.releases:
            item = QListWidgetItem()
            item.setData(TAG_ROLE, release.tag)
            row = ReleaseRow(release, release.version == self._installed, release.tag in self.downloaded)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            row.ensurePolished()  # Measure the tags with their style sheets, or they come out clipped.
            item.setSizeHint(row.sizeHint())
            if selected is not None and release.tag == selected.tag:
                item.setSelected(True)
        self.list.blockSignals(False)
        self._render_status()
        self._show_selected()

    def _render_status(self) -> None:
        repo = html.escape(firmware.REPO, quote=False)
        count = len(self.releases)
        if self.error:
            text = colored(html.escape(self.error, quote=False), theme.WARN)
        elif self.checking:
            text = f"Checking {repo} for releases…"
        elif not self.checked:
            text = "Check for releases to see what is on GitHub."
        elif not count:
            text = f"No firmware releases found in {repo}."
        else:
            text = f"{count} release{'s' if count != 1 else ''} in {repo}."
        self.status.setText(text)

    def _show_selected(self) -> None:
        """Say what the selected release's files are, or where they were downloaded to."""
        release = self._selected()
        if release is None:
            self.files.hide()
        elif release.tag in (self.downloading, self.programming):
            doing = "Downloading" if release.tag == self.downloading else "Programming the BMS with"
            self.files.setText(f"{doing} {html.escape(release.tag, quote=False)}…")
            self.files.show()
        elif release.tag in self.downloaded:
            folder = firmware.download_folder(release)
            link = f"<a href='{QUrl.fromLocalFile(str(folder)).toString()}'>{html.escape(str(folder), quote=False)}</a>"
            self.files.setText(f"Downloaded to {link}")
            self.files.show()
        elif release.files:
            names = ", ".join(f"{html.escape(f.name, quote=False)} ({_size(f.size)})" for f in release.files)
            self.files.setText(names)
            self.files.show()
        else:
            self.files.setText(f"No files are attached to {html.escape(release.tag, quote=False)}, so there is "
                               "nothing to download.")
            self.files.show()
        self._update_buttons()

    def _update_buttons(self) -> None:
        release = self._selected()
        downloaded = release is not None and release.tag in self.downloaded
        self.download_button.setEnabled(release is not None and bool(release.files) and not downloaded
                                        and not self.busy)
        self.program.setEnabled(downloaded and self.ctx.connected and not self.busy)
        self.check_button.setEnabled(not self.checking and self.programming is None)

    # Programming

    def _program(self) -> None:
        release = self._selected()
        if release is None or self.busy:
            return
        flash = getattr(self.ctx.link, "flash", None)
        if flash is None:
            QMessageBox.information(
                self, "Not available yet",
                "Programming this BMS needs the bootloader protocol, which is not defined yet. Until then, "
                "only the Simulated BMS can be programmed.")
            return
        if not firmware.is_downloaded(release):  # Check again: the files may have changed since.
            self.downloaded.discard(release.tag)
            self._render()
            QMessageBox.warning(self, "Program firmware",
                                "The downloaded files are missing or damaged. Download the firmware again.")
            return
        answer = QMessageBox.question(
            self, "Program firmware",
            f"Program firmware {release.version} into the BMS?\n\nKeep the BMS powered and connected until "
            "it finishes. The downloaded files are then deleted from this computer.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.programming = release.tag
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.show()
        self._show_selected()
        folder = firmware.download_folder(release)
        flash([folder / f.name for f in release.files], release.version,
              lambda fraction: self.progress.setValue(round(fraction * 1000)),
              lambda error: self._on_programmed(release, error))

    def _on_programmed(self, release: FirmwareRelease, error: str) -> None:
        self.programming = None
        self.progress.hide()
        if error:
            self._show_selected()
            QMessageBox.warning(self, "Programming failed", f"{error}\n\nThe downloaded firmware has been kept.")
            return
        self.downloaded.discard(release.tag)
        try:
            firmware.delete_download(release)
        except core.InstallError as failure:
            QMessageBox.warning(self, "Programmed", f"Firmware {release.version} was programmed.\n\n{failure}")
        self._render()
        self.ctx.message.emit(f"Programmed firmware {release.version}. Its download was deleted.")
