"""ui/dialogs/panel_dialog.py: presets, spin boxes, coverage table and the OK state."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from track2data.core.models import PanelRect, Session, VideoInfo
from ui.dialogs.panel_dialog import PanelDialog
from ui.widgets.panel_preview import PanelPreview


def _session(raw_xy, w=400, h=200, labels=None, stable=True) -> Session:
    raw_xy = np.asarray(raw_xy, dtype=float)
    return Session(
        session_id="s",
        folder="/tmp/s",
        reader="test",
        video=VideoInfo(path=None, fps=25.0, n_frames=raw_xy.shape[0], width_px=w, height_px=h),
        n_animals=raw_xy.shape[1],
        trajectory_variant="with_gaps",
        has_stable_identities=stable,
        raw_xy=raw_xy,
        identities_labels=labels,
    )


def _two_clusters() -> Session:
    # fish 0 and 1 left of x=200, fish 2 and 3 right of it; 10 frames
    xy = np.zeros((10, 4, 2))
    xy[:, 0] = [50, 50]
    xy[:, 1] = [100, 100]
    xy[:, 2] = [300, 50]
    xy[:, 3] = [350, 150]
    return _session(xy)


def _dlg(qtbot, session=None, mode="split", **kw) -> PanelDialog:
    d = PanelDialog(session or _two_clusters(), mode, **kw)
    qtbot.addWidget(d)
    return d


def _rects(d):
    return d.result_rects()


def test_default_state(qtbot):
    d = _dlg(qtbot)
    assert d._preset_combo.currentText() == "Left | Right"
    assert [d._preset_combo.itemText(i) for i in range(3)] == [
        "Left | Right",
        "Top | Bottom",
        "Custom",
    ]
    assert d._split_slider.value() == 50
    assert (d._split_slider.minimum(), d._split_slider.maximum()) == (5, 95)
    top, side = d.result_rects()
    assert top == PanelRect(x=0, y=0, width=200, height=200)
    assert side == PanelRect(x=200, y=0, width=200, height=200)
    assert isinstance(d._preview, PanelPreview)


def test_slider(qtbot):
    d = _dlg(qtbot)
    d._split_slider.setValue(30)
    top, side = d.result_rects()
    assert top.width == 120 and side.width == 280 and side.x == 120


def test_top_bottom_preset(qtbot):
    d = _dlg(qtbot)
    d._preset_combo.setCurrentText("Top | Bottom")
    top, side = d.result_rects()
    assert top == PanelRect(x=0, y=0, width=400, height=100)
    assert side == PanelRect(x=0, y=100, width=400, height=100)


def test_spin_edit_sets_custom_without_refill(qtbot):
    d = _dlg(qtbot)
    d._top_w.setValue(150)
    assert d._preset_combo.currentText() == "Custom"
    assert d._top_w.value() == 150
    assert d._side_x.value() == 200  # not refilled


def test_first_view_swap(qtbot):
    d = _dlg(qtbot)
    assert [d._first_view_combo.itemText(i) for i in range(2)] == ["Top view", "Side view"]
    d._first_view_combo.setCurrentIndex(1)
    top, side = d.result_rects()
    assert side.x == 0 and top.x == 200


def test_table_and_flags(qtbot):
    xy = np.full((10, 4, 2), np.nan)
    xy[:, 0] = [50, 50]  # all in left
    xy[:8, 1] = [50, 50]  # 80% left
    xy[8:, 1] = [300, 50]
    xy[:4, 2] = [50, 50]  # 40% left, 60% right -> right, flagged "low"
    xy[4:, 2] = [300, 50]
    # fish 3 has no data
    d = _dlg(qtbot, _session(xy, labels=["a", "b", "c", "d"]))
    t = d._coverage_table
    assert [t.horizontalHeaderItem(i).text() for i in range(4)] == [
        "Fish",
        "Panel",
        "Inside",
        "Flag",
    ]
    assert t.rowCount() == 4
    row = lambda r: [t.item(r, c).text() for c in range(4)]  # noqa: E731
    assert row(0) == ["a", "Top view", "100%", ""]
    assert row(1) == ["b", "Top view", "80%", "low"]
    assert row(2) == ["c", "Side view", "60%", "low"]
    assert row(3) == ["d", "—", "—", "no data"]


def test_left_out_flag(qtbot):
    xy = np.full((10, 2, 2), np.nan)
    xy[:, 0] = [50, 50]
    xy[:4, 1] = [50, 50]  # 40% in left
    xy[4:, 1] = [500, 50]  # 60% outside the frame (neither panel)
    d = _dlg(qtbot, _session(xy))
    t = d._coverage_table
    assert t.item(1, 1).text() == "Top view"
    assert t.item(1, 2).text() == "40%"
    assert t.item(1, 3).text() == "left out"


def test_ok_enabled_default(qtbot):
    assert _dlg(qtbot)._ok_button.isEnabled()


def test_ok_disabled_when_panel_outside_frame(qtbot):
    d = _dlg(qtbot)
    d._side_w.setValue(300)  # 200 + 300 > 400
    assert not d._ok_button.isEnabled()
    d._side_w.setValue(200)
    assert d._ok_button.isEnabled()


def test_ok_disabled_when_panel_keeps_no_animal(qtbot):
    d = _dlg(qtbot)
    d._side_x.setValue(380)
    d._side_w.setValue(20)
    d._side_y.setValue(190)
    d._side_h.setValue(10)
    assert not d._ok_button.isEnabled()


def test_single_mode(qtbot):
    d = _dlg(qtbot, mode="single")
    d.show()
    assert d._top_w.isVisible()
    assert not d._side_w.isVisible()
    assert not d._coverage_table.isVisible()
    assert not d._preset_combo.isVisible()
    assert not d._split_slider.isVisible()
    assert not d._first_view_combo.isVisible()
    assert d._ok_button.isEnabled()
    d._top_x.setValue(0)
    d._top_w.setValue(100)
    d._top_h.setValue(100)
    assert d.result_rect() == PanelRect(x=0, y=0, width=100, height=100)
    assert d._ok_button.isEnabled()
    d._top_w.setValue(500)  # outside the frame
    assert not d._ok_button.isEnabled()


def test_single_mode_no_animal(qtbot):
    d = _dlg(qtbot, mode="single")
    d._top_x.setValue(380)
    d._top_y.setValue(190)
    d._top_w.setValue(10)
    d._top_h.setValue(10)
    assert not d._ok_button.isEnabled()


def test_result_rects_match_spin_boxes(qtbot):
    d = _dlg(qtbot)
    d._top_x.setValue(1)
    top, side = d.result_rects()
    assert top.x == 1
    assert (side.x, side.y, side.width, side.height) == (
        d._side_x.value(),
        d._side_y.value(),
        d._side_w.value(),
        d._side_h.value(),
    )


def test_zero_animals(qtbot):
    for mode in ("split", "single"):
        d = _dlg(qtbot, _session(np.zeros((5, 0, 2))), mode=mode)
        assert d._coverage_table.rowCount() == 0
        assert not d._ok_button.isEnabled()
        d._split_slider.setValue(40)
        d._top_w.setValue(50)


def test_identity_free_session(qtbot):
    xy = np.full((6, 1, 2), np.nan)
    xy[:3, 0] = [50, 50]
    xy[3:, 0] = [300, 50]
    d = _dlg(qtbot, _session(xy, stable=False))
    assert d._coverage_table.rowCount() == 1


def test_no_video_size(qtbot):
    d = _dlg(qtbot, _session(_two_clusters().raw_xy, w=0, h=0))
    top, side = d.result_rects()
    assert top.width > 0 and side.width > 0
    d._split_slider.setValue(30)
    d._top_w.setValue(10)
    assert d._coverage_table.rowCount() == 4
    d2 = _dlg(qtbot, _session(np.zeros((5, 0, 2)), w=0, h=0))
    assert d2._coverage_table.rowCount() == 0


def test_set_source_called_once(qtbot, monkeypatch):
    calls = []
    orig = PanelPreview.set_source

    def spy(self, *a, **k):
        calls.append(a)
        return orig(self, *a, **k)

    monkeypatch.setattr(PanelPreview, "set_source", spy)
    d = _dlg(qtbot)
    d._split_slider.setValue(30)
    d._preset_combo.setCurrentText("Top | Bottom")
    d._top_w.setValue(100)
    d._first_view_combo.setCurrentIndex(1)
    assert len(calls) == 1
    assert calls[0][0] == (400, 200)


def test_preview_rects_follow_edits(qtbot):
    d = _dlg(qtbot)
    assert d._preview.rect_item_count == 2
    d = _dlg(qtbot, mode="single")
    assert d._preview.rect_item_count == 1
