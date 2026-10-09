"""
Tests for ui/widgets/zone_canvas.py.

PointSelector is deliberately plain Python (no Qt dependency) so its
click/selection logic is directly unit-testable without a QApplication
-- see its own docstring. ZoneCanvas (the QGraphicsView wrapper) gets a
separate, smaller set of Qt-level tests for rendering/loading, and
exposes click_at() as the same click-at-image-coordinates entry point
PointSelector uses, so tests never need to synthesize a real QMouseEvent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# PointSelector itself needs no Qt (see the module docstring), but
# ZoneCanvas below does -- gated the same way as every other file in
# tests/test_ui/, at the top, before any test function definitions.
pytest.importorskip("PySide6")

from ui.widgets.zone_canvas import PointSelector, ZoneCanvas


def test_load_setup_points_unwraps_the_real_idtrackerai_shape() -> None:
    """Real session.json setup_points look like
    {"BP1": [[303, 477]]} -- a name mapped to a *list containing one*
    [x, y] pair, not a bare [x, y] pair (verified against the real
    70-session corpus)."""
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[303, 477]], "BP2": [[1037, 497]]})

    assert selector.points() == {"BP1": (303.0, 477.0), "BP2": (1037.0, 497.0)}


def test_load_setup_points_also_accepts_a_flat_pair() -> None:
    """Defensive: hand-authored fixtures/tests elsewhere in this repo
    use a flat [x, y] pair rather than idtracker.ai's wrapped shape --
    both must work."""
    selector = PointSelector()
    selector.load_setup_points({"feeder": [12.0, 34.0]})

    assert selector.points() == {"feeder": (12.0, 34.0)}


def test_load_setup_points_none_gives_an_empty_selector() -> None:
    selector = PointSelector()
    selector.load_setup_points(None)

    assert selector.points() == {}


def test_load_setup_points_resets_prior_state() -> None:
    selector = PointSelector()
    selector.load_setup_points({"a": [[0.0, 0.0]]})
    selector.click_at(0.0, 0.0)
    assert selector.selected_names() == ["a"]

    selector.load_setup_points({"b": [[5.0, 5.0]]})

    assert selector.points() == {"b": (5.0, 5.0)}
    assert selector.selected_names() == []


def test_click_near_a_point_selects_it() -> None:
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[303, 477]]})

    hit = selector.click_at(304.0, 478.0)  # within hit radius, not exact

    assert hit == "BP1"
    assert selector.selected_names() == ["BP1"]


def test_click_far_from_any_point_with_custom_mode_off_does_nothing() -> None:
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[303, 477]]})

    hit = selector.click_at(900.0, 900.0)

    assert hit is None
    assert selector.selected_names() == []


def test_clicking_the_same_point_twice_toggles_it_off() -> None:
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[303, 477]]})

    selector.click_at(303.0, 477.0)
    selector.click_at(303.0, 477.0)

    assert selector.selected_names() == []


def test_selection_order_matches_click_order() -> None:
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]})

    selector.click_at(10.0, 10.0)  # BP3 first
    selector.click_at(0.0, 0.0)  # then BP1
    selector.click_at(10.0, 0.0)  # then BP2

    assert selector.selected_names() == ["BP3", "BP1", "BP2"]
    assert selector.selected_points() == [(10.0, 10.0), (0.0, 0.0), (10.0, 0.0)]


def test_custom_point_mode_off_ignores_empty_space_clicks() -> None:
    selector = PointSelector()
    selector.set_custom_point_mode(False)

    hit = selector.click_at(50.0, 50.0)

    assert hit is None
    assert selector.points() == {}


def test_custom_point_mode_on_adds_and_selects_a_new_point() -> None:
    selector = PointSelector()
    selector.set_custom_point_mode(True)

    hit = selector.click_at(50.0, 60.0)

    assert hit == "Custom 1"
    assert selector.points()["Custom 1"] == (50.0, 60.0)
    assert selector.selected_names() == ["Custom 1"]


def test_custom_points_are_numbered_sequentially() -> None:
    selector = PointSelector()
    selector.set_custom_point_mode(True)

    selector.click_at(1.0, 1.0)
    selector.click_at(500.0, 500.0)  # far from the first, so a new point

    assert list(selector.points().keys()) == ["Custom 1", "Custom 2"]


def test_custom_point_mode_still_toggles_existing_points_instead_of_duplicating() -> None:
    """Clicking on an already-placed point (custom or setup) toggles
    it, even while custom-point mode is on -- it must not place a
    second point on top of the first."""
    selector = PointSelector()
    selector.set_custom_point_mode(True)
    selector.click_at(50.0, 50.0)

    selector.click_at(50.0, 50.0)  # click the same spot again

    assert list(selector.points().keys()) == ["Custom 1"]
    assert selector.selected_names() == []  # toggled off


def test_clear_selection_empties_selection_but_keeps_points() -> None:
    selector = PointSelector()
    selector.load_setup_points({"BP1": [[0, 0]]})
    selector.set_custom_point_mode(True)
    selector.click_at(0.0, 0.0)
    selector.click_at(50.0, 50.0)

    selector.clear_selection()

    assert selector.selected_names() == []
    assert set(selector.points().keys()) == {"BP1", "Custom 1"}


# ── ZoneCanvas: the Qt-facing QGraphicsView wrapper ──────────────────────────


def test_canvas_click_at_delegates_to_the_selector(qtbot) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)
    canvas.load_session(None, {"BP1": [[10, 10]]})

    canvas.click_at(10.0, 10.0)

    assert canvas.selected_points() == [(10.0, 10.0)]


def test_canvas_selection_changed_signal_fires_on_click(qtbot) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)
    canvas.load_session(None, {"BP1": [[10, 10]]})

    with qtbot.waitSignal(canvas.selectionChanged, timeout=1000):
        canvas.click_at(10.0, 10.0)


def test_canvas_clear_selection_resets_and_emits(qtbot) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)
    canvas.load_session(None, {"BP1": [[10, 10]]})
    canvas.click_at(10.0, 10.0)

    with qtbot.waitSignal(canvas.selectionChanged, timeout=1000):
        canvas.clear_selection()

    assert canvas.selected_points() == []


def test_canvas_load_session_with_missing_background_path_does_not_crash(
    qtbot, tmp_path: Path
) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)

    canvas.load_session(tmp_path / "does_not_exist.png", {"BP1": [[10, 10]]})  # must not raise

    assert canvas.selected_points() == []


def test_canvas_load_session_with_a_real_background_image(qtbot, tmp_path: Path) -> None:
    from PySide6.QtGui import QImage

    png_path = tmp_path / "background.png"
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(0)
    image.save(str(png_path))

    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)

    canvas.load_session(png_path, None)  # must not raise

    assert canvas.scene().sceneRect().width() == 20


def test_canvas_set_custom_point_mode_enables_empty_space_clicks(qtbot) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)
    canvas.load_session(None, None)
    canvas.set_custom_point_mode(True)

    canvas.click_at(5.0, 5.0)

    assert canvas.selected_points() == [(5.0, 5.0)]


# ── GUI-04: undo, drag, shape tools (PointSelector, Qt-free) ─────────────────


def _custom_selector() -> PointSelector:
    s = PointSelector()
    s.set_custom_point_mode(True)
    return s


def test_undo_removes_the_last_custom_point_entirely() -> None:
    s = _custom_selector()
    s.click_at(10, 10)
    s.click_at(50, 10)
    assert s.undo() == "Custom 2"
    assert s.selected_names() == ["Custom 1"]
    assert "Custom 2" not in s.points()


def test_undo_of_a_setup_point_only_deselects_it() -> None:
    s = PointSelector()
    s.load_setup_points({"A": [[0.0, 0.0]], "B": [[100.0, 0.0]]})
    s.click_at(0, 0)
    s.click_at(100, 0)
    assert s.undo() == "B"
    assert s.selected_names() == ["A"]
    assert "B" in s.points()  # landmarks are never deleted


def test_undo_on_empty_selection_is_a_noop() -> None:
    assert PointSelector().undo() is None


def test_move_point_moves_custom_points_but_not_landmarks() -> None:
    s = PointSelector()
    s.load_setup_points({"A": [[0.0, 0.0]]})
    s.set_custom_point_mode(True)
    s.click_at(40, 40)
    assert s.move_point("Custom 1", 45.0, 50.0) is True
    assert s.points()["Custom 1"] == (45.0, 50.0)
    assert s.move_point("A", 9.0, 9.0) is False
    assert s.points()["A"] == (0.0, 0.0)


def test_add_rectangle_selects_four_corners_in_order() -> None:
    s = PointSelector()
    s.add_rectangle(10, 20, 110, 70)
    assert s.selected_points() == [(10, 20), (110, 20), (110, 70), (10, 70)]


def test_add_rectangle_normalises_reversed_corners() -> None:
    s = PointSelector()
    s.add_rectangle(110, 70, 10, 20)
    assert s.selected_points() == [(10, 20), (110, 20), (110, 70), (10, 70)]


def test_add_circle_makes_a_polygon_on_the_circle() -> None:
    import math

    s = PointSelector()
    s.add_circle(100, 100, 50, n_vertices=24)
    pts = s.selected_points()
    assert len(pts) == 24
    assert all(math.hypot(x - 100, y - 100) == pytest.approx(50.0) for x, y in pts)


def test_shape_tools_replace_a_previous_selection() -> None:
    s = PointSelector()
    s.add_rectangle(0, 0, 10, 10)
    s.add_circle(5, 5, 3, n_vertices=8)
    assert len(s.selected_points()) == 8


def test_degenerate_shapes_are_ignored() -> None:
    s = PointSelector()
    s.add_rectangle(5, 5, 5, 40)   # zero width
    s.add_circle(5, 5, 0)          # zero radius
    assert s.selected_points() == []


# ── GUI-04: ZoneCanvas rendering and tools ───────────────────────────────────


def _canvas(qtbot) -> ZoneCanvas:
    c = ZoneCanvas()
    qtbot.addWidget(c)
    c.load_session(None, None)
    return c


def test_selection_is_drawn_as_a_filled_polygon_with_edges(qtbot) -> None:
    c = _canvas(qtbot)
    c.set_custom_point_mode(True)
    c.click_at(10, 10)
    c.click_at(100, 10)
    assert c.outline_item_count() == 0 or c.polygon_item() is None  # < 3 points: no fill
    c.click_at(100, 100)
    poly = c.polygon_item()
    assert poly is not None
    assert poly.polygon().size() == 3
    assert poly.brush().color().alpha() > 0  # translucent fill


def test_two_points_draw_an_edge_but_no_fill(qtbot) -> None:
    c = _canvas(qtbot)
    c.set_custom_point_mode(True)
    c.click_at(10, 10)
    c.click_at(100, 10)
    assert c.polygon_item() is None
    assert c.outline_item_count() == 1


def test_saved_zones_are_shown_with_labels(qtbot) -> None:
    from track2data.core.models import ROI

    c = _canvas(qtbot)
    c.set_saved_zones(
        [
            ROI(name="centre", vertices=[(0, 0), (50, 0), (50, 50)]),
            ROI(name="edge", vertices=[(60, 0), (90, 0), (90, 30)]),
        ]
    )
    assert sorted(c.saved_zone_names()) == ["centre", "edge"]
    c.set_saved_zones([])
    assert c.saved_zone_names() == []


def test_saved_zones_survive_loading_another_session(qtbot) -> None:
    from track2data.core.models import ROI

    c = _canvas(qtbot)
    c.set_saved_zones([ROI(name="z", vertices=[(0, 0), (5, 0), (5, 5)])])
    c.load_session(None, None)
    assert c.saved_zone_names() == ["z"]


def test_undo_last_point_and_signal(qtbot) -> None:
    c = _canvas(qtbot)
    c.set_custom_point_mode(True)
    c.click_at(10, 10)
    c.click_at(40, 40)
    with qtbot.waitSignal(c.selectionChanged):
        c.undo_last_point()
    assert c.selected_points() == [(10.0, 10.0)]


def test_rectangle_tool_drag_creates_a_four_vertex_selection(qtbot) -> None:
    c = _canvas(qtbot)
    c.set_tool("rect")
    c.drag_shape((20, 30), (120, 90))
    assert c.selected_points() == [(20, 30), (120, 30), (120, 90), (20, 90)]


def test_circle_tool_drag_uses_centre_and_radius(qtbot) -> None:
    import math

    c = _canvas(qtbot)
    c.set_tool("circle")
    c.drag_shape((100, 100), (130, 140))  # radius 50
    pts = c.selected_points()
    assert len(pts) >= 12
    assert all(math.hypot(x - 100, y - 100) == pytest.approx(50.0) for x, y in pts)


def test_dragging_a_custom_vertex_moves_it(qtbot) -> None:
    c = _canvas(qtbot)
    c.set_custom_point_mode(True)
    for xy in [(10, 10), (100, 10), (100, 100)]:
        c.click_at(*xy)
    c.set_custom_point_mode(False)
    assert c.drag_vertex((100, 100), (120, 130)) is True
    assert (120.0, 130.0) in c.selected_points()
    assert c.drag_vertex((500, 500), (1, 1)) is False  # nothing there


def test_zoom_changes_scale_and_fit_resets_it(qtbot) -> None:
    c = _canvas(qtbot)
    c.show()
    base = c.transform().m11()
    c.zoom_by(1.25)
    assert c.transform().m11() == pytest.approx(base * 1.25)
    c.zoom_by(1 / 1.25)
    c.fit_to_view()
    assert c.transform().m11() > 0


def test_zoom_is_clamped(qtbot) -> None:
    c = _canvas(qtbot)
    for _ in range(80):
        c.zoom_by(1.5)
    assert c.transform().m11() <= 40.0
    for _ in range(200):
        c.zoom_by(0.5)
    assert c.transform().m11() >= 0.02


# ── a blank canvas is the size of the video frame ────────────────────────────


def test_canvas_without_a_background_is_sized_from_the_frame(qtbot) -> None:
    """Zones are stored in image pixels: a blank scene of any other size would make every
    vertex a coordinate in a picture that is not the video."""
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)

    canvas.load_session(None, None, frame_size=(1920, 1080))

    rect = canvas.scene().sceneRect()
    assert (rect.width(), rect.height()) == (1920, 1080)


@pytest.mark.parametrize("frame_size", [None, (0, 0), (1920, 0), (0, 1080)])
def test_canvas_keeps_the_default_scene_when_the_frame_is_unknown(qtbot, frame_size) -> None:
    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)

    canvas.load_session(None, None, frame_size=frame_size)

    rect = canvas.scene().sceneRect()
    assert (rect.width(), rect.height()) == (640, 480)


def test_canvas_background_image_wins_over_the_frame_size(qtbot, tmp_path: Path) -> None:
    from PySide6.QtGui import QImage

    png_path = tmp_path / "background.png"
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(0)
    image.save(str(png_path))

    canvas = ZoneCanvas()
    qtbot.addWidget(canvas)
    canvas.load_session(png_path, None, frame_size=(1920, 1080))

    rect = canvas.scene().sceneRect()
    assert (rect.width(), rect.height()) == (20, 10)
