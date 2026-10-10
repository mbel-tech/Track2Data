"""Timepoint binning: split a session into windows of true video time.

``MetricSelection.timepoint_minutes`` asks for one result row per
(session, animal, bin) instead of one per (session, animal). Bins are cut by
*true video time* -- the same ``time_s`` the per-frame table exports -- so a
bin boundary lines up with the data a user plots next to it. Rows are
contiguous in time, so each bin is a plain slice of every per-frame array.

Empty bins (the gap between two tracking intervals) are skipped.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from track2data.core.models import KinematicsArrays, PreprocessedSession


@dataclass(frozen=True)
class BinWindow:
    index: int       # bin number in video time: floor(time_s / bin_seconds)
    start_row: int   # first trajectory row in the bin
    stop_row: int    # one past the last row
    start_s: float   # nominal start of the bin
    end_s: float     # nominal end, clipped to where the data actually stops


def bin_windows(psess: PreprocessedSession, bin_seconds: float) -> list[BinWindow]:
    """Windows covering every row of *psess* exactly once, in time order."""
    if not bin_seconds > 0:
        raise ValueError("bin_seconds must be positive")
    n = psess.n_frames
    if n == 0:
        return []
    fps = psess.fps
    true_frames, _valid = psess.timeline()
    time_s = np.asarray(true_frames, dtype=np.float64) / fps
    bin_idx = np.floor(time_s / bin_seconds + 1e-9).astype(np.int64)
    # true_frames never decrease, so bin_idx is sorted: each bin is contiguous
    starts = np.flatnonzero(np.r_[True, np.diff(bin_idx) != 0])
    stops = np.r_[starts[1:], n]
    out: list[BinWindow] = []
    for a, b in zip(starts, stops, strict=True):
        idx = int(bin_idx[a])
        data_end = (float(true_frames[b - 1]) + 1.0) / fps
        out.append(
            BinWindow(
                index=idx,
                start_row=int(a),
                stop_row=int(b),
                start_s=idx * bin_seconds,
                end_s=min((idx + 1) * bin_seconds, data_end),
            )
        )
    return out


def slice_psess(psess: PreprocessedSession, start: int, stop: int) -> PreprocessedSession:
    """A copy of *psess* restricted to trajectory rows ``[start, stop)``.

    Metrics read only the per-frame arrays plus ``fps``/``session_id`` and the
    calibration fields, so a sliced copy is a drop-in input for ``compute()``.
    """
    kin = psess.kinematics
    frames, valid = psess.timeline()
    return dataclasses.replace(
        psess,
        # the window keeps the original video frames of its rows
        frame_index=frames[start:stop],
        timeline_valid=valid,
        jump_replaced=None if psess.jump_replaced is None else psess.jump_replaced[start:stop],
        tracked_mask=None if psess.tracked_mask is None else psess.tracked_mask[start:stop],
        separator_mask=None if psess.separator_mask is None else psess.separator_mask[start:stop],
        raw_xy_rows=None if psess.raw_xy_rows is None else psess.raw_xy_rows[start:stop],
        id_probabilities_rows=(
            None if psess.id_probabilities_rows is None else psess.id_probabilities_rows[start:stop]
        ),
        xy=psess.xy[start:stop],
        depth=None if psess.depth is None else psess.depth[start:stop],
        depth_outside_mask=(
            None if psess.depth_outside_mask is None else psess.depth_outside_mask[start:stop]
        ),
        kinematics=KinematicsArrays(
            speed_px_s=kin.speed_px_s[start:stop],
            accel_px_s2=kin.accel_px_s2[start:stop],
            heading_rad=kin.heading_rad[start:stop],
        ),
        main_zone=None if psess.main_zone is None else psess.main_zone[start:stop],
        sec_zone=None if psess.sec_zone is None else psess.sec_zone[start:stop],
    )
