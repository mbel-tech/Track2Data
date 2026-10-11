"""3-D positions in cm for a fused session, shared by the 3-D metrics.

A fused session carries the top view's ``xy`` (px), the side view's ``depth`` (fraction of the
water column, 0 = surface, 1 = floor), the top view's ``px_per_cm`` and the tank height
``depth_height_cm``. A native 3-D session carries an absolute ``z`` instead of a depth. Without
a z (or a depth and its height) and the scale there are no 3-D positions and the metrics report
NaN.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import KinematicsCfg, PreprocessedSession


def z_cm(psess: PreprocessedSession) -> np.ndarray | None:
    """``(n_frames, n_animals)`` float64 vertical coordinate in cm, or None without one.

    ``psess.z`` for a native 3-D session (absolute, in the project unit), else
    ``depth * depth_height_cm`` for a fused one. Not masked by the horizontal position.
    """
    if psess.z is not None:
        return np.asarray(psess.z, dtype=np.float64)
    if psess.depth is not None and psess.depth_height_cm is not None:
        return np.asarray(psess.depth, dtype=np.float64) * float(psess.depth_height_cm)
    return None


def vertical_speed(psess: PreprocessedSession, kin_cfg: KinematicsCfg | dict) -> np.ndarray | None:
    """``(n_frames, n_animals)`` vertical speed (cm/s, unsigned) of the session's Z, or None.

    The single implementation of IL-17's vertical part: the pipeline's own derivative
    (``compute_kinematics``) applied to ``[Z, 0]``, so the speed is ``|vz|``, NaN wherever Z is
    or the estimator has no value. The Engine calls it once on the whole session and slices the
    result with the windows; ``Speed3D`` calls it only when the session carries no precomputed
    series. None without a Z or without the cm scale.
    """
    from track2data.core.models import KinematicsCfg
    from track2data.preprocess.kinematics import compute_kinematics

    z = z_cm(psess)
    if z is None or psess.px_per_cm is None:
        return None
    kcfg = KinematicsCfg.model_validate(kin_cfg or {})
    zz = np.stack([z, np.where(np.isnan(z), np.nan, 0.0)], axis=-1)
    return compute_kinematics(zz, psess.fps, kcfg).speed_px_s


def positions_cm(psess: PreprocessedSession) -> np.ndarray | None:
    """``(n_frames, n_animals, 3)`` float64 ``(X, Y, Z)`` in cm, or None without a 3-D scale.

    ``X = x_px / px_per_cm``, ``Y = y_px / px_per_cm``. ``Z`` is ``psess.z`` when the session
    carries an absolute z (a native 3-D file), else ``depth * depth_height_cm``. A position is
    NaN in every component where any of the three is NaN (a step or a frame needs all three).
    None when ``px_per_cm`` is missing, or when there is neither a ``z`` nor a ``depth`` with
    its ``depth_height_cm``.
    """
    if psess.px_per_cm is None:
        return None
    z = z_cm(psess)
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
