"""Speed, acceleration, and heading computation from preprocessed xy trajectories."""

from __future__ import annotations

import numpy as np

from track2data.core.models import KinematicsArrays


def compute_kinematics(xy: np.ndarray, fps: float) -> KinematicsArrays:
    """Compute speed, acceleration, and heading from a preprocessed xy array.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
        NaN values indicate missing positions.
    fps:
        Frames per second used to convert frame-differences to real time.

    Returns
    -------
    KinematicsArrays
        ``speed_px_s[t, k]``  = Euclidean displacement from frame *t* to *t+1*
        multiplied by *fps*.  NaN at the last frame and wherever positions are NaN.

        ``accel_px_s2[t, k]`` = ``(speed[t+1] - speed[t]) * fps``.
        NaN at the last two frames.

        ``heading_rad[t, k]`` = ``arctan2(dy, dx)`` of the displacement vector.
        NaN when displacement is zero or NaN.
    """
    n_frames, n_animals, _ = xy.shape
    speed = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    heading = np.full((n_frames, n_animals), np.nan, dtype=np.float64)

    # Displacement vectors: shape (n_frames-1, n_animals, 2)
    delta = xy[1:] - xy[:-1]  # (n_frames-1, n_animals, 2)

    # Euclidean distance
    dist = np.sqrt(delta[:, :, 0] ** 2 + delta[:, :, 1] ** 2)  # (n_frames-1, n_animals)

    speed[:-1] = dist * fps

    # Heading: arctan2(dy, dx); NaN where displacement is zero
    with np.errstate(invalid="ignore"):
        dx = delta[:, :, 0]
        dy = delta[:, :, 1]
        h = np.arctan2(dy, dx)
        zero_disp = dist == 0.0
        h[zero_disp] = np.nan
        heading[:-1] = h

    # Acceleration: (speed[t+1] - speed[t]) * fps
    accel = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    # speed[:-1] covers frames 0..n_frames-2; speed_diff needs speed[t] and speed[t+1]
    # speed[t] is defined for t in 0..n_frames-2
    # speed[t+1] is defined for t in 0..n_frames-3
    speed_diff = speed[1:-1] - speed[:-2]  # (n_frames-2, n_animals)
    accel[:-2] = speed_diff * fps

    return KinematicsArrays(
        speed_px_s=speed,
        accel_px_s2=accel,
        heading_rad=heading,
    )
