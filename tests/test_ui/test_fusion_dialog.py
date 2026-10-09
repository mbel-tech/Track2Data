"""ui/dialogs/fusion_dialog.py: defaults, sync with the water view, summary, OK state, suggest."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from tests.test_fusion.builders import make_pair, make_psess, settings
from track2data.core.models import ViewPair
from track2data.fusion import fuse
from ui.dialogs.fusion_dialog import FusionDialog
from ui.widgets.water_column_view import WaterColumnView


def _dlg(qtbot, *, pair_kw=None, same_video=False, **kw) -> FusionDialog:
    top, side, pair = make_pair(**(pair_kw or {}))
    dlg = FusionDialog(top, side, pair, same_video, **kw)
    qtbot.addWidget(dlg)
    return dlg


def _settle(d: FusionDialog) -> None:
    """Run the debounced recompute now."""
    d._refresh_now()


def _lagged_pair(lag: int):
    rng = np.random.default_rng(1)
    n = 300
    x = np.cumsum(rng.normal(size=(n, 3)), axis=0) * 3
    top_xy = np.zeros((n, 3, 2))
    top_xy[..., 0] = x
    side_xy = np.zeros((n, 3, 2))
    side_xy[..., 1] = 200.0
    side_xy[lag:, :, 0] = x[: n - lag] * 0.2  # side cm == top cm (px_per_cm 10 vs 2)
    labels = ["a", "b", "c"]
    top = make_psess("t", top_xy, labels=labels, px_per_cm=10.0)
    side = make_psess("s", side_xy, labels=labels)
    side.xy[..., 0] = side_xy[..., 0] * 5.0
    side.session.raw_xy[...] = side.xy
    pair = ViewPair(
        top_session_id="t",
        side_session_id="s",
        fish_map={k: k for k in labels},
        fusion=settings(),
    )
    return top, side, pair


def test_defaults(qtbot):
    top, side, pair = make_pair()
    pair = pair.model_copy(update={"fusion": None})
    d = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d)
    assert d._surface_spin.value() == pytest.approx(30.0)
    assert d._floor_spin.value() == pytest.approx(270.0)
    assert d._height_spin.value() == 20.0
    assert d._axis_combo.currentText() == "Top-view x"
    assert [d._axis_combo.itemText(i) for i in range(2)] == ["Top-view x", "Top-view y"]
    assert not d._flip_check.isChecked()
    assert d._offset_spin.value() == 0
    assert isinstance(d._water_view, WaterColumnView)


def test_starts_from_existing_settings(qtbot):
    fs = settings(frame_offset=3, horizontal_axis="y", flip=True, tank_height_cm=15.0)
    d = _dlg(qtbot, pair_kw={"fusion": fs})
    assert d.result_settings() == fs
    assert d._water_view.rows() == (100.0, 300.0)


def test_spin_moves_line_and_drag_moves_spin(qtbot):
    d = _dlg(qtbot)
    d._surface_spin.setValue(120.0)
    assert d._water_view.rows()[0] == pytest.approx(120.0)
    d._water_view._drag_line("floor", 250.0)
    assert d._floor_spin.value() == pytest.approx(250.0)
    assert d.result_settings().floor_row == pytest.approx(250.0)


def test_invalid_rows_disable_ok(qtbot):
    d = _dlg(qtbot)
    assert d._ok_button.isEnabled()
    d._surface_spin.setValue(d._floor_spin.value())
    _settle(d)
    assert not d._ok_button.isEnabled()
    assert "surface" in d._summary.text().lower()
    d._surface_spin.setValue(100.0)
    _settle(d)
    assert d._ok_button.isEnabled()
    d._height_spin.setValue(0.0)
    _settle(d)
    assert not d._ok_button.isEnabled()
    assert "height" in d._summary.text().lower()


def test_fuse_error_shown_and_ok_disabled(qtbot):
    d = _dlg(qtbot, pair_kw={"fps_side": 30.0})
    assert not d._ok_button.isEnabled()
    assert "frame rates differ" in d._summary.text()


def test_valid_settings_result(qtbot):
    d = _dlg(qtbot)
    d._flip_check.setChecked(True)
    d._axis_combo.setCurrentIndex(1)
    d._offset_spin.setValue(2)
    d._height_spin.setValue(25.0)
    _settle(d)
    assert d._ok_button.isEnabled()
    fs = d.result_settings()
    assert (fs.frame_offset, fs.horizontal_axis, fs.flip, fs.tank_height_cm) == (2, "y", True, 25.0)
    assert (fs.surface_row, fs.floor_row) == (100.0, 300.0)


def test_same_video_hides_offset(qtbot):
    fs = settings(frame_offset=4)
    d = _dlg(qtbot, same_video=True, pair_kw={"fusion": fs})
    assert d._offset_spin.isHidden() and d._suggest_btn.isHidden()
    assert d.result_settings().frame_offset == 0


def test_summary_numbers(qtbot):
    top, side, pair = make_pair()
    d = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d)
    rep = fuse(top, side, pair, same_video=False).report
    text = d._summary.text()
    assert f"{rep.overlap_frames}" in text
    assert "3 fish" in text
    assert f"{rep.n_outside_column}" in text
    assert f"{rep.agreement_rms_cm:.2f}" in text


def test_summary_uncalibrated_reason(qtbot):
    d = _dlg(qtbot, pair_kw={"px_per_cm": None})
    assert "top view not calibrated" in d._summary.text()


def test_suggest_offset_fills_lag(qtbot):
    top, side, pair = _lagged_pair(7)
    d = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d)
    d._suggest_btn.click()
    assert d._offset_spin.value() == 7


def test_suggest_disabled_without_top_calibration(qtbot):
    d = _dlg(qtbot, pair_kw={"px_per_cm": None})
    assert not d._suggest_btn.isEnabled()
    assert "calibrated top view" in d._suggest_btn.toolTip()
    text = d._summary.text()
    assert "Suggest offset needs a calibrated top view" in text
    assert "Calibration page" in text
    assert "Agreement not checked: top view not calibrated" in text


def test_suggest_enabled_with_top_calibration(qtbot):
    d = _dlg(qtbot)
    assert d._suggest_btn.isEnabled()
    assert "Suggest offset needs" not in d._summary.text()


def test_suggest_already_best_leaves_spin(qtbot):
    top, side, pair = _lagged_pair(7)
    d = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d)
    d._offset_spin.setValue(7)
    d._suggest_btn.click()
    assert d._offset_spin.value() == 7
    assert "already best" in d._summary.text()


def test_set_source_once(qtbot, monkeypatch, tmp_path):
    calls = []
    orig = WaterColumnView.set_source
    monkeypatch.setattr(
        WaterColumnView, "set_source", lambda self, *a: (calls.append(a), orig(self, *a))[1]
    )
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"x")
    d = _dlg(qtbot, background_path=bg)
    d._surface_spin.setValue(90.0)
    d._offset_spin.setValue(1)
    d._water_view._drag_line("floor", 200.0)
    _settle(d)
    assert len(calls) == 1
    size, background, video, tracks, crop = calls[0]
    assert size == (400.0, 300.0)
    assert background == bg
    assert video is None  # make_pair has no video file
    assert tracks is d._side.xy
    assert crop is None


def test_background_crop_reaches_the_preview(qtbot, tmp_path):
    from PySide6.QtGui import QImage

    from track2data.core.models import PanelRect

    full = QImage(800, 600, QImage.Format.Format_RGB32)
    full.fill(0x123456)
    bg = tmp_path / "bg.png"
    assert full.save(str(bg))
    crop = PanelRect(x=400, y=300, width=400, height=300)
    d = _dlg(qtbot, background_path=bg, background_crop=crop)
    items = d._water_view.preview._backdrop_items
    assert d._water_view.preview.backdrop_kind == "image"
    pix = items[0].pixmap()
    assert (pix.width(), pix.height()) == (400, 300)
    d2 = _dlg(qtbot, background_path=bg)
    pix = d2._water_view.preview._backdrop_items[0].pixmap()
    assert (pix.width(), pix.height()) == (800, 600)


def test_row_spin_maxima_follow_frame_height(qtbot):
    d = _dlg(qtbot)
    assert d._surface_spin.maximum() == 300.0 and d._floor_spin.maximum() == 300.0
    d._floor_spin.setValue(5000.0)
    assert d._floor_spin.value() == 300.0
    top, side, pair = make_pair()
    side.session.video.height_px = 0
    side.session.video.width_px = 0
    d2 = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d2)
    assert d2._floor_spin.maximum() >= 1_000_000.0


def test_edits_are_debounced(qtbot, monkeypatch):
    d = _dlg(qtbot)
    calls = []
    orig = FusionDialog._fuse_pair
    monkeypatch.setattr(
        FusionDialog, "_fuse_pair", lambda self, fs: (calls.append(1), orig(self, fs))[1]
    )
    for v in (110.0, 111.0, 112.0, 113.0):
        d._surface_spin.setValue(v)
    assert calls == []
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    qtbot.wait(200)
    assert len(calls) == 1


def test_accept_flushes_pending_refresh(qtbot):
    d = _dlg(qtbot)
    d._surface_spin.setValue(d._floor_spin.value())  # invalid, summary not yet recomputed
    d.accept()
    assert d.result() == 0  # refused: the pending recompute found the settings invalid


def test_unknown_video_size_does_not_raise(qtbot):
    top, side, pair = make_pair()
    side.session.video.height_px = 0
    side.session.video.width_px = 0
    pair = pair.model_copy(update={"fusion": None})
    d = FusionDialog(top, side, pair, False)
    qtbot.addWidget(d)
    assert d._surface_spin.value() == pytest.approx(10.0)
    assert d._floor_spin.value() == pytest.approx(90.0)
    d._water_view._drag_line("floor", 500.0)
