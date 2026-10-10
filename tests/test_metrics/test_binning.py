"""Timepoint binning: windows by true video time, whole-session-resolved config."""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    PreprocessReport,
    Session,
    VideoInfo,
)
from track2data.metrics.binning import bin_windows, slice_psess


def _psess(n_frames=100, n_animals=2, fps=10.0, intervals=None, zones=False):
    xy = np.zeros((n_frames, n_animals, 2))
    xy[:, 0, 0] = np.arange(n_frames) * 5.0
    xy[:, 1, 1] = np.arange(n_frames) * 3.0
    sess = Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="t",
        video=VideoInfo(fps=fps, n_frames=n_frames, width_px=500, height_px=500),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        tracking_intervals=intervals,
    )
    speed = np.full((n_frames, n_animals), 50.0)
    kin = KinematicsArrays(speed, np.zeros_like(speed), np.zeros_like(speed))
    main = None
    if zones:
        main = np.full((n_frames, n_animals), "", dtype=object)
        main[: n_frames // 2, 0] = "A"
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kin, report=PreprocessReport(), main_zone=main
    )


# ── bin_windows ──────────────────────────────────────────────────────────────


def test_even_bins() -> None:
    # 100 frames at 10 fps = 10 s; 5 s bins
    w = bin_windows(_psess(), bin_seconds=5.0)
    assert [(x.index, x.start_row, x.stop_row) for x in w] == [(0, 0, 50), (1, 50, 100)]
    assert [(x.start_s, x.end_s) for x in w] == [(0.0, 5.0), (5.0, 10.0)]


def test_partial_last_bin_is_kept_with_its_true_end() -> None:
    w = bin_windows(_psess(n_frames=70), bin_seconds=5.0)
    assert [(x.start_row, x.stop_row) for x in w] == [(0, 50), (50, 70)]
    assert w[-1].end_s == pytest.approx(7.0)  # data ends at 7 s, not at the nominal 10 s


def test_bins_follow_true_video_time_with_a_tracking_interval_offset() -> None:
    # array row 0 is video frame 100 (10 s); 5 s bins -> first bin index is 2
    w = bin_windows(_psess(n_frames=50, intervals=[(100, 150)]), bin_seconds=5.0)
    assert [x.index for x in w] == [2]
    assert (w[0].start_row, w[0].stop_row) == (0, 50)
    assert w[0].start_s == pytest.approx(10.0)


def test_gap_between_intervals_skips_empty_bins() -> None:
    # 20 frames at 0-20, 20 frames at 200-220 (20 s later); 5 s bins
    w = bin_windows(_psess(n_frames=40, intervals=[(0, 20), (200, 220)]), bin_seconds=5.0)
    assert [x.index for x in w] == [0, 4]
    assert [(x.start_row, x.stop_row) for x in w] == [(0, 20), (20, 40)]


def test_invalid_interval_mapping_falls_back_to_array_position() -> None:
    w = bin_windows(_psess(n_frames=100, intervals=[(0, 30)]), bin_seconds=5.0)  # 30 != 100
    assert [(x.index, x.start_row, x.stop_row) for x in w] == [(0, 0, 50), (1, 50, 100)]


def test_windows_tile_every_row_exactly_once() -> None:
    w = bin_windows(_psess(n_frames=97), bin_seconds=3.3)
    assert w[0].start_row == 0 and w[-1].stop_row == 97
    assert all(a.stop_row == b.start_row for a, b in itertools.pairwise(w))


def test_non_positive_bin_length_is_rejected() -> None:
    with pytest.raises(ValueError):
        bin_windows(_psess(), bin_seconds=0)


# ── slice_psess ──────────────────────────────────────────────────────────────


def test_slice_psess_slices_every_per_frame_array() -> None:
    p = _psess(zones=True)
    s = slice_psess(p, 10, 30)
    assert s.n_frames == 20 and s.n_animals == 2
    assert s.kinematics.speed_px_s.shape == (20, 2)
    assert s.main_zone.shape == (20, 2) and s.sec_zone is None
    assert s.xy[0, 0, 0] == 50.0  # row 10
    assert s.fps == p.fps and s.session_id == p.session_id
    assert p.n_frames == 100  # original untouched


def test_slice_psess_slices_depth() -> None:
    p = _psess()
    p.depth = np.tile(np.arange(100.0)[:, None], (1, 2))
    s = slice_psess(p, 10, 30)
    assert s.depth.shape == (20, 2)
    assert s.depth[0, 0] == 10.0
    assert _psess().depth is None and slice_psess(_psess(), 0, 5).depth is None


def test_slice_psess_keeps_depth_metadata() -> None:
    p = _psess()
    p.depth = np.zeros((100, 2))
    p.depth_height_cm = 25.0
    p.depth_outside = np.array([3, 1])
    s = slice_psess(p, 10, 30)
    assert s.depth_height_cm == 25.0
    assert s.depth_outside.tolist() == [3, 1]
