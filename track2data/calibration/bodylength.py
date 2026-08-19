"""Per-session body-length normalisation calibration.

Public API
----------
apply_bodylength_calibration  -- derive body_length_cm (and optionally
                                  px_per_cm) from Session.body_length_px
                                  and Session.length_unit.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from track2data.core.errors import CalibrationError
from track2data.core.models import CalibrationConfig, PreprocessedSession


def apply_bodylength_calibration(
    psess: PreprocessedSession,
    cfg: CalibrationConfig,
) -> PreprocessedSession:
    """Apply body-length-based calibration to a preprocessed session.

    Behaviour
    ---------
    1. **Validates** that ``cfg.mode == 'bodylength'`` and that
       ``Session.body_length_px`` is available.
    2. **Checks sample count**: ``psess.n_frames`` must be >=
       ``cfg.bl_min_samples`` (default 30).  This acts as a guard against
       sessions that are too short to produce reliable body-length estimates.
    3. **Converts** body lengths:

       * If ``session.length_unit`` is set and > 0:
         ``body_length_cm[k] = body_length_px[k] / length_unit``
         and ``px_per_cm`` is set to ``length_unit``.
       * Otherwise (no ``length_unit``):
         ``body_length_cm = body_length_px``  (values remain in pixels;
         the field name is a misnomer in this mode, but it preserves a
         uniform interface for downstream metric code).

    Parameters
    ----------
    psess:
        The preprocessed session to calibrate.
    cfg:
        Calibration configuration.  ``cfg.mode`` must be ``'bodylength'``.

    Returns
    -------
    PreprocessedSession
        A copy of *psess* with ``body_length_cm`` (and optionally
        ``px_per_cm``) populated.

    Raises
    ------
    CalibrationError
        * ``cfg.mode != 'bodylength'``
        * ``session.body_length_px`` is ``None``
        * ``psess.n_frames < cfg.bl_min_samples``
        * ``session.length_unit`` is 0 (division by zero guard)
    """
    if cfg.mode != "bodylength":
        raise CalibrationError(
            f"apply_bodylength_calibration requires mode='bodylength', got '{cfg.mode}'.",
            code="CAL-BL-MODE",
            remediation="Set CalibrationConfig(mode='bodylength').",
        )

    session = psess.session

    if session.body_length_px is None:
        raise CalibrationError(
            "Session has no body_length_px data; cannot apply body-length calibration.",
            code="CAL-BL-MISSING",
            remediation=(
                "Run extract_bboxes to compute per-animal body lengths, or switch to "
                "scalar calibration mode."
            ),
        )

    if psess.n_frames < cfg.bl_min_samples:
        raise CalibrationError(
            f"Session has only {psess.n_frames} frames but bl_min_samples={cfg.bl_min_samples}. "
            "Body-length calibration requires more data.",
            code="CAL-BL-SAMPLES",
            remediation=(
                f"Use sessions with at least {cfg.bl_min_samples} frames, or lower "
                "bl_min_samples in CalibrationConfig."
            ),
        )

    body_length_px: np.ndarray = session.body_length_px.astype(np.float64)
    length_unit: float | None = session.length_unit

    if length_unit is not None and length_unit == 0.0:
        raise CalibrationError(
            "session.length_unit is 0, which would cause division by zero.",
            code="CAL-BL-UNIT-ZERO",
            remediation="Correct the length_unit value in the session source data.",
        )

    if length_unit is not None and length_unit > 0:
        body_length_cm = body_length_px / length_unit
        return dataclasses.replace(
            psess,
            body_length_cm=body_length_cm,
            px_per_cm=length_unit,
        )

    # No length_unit: store body lengths in pixel units under body_length_cm.
    body_length_cm = body_length_px.copy()
    return dataclasses.replace(psess, body_length_cm=body_length_cm)
