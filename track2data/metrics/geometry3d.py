"""3-D positions in cm for a fused session, shared by the 3-D metrics.

A fused session carries the top view's ``xy`` (px), the side view's ``depth`` (fraction of the
water column, 0 = surface, 1 = floor), the top view's ``px_per_cm`` and the tank height
``depth_height_cm``. Without all of them there are no 3-D positions and the metrics report NaN.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import PreprocessedSession


def positions_cm(psess: PreprocessedSession) -> np.ndarray | None:
    """``(n_frames, n_animals, 3)`` float64 ``(X, Y, Z)`` in cm, or None without a 3-D scale.

    ``X = x_px / px_per_cm``, ``Y = y_px / px_per_cm``, ``Z = depth * depth_height_cm``. A
    position is NaN in every component where any of the three is NaN (a step or a frame needs
    all three). None when ``depth``, ``px_per_cm`` or ``depth_height_cm`` is missing.
    """
    if psess.depth is None or psess.px_per_cm is None or psess.depth_height_cm is None:
        return None
    xy = np.asarray(psess.xy, dtype=np.float64)
    z = np.asarray(psess.depth, dtype=np.float64) * float(psess.depth_height_cm)
    pos = np.empty((*xy.shape[:2], 3), dtype=np.float64)
    pos[..., :2] = xy / float(psess.px_per_cm)
    pos[..., 2] = z
    pos[np.isnan(pos).any(axis=-1)] = np.nan
    return pos


def body_length_cm(psess: PreprocessedSession, k: int) -> float:
    """Body length of animal *k* in cm; NaN when unknown or when there is no scale."""
    if psess.px_per_cm is None:
        return float("nan")
    bl_px = psess.body_length_in_px()
    if bl_px is None:
        return float("nan")
    value = float(np.asarray(bl_px, dtype=np.float64)[k]) / float(psess.px_per_cm)
    return value if np.isfinite(value) and value > 0 else float("nan")
