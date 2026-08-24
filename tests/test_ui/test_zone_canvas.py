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
