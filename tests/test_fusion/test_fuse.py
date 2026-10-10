import numpy as np
import pytest

from track2data.core.models import ViewPair
from track2data.fusion.fuse import FusionError, fuse

from .builders import make_pair, make_psess, settings, side_xy, top_xy


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


def test_depth_metadata_per_animal_outside_counts():
    top, side, pair = make_pair()
    side.xy[0, 0, 1] = 50.0
    side.xy[3, 0, 1] = 301.0
    side.xy[1, 2, 1] = 350.0
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.depth_height_cm == settings().tank_height_cm
    out = fused.psess.depth_outside
    assert out.shape == (3,) and out.dtype.kind == "i"
    assert out.tolist() == [2, 0, 1]
    assert int(out.sum()) == fused.report.n_outside_column == 3


def test_depth_outside_is_zeros_not_none_when_all_inside():
    top, side, pair = make_pair()
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.depth_outside.tolist() == [0, 0, 0]
    assert fused.psess.depth_height_cm == settings().tank_height_cm


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
    # the inputs are untouched
    top2, side2, _ = make_pair()
    assert top.session.session_id == "t" and top.depth is None
    np.testing.assert_array_equal(top.xy, top2.xy)
    np.testing.assert_array_equal(side.xy, side2.xy)
    np.testing.assert_array_equal(top.session.raw_xy, top2.session.raw_xy)


def test_timeline_validity_carried():
    top, side, pair = make_pair()
    top.session.tracking_intervals = [(0, 10), (20, 30)]  # does not reconcile with 100 rows
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.timeline()[1] is False
    top, side, pair = make_pair()
    top.session.tracking_intervals = [(0, 100)]
    side.session.tracking_intervals = [(0, 100)]
    assert fuse(top, side, pair, same_video=False).psess.timeline()[1] is True


def test_outside_counted_on_side_y_alone():
    top, side, pair = make_pair()
    top.xy[0, 0] = np.nan
    side.xy[1, 1, 0] = np.nan
    side.xy[0, 0, 1] = 50.0
    side.xy[1, 1, 1] = 350.0
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.n_outside_column == 2
    assert np.isnan(fused.psess.depth[0, 0]) and np.isnan(fused.psess.depth[1, 1])


def test_label_guards():
    top, side, pair = make_pair()
    top.session.identities_labels = ["a", "a", "c"]
    with pytest.raises(FusionError, match="duplicate fish labels in the top view"):
        fuse(top, side, pair, same_video=False)
    top, side, pair = make_pair()
    side.session.identities_labels = ["a", "b", "b"]
    with pytest.raises(FusionError, match="duplicate fish labels in the side view"):
        fuse(top, side, pair, same_video=False)
    top, side, pair = make_pair()
    top.session.identities_labels = ["a", "b"]
    msg = "fish labels do not match the number of animals in the top view"
    with pytest.raises(FusionError, match=msg):
        fuse(top, side, pair, same_video=False)
    top, side, pair = make_pair()
    side.session.identities_labels = ["a", "b", "c", "d"]
    msg = "fish labels do not match the number of animals in the side view"
    with pytest.raises(FusionError, match=msg):
        fuse(top, side, pair, same_video=False)


def test_unknown_top_label():
    top, side, pair = make_pair()
    pair = pair.model_copy(update={"fish_map": {"z": "a", "b": "b", "c": "c"}})
    with pytest.raises(FusionError, match="unknown top fish: z"):
        fuse(top, side, pair, same_video=False)


def test_fps_tolerance_boundary():
    top, side, pair = make_pair(fps_side=25.02)
    fuse(top, side, pair, same_video=False)
    top, side, pair = make_pair(fps_side=25.1)
    with pytest.raises(FusionError, match=r"frame rates differ: 25 vs 25\.1 fps"):
        fuse(top, side, pair, same_video=False)


def test_per_row_arrays_trimmed_together():
    top, side, pair = make_pair(fusion=settings(frame_offset=5))
    r = np.arange(100)
    top.main_zone = np.array([[f"m{i}"] * 3 for i in r], dtype=object)
    top.sec_zone = np.array([[f"s{i}"] * 3 for i in r], dtype=object)
    jump = np.zeros((100, 3), dtype=bool)
    jump[7, 1] = True
    top.jump_replaced = jump
    top.raw_xy_rows = top.xy + 0.5
    top.id_probabilities_rows = np.tile(r[:, None] / 100.0, (1, 3))
    f = fuse(top, side, pair, same_video=False).psess
    assert f.main_zone.shape == (95, 3) and f.main_zone[7, 2] == "m7"
    assert f.sec_zone.shape == (95, 3) and f.sec_zone[9, 0] == "s9"
    assert f.jump_replaced.shape == (95, 3) and f.jump_replaced[7, 1] and f.jump_replaced.sum() == 1
    assert f.raw_xy_rows.shape == (95, 3, 2)
    np.testing.assert_allclose(f.raw_xy_rows[4], top.xy[4] + 0.5)
    assert f.id_probabilities_rows.shape == (95, 3)
    assert f.id_probabilities_rows[12, 1] == pytest.approx(0.12)


def test_outside_mask_matches_counts_and_shape():
    top, side, pair = make_pair()
    side.xy[0, 0, 1] = 50.0
    side.xy[3, 0, 1] = 301.0
    side.xy[1, 2, 1] = 350.0
    fused = fuse(top, side, pair, same_video=False)
    mask = fused.psess.depth_outside_mask
    assert mask.dtype == bool and mask.shape == fused.psess.depth.shape
    np.testing.assert_array_equal(mask.sum(axis=0), fused.psess.depth_outside)
    assert mask[0, 0] and mask[3, 0] and mask[1, 2] and int(mask.sum()) == 3
    assert np.isnan(fused.psess.depth[mask]).all()


def test_outside_mask_is_all_false_not_none_when_all_inside():
    top, side, pair = make_pair()
    mask = fuse(top, side, pair, same_video=False).psess.depth_outside_mask
    assert mask is not None and not mask.any()


def test_outside_counted_per_animal_on_side_y_alone_with_top_nan():
    top, side, pair = make_pair()
    top.xy[0, 1] = np.nan  # top view lacks fish 1 on frame 0
    side.xy[0, 1, 1] = 50.0
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.depth_outside.tolist() == [0, 1, 0]
    assert fused.psess.depth_outside_mask[0, 1]
