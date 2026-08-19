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

    app = QApplication(sys.argv)
    app.setApplicationName("Track2Data")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("Track2Data")
    app.setOrganizationDomain("track2data.io")

    # Import here so PySide6 is only required at runtime, not at import time.
    from app.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
