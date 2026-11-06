"""Placeholder window, so the installer has a real application to deliver."""

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from equilibrium import __version__


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Equilibrium")

    window = QMainWindow()
    window.setWindowTitle("Equilibrium")
    window.resize(900, 600)
    label = QLabel(f"Equilibrium {__version__}")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.setCentralWidget(label)
    window.show()

    # Lets CI prove that the frozen build can really start Qt.
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(0, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
