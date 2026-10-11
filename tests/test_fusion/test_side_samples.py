"""The share of side samples outside the water column must not depend on top-view gaps."""

from __future__ import annotations

import logging

import numpy as np

from track2data.fusion.fuse import fuse
from track2data.metrics import get
from track2data.metrics.binning import slice_psess

from .builders import make_pair


def _scene(top_gaps: int = 0, outside: int = 10):
    top, side, pair = make_pair()
    side.xy[:outside, 0, 1] = 50.0  # above the surface: genuinely outside the column
    if top_gaps:
        top.xy[-top_gaps:, 0] = np.nan  # the top view lost this fish for its last frames
    return top, side, pair, fuse(top, side, pair, same_video=False)


def test_side_valid_marks_every_frame_the_side_view_had_a_position():
    _, _, _, fused = _scene(top_gaps=50)
    valid = fused.psess.depth_side_valid
    assert valid.shape == fused.psess.depth.shape and valid.dtype == bool
    assert valid[:, 0].all()  # side tracked the fish throughout, top gaps notwithstanding
    assert int(np.isfinite(fused.psess.depth[:, 0]).sum()) == 40  # 100 - 50 gaps - 10 outside


def test_frac_outside_does_not_grow_with_top_view_gaps():
    shares = []
    for gaps in (0, 50):
        *_, fused = _scene(top_gaps=gaps)
        row = get("IL-15")().compute(fused.psess).iloc[0]
        shares.append(row["frac_outside_extent"])
    assert shares[0] == shares[1] == 0.1


def test_a_side_sample_with_no_horizontal_coordinate_still_gives_a_depth():
    top, side, pair = make_pair()
    side.xy[5, 0, 0] = np.nan  # x lost, y kept: depth needs only y
    fused = fuse(top, side, pair, same_video=False)
    assert np.isfinite(fused.psess.depth[5, 0])
    assert fused.psess.depth_side_valid[5, 0]


def test_separator_rows_are_not_side_samples():
    top, side, pair = make_pair()
    tracked = np.ones(100, dtype=bool)
    tracked[30:70] = False
    side.tracked_mask = tracked
    fused = fuse(top, side, pair, same_video=False)
    sep = fused.psess.separator_mask
    assert sep is not None and not fused.psess.depth_side_valid[sep].any()


def test_slice_psess_slices_the_side_samples():
    *_, fused = _scene()
    window = slice_psess(fused.psess, 10, 30)
    assert window.depth_side_valid.shape == (20, 3)


def test_the_warning_does_not_blame_the_fusion_settings_alone(caplog):
    *_, fused = _scene(outside=30)
    with caplog.at_level(logging.WARNING):
        get("IL-15")().compute(fused.psess)
    assert "outside the water column" in caplog.text
    assert "check the fusion settings." not in caplog.text
    assert "side" in caplog.text
