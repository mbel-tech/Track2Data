"""
Track2Data desktop application entry point.

Run:
    python -m app.main
    # or, once installed with [ui] extra:
    track2data-gui
"""

from __future__ import annotations

import logging
import sys
import traceback
from types import TracebackType

logger = logging.getLogger("track2data.app")

#: True while the error dialog is showing (see _excepthook).
_dialog_open = False


def _show_error_dialog(text: str) -> None:
    """Tell the user an unexpected error happened (no-op without a QApplication)."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Unexpected error")
    box.setText(
        "Track2Data hit an unexpected error. The action you took may not have finished; "
        "your saved project is unchanged. Click Show Details for the error."
    )
    box.setDetailedText(text)
    box.exec()


def _excepthook(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.error("Unhandled exception", exc_info=(exc_type, exc, tb))
    global _dialog_open
    if _dialog_open:
        # Raised again while the dialog's own event loop runs (a timer or paint slot that
        # keeps failing): log only, or dialogs would stack without end.
        return
    _dialog_open = True
    try:
        _show_error_dialog("".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:  # the dialog itself must never raise out of the hook
        logger.exception("Could not show the error dialog")
    finally:
        _dialog_open = False


def install_excepthook() -> None:
    """Log and show exceptions that would otherwise vanish.

    PySide6 hands an exception raised in a slot to ``sys.excepthook`` and carries on; in a
    windowed build (no console) the default hook prints to nowhere, so the user saw nothing.
    """
    sys.excepthook = _excepthook


def main() -> None:
    if "--self-check" in sys.argv[1:]:
        # Headless: used by packaging/smoke_test.py on the frozen binary.
        from app import selfcheck

        sys.exit(selfcheck.run_self_check())

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
    install_excepthook()
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
