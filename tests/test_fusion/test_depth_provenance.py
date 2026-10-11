"""A fused depth carries the side view's own status: which values were reconstructed."""

from __future__ import annotations

import numpy as np

from track2data.exporters.schema import depth_columns
from track2data.fusion.fuse import fuse
from track2data.metrics.binning import slice_psess

from .builders import make_pair, settings


def _fused(**side_updates):
    top, side, pair = make_pair(fusion=side_updates.pop("fusion", None))
    n = side.xy.shape[0]
    # the tracker's own side positions; NaN where the preprocessing later filled a gap
    side.raw_xy_rows = side.xy.copy()
    for rows, animal in side_updates.pop("interpolated", []):
        side.raw_xy_rows[rows, animal] = np.nan
    jumped = side_updates.pop("jumped", [])
    if jumped:
        side.jump_replaced = np.zeros((n, 3), dtype=bool)
        for rows, animal in jumped:
            side.jump_replaced[rows, animal] = True
    return top, side, pair, fuse(top, side, pair, same_video=False)


def test_depth_interpolated_marks_the_sides_filled_frames_for_that_fish():
    _, _, _, fused = _fused(interpolated=[(slice(10, 20), 0)])
    flag = fused.psess.depth_interpolated
    assert flag.shape == fused.psess.depth.shape and flag.dtype == bool
    expected = np.zeros_like(flag)
    expected[10:20, 0] = True
    np.testing.assert_array_equal(flag, expected)
    assert np.isfinite(fused.psess.depth[10:20, 0]).all()  # still a number, now marked


def test_depth_jump_replaced_marks_the_sides_replaced_frames():
    _, _, _, fused = _fused(jumped=[(slice(30, 35), 1)])
    flag = fused.psess.depth_jump_replaced
    expected = np.zeros_like(flag)
    expected[30:35, 1] = True
    np.testing.assert_array_equal(flag, expected)


def test_a_side_without_a_jump_mask_gives_an_all_false_flag_not_none():
    _, _, _, fused = _fused()
    assert fused.psess.depth_jump_replaced is not None
    assert not fused.psess.depth_jump_replaced.any()
    assert not fused.psess.depth_interpolated.any()


def test_the_flags_follow_the_frame_offset():
    top, side, pair = make_pair(fusion=settings(frame_offset=5))
    side.raw_xy_rows = side.xy.copy()
    side.raw_xy_rows[15, 0] = np.nan  # side row 15 is top frame 10
    fused = fuse(top, side, pair, same_video=False)
    assert fused.psess.depth_interpolated[:, 0].nonzero()[0].tolist() == [10]


def test_a_flag_is_false_where_the_depth_is_missing():
    top, side, pair = make_pair()
    side.raw_xy_rows = side.xy.copy()
    side.raw_xy_rows[3, 0] = np.nan
    side.xy[3, 0, 1] = 50.0  # filled, but outside the water column, so no depth
    fused = fuse(top, side, pair, same_video=False)
    assert np.isnan(fused.psess.depth[3, 0])
    assert not fused.psess.depth_interpolated[3, 0]


def test_separator_rows_are_false():
    top, side, pair = make_pair()
    tracked = np.ones(100, dtype=bool)
    tracked[30:70] = False
    side.tracked_mask = tracked
    side.raw_xy_rows = side.xy.copy()
    side.raw_xy_rows[:, :] = np.nan  # every tracked side frame counts as filled
    fused = fuse(top, side, pair, same_video=False)
    sep = fused.psess.separator_mask
    assert sep is not None and sep.any()
    assert not fused.psess.depth_interpolated[sep].any()
    assert fused.psess.depth_interpolated[~sep].all()


def test_slice_psess_slices_the_flags():
    _, _, _, fused = _fused(interpolated=[(slice(10, 20), 0)], jumped=[(slice(30, 35), 1)])
    window = slice_psess(fused.psess, 8, 22)
    assert window.depth_interpolated.shape == (14, 3)
    assert window.depth_interpolated[2:12, 0].all() and not window.depth_interpolated[:2].any()
    assert window.depth_jump_replaced.shape == (14, 3) and not window.depth_jump_replaced.any()


def test_the_export_columns_carry_the_flags_beside_depth():
    _, _, _, fused = _fused(interpolated=[(slice(10, 20), 0)], jumped=[(slice(30, 35), 1)])
    cols = depth_columns(fused.psess)
    assert list(cols) == [
        "depth_fraction", "depth_cm", "depth_interpolated", "depth_jump_replaced"
    ]
    assert cols["depth_interpolated"].dtype == bool
    flat = fused.psess.depth_interpolated.reshape(-1)
    np.testing.assert_array_equal(cols["depth_interpolated"], flat)
    assert cols["depth_jump_replaced"].sum() == 5


def test_a_session_without_a_depth_exports_no_flag_columns():
    top, _, _ = make_pair()
    assert depth_columns(top) == {}
