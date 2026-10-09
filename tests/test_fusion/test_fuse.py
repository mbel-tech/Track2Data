import numpy as np
import pytest

from track2data.core.models import ViewPair
from track2data.fusion.fuse import FusionError, fuse

from .builders import SIDE_Y, make_pair, make_psess, settings, side_xy, top_xy


def test_depth_exact_and_top_order_with_reversed_side():
    top, side, pair = make_pair(reverse_side=True)
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.fused_labels == ["a", "b", "c"]
    for k, want in enumerate((0.25, 0.5, 0.75)):
        np.testing.assert_allclose(fused.psess.depth[:, k], want)
    np.testing.assert_allclose(fused.psess.xy, top.xy)
    assert fused.report.overlap_frames == 100


def test_offset_shifts_side_rows():
    top, side, pair = make_pair(fusion=settings(frame_offset=5))
    side.xy[:, 0, 1] = 100 + np.arange(100)  # depth = row / 200
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.overlap_frames == 95
    np.testing.assert_allclose(fused.psess.depth[:, 0], (5 + np.arange(95)) / 200)
    np.testing.assert_array_equal(fused.psess.frame_index, np.arange(95))
    np.testing.assert_allclose(fused.psess.xy, top.xy[:95])


def test_same_video_ignores_offset():
    top, side, pair = make_pair(fusion=settings(frame_offset=7))
    fused = fuse(top, side, pair, same_video=True)
    assert fused.report.overlap_frames == 100


def test_outside_column_is_nan_and_counted():
    top, side, pair = make_pair()
    side.xy[0, 0, 1] = 50.0
    side.xy[1, 1, 1] = 350.0
    side.xy[2, 2, 1] = 99.0
    side.xy[3, 0, 1] = 301.0
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.n_outside_column == 4
    assert np.isnan(fused.psess.depth[0, 0]) and np.isnan(fused.psess.depth[3, 0])
    assert int(np.isnan(fused.psess.depth).sum()) == 4


def test_boundary_values_kept():
    top, side, pair = make_pair()
    side.xy[0, 0, 1] = 100.0
    side.xy[0, 1, 1] = 300.0
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.depth[0, 0] == 0.0 and fused.psess.depth[0, 1] == 1.0
    assert fused.report.n_outside_column == 0


def test_nan_in_either_view_is_nan_not_outside():
    top, side, pair = make_pair()
    top.xy[3, 0] = np.nan
    side.xy[4, 1] = np.nan
    fused = fuse(top, side, pair, same_video=False)
    assert np.isnan(fused.psess.depth[3, 0]) and np.isnan(fused.psess.depth[4, 1])
    assert int(np.isnan(fused.psess.depth).sum()) == 2
    assert fused.report.n_outside_column == 0


def test_unmatched_fish_dropped():
    top, side, pair = make_pair()
    pair = ViewPair(
        top_session_id="t", side_session_id="s", fish_map={"a": "a", "c": "c"}, fusion=settings()
    )
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.fused_labels == ["a", "c"]
    assert fused.report.unmatched_top == ["b"]
    assert fused.report.unmatched_side == ["b"]
    assert fused.psess.xy.shape[1] == 2
    assert fused.psess.session.n_animals == 2
    assert fused.psess.session.identities_labels == ["a", "c"]
    np.testing.assert_allclose(fused.psess.depth[:, 1], 0.75)
    np.testing.assert_allclose(fused.psess.session.raw_xy, top.xy[:, [0, 2]])
    np.testing.assert_allclose(fused.psess.session.body_length_px, [10.0, 30.0])
    assert fused.psess.kinematics.speed_px_s.shape == (100, 2)


def test_separator_rows_not_fused():
    top, side, pair = make_pair()
    sep = np.zeros(100, dtype=bool)
    sep[[10, 11]] = True
    top.separator_mask = sep
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.overlap_frames == 98
    assert 10 not in fused.psess.frame_index and 11 not in fused.psess.frame_index
    assert fused.psess.separator_mask is None and fused.psess.tracked_mask is None


def test_side_separator_and_untracked_rows_not_fused():
    top, side, pair = make_pair()
    sep = np.zeros(100, dtype=bool)
    sep[20] = True
    side.separator_mask = sep
    tracked = np.ones(100, dtype=bool)
    tracked[30] = False
    top.tracked_mask = tracked
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.overlap_frames == 98
    assert 20 not in fused.psess.frame_index and 30 not in fused.psess.frame_index


def test_true_frames_used_not_row_numbers():
    top = make_psess("t", top_xy(10), labels=["a", "b", "c"], frame_index=np.arange(50, 60))
    side = make_psess("s", side_xy(10), labels=["a", "b", "c"], frame_index=np.arange(52, 62))
    pair = make_pair()[2]
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.overlap_frames == 8
    np.testing.assert_array_equal(fused.psess.frame_index, np.arange(52, 60))


@pytest.mark.parametrize(
    "case,message",
    [
        ("no_settings", "no fusion settings for this pair"),
        ("empty_map", "no fish are matched"),
        ("identity_free", "cannot match fish: this session has no stable identities"),
        ("fps", "frame rates differ: 25 vs 30 fps"),
        ("no_overlap", "no shared frames between the two views"),
        ("unknown_side", "unknown side fish: z"),
    ],
)
def test_fusion_errors(case, message):
    kw = {}
    if case == "fps":
        kw["fps_side"] = 30.0
    top, side, pair = make_pair(**kw)
    if case == "no_settings":
        pair = pair.model_copy(update={"fusion": None})
    elif case == "empty_map":
        pair = pair.model_copy(update={"fish_map": {}})
    elif case == "identity_free":
        top.session.has_stable_identities = False
    elif case == "no_overlap":
        pair = pair.model_copy(update={"fusion": settings(frame_offset=1000)})
    elif case == "unknown_side":
        pair = pair.model_copy(update={"fish_map": {"a": "z", "b": "b", "c": "c"}})
    with pytest.raises(FusionError) as exc:
        fuse(top, side, pair, same_video=False)
    assert message in str(exc.value)


def test_ids_and_shapes():
    top, side, pair = make_pair()
    fused = fuse(top, side, pair, same_video=False)
    assert fused.session_id == "t+s"
    assert fused.psess.session_id == "t+s"
    assert fused.psess.depth.shape == fused.psess.xy.shape[:2]
    assert fused.report.agreement_rms_cm is None and fused.report.agreement_skipped is None
    # the inputs are untouched
    assert top.session.session_id == "t" and top.depth is None
    assert SIDE_Y[0] == side.xy[0, 0, 1]
