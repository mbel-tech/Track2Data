"""3-D positions in cm for a fused session, shared by the 3-D metrics.

A fused session carries the top view's ``xy`` (px), the side view's ``depth`` (fraction of the
water column, 0 = surface, 1 = floor), the top view's ``px_per_cm`` and the tank height
``depth_height_cm``. A native 3-D session carries an absolute ``z`` instead of a depth. Without
a z (or a depth and its height) and the scale there are no 3-D positions and the metrics report
NaN.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import PreprocessedSession


def vertical_cm(psess: PreprocessedSession) -> np.ndarray | None:
    """``(n_frames, n_animals)`` vertical coordinate in cm that the 3-D metrics use, or None.

    A native 3-D session's ``psess.z`` (already absolute, in the project's length unit) with the
    samples that fall outside the water column set to NaN: the column that bounds IL-15's depth
    bounds the path length and the speed too, so a mis-triangulated or out-of-tank sample is out
    of every 3-D metric alike. Nothing is clipped, and ``psess.z`` itself is not modified (the
    exported ``z_cm`` is the file's own coordinate). Without a water column the whole z is used.
    A fused session has ``depth * depth_height_cm``, which is already NaN outside the column.
    None when there is neither a ``z`` nor a ``depth`` with its ``depth_height_cm``.
    """
    if psess.z is not None:
        z = np.array(psess.z, dtype=np.float64)
        if psess.depth_outside_mask is not None:
            z[np.asarray(psess.depth_outside_mask, dtype=bool)] = np.nan
        return z
    if psess.depth is not None and psess.depth_height_cm is not None:
        return np.asarray(psess.depth, dtype=np.float64) * float(psess.depth_height_cm)
    return None


def positions_cm(psess: PreprocessedSession) -> np.ndarray | None:
    """``(n_frames, n_animals, 3)`` float64 ``(X, Y, Z)`` in cm, or None without a 3-D scale.

    ``X = x_px / px_per_cm``, ``Y = y_px / px_per_cm``. ``Z`` is :func:`vertical_cm` (a native
    3-D file's absolute z inside its water column, else ``depth * depth_height_cm``). A position is
    NaN in every component where any of the three is NaN (a step or a frame needs all three).
    None when ``px_per_cm`` is missing, or when there is neither a ``z`` nor a ``depth`` with
    its ``depth_height_cm``.
    """
    if psess.px_per_cm is None:
        return None
    z = vertical_cm(psess)
    if z is None:
        return None
    xy = np.asarray(psess.xy, dtype=np.float64)
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
