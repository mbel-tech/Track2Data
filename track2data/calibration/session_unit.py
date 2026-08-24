"""Per-session length-unit calibration.

Public API
----------
apply_session_calibration  -- set psess.px_per_cm from the session's own
                               Session.length_unit, rather than one
                               project-wide scalar value or a derived
                               body-length ratio.
"""

from __future__ import annotations

import dataclasses

from track2data.core.errors import CalibrationError
from track2data.core.models import CalibrationConfig, PreprocessedSession


def apply_session_calibration(
    psess: PreprocessedSession,
    cfg: CalibrationConfig,
) -> PreprocessedSession:
    """Apply per-session length-unit calibration.

    Unlike ``scalar`` mode (one project-wide ``px_per_cm``) or
    ``bodylength`` mode (a per-individual ratio derived from bounding
    boxes), this mode trusts each session's own ``length_unit`` --
    idtracker.ai's own record of the validator's Length Calibration
    tool ratio for *that* recording -- so different sessions in the
    same project can legitimately have different ``px_per_cm`` values.

    Parameters
    ----------
    psess:
        The preprocessed session to calibrate.
    cfg:
        Calibration configuration. ``cfg.mode`` must be ``'session'``.

    Returns
    -------
    PreprocessedSession
        A copy of *psess* with ``px_per_cm`` set from
        ``psess.session.length_unit``.

    Raises
    ------
    CalibrationError
        * ``cfg.mode != 'session'``
        * ``session.length_unit`` is ``None`` -- this session was never
          run through the validator's calibration tool (or its
          length_unit failed normalisation; see
          IDT_LENGTH_UNIT_INVALID in the reader logs for which).
    """
    if cfg.mode != "session":
        raise CalibrationError(
            f"apply_session_calibration requires mode='session', got '{cfg.mode}'.",
            code="CAL-SESSION-MODE",
            remediation="Set CalibrationConfig(mode='session').",
        )

    session = psess.session

    if session.length_unit is None:
        raise CalibrationError(
            f"Session '{session.session_id}' has no length_unit -- it was never "
            "calibrated in the idtracker.ai validator (or its length_unit was "
            "invalid; check the reader log for IDT_LENGTH_UNIT_INVALID).",
            code="CAL-SESSION-MISSING",
            subject=session.session_id,
            remediation=(
                "Calibrate this session's length in the idtracker.ai validator "
                "and re-export, or switch to scalar or body-length calibration mode."
            ),
        )

    return dataclasses.replace(psess, px_per_cm=session.length_unit)
