"""Entry point for both the setup wizard and the installed uninstaller."""

import sys
from pathlib import Path


def main() -> int:
    if "--smoke-test" in sys.argv:
        # Lets CI prove that the frozen build bundled tkinter and CA certificates.
        import tkinter  # noqa: F401

        from equilibrium_setup import core

        core._ssl_context()
        import certifi  # noqa: F401

        return 0

    if sys.platform == "win32":
        # Keeps text sharp on high-DPI displays rather than letting Windows blur it.
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    from equilibrium_setup import wizard

    if "--uninstall" in sys.argv:
        return wizard.run_uninstall(Path(sys.executable).resolve().parent)
    return wizard.run_wizard()


if __name__ == "__main__":
    sys.exit(main())
