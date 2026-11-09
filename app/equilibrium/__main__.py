"""Starts the app: splash screen, update check, then the main window."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from equilibrium import splash, theme
from equilibrium.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Equilibrium")
    icon = QIcon(str(Path(__file__).parent / "assets" / "icon.png"))
    app.setWindowIcon(icon)
    theme.apply(app)

    window = MainWindow()

    # Lets CI prove that the frozen build can really start Qt and check for updates.
    if "--smoke-test" in sys.argv:
        if icon.isNull():
            return 1
        import pyqtgraph  # noqa: F401

        from equilibrium import update_ui  # noqa: F401
        from equilibrium_setup import core

        core._ssl_context()
        import certifi  # noqa: F401

        window.show()
        QTimer.singleShot(0, app.quit)
        return app.exec()

    startup = splash.Splash(icon, window)
    startup.show()

    # Source runs have no installer to update them, or the installer package on their path.
    controller = None
    if getattr(sys, "frozen", False):
        from equilibrium import update_ui

        controller = update_ui.install(window)

    if controller is None:
        startup.ready()
    else:
        # The splash stays up for the startup check. Any update prompt waits for the window.
        controller.check_finished.connect(startup.ready)
        controller.check(defer=startup.after_reveal)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
