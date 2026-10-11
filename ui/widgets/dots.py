"""Traffic-light dots for table cells.

A dot is an icon rather than coloured text, so a selected row's text colour can
never hide it, and the colours follow the active theme.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from app.theme import theme

_LIGHT = {"good": "#00a3d1", "check": "#e0a92a", "review": "#f03500"}
_DARK = {"good": "#00bbf0", "check": "#fdb44b", "review": "#f03500"}


def level_colour(level: str) -> str:
    """Hex colour for good / check / review in the current theme (grey for anything else)."""
    palette = _DARK if theme.name == "dark" else _LIGHT
    return palette.get(level, "#88949b")


def dot_icon(colour: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pixmap)


def level_icon(level: str) -> QIcon:
    return dot_icon(level_colour(level))
