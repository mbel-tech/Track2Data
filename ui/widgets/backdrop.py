"""Load a session's backdrop image, cut to its panel when it has one.

``apply_panel`` keeps the whole-frame background image of a 'One video, two panels' session,
while every coordinate of the session is relative to the panel's top-left corner. Whatever
draws the backdrop under such coordinates has to crop it the same way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from track2data.core.models import PanelRect


def load_backdrop_image(path: Path | None, crop: PanelRect | None = None) -> QImage | None:
    """The image at *path*, or None when it is missing or unreadable.

    With *crop* the result is that rectangle of the image, clamped to the image bounds
    (x, y truncated and width, height rounded, like the panel session's video size).
    """
    if path is None or not Path(path).exists():
        return None
    image = QImage(str(path))
    if image.isNull():
        return None
    if crop is None:
        return image
    x0 = max(0, int(crop.x))
    y0 = max(0, int(crop.y))
    x1 = min(image.width(), x0 + max(1, round(crop.width)))
    y1 = min(image.height(), y0 + max(1, round(crop.height)))
    if x1 <= x0 or y1 <= y0:
        return None
    return image.copy(QRect(x0, y0, x1 - x0, y1 - y0))
