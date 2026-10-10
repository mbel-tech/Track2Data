"""ui/widgets/water_column_view.py: side-view preview with draggable surface and floor lines."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from ui.widgets.water_column_view import WaterColumnView

SIZE = (200.0, 500.0)


@pytest.fixture
def view(qtbot) -> WaterColumnView:
    widget = WaterColumnView()
    qtbot.addWidget(widget)
    widget.resize(300, 600)
    widget.show()
    widget.set_source(SIZE, None, None, None)
    return widget


def _line_y(item) -> float:
    return item.scenePos().y() + item.line().y1()


def test_no_rows_no_lines(view):
    assert view.line_count == 0
    assert view.rows() == (None, None)


def test_set_rows_shows_lines_without_signal(view, qtbot):
    with qtbot.assertNotEmitted(view.rowsChanged):
        view.set_rows(100, 400)
    assert view.line_count == 2
    assert view.rows() == (100.0, 400.0)
    assert _line_y(view._surface_line) == pytest.approx(100)
    assert _line_y(view._floor_line) == pytest.approx(400)


def test_drag_floor_emits(view, qtbot):
    view.set_rows(100, 400)
    with qtbot.waitSignal(view.rowsChanged) as sig:
        view._drag_line("floor", 450)
    assert sig.args == [100.0, 450.0]
    assert view.rows() == (100.0, 450.0)
    assert _line_y(view._floor_line) == pytest.approx(450)


def test_surface_cannot_cross_floor(view):
    view.set_rows(100, 400)
    view._drag_line("surface", 480)
    s, f = view.rows()
    assert f == 400.0 and 399 <= s < 400
    view._drag_line("floor", 10)
    s, f = view.rows()
    assert s < f and f - s < 2


def test_rows_clamped_to_frame(view):
    view.set_rows(-20, 900)
    assert view.rows() == (0.0, 500.0)
    view._drag_line("floor", 9999)
    assert view.rows()[1] == 500.0
    view._drag_line("surface", -5)
    assert view.rows()[0] == 0.0


@pytest.mark.parametrize("size", [(float("nan"), float("nan")), (0.0, 0.0), (-1.0, 5.0)])
def test_set_source_bad_size_keeps_lines(view, size, tmp_path):
    view.set_rows(10, 60)
    view.set_source(size, tmp_path / "missing.png", None, None)
    assert view.line_count == 2
    assert view.rows() == (10.0, 60.0)


def test_set_source_keeps_lines_in_scene(view):
    view.set_rows(100, 400)
    view.set_source((200.0, 300.0), None, None, None)
    scene = view.preview.scene()
    assert view._surface_line.scene() is scene
    assert view._floor_line.scene() is scene
    assert view.rows() == (100.0, 300.0)  # floor clamped to the new frame height
    view.set_source(SIZE, None, None, None)
    assert view.rows() == (100.0, 400.0)


def test_clear_rows(view):
    view.set_rows(100, 400)
    view.set_rows(None, None)
    assert view.line_count == 0
    assert view.rows() == (None, None)
    view.set_rows(float("nan"), 200)
    assert view.rows() == (None, 200.0) and view.line_count == 1


def test_labels(view):
    view.set_rows(100, 400)
    assert view._surface_line.label_text() == "Surface"
    assert view._floor_line.label_text() == "Floor"


def test_real_mouse_drag(view, qtbot):
    view.set_rows(100, 400)
    pv = view.preview
    vp = pv.viewport()
    x = pv.mapFromScene(100, 400).x()
    y0 = pv.mapFromScene(100, 400).y()
    y1 = pv.mapFromScene(100, 450).y()
    with qtbot.waitSignal(view.rowsChanged) as sig:
        QTest.mousePress(
            vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y0)
        )
        QTest.mouseMove(vp, QPoint(x, y1))
        QTest.mouseRelease(
            vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y1)
        )
    assert sig.args[0] == 100.0
    assert sig.args[1] == pytest.approx(450, abs=2)
