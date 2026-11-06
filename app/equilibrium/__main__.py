"""Placeholder window, so the installer has a real application to deliver."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from equilibrium import __version__


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Equilibrium")
    icon = QIcon(str(Path(__file__).parent / "assets" / "icon.png"))
    app.setWindowIcon(icon)

    window = QMainWindow()
    window.setWindowTitle("Equilibrium")
    window.resize(900, 600)
    label = QLabel(f"Equilibrium {__version__}")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.setCentralWidget(label)
    window.show()

    # Lets CI prove that the frozen build can really start Qt and check for updates.
    if "--smoke-test" in sys.argv:
        if icon.isNull():
            return 1
        from equilibrium import update_ui  # noqa: F401
        from equilibrium_setup import core

        core._ssl_context()
        import certifi  # noqa: F401

        QTimer.singleShot(0, app.quit)
    elif getattr(sys, "frozen", False):
        # Source runs have no installer to update them, or the installer package on their path.
        from equilibrium import update_ui

        update_ui.install(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
