"""PP-2 jump detection — flag and replace anomalous inter-frame displacements."""

from __future__ import annotations

import numpy as np
import pandas as pd

from track2data.core.models import JumpCfg, PPStepResult


def _compute_displacement(xy: np.ndarray) -> np.ndarray:
    """Return per-frame Euclidean displacement, shape (n_frames, n_animals).

    Frame 0 is set to NaN (no previous frame).
    """
    n_frames, n_animals, _ = xy.shape
    disp = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    delta = xy[1:] - xy[:-1]  # (n_frames-1, n_animals, 2)
    disp[1:] = np.sqrt(delta[:, :, 0] ** 2 + delta[:, :, 1] ** 2)
    return disp


def _flag_jumps_sd(disp: np.ndarray, sd_mult: float) -> np.ndarray:
    """Flag frames where displacement > mean + sd_mult * std per animal."""
    n_frames, n_animals = disp.shape
    flags = np.zeros((n_frames, n_animals), dtype=bool)
    for k in range(n_animals):
        d = disp[:, k]
        valid = d[~np.isnan(d)]
        if valid.size == 0:
            continue
        threshold = np.nanmean(d) + sd_mult * np.nanstd(d)
        flags[:, k] = d > threshold
    return flags


def _flag_jumps_percentile(disp: np.ndarray, percentile: float, pct_mult: float) -> np.ndarray:
    """Flag frames where displacement > nanpercentile(disp, p) * pct_mult per animal."""
    n_frames, n_animals = disp.shape
    flags = np.zeros((n_frames, n_animals), dtype=bool)
    for k in range(n_animals):
        d = disp[:, k]
        valid = d[~np.isnan(d)]
        if valid.size == 0:
            continue
        threshold = np.nanpercentile(d, percentile) * pct_mult
        flags[:, k] = d > threshold
    return flags


def detect_jumps(xy: np.ndarray, cfg: JumpCfg) -> tuple[np.ndarray, PPStepResult]:
    """Detect and replace anomalously large inter-frame displacements.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Jump-detection configuration.

    Returns
    -------
    out:
        New array with flagged frames replaced (NaN or linearly interpolated).
        Input is *not* mutated.
    result:
        ``PPStepResult`` describing how many frames were affected.
    """
    _, n_animals, _ = xy.shape
    out = xy.copy()

    if not cfg.enabled:
        return out, PPStepResult(
            step_name="jump_detect",
            affected_frames=0,
            affected_per_individual=[0] * n_animals,
        )

    disp = _compute_displacement(xy)

    if cfg.method == "sd_multiple":
        flags = _flag_jumps_sd(disp, cfg.sd_mult)
    else:
        flags = _flag_jumps_percentile(disp, cfg.percentile, cfg.pct_mult)

    affected_per_individual: list[int] = []

    for k in range(n_animals):
        flagged_frames = np.where(flags[:, k])[0]
        if flagged_frames.size == 0:
            affected_per_individual.append(0)
            continue

        # Set flagged positions to NaN first
        for f in flagged_frames:
            out[f, k, :] = np.nan

        # Optionally interpolate
        if cfg.replacement == "linear_interp":
            for axis in range(2):
                series = pd.Series(out[:, k, axis])
                filled = series.interpolate(method="linear", limit_direction="both")
                out[:, k, axis] = filled.to_numpy(dtype=np.float64, na_value=np.nan)

        affected_per_individual.append(int(flagged_frames.size))

    total_affected = sum(affected_per_individual)

    return out, PPStepResult(
        step_name="jump_detect",
        affected_frames=total_affected,
        affected_per_individual=affected_per_individual,
    )
