"""Calibration ruler: click two points on a frame, enter the real length."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from ui.widgets.ruler_dialog import Ruler, RulerDialog


def test_ruler_distance_and_scale() -> None:
    r = Ruler()
    r.click(0, 0)
    assert r.distance_px() is None
    r.click(300, 400)
    assert r.distance_px() == pytest.approx(500.0)
    assert r.px_per_unit(10.0) == pytest.approx(50.0)


def test_third_click_starts_a_new_measurement() -> None:
    r = Ruler()
    r.click(0, 0)
    r.click(10, 0)
    r.click(5, 5)
    assert r.points == [(5.0, 5.0)]
    assert r.distance_px() is None


def test_scale_needs_a_positive_length_and_two_points() -> None:
    r = Ruler()
    assert r.px_per_unit(10.0) is None
    r.click(0, 0)
    r.click(10, 0)
    assert r.px_per_unit(0) is None
    assert r.px_per_unit(-1) is None


def test_zero_length_measurement_is_rejected() -> None:
    r = Ruler()
    r.click(5, 5)
    r.click(5, 5)
    assert r.px_per_unit(10.0) is None


def test_dialog_accepts_only_with_a_valid_measurement(qtbot) -> None:
    d = RulerDialog(None, (640, 480), unit_label="cm")
    qtbot.addWidget(d)
    assert not d.ok_enabled()
    d.canvas.click_at(0, 0)
    d.canvas.click_at(200, 0)
    assert not d.ok_enabled()  # length still 0
    d.length_spin.setValue(10.0)
    assert d.ok_enabled()
    assert d.px_per_unit() == pytest.approx(20.0)
    assert "20" in d.result_label.text()


def test_dialog_resets_on_third_click(qtbot) -> None:
    d = RulerDialog(None, (640, 480))
    qtbot.addWidget(d)
    d.length_spin.setValue(5.0)
    d.canvas.click_at(0, 0)
    d.canvas.click_at(100, 0)
    d.canvas.click_at(50, 50)
    assert not d.ok_enabled()
