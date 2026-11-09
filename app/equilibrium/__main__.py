"""Placeholder window, so the installer has a real application to deliver."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from equilibrium import __version__, personal, splash, startup_sound


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

    # Lets CI prove that the frozen build can really start Qt and check for updates.
    if "--smoke-test" in sys.argv:
        if icon.isNull():
            return 1
        from equilibrium import update_ui  # noqa: F401
        from equilibrium_setup import core

        core._ssl_context()
        import certifi  # noqa: F401

        window.show()
        QTimer.singleShot(0, app.quit)
        return app.exec()

    startup = splash.Splash(icon, window)
    startup.show()

    sound_file = personal.asset("sound")
    if sound_file is not None:
        startup_sound.StartupSound(sound_file, app).play()

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
