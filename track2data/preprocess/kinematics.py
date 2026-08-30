"""Speed, acceleration, and heading computation from preprocessed xy trajectories.

Two estimators, selected by ``KinematicsCfg.method``.

``savgol`` (default) differentiates the trajectory with a Savitzky-Golay
filter -- the same filter family already used to smooth positions -- and is
the reason this module is no longer a pair of finite differences:

* **No half-frame offset.** A forward difference assigned to frame *t*
  actually estimates the derivative at *t + ½*, so every speed value sat half
  a frame away from its own timestamp. SG differentiation is centred.
* **No squared noise.** Acceleration used to be a first difference *of the
  first difference*, which amplifies positional noise twice over. Here
  velocity and acceleration each come from one filtered derivative of
  position, and tangential acceleration is then obtained analytically
  (see ``_tangential_acceleration``) rather than by differencing a
  differenced series.

``forward_difference`` reproduces the previous estimator exactly, kept for
one release so a project can reproduce older numbers. See the CHANGELOG:
values shift when you switch.

Note on double filtering: the pipeline smooths positions before this runs, so
with both enabled the trajectory is filtered once for position and again for
the derivative. That is mild and deliberate -- differentiating an unsmoothed
trajectory is far noisier -- but it is why ``KinematicsCfg`` carries its own
window rather than silently reusing ``SmoothCfg``'s.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter  # type: ignore[import-untyped]

from track2data.core.models import KinematicsArrays, KinematicsCfg


def _segments(series: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous runs of non-NaN values, as ``(start, end)`` half-open pairs.

    Derivatives are taken per segment so a gap is never bridged: filtering
    across one would invent motion that was never observed. Mirrors the
    segmentation in ``preprocess/smoothing.py``.
    """
    not_nan = ~np.isnan(series)
    changes = np.diff(not_nan.astype(int), prepend=0, append=0)
    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]
    return list(zip(starts, ends, strict=True))


def _savgol_derivative(
    series: np.ndarray, window: int, polyorder: int, dt: float, order: int
) -> np.ndarray:
    """``order``-th time-derivative of *series*, NaN-preserving.

    Returns NaN for any segment too short to support the requested
    polynomial order -- refusing to estimate is better than estimating from
    fewer points than the fit needs.
    """
    out = np.full_like(series, np.nan)
    if polyorder < order:
        # A quadratic fit has no third derivative; say so rather than
        # returning zeros, which would read as "measured no acceleration".
        return out

    for start, end in _segments(series):
        seg = series[start:end]
        seg_len = len(seg)
        w = min(window, seg_len)
        if w % 2 == 0:
            w -= 1
        if w < polyorder + 1:
            continue
        # Centre the segment first. A derivative is unchanged by a constant
        # offset, but the conditioning is not: filtering raw pixel
        # coordinates (order 1e3) leaves ~1e-12 of floating-point residue
        # where the true derivative is zero. On a stationary animal that
        # residue is the *entire* signal, so speed came out ~1e-12 instead
        # of 0 and -- worse -- `speed == 0` was then False, giving a
        # perfectly still animal a heading invented from rounding error.
        # Centred, a constant segment differences to exactly zero.
        seg = seg - seg.mean()
        out[start:end] = savgol_filter(
            seg, window_length=w, polyorder=polyorder, deriv=order, delta=dt
        )
    return out


def _tangential_acceleration(
    vx: np.ndarray, vy: np.ndarray, ax: np.ndarray, ay: np.ndarray
) -> np.ndarray:
    """Rate of change of *speed*, d|v|/dt, from the velocity and acceleration.

    ``d|v|/dt = (v · a) / |v|`` -- an exact identity, so this is the same
    quantity the forward-difference estimator approximated, obtained without
    differencing an already-differenced series.

    Deliberately not ``|a|``: that would include the centripetal component, so
    an animal turning at constant speed would report acceleration. IL-6 is
    documented as the rate of change of speed, and changing which quantity it
    names would be a silent redefinition rather than a better estimate.

    NaN where the animal is stationary, since the direction of travel -- and
    so the tangent -- is undefined there. Same convention as ``heading_rad``.
    """
    speed = np.sqrt(vx ** 2 + vy ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        tangential = (vx * ax + vy * ay) / speed
    tangential[speed == 0.0] = np.nan
    return tangential


def _savgol_kinematics(
    xy: np.ndarray, fps: float, cfg: KinematicsCfg
) -> KinematicsArrays:
    """Centred, consistently-filtered kinematics via SG differentiation."""
    n_frames, n_animals, _ = xy.shape
    dt = 1.0 / fps

    speed = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    accel = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    heading = np.full((n_frames, n_animals), np.nan, dtype=np.float64)

    for k in range(n_animals):
        vx = _savgol_derivative(xy[:, k, 0], cfg.window, cfg.polyorder, dt, order=1)
        vy = _savgol_derivative(xy[:, k, 1], cfg.window, cfg.polyorder, dt, order=1)
        ax = _savgol_derivative(xy[:, k, 0], cfg.window, cfg.polyorder, dt, order=2)
        ay = _savgol_derivative(xy[:, k, 1], cfg.window, cfg.polyorder, dt, order=2)

        speed[:, k] = np.sqrt(vx ** 2 + vy ** 2)
        accel[:, k] = _tangential_acceleration(vx, vy, ax, ay)

        with np.errstate(invalid="ignore"):
            h = np.arctan2(vy, vx)
        h[speed[:, k] == 0.0] = np.nan
        heading[:, k] = h

    return KinematicsArrays(speed_px_s=speed, accel_px_s2=accel, heading_rad=heading)


def _forward_difference_kinematics(xy: np.ndarray, fps: float) -> KinematicsArrays:
    """The pre-0.2 estimator, kept verbatim so older numbers reproduce.

    Retains both of its known defects: speed is a forward difference labelled
    with the earlier frame (a half-frame offset), and acceleration is a first
    difference of that (which squares the noise amplification).
    """
    n_frames, n_animals, _ = xy.shape
    speed = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    heading = np.full((n_frames, n_animals), np.nan, dtype=np.float64)

    delta = xy[1:] - xy[:-1]  # (n_frames-1, n_animals, 2)
    dist = np.sqrt(delta[:, :, 0] ** 2 + delta[:, :, 1] ** 2)
    speed[:-1] = dist * fps

    with np.errstate(invalid="ignore"):
        h = np.arctan2(delta[:, :, 1], delta[:, :, 0])
        h[dist == 0.0] = np.nan
        heading[:-1] = h

    accel = np.full((n_frames, n_animals), np.nan, dtype=np.float64)
    accel[:-2] = (speed[1:-1] - speed[:-2]) * fps

    return KinematicsArrays(speed_px_s=speed, accel_px_s2=accel, heading_rad=heading)


def compute_kinematics(
    xy: np.ndarray, fps: float, cfg: KinematicsCfg | None = None
) -> KinematicsArrays:
    """Compute speed, acceleration, and heading from a preprocessed xy array.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
        NaN values indicate missing positions.
    fps:
        Frames per second used to convert frame-differences to real time.
    cfg:
        Estimator configuration. Defaults to Savitzky-Golay differentiation.

    Returns
    -------
    KinematicsArrays
        ``speed_px_s[t, k]``  -- speed in px/s, NaN where position is missing.

        ``accel_px_s2[t, k]`` -- rate of change of speed in px/s^2 (the
        tangential component, not the magnitude of the acceleration vector --
        see ``_tangential_acceleration``). NaN where the animal is stationary.

        ``heading_rad[t, k]`` -- direction of travel, ``arctan2(vy, vx)``.
        NaN when the animal is stationary, because direction is undefined
        there. This silently thins the sample of any turning or
        angular-velocity metric, which is recorded in those metrics'
        documented assumptions.
    """
    cfg = cfg or KinematicsCfg()
    if cfg.method == "forward_difference":
        return _forward_difference_kinematics(xy, fps)
    return _savgol_kinematics(xy, fps, cfg)
