"""Put a session stored as tracking intervals onto real elapsed time before preprocessing.

idtracker.ai can track only some stretches of a video, and its trajectory array then holds just
those rows (rows 0-9 = frames 0-9, rows 10-19 = frames 1000-1009). Every temporal step -- gap
filling, smoothing, differentiation, jump detection -- assumes adjacent rows are ``1 / fps``
apart, so run on the compact array they treat the animal's move across the untracked stretch as
one frame of motion.

Each stretch of unobserved video between two intervals becomes one of two things:

* **bridged**: when the project allows it and the gap is short enough, one row per missing frame,
  filled by a straight line between the animal's last and next observed positions, in true frame
  coordinates. These rows are estimates and are marked as such.
* **a separator**: otherwise a single all-NaN row, so the two sides are never adjacent. It costs
  one row however long the gap is, and every step already keeps NaN rows as breaks.

Sessions without such gaps (contiguous, a single interval, no interval metadata, or intervals that
do not match the data) are returned as None and processed exactly as before.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from track2data.core.errors import ProcessingError
from track2data.core.models import GapFillCfg, PPStepResult, Session
from track2data.core.timeline import map_array_index_to_true_frame

#: Rows x animals the rebuilt arrays may hold. Beyond this a bridging limit was set far higher than
#: any real gap needs, and allocating it would take the machine down instead of failing clearly.
MAX_EXPANDED_CELLS = 50_000_000


@dataclass
class Expansion:
    """Where each stored row went, and what the inserted rows are."""

    n_rows: int
    row_of_source: np.ndarray  # (n_stored,) row in the expanded arrays of each stored row
    frame_index: np.ndarray  # (n_rows,) video frame of each row (a separator gets prev + 1)
    tracked_mask: np.ndarray  # (n_rows,) True for stored rows
    separator_mask: np.ndarray  # (n_rows,) True for the single NaN row of an unfilled gap
    bridged_mask: np.ndarray  # (n_rows,) True for inserted rows of a bridged gap


def plan_expansion(
    session: Session, cfg: GapFillCfg, *, bridge_allowed: bool = True
) -> Expansion | None:
    """The expansion for *session*, or None when its rows already are its frames."""
    n = int(session.raw_xy.shape[0])
    frames, valid = map_array_index_to_true_frame(session.tracking_intervals, n)
    if not valid or n < 2:
        return None
    missing = np.diff(frames) - 1  # frames never tracked between consecutive stored rows
    gap_at = np.flatnonzero(missing > 0) + 1  # stored row that follows each gap
    if len(gap_at) == 0:
        return None

    stable = session.has_stable_identities and session.track_wo_identities is not True
    bridging = bool(
        cfg.enabled and cfg.across_tracking_intervals and bridge_allowed and stable
    )
    limit_frames = math.floor(cfg.max_cross_interval_gap_s * session.video.fps + 1e-9)
    bridged_gap = [bool(bridging and missing[i - 1] <= limit_frames) for i in gap_at]
    inserted = [int(missing[i - 1]) if b else 1 for i, b in zip(gap_at, bridged_gap, strict=True)]

    n_rows = n + sum(inserted)
    if n_rows * session.n_animals > MAX_EXPANDED_CELLS:
        raise ProcessingError(
            f"Bridging the gaps between tracking intervals would need {n_rows:,} rows for "
            f"{session.n_animals} animals. Lower the cross-interval limit "
            f"({cfg.max_cross_interval_gap_s:g} s) so only the gaps you mean to bridge are "
            "filled.",
            code="TIMELINE_TOO_LARGE",
            subject=session.session_id,
        )

    row_of_source = np.arange(n, dtype=np.int64)
    shift = 0
    frame_index = np.empty(n_rows, dtype=np.int64)
    tracked = np.zeros(n_rows, dtype=bool)
    separator = np.zeros(n_rows, dtype=bool)
    bridged = np.zeros(n_rows, dtype=bool)
    previous = 0
    for i, count in zip(gap_at, inserted, strict=True):
        row_of_source[previous:i] += shift
        shift += count
        previous = i
    row_of_source[previous:] += shift

    frame_index[row_of_source] = frames
    tracked[row_of_source] = True
    for i, count, is_bridged in zip(gap_at, inserted, bridged_gap, strict=True):
        first = int(row_of_source[i - 1]) + 1
        rows = slice(first, first + count)
        frame_index[rows] = int(frames[i - 1]) + 1 + np.arange(count)
        if is_bridged:
            bridged[rows] = True
        else:
            separator[rows] = True
    return Expansion(n_rows, row_of_source, frame_index, tracked, separator, bridged)


def lay_out(expansion: Expansion, stored: np.ndarray) -> np.ndarray:
    """*stored* ``(n_stored, ...)`` placed on the expanded rows, NaN everywhere else."""
    out = np.full((expansion.n_rows, *stored.shape[1:]), np.nan, dtype=np.float64)
    out[expansion.row_of_source] = stored
    return out


def bridge_gaps(xy: np.ndarray, expansion: Expansion) -> tuple[np.ndarray, PPStepResult]:
    """Fill each bridged gap with a straight line in true frame coordinates.

    Per animal and per gap, only when that animal has an observed position on both sides: a
    missing anchor leaves the gap NaN (no extrapolation, no guess). The line is
    ``p(f) = p(left) + (p(right) - p(left)) * (f - left) / (right - left)`` over video frames.
    """
    out = xy.copy()
    n_animals = xy.shape[1]
    filled = [0] * n_animals
    rows = np.flatnonzero(expansion.bridged_mask)
    if len(rows):
        # contiguous runs of bridged rows are one gap each
        starts = rows[np.concatenate(([True], np.diff(rows) != 1))]
        ends = rows[np.concatenate((np.diff(rows) != 1, [True]))]
        frames = expansion.frame_index
        for first, last in zip(starts, ends, strict=True):
            left, right = int(first) - 1, int(last) + 1
            span = float(frames[right] - frames[left])
            t = (frames[first : last + 1] - frames[left]) / span
            for k in range(n_animals):
                p0, p1 = xy[left, k], xy[right, k]
                if np.isnan(p0).any() or np.isnan(p1).any():
                    continue
                out[first : last + 1, k] = p0 + np.outer(t, p1 - p0)
                filled[k] += int(last - first + 1)
    total = int(expansion.bridged_mask.sum())
    note = (
        f"{int(expansion.separator_mask.sum())} gap(s) left unfilled and kept as breaks"
        if expansion.separator_mask.any()
        else ""
    )
    return out, PPStepResult(
        step_name="gap_fill_across_intervals",
        affected_frames=total,
        affected_per_individual=filled,
        notes=note,
    )
