"""ui/widgets/panel_preview.py: backdrop fallback and the two panel rectangles."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from track2data.core.models import PanelRect
from ui.widgets import panel_preview as pp
from ui.widgets.panel_preview import PanelPreview

SIZE = (40.0, 20.0)


@pytest.fixture
def view(qtbot) -> PanelPreview:
    widget = PanelPreview()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def bg_png(qtbot, tmp_path: Path) -> Path:
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    path = tmp_path / "bg.png"
    assert image.save(str(path))
    return path


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    return path


def _tracks(n_frames: int = 10, n_animals: int = 2) -> np.ndarray:
    tr = np.zeros((n_frames, n_animals, 2))
    tr[:, :, 0] = np.arange(n_frames)[:, None]
    tr[:, :, 1] = np.arange(n_animals)[None, :] * 5
    return tr


def test_background_image_wins(view, bg_png, video, monkeypatch) -> None:
    monkeypatch.setattr(pp, "extract_frame", lambda p, i=0: bytes(40 * 20 * 3))
    view.set_source(SIZE, bg_png, video, _tracks())
    assert view.backdrop_kind == "image"
    assert any(isinstance(i, QGraphicsPixmapItem) for i in view.scene().items())


def test_video_frame_when_no_background(view, video, monkeypatch) -> None:
    monkeypatch.setattr(pp, "extract_frame", lambda p, i=0: bytes(40 * 20 * 3))
    view.set_source(SIZE, None, video, _tracks())
    assert view.backdrop_kind == "video"


def test_missing_background_file_falls_to_video(view, tmp_path, video, monkeypatch) -> None:
    monkeypatch.setattr(pp, "extract_frame", lambda p, i=0: bytes(40 * 20 * 3))
    view.set_source(SIZE, tmp_path / "gone.png", video, None)
    assert view.backdrop_kind == "video"


def test_wrong_length_frame_falls_to_tracks(view, video, monkeypatch) -> None:
    monkeypatch.setattr(pp, "extract_frame", lambda p, i=0: bytes(10))
    view.set_source(SIZE, None, video, _tracks())
    assert view.backdrop_kind == "tracks"


def test_none_frame_falls_to_tracks(view, video, monkeypatch) -> None:
    monkeypatch.setattr(pp, "extract_frame", lambda p, i=0: None)
    view.set_source(SIZE, None, video, _tracks())
    assert view.backdrop_kind == "tracks"


def test_raising_extract_falls_to_tracks(view, video, monkeypatch) -> None:
    def boom(p, i=0):
        raise RuntimeError("no codec")

    monkeypatch.setattr(pp, "extract_frame", boom)
    view.set_source(SIZE, None, video, _tracks())
    assert view.backdrop_kind == "tracks"


def test_missing_video_is_not_read(view, tmp_path, monkeypatch) -> None:
    def boom(p, i=0):
        raise AssertionError("must not be called")

    monkeypatch.setattr(pp, "extract_frame", boom)
    view.set_source(SIZE, None, tmp_path / "nope.mp4", _tracks())
    assert view.backdrop_kind == "tracks"


def test_tracks_one_item_per_animal(view) -> None:
    view.set_source(SIZE, None, None, _tracks(n_frames=10, n_animals=3))
    assert view.backdrop_kind == "tracks"
    assert len(view.scene().items()) == 3


def test_tracks_point_count_is_capped(view) -> None:
    tr = np.random.default_rng(0).uniform(0, 20, (50000, 2, 2))
    view.set_source(SIZE, None, None, tr)
    items = [i for i in view.scene().items() if isinstance(i, QGraphicsPathItem)]
    assert len(items) == 2
    # a rectangle point is 5 path elements
    points = sum(i.path().elementCount() for i in items) // 5
    assert 0 < points <= 3000 + 10


def test_no_files_with_tracks_is_tracks(view, tmp_path) -> None:
    view.set_source(SIZE, tmp_path / "no.png", tmp_path / "no.mp4", _tracks())
    assert view.backdrop_kind == "tracks"


@pytest.mark.parametrize("size", [(float("nan"), 20.0), (float("inf"), 20.0), (0.0, 0.0)])
def test_bad_frame_size_does_not_raise(view, size) -> None:
    view.set_source(size, None, None, None)
    assert view.backdrop_kind == "none"
    assert view.scene().sceneRect().width() > 0


@pytest.mark.parametrize(
    "tracks",
    [np.zeros((5, 2, 1)), np.array([[["a", "b"]]]), np.zeros((5, 0, 2)), np.zeros((5, 2)), "x"],
)
def test_malformed_tracks_do_not_raise(view, tracks) -> None:
    view.set_source(SIZE, None, None, tracks)
    assert view.backdrop_kind == "none"
    assert not view.scene().items()


def test_nan_only_tracks_still_tracks_kind(view) -> None:
    view.set_source(SIZE, None, None, np.full((5, 2, 2), np.nan))
    assert view.backdrop_kind == "tracks"


def test_nothing_gives_blank_scene_of_frame_size(view) -> None:
    view.set_source(SIZE, None, None, None)
    assert view.backdrop_kind == "none"
    rect = view.scene().sceneRect()
    assert (rect.width(), rect.height()) == SIZE


def test_set_rects_draws_and_clears(view) -> None:
    view.set_source(SIZE, None, None, None)
    view.set_rects(
        PanelRect(x=0, y=0, width=20, height=10), PanelRect(x=0, y=10, width=20, height=10)
    )
    assert view.rect_item_count == 2
    rects = [i for i in view.scene().items() if isinstance(i, QGraphicsRectItem)]
    assert len(rects) == 2
    assert rects[0].pen().color() != rects[1].pen().color()
    view.set_rects(PanelRect(x=0, y=0, width=20, height=10), None)
    assert view.rect_item_count == 1
    view.set_rects(None, None)
    assert view.rect_item_count == 0
    assert not [
        i
        for i in view.scene().items()
        if isinstance(i, QGraphicsRectItem | QGraphicsSimpleTextItem)
    ]


def test_set_rects_labels_present(view) -> None:
    view.set_source(SIZE, None, None, None)
    view.set_rects(
        PanelRect(x=0, y=0, width=20, height=10), PanelRect(x=0, y=10, width=20, height=10)
    )
    texts = {i.text() for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem)}
    assert texts == {"Top view", "Side view"}


def test_rects_survive_a_new_source(view) -> None:
    view.set_source(SIZE, None, None, None)
    view.set_rects(PanelRect(x=0, y=0, width=20, height=10), None)
    view.set_source(SIZE, None, None, _tracks())
    assert view.rect_item_count == 1
