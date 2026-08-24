"""
Track2Data desktop application entry point.

Run:
    python -m app.main
    # or, once installed with [ui] extra:
    track2data-gui
"""

from __future__ import annotations

import sys


def main() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # Enable high-DPI fractional scaling (Qt 6 default is already good;
    # this is belt-and-suspenders for mixed-DPI setups).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # track2data.__version__, not app.main_window.APP_VERSION: this runs
    # before QApplication is constructed, and importing main_window here
    # would pull in the whole PySide6 widget tree earlier than needed.
    from track2data import __version__

    app = QApplication(sys.argv)
    app.setApplicationName("Track2Data")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Track2Data")
    app.setOrganizationDomain("track2data.io")

    # Import here so PySide6 is only required at runtime, not at import time.
    from app.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
