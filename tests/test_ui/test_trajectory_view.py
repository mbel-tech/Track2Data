"""GUI-02: trajectory viewer widget."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt

pytest.importorskip("PySide6")

from track2data.core.models import ROI
from ui.widgets.trajectory_view import TrajectoryView, occupancy_heatmap, split_on_nan


def _line_xy(n=100, animals=2) -> np.ndarray:
    xy = np.zeros((n, animals, 2))
    xy[:, 0, 0] = np.linspace(10, 190, n)
    xy[:, 0, 1] = 50
    xy[:, 1, 0] = 100
    xy[:, 1, 1] = np.linspace(10, 190, n)
    return xy


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_split_on_nan_breaks_the_path_at_missing_frames() -> None:
    pts = np.array([[0, 0], [1, 1], [np.nan, np.nan], [3, 3], [4, 4], [5, 5]], float)
    segs = split_on_nan(pts)
    assert [len(s) for s in segs] == [2, 3]


def test_split_on_nan_all_missing_gives_nothing() -> None:
    assert split_on_nan(np.full((4, 2), np.nan)) == []


def test_heatmap_peaks_where_the_animal_sat() -> None:
    xy = np.full((200, 1, 2), np.nan)
    xy[:, 0, 0] = 80.0
    xy[:, 0, 1] = 40.0
    heat = occupancy_heatmap(xy, width=160, height=80, cell_px=8, sigma_cells=0.5)
    assert heat.max() == pytest.approx(1.0)
    row, col = np.unravel_index(np.argmax(heat), heat.shape)
    assert col == 80 // 8 and row == 40 // 8


def test_heatmap_ignores_nan_and_out_of_bounds() -> None:
    xy = np.full((10, 1, 2), np.nan)
    xy[0, 0] = (1000, 1000)
    heat = occupancy_heatmap(xy, width=100, height=100)
    assert heat.max() == 0.0


# ── widget ───────────────────────────────────────────────────────────────────


def _view(qtbot, xy=None, raw=None, rois=()) -> TrajectoryView:
    v = TrajectoryView()
    qtbot.addWidget(v)
    xy = _line_xy() if xy is None else xy
    v.set_data(raw if raw is not None else xy, xy, fps=25.0, rois=rois, size=(200, 200))
    return v


def test_set_data_exposes_frame_count_and_starts_at_zero(qtbot) -> None:
    v = _view(qtbot)
    assert v.n_frames == 100
    assert v.current_frame == 0


def test_trails_grow_with_the_frame(qtbot) -> None:
    v = _view(qtbot)
    v.set_trail_length(1000)
    v.set_frame(0)
    first = v.trail_point_count()
    v.set_frame(60)
    assert v.trail_point_count() > first


def test_trail_length_limits_the_visible_history(qtbot) -> None:
    v = _view(qtbot)
    v.set_trail_length(10)
    v.set_frame(80)
    assert v.trail_point_count() <= 2 * 11  # two animals, trail+current frame


def test_one_trail_and_one_marker_per_animal(qtbot) -> None:
    v = _view(qtbot)
    v.set_frame(50)
    assert v.marker_count() == 2
    assert v.trail_item_count() == 2


def test_source_both_draws_raw_and_processed(qtbot) -> None:
    xy = _line_xy()
    raw = xy + 3.0
    v = _view(qtbot, xy=xy, raw=raw)
    v.set_frame(50)
    v.set_source("processed")
    n_proc = v.trail_item_count()
    v.set_source("both")
    assert v.trail_item_count() == 2 * n_proc
    with pytest.raises(ValueError):
        v.set_source("nonsense")


def test_marker_is_skipped_for_a_missing_position(qtbot) -> None:
    xy = _line_xy()
    xy[50, 1] = np.nan
    v = _view(qtbot, xy=xy)
    v.set_frame(50)
    assert v.marker_count() == 1


def test_zone_overlay_can_be_toggled(qtbot) -> None:
    rois = [ROI(name="a", vertices=[(0, 0), (50, 0), (50, 50)])]
    v = _view(qtbot, rois=rois)
    assert v.zone_item_count() == 1
    v.set_show_zones(False)
    assert v.zone_item_count() == 0


def test_heatmap_toggle(qtbot) -> None:
    v = _view(qtbot)
    assert not v.heatmap_visible()
    v.set_heatmap(True)
    assert v.heatmap_visible()
    v.set_heatmap(False)
    assert not v.heatmap_visible()


def test_set_frame_is_clamped_and_emits(qtbot) -> None:
    v = _view(qtbot)
    with qtbot.waitSignal(v.frameChanged) as sig:
        v.set_frame(10_000)
    assert v.current_frame == 99
    assert sig.args == [99]
    v.set_frame(-5)
    assert v.current_frame == 0


def test_empty_view_is_safe(qtbot) -> None:
    v = TrajectoryView()
    qtbot.addWidget(v)
    v.set_frame(3)
    assert v.n_frames == 0 and v.trail_item_count() == 0


def test_set_highlight_thickens_one_animal(qtbot) -> None:
    xy = np.zeros((100, 4, 2))
    for a in range(4):
        xy[:, a, 0] = np.linspace(10, 190, 100)
        xy[:, a, 1] = 20 + 40 * a
    view = TrajectoryView()
    qtbot.addWidget(view)
    view.set_data(xy, xy, 30.0)
    view.set_frame(50)
    assert view.highlighted_animal is None

    def trails():
        """Pen (width, alpha) of each trail, in animal order, plus marker radii."""
        paths = [i for i in view.scene().items(order=Qt.SortOrder.AscendingOrder)
                 if hasattr(i, "path") and i.zValue() == 2]
        dots = [i for i in view.scene().items(order=Qt.SortOrder.AscendingOrder)
                if i.zValue() == 3]
        return (
            [(i.pen().widthF(), i.pen().color().alphaF()) for i in paths],
            [d.rect().width() for d in dots],
        )

    base_pens, base_dots = trails()
    assert len(set(base_pens)) == 1 and len(set(base_dots)) == 1
    view.set_highlight(2)
    assert view.highlighted_animal == 2
    pens, dots = trails()
    # Items are ordered by y here: animal index == position in the list.
    ys = sorted(range(4), key=lambda a: a)
    assert pens[2][0] >= 2 * max(pens[a][0] for a in ys if a != 2)
    assert dots[2] > max(dots[a] for a in ys if a != 2)
    assert all(pens[a][1] < pens[2][1] for a in ys if a != 2)
    view.set_highlight(99)  # out of range: nothing highlighted, no crash
    view.set_highlight(None)
    assert view.highlighted_animal is None
    assert trails() == (base_pens, base_dots)


def test_raw_trails_dimmed_when_highlighting(qtbot) -> None:
    view = TrajectoryView()
    qtbot.addWidget(view)
    view.set_data(_line_xy(animals=2), _line_xy(animals=2), 30.0)
    view.set_source("raw")
    view.set_frame(50)
    view.set_highlight(0)
    alphas = sorted(
        i.pen().color().alphaF() for i in view.scene().items()
        if hasattr(i, "path") and i.zValue() == 2
    )
    assert alphas[0] < alphas[1]


def test_clear_drops_loaded_data(qtbot) -> None:
    view = TrajectoryView()
    qtbot.addWidget(view)
    view.set_data(_line_xy(), _line_xy(), 30.0)
    view.clear()
    assert view.n_frames == 0 and view.trail_item_count() == 0


def test_set_data_crops_the_backdrop_to_the_panel(qtbot, tmp_path) -> None:
    from PySide6.QtGui import QColor, QImage

    from track2data.core.models import PanelRect

    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    path = tmp_path / "bg.png"
    assert image.save(str(path))
    view = TrajectoryView()
    qtbot.addWidget(view)
    xy = _line_xy()
    view.set_data(
        xy, xy, 30.0, background_path=path, crop=PanelRect(x=100, y=50, width=200, height=100)
    )
    rect = view._gscene.sceneRect()
    assert (rect.width(), rect.height()) == (200, 100)
    view.set_data(xy, xy, 30.0, background_path=path)
    assert view._gscene.sceneRect().width() == 400
