"""Scalar px-per-cm calibration and unit-conversion utilities.

Public API
----------
apply_scalar_calibration  -- set psess.px_per_cm from a CalibrationConfig
px_to_cm                  -- convert pixel distances to centimetres
px_to_bl                  -- convert pixel distances to body-length units
"""

from __future__ import annotations

import dataclasses

import numpy as np

from track2data.core.errors import CalibrationError
from track2data.core.models import CalibrationConfig, PreprocessedSession


def px_to_cm(px_values: np.ndarray, px_per_cm: float) -> np.ndarray:
    """Convert pixel distances to centimetres.

    Parameters
    ----------
    px_values:
        Array of distances in pixels (any shape).  NaN values pass through
        unchanged.
    px_per_cm:
        Conversion factor (pixels per centimetre, must be > 0).

    Returns
    -------
    np.ndarray
        New array of the same shape and dtype, with values in centimetres.
    """
    return px_values / px_per_cm


def px_to_bl(px_values: np.ndarray, body_length_px: np.ndarray) -> np.ndarray:
    """Convert per-animal pixel values to body-length units.

    Parameters
    ----------
    px_values:
        Pixel distances.  Accepted shapes:

        * ``(n_animals,)``  — one value per animal.
        * ``(n_frames, n_animals)``  — time-series per animal.

        NaN values pass through unchanged.
    body_length_px:
        Shape ``(n_animals,)``.  Each animal's body length in pixels.
        Each animal column in *px_values* is divided by the corresponding
        entry.

    Returns
    -------
    np.ndarray
        Array of the same shape as *px_values*, in body-length units.
    """
    return px_values / body_length_px


def apply_scalar_calibration(
    psess: PreprocessedSession,
    cfg: CalibrationConfig,
) -> PreprocessedSession:
    """Apply scalar px-per-cm calibration to a preprocessed session.

    Sets ``psess.px_per_cm`` to ``cfg.px_per_cm`` and returns the updated
    session object.  The function uses ``dataclasses.replace`` so the
    original is not mutated if the caller retains a reference.

    Parameters
    ----------
    psess:
        The preprocessed session to calibrate.
    cfg:
        Calibration configuration.  ``cfg.mode`` must be ``"scalar"`` and
        ``cfg.px_per_cm`` must be a finite positive number.

    Returns
    -------
    PreprocessedSession
        A copy of *psess* with ``px_per_cm`` populated.

    Raises
    ------
    CalibrationError
        If ``cfg.mode != 'scalar'``, ``cfg.px_per_cm is None``, or
        ``cfg.px_per_cm <= 0``.
    """
    if cfg.mode != "scalar":
        raise CalibrationError(
            f"apply_scalar_calibration requires mode='scalar', got '{cfg.mode}'.",
            code="CAL-SCALAR-MODE",
            remediation="Set CalibrationConfig(mode='scalar', px_per_cm=<value>).",
        )
    if cfg.px_per_cm is None:
        raise CalibrationError(
            "px_per_cm must be set for scalar calibration.",
            code="CAL-SCALAR-MISSING",
            remediation="Provide a positive px_per_cm value in CalibrationConfig.",
        )
    if cfg.px_per_cm <= 0:
        raise CalibrationError(
            f"px_per_cm must be > 0, got {cfg.px_per_cm!r}.",
            code="CAL-SCALAR-INVALID",
            remediation="Provide a positive px_per_cm value in CalibrationConfig.",
        )

    return dataclasses.replace(psess, px_per_cm=cfg.px_per_cm)
