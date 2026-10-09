from pathlib import Path

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
        roi_mask_path=Path("/tmp/mask.png"),
        background_image_path=Path("/tmp/bg.png"),
    )
    out = apply_panel(s, PANEL)
    assert out.bbox_table is None and out.bbox_summary is None
    assert out.identities_groups is None
    assert out.fragments is None
    assert out.roi_mask_path is None
    # kept: the backdrop is cropped by its consumers; the blob lengths are filtered, not recomputed
    assert out.background_image_path == Path("/tmp/bg.png")
    assert out.blob_body_length_source_file == "list_of_blobs.pickle"


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


def test_keypoints_filtered_masked_and_shifted():
    from track2data.core.models import KeypointData, KeypointSelection

    inside, outside = [150, 80], [10, 10]
    s = _session([[inside, outside]] * 2)
    xy = np.full((2, 2, 2, 2), 150.0)
    xy[:, :, 0, 1] = 80.0
    xy[:, 1] = 10.0
    xy[1, 0, 1] = [10.0, 10.0]  # second keypoint of the kept animal leaves the panel
    kp = KeypointData(
        xy=xy,
        names=["nose", "tail"],
        confidence=np.ones((2, 2, 2)),
        selection=KeypointSelection(keypoint="nose", chosen_by="user", coverage=1.0),
    )
    out = apply_panel(s.model_copy(update={"keypoints": kp}), PANEL)
    assert out.keypoints.xy.shape == (2, 1, 2, 2)
    np.testing.assert_allclose(out.keypoints.xy[0, 0, 0], [50, 30])
    assert np.isnan(out.keypoints.xy[1, 0, 1]).all()
    assert out.keypoints.confidence[0, 0, 0] == 1.0
    assert np.isnan(out.keypoints.confidence[1, 0, 1])
    np.testing.assert_allclose(kp.xy[1, 0, 1], [10, 10])


def test_nested_setup_points_keep_shape_and_type():
    s = _session(
        [[[150, 80]]],
        setup_points={
            "BP1": [[150, 80]],
            "flat": [150, 80],
            "tup": (150.0, 80.0),
            "arr": np.array([[150.0, 80.0]]),
            "text": "hello",
            "three": [1, 2, 3],
            "names": ["a", "b"],
        },
    )
    sp = apply_panel(s, PANEL).setup_points
    assert sp["BP1"] == [[50.0, 30.0]]
    assert sp["flat"] == [50.0, 30.0]
    assert sp["tup"] == (50.0, 30.0)
    assert isinstance(sp["arr"], np.ndarray) and sp["arr"].shape == (1, 2)
    np.testing.assert_allclose(sp["arr"], [[50, 30]])
    assert sp["text"] == "hello" and sp["names"] == ["a", "b"] and sp["three"] == [1, 2, 3]
    assert s.setup_points["BP1"] == [[150, 80]]


def test_length_calibrations_shifted_nested_or_flat():
    s = _session(
        [[[150, 80]]],
        length_calibrations=[
            {"point_A": [[150, 80]], "point_B": [200, 100], "distance": 5.0},
        ],
    )
    c = apply_panel(s, PANEL).length_calibrations[0]
    assert c == {"point_A": [[50.0, 30.0]], "point_B": [100.0, 50.0], "distance": 5.0}
    assert s.length_calibrations[0]["point_A"] == [[150, 80]]


def test_roi_raw_string_regenerated():
    s = _session(
        [[[150, 80]]],
        roi_list=[
            {"sign": "-", "vertices": [(100.0, 50.0), (110.0, 50.0), (110.0, 60.0)], "raw": "old"}
        ],
    )
    roi = apply_panel(s, PANEL).roi_list[0]
    assert roi["raw"] == "- Polygon [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]"


def test_half_open_bounds():
    left, right = preset_rects("left_right", 400, 200)
    s = _session([[[200, 100]], [[0, 100]]])
    # x == 200 is on the shared line: right panel only; x == 0 is the near edge: inside left
    assert panel_coverage(s, left)[0].share_inside == 0.5
    assert panel_coverage(s, right)[0].share_inside == 0.5
    lo = apply_panel(s, left)
    ro = apply_panel(s, right)
    assert np.isnan(lo.raw_xy[0, 0]).all() and not np.isnan(lo.raw_xy[1, 0]).any()
    np.testing.assert_allclose(ro.raw_xy[0, 0], [0, 100])
    assert np.isnan(ro.raw_xy[1, 0]).all()
    # far video edge x == 400 belongs to no panel
    s2 = _session([[[400, 100]]])
    assert panel_coverage(s2, right)[0].share_inside == 0.0


def test_zero_kept_animals():
    s = _session([[[10, 10]]] * 3)
    assert panel_coverage(s, PANEL)[0].share_inside == 0.0
    out = apply_panel(s, PANEL)
    assert out.n_animals == 0 and out.raw_xy.shape == (3, 0, 2)


def test_mismatched_per_animal_data_is_dropped():
    inside = [150, 80]
    s = _session(
        [[inside, inside]] * 2,
        identities_labels=["a"],
        identities_colors=["#111111"],
        body_length_px=np.array([1.0]),
        id_probabilities=np.ones((2, 1)),
    )
    out = apply_panel(s, PANEL)
    assert out.n_animals == 2
    assert out.identities_labels is None and out.identities_colors is None
    assert out.body_length_px is None and out.id_probabilities is None
