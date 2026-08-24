"""Per-session body-length normalisation calibration.

Public API
----------
apply_bodylength_calibration  -- derive body_length_cm from
                                  Session.body_length_px.

Changed: this mode used to also silently divide by Session.length_unit
when present, setting px_per_cm=length_unit -- so every "*_cm" export
column was quietly calibrated from a value the user never confirmed
using. That is now what "session" mode
(track2data/calibration/session_unit.py) does explicitly, with a
required user confirmation in the GUI (CalibrationConfig.
length_unit_confirmed_by_user). "bodylength" mode always stores raw
body-length-derived values (in pixels; the "_cm" field name is a
long-standing misnomer kept for downstream interface stability) and
never reads length_unit for calibration purposes.
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
    3. **Stores body lengths as-is**: ``body_length_cm = body_length_px``
       (values remain in pixels; the field name is a long-standing
       misnomer kept for downstream interface stability). ``px_per_cm``
       is left unset. ``session.length_unit`` is not read here at all --
       see this module's docstring for why, and use ``mode='session'``
       for a px-per-cm value derived from it.

    Parameters
    ----------
    psess:
        The preprocessed session to calibrate.
    cfg:
        Calibration configuration.  ``cfg.mode`` must be ``'bodylength'``.

    Returns
    -------
    PreprocessedSession
        A copy of *psess* with ``body_length_cm`` populated.

    Raises
    ------
    CalibrationError
        * ``cfg.mode != 'bodylength'``
        * ``session.body_length_px`` is ``None``
        * ``psess.n_frames < cfg.bl_min_samples``
        * ``session.length_unit`` is exactly ``0`` -- a defensive guard
          against corrupt session data; kept even though this mode no
          longer *uses* length_unit, since a session shipping a literal
          zero there points at a data problem worth surfacing regardless.
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

    if session.length_unit is not None and session.length_unit == 0.0:
        raise CalibrationError(
            "session.length_unit is exactly 0, which is not a valid calibration "
            "ratio for any mode; this session's source data looks corrupt.",
            code="CAL-BL-UNIT-ZERO",
            remediation="Correct the length_unit value in the session source data.",
        )

    # Body lengths are always stored in pixel units here -- see this
    # module's docstring for why length_unit is never consumed for
    # conversion in this mode.
    body_length_cm = body_length_px.copy()
    return dataclasses.replace(psess, body_length_cm=body_length_cm)
