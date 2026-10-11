"""The vertical axis of a native 3-D file, put through the same cleaning steps as xy.

``z`` is a single column per animal, so it reuses the one-dimensional workers of the xy steps
(``gap_fill._fill_series``, ``smoothing._smooth_series_*``, ``timeline_expand.bridge_gaps``) rather
than the ``(n_frames, n_animals, 2)`` wrappers. The same settings govern it, so a 3-D position is
cleaned as one object: smoothing the horizontal plane while leaving the vertical raw made the
vertical share of a 3-D path length several times too large and no setting could reduce it.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import GapFillCfg, SmoothCfg
from track2data.preprocess.gap_fill import _fill_series
from track2data.preprocess.smoothing import _smooth_series_moving_avg, _smooth_series_savgol
from track2data.preprocess.timeline_expand import Expansion, bridge_gaps


def clean_z(
    z: np.ndarray,
    gap_cfg: GapFillCfg,
    smooth_cfg: SmoothCfg,
    expansion: Expansion | None,
) -> np.ndarray:
    """``z`` ``(n_rows, n_animals)`` bridged, gap-filled and smoothed like xy; input untouched.

    The caller blanks the rows where xy was jump-replaced first, so they are re-filled from their
    neighbours instead of keeping a raw vertical value beside a corrected horizontal one.
    """
    out = z.copy()
    if expansion is not None and expansion.bridged_mask.any():
        out, _ = bridge_gaps(out[:, :, None], expansion)
        out = out[:, :, 0]
    if gap_cfg.enabled:
        protected = None if expansion is None else ~expansion.tracked_mask
        for k in range(out.shape[1]):
            out[:, k], _ = _fill_series(out[:, k], gap_cfg.max_gap_frames, protected)
    if smooth_cfg.enabled and smooth_cfg.method != "none":
        for k in range(out.shape[1]):
            if smooth_cfg.method == "savgol":
                out[:, k] = _smooth_series_savgol(
                    out[:, k], smooth_cfg.window, smooth_cfg.polyorder
                )
            else:
                out[:, k] = _smooth_series_moving_avg(out[:, k], smooth_cfg.window)
    return out
