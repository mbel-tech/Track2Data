"""ui/widgets/backdrop.py: the backdrop image, cut to a session's panel."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage

from track2data.core.models import PanelRect
from ui.widgets.backdrop import load_backdrop_image


@pytest.fixture
def frame_png(qtbot, tmp_path: Path) -> Path:
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    image.setPixelColor(100, 50, QColor(255, 0, 0))
    path = tmp_path / "bg.png"
    assert image.save(str(path))
    return path


def test_crop_returns_the_panel_rectangle(frame_png: Path) -> None:
    image = load_backdrop_image(frame_png, PanelRect(x=100, y=50, width=200, height=100))
    assert (image.width(), image.height()) == (200, 100)
    assert image.pixelColor(0, 0) == QColor(255, 0, 0)


def test_no_crop_returns_the_whole_image(frame_png: Path) -> None:
    image = load_backdrop_image(frame_png)
    assert (image.width(), image.height()) == (400, 200)


def test_missing_file_is_none(tmp_path: Path) -> None:
    assert load_backdrop_image(tmp_path / "nope.png") is None
    assert load_backdrop_image(None) is None


def test_crop_beyond_the_image_is_clamped(frame_png: Path) -> None:
    image = load_backdrop_image(frame_png, PanelRect(x=300, y=150, width=500, height=500))
    assert (image.width(), image.height()) == (100, 50)
    assert load_backdrop_image(frame_png, PanelRect(x=900, y=0, width=10, height=10)) is None
