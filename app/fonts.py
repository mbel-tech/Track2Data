"""Register the bundled UI fonts (Atkinson Hyperlegible, IBM Plex Mono) with Qt.

Both are SIL OFL fonts and live in ``app/resources/fonts``. The stylesheets name
them first and fall back to system fonts, so an empty folder still renders.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).parent / "resources" / "fonts"
_SUFFIXES = {".ttf", ".otf"}


def load_bundled_fonts(directory: Path = FONT_DIR) -> list[str]:
    """Add every font file in *directory*; returns the families that registered."""
    families: list[str] = []
    if not directory.is_dir():
        return families
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in _SUFFIXES:
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    return families
