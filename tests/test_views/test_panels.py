import numpy as np
import pandas as pd
import pytest

from track2data.core.models import PanelRect, Session, VideoInfo
from track2data.views.panels import (
    LOW_COVERAGE,
    MIN_COVERAGE,
    apply_panel,
    panel_coverage,
    preset_rects,
)

PANEL = PanelRect(x=100, y=50, width=200, height=100)


def _session(raw_xy, stable=True, w=400, h=200, **kw) -> Session:
    raw_xy = np.asarray(raw_xy, dtype=float)
    n = raw_xy.shape[1]
    return Session(
        session_id="s",
        folder="/tmp/s",
        reader="test",
        video=VideoInfo(path=None, fps=25.0, n_frames=raw_xy.shape[0], width_px=w, height_px=h),
        n_animals=n,
        trajectory_variant="with_gaps",
        has_stable_identities=stable,
        raw_xy=raw_xy,
        **kw,
    )


def test_constants():
    assert MIN_COVERAGE == 0.5
    assert LOW_COVERAGE == 0.9


def test_shift_and_size():
    s = _session([[[150, 80]], [[160, 90]]])
    out = apply_panel(s, PANEL)
    np.testing.assert_allclose(out.raw_xy[0, 0], [50, 30])
    assert out.video.width_px == 200 and out.video.height_px == 100
    assert out.video.fps == 25.0
    # input untouched
    np.testing.assert_allclose(s.raw_xy[0, 0], [150, 80])
    assert s.video.width_px == 400


def test_filter_animals_together():
    inside, outside = [150, 80], [10, 10]
    raw = [[inside, outside, inside], [inside, outside, outside]]
    s = _session(
        raw,
        identities_labels=["a", "b", "c"],
        identities_colors=["#111111", "#222222", "#333333"],
        id_probabilities=np.array([[1.0, 0.5, 0.2], [0.9, 0.4, 0.3]]),
        body_length_px=np.array([10.0, 20.0, 30.0]),
    )
    cov = panel_coverage(s, PANEL)
    assert [c.label for c in cov] == ["a", "b", "c"]
    assert [c.share_inside for c in cov] == [1.0, 0.0, 0.5]
    assert [c.n_valid for c in cov] == [2, 2, 2]
    out = apply_panel(s, PANEL)
    assert out.n_animals == 2
    assert out.raw_xy.shape == (2, 2, 2)
    assert out.identities_labels == ["a", "c"]
    assert out.identities_colors == ["#111111", "#333333"]
    np.testing.assert_allclose(out.body_length_px, [10.0, 30.0])
    np.testing.assert_allclose(out.id_probabilities, [[1.0, 0.2], [0.9, 0.3]])
    # the kept animal "c" has a second position outside -> NaN
    assert np.isnan(out.raw_xy[1, 1]).all()
    assert not np.isnan(out.raw_xy[0, 1]).any()


def test_no_valid_positions_is_dropped():
    s = _session([[[150, 80], [np.nan, np.nan]]] * 3)
    cov = panel_coverage(s, PANEL)
    assert cov[1].share_inside == 0.0 and cov[1].n_valid == 0
    assert apply_panel(s, PANEL).n_animals == 1


def test_identity_free_keeps_partial_drops_empty():
    inside, outside = [150, 80], [10, 10]
    raw = [[inside, inside, outside], [outside, inside, outside]]
    out = apply_panel(_session(raw, stable=False), PANEL)
    # slot 0 has 1 of 2 inside, slot 1 has 2 of 2, slot 2 none -> dropped
    assert out.n_animals == 2
    assert np.isnan(out.raw_xy[1, 0]).all()
    assert not np.isnan(out.raw_xy[0, 0]).any()


def test_identity_free_has_no_fifty_percent_rule():
    inside, outside = [150, 80], [10, 10]
    raw = [[inside]] + [[outside]] * 9
    assert apply_panel(_session(raw, stable=False), PANEL).n_animals == 1
    assert apply_panel(_session(raw, stable=True), PANEL).n_animals == 0


def test_setup_points_and_roi_shift():
    s = _session(
        [[[150, 80]]],
        setup_points={"a": [150.0, 80.0], "note": "x", "n": 3},
        roi_list=[
            {
                "sign": "+",
                "vertices": [(100.0, 50.0), (300.0, 50.0), (300.0, 150.0)],
                "raw": "+ Polygon [[100, 50]]",
            }
        ],
    )
    out = apply_panel(s, PANEL)
    assert out.setup_points == {"a": [50.0, 30.0], "note": "x", "n": 3}
    assert out.roi_list[0]["vertices"] == [(0.0, 0.0), (200.0, 0.0), (200.0, 100.0)]
    assert out.roi_list[0]["sign"] == "+"
    assert s.roi_list[0]["vertices"][0] == (100.0, 50.0)
    assert s.setup_points["a"] == [150.0, 80.0]


def test_per_animal_extras_dropped():
    s = _session(
        [[[150, 80]]],
        bbox_table=pd.DataFrame({"a": [1]}),
        bbox_summary={"k": 1},
        identities_groups={"g": ["a"]},
        blob_body_length_source_file="list_of_blobs.pickle",
        fragments={"x": 1},
    )
    out = apply_panel(s, PANEL)
    assert out.bbox_table is None and out.bbox_summary is None
    assert out.identities_groups is None
    assert out.blob_body_length_source_file is None
    assert out.fragments is None


def test_panel_outside_or_larger_raises():
    s = _session([[[150, 80]]])
    with pytest.raises(ValueError):
        apply_panel(s, PanelRect(x=300, y=0, width=200, height=100))
    with pytest.raises(ValueError):
        apply_panel(s, PanelRect(x=0, y=0, width=500, height=100))
    with pytest.raises(ValueError):
        panel_coverage(s, PanelRect(x=0, y=0, width=100, height=300))


def test_unknown_video_size_skips_check():
    s = _session([[[150, 80]]], w=0, h=0)
    out = apply_panel(s, PanelRect(x=0, y=0, width=500, height=300))
    assert out.video.width_px == 500


def test_preset_rects():
    a, b = PanelRect(x=0, y=0, width=200, height=200), PanelRect(x=200, y=0, width=200, height=200)
    assert preset_rects("left_right", 400, 200, 0.5, True) == (a, b)
    assert preset_rects("left_right", 400, 200, 0.5, False) == (b, a)
    top, side = preset_rects("top_bottom", 400, 200)
    assert top == PanelRect(x=0, y=0, width=400, height=100)
    assert side == PanelRect(x=0, y=100, width=400, height=100)
    top, side = preset_rects("left_right", 400, 200, 0.3, True)
    assert (top.width, side.width, side.x) == (120, 280, 120)


def test_keypoints_filtered_and_shifted():
    from track2data.core.models import KeypointData, KeypointSelection

    inside, outside = [150, 80], [10, 10]
    s = _session([[inside, outside]] * 2)
    xy = np.full((2, 2, 1, 2), 150.0)
    xy[:, 1] = 10.0
    kp = KeypointData(
        xy=xy,
        names=["nose"],
        confidence=np.ones((2, 2, 1)),
        selection=KeypointSelection(keypoint="nose", chosen_by="user", coverage=1.0),
    )
    out = apply_panel(s.model_copy(update={"keypoints": kp}), PANEL)
    assert out.keypoints.xy.shape == (2, 1, 1, 2)
    assert out.keypoints.xy[0, 0, 0, 0] == 50.0
    assert out.keypoints.confidence.shape == (2, 1, 1)
