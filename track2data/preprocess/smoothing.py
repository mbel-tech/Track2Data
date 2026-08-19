"""PP-4 trajectory smoothing — moving average and Savitzky-Golay filter."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter  # type: ignore[import-untyped]

from track2data.core.models import PPStepResult, SmoothCfg


def _smooth_series_savgol(series: np.ndarray, window: int, polyorder: int) -> np.ndarray:
    """Apply Savitzky-Golay filter, preserving NaN frames.

    Segments between NaN values are filtered independently so that NaN
    values are never filled or propagated.
    """
    out = series.copy()
    nan_mask = np.isnan(series)
    if nan_mask.all():
        return out

    # Find contiguous non-NaN segments
    not_nan = ~nan_mask
    changes = np.diff(not_nan.astype(int), prepend=0, append=0)
    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]

    for s, e in zip(starts, ends, strict=True):
        seg = series[s:e]
        seg_len = len(seg)
        if seg_len < polyorder + 1:
            continue
        w = min(window, seg_len)
        if w % 2 == 0:
            w -= 1
        if w < polyorder + 1:
            continue
        out[s:e] = savgol_filter(seg, window_length=w, polyorder=polyorder)

    return out


def _smooth_series_moving_avg(series: np.ndarray, window: int) -> np.ndarray:
    """Apply uniform moving-average, preserving NaN frames."""
    if window <= 1:
        return series.copy()
    out = series.copy()
    nan_mask = np.isnan(series)

    # Use pandas rolling on non-NaN segments
    not_nan = ~nan_mask
    changes = np.diff(not_nan.astype(int), prepend=0, append=0)
    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]

    for s, e in zip(starts, ends, strict=True):
        seg = series[s:e]
        seg_len = len(seg)
        if seg_len < window:
            continue
        smoothed = (
            pd.Series(seg).rolling(window, min_periods=1, center=True).mean().to_numpy()
        )
        out[s:e] = smoothed

    return out


def smooth_trajectories(xy: np.ndarray, cfg: SmoothCfg) -> tuple[np.ndarray, PPStepResult]:
    """Smooth per-animal trajectories using the configured method.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Smoothing configuration.

    Returns
    -------
    out:
        New smoothed array (input not mutated).
    result:
        ``PPStepResult`` recording affected frames.
    """
    n_frames, n_animals, _ = xy.shape
    out = xy.copy()

    if not cfg.enabled or cfg.method == "none":
        return out, PPStepResult(
            step_name="smoothing",
            affected_frames=0,
            affected_per_individual=[0] * n_animals,
        )

    affected_per_individual = [n_frames] * n_animals

    for k in range(n_animals):
        for axis in range(2):
            series = xy[:, k, axis]
            if cfg.method == "savgol":
                out[:, k, axis] = _smooth_series_savgol(series, cfg.window, cfg.polyorder)
            elif cfg.method == "moving_avg":
                out[:, k, axis] = _smooth_series_moving_avg(series, cfg.window)

    return out, PPStepResult(
        step_name="smoothing",
        affected_frames=n_frames,
        affected_per_individual=affected_per_individual,
    )
