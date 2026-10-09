"""Light / dark ("Teal Field" / graphite) theme loader.

The stylesheets live in ``app/resources/track2data-{light,dark}.qss`` and map
the design tokens onto Qt widgets through objectName / dynamic properties.
The chosen theme is remembered in QSettings; the first launch follows the
operating system.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app.fonts import load_bundled_fonts

RESOURCES = Path(__file__).parent / "resources"
THEMES = ("light", "dark")

#: Per-theme colours the custom-painted widgets (sidebar delegate, toast) need.
PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "sidebar": "#1c5866", "sideActive": "#174b57", "sideHover": "#1f6170",
        "sideSub": "#a9cdd1", "sideLocked": "#7fa8ae", "mustard": "#e8b64c",
        "mustardFg": "#2a2205", "tealText": "#1c5866",
    },
    "dark": {
        "sidebar": "#0f1315", "sideActive": "#1e272b", "sideHover": "#171d20",
        "sideSub": "#7f8b91", "sideLocked": "#4f5a60", "mustard": "#e8b64c",
        "mustardFg": "#1b1503", "tealText": "#06181b",
    },
}


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = "light"
        self._fonts_loaded = False

    @property
    def name(self) -> str:
        return self._name

    def color(self, key: str) -> QColor:
        return QColor(PALETTES[self._name][key])

    def initial(self) -> str:
        saved = QSettings().value("ui/theme", "")
        if saved in THEMES:
            return str(saved)
        app = QApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
        return "light"

    def apply(self, name: str | None = None, *, persist: bool = True) -> None:
        name = name or self.initial()
        if name not in THEMES:
            name = "light"
        app = QApplication.instance()
        if app is None:
            return
        if not self._fonts_loaded:
            load_bundled_fonts()
            self._fonts_loaded = True
        qss = (RESOURCES / f"track2data-{name}.qss").read_text(encoding="utf-8")
        qss = qss.replace(":/icons/", (RESOURCES / "icons").as_posix() + "/")
        app.setStyleSheet(qss)
        self._name = name
        if persist:
            QSettings().setValue("ui/theme", name)
        self.changed.emit(name)

    def toggle(self) -> None:
        self.apply("dark" if self._name == "light" else "light")


theme = ThemeManager()
