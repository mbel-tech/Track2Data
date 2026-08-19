"""PP-1 gap filling — linear interpolation of short NaN gaps."""

from __future__ import annotations

import numpy as np

from track2data.core.models import GapFillCfg, PPStepResult


def _find_nan_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return list of (start, end) index pairs for consecutive True runs.

    ``end`` is exclusive (Python-slice convention).
    """
    runs: list[tuple[int, int]] = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _fill_series(series: np.ndarray, max_gap: int) -> tuple[np.ndarray, int]:
    """Fill NaN gaps of at most *max_gap* frames via linear interpolation.

    Gaps longer than *max_gap* are left as NaN.

    Returns
    -------
    out:
        New array with short gaps filled.
    filled_count:
        Number of frames that were filled.
    """
    out = series.copy()
    nan_mask = np.isnan(series)
    runs = _find_nan_runs(nan_mask)
    filled_count = 0

    for start, end in runs:
        gap_len = end - start
        if gap_len > max_gap:
            continue  # leave this gap as NaN
        # Need valid anchors on both sides
        if start == 0 or end == len(series):
            continue  # can't interpolate at the boundary
        x0 = series[start - 1]
        x1 = series[end]
        if np.isnan(x0) or np.isnan(x1):
            continue
        # Linear interpolation: x0 to x1 over (gap_len + 1) steps
        for i, f in enumerate(range(start, end), start=1):
            out[f] = x0 + (x1 - x0) * i / (gap_len + 1)
            filled_count += 1

    return out, filled_count


def fill_gaps(xy: np.ndarray, cfg: GapFillCfg) -> tuple[np.ndarray, PPStepResult]:
    """Fill short NaN gaps in trajectories via linear interpolation.

    Only gaps of at most *cfg.max_gap_frames* consecutive NaN frames are
    filled.  Longer gaps are left as NaN.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Gap-fill configuration.

    Returns
    -------
    out:
        New array of same shape with short gaps filled.  The input is *not*
        mutated.
    result:
        ``PPStepResult`` recording how many frames were affected.
    """
    _, n_animals, _ = xy.shape
    out = xy.copy()

    if not cfg.enabled:
        return out, PPStepResult(
            step_name="gap_fill",
            affected_frames=0,
            affected_per_individual=[0] * n_animals,
        )

    affected_per_individual: list[int] = []

    for k in range(n_animals):
        total_filled = 0
        for axis in range(2):
            filled_series, count = _fill_series(xy[:, k, axis], cfg.max_gap_frames)
            out[:, k, axis] = filled_series
            if axis == 0:
                total_filled = count
        affected_per_individual.append(total_filled)

    total_affected = sum(affected_per_individual)

    return out, PPStepResult(
        step_name="gap_fill",
        affected_frames=total_affected,
        affected_per_individual=affected_per_individual,
    )
