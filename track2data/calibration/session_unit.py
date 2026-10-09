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
import logging
import math
import statistics
from typing import Any

from track2data.core.errors import CalibrationError
from track2data.core.models import CalibrationConfig, PreprocessedSession

logger = logging.getLogger(__name__)

#: Relative SD between calibration clicks above which every *_cm value of the
#: session is flagged as carrying a visible calibration error. 5% means the
#: clicks disagree by more than the difference between an exact and a sloppy
#: ruler placement; Track2Data's choice, not an idtracker.ai constant.
CALIBRATION_SPREAD_WARN = 0.05


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
    scale = session_scale(
        session.length_unit, session.length_calibrations, cfg.session_calibration_stat
    )

    if scale is None:
        raise CalibrationError(
            f"Session '{session.session_id}' has no length_unit -- it was never "
            "calibrated in the idtracker.ai validator (or its length_unit was "
            "invalid; check the reader log for IDT_LENGTH_UNIT_INVALID), or, for another "
            "tracker, no scale was given at import.",
            code="CAL-SESSION-MISSING",
            subject=session.session_id,
            remediation=(
                "Calibrate this session's length in the idtracker.ai validator "
                "and re-export, or switch to scalar or body-length calibration mode."
            ),
        )

    n_clicks, rel_sd = length_calibration_spread(session.length_calibrations)
    if rel_sd is not None and rel_sd > CALIBRATION_SPREAD_WARN:
        logger.warning(
            "Session '%s': its %d length-calibration clicks disagree by %.1f%% "
            "(relative SD); every *_cm value inherits at least that error.",
            session.session_id,
            n_clicks,
            100 * rel_sd,
        )
    ratios = calibration_ratios(session.length_calibrations)
    if ratios and session.length_unit and cfg.session_calibration_stat == "mean":
        # idtracker.ai defines length_unit as the mean of the calibrations; a stored value that
        # differs (calibrations edited after export) is kept, but the user should know.
        recomputed = statistics.fmean(ratios)
        if abs(recomputed - session.length_unit) > 1e-6 * session.length_unit:
            logger.warning(
                "Session '%s': length_unit (%.6g) differs from the mean of its length "
                "calibrations (%.6g); the stored length_unit was used.",
                session.session_id,
                session.length_unit,
                recomputed,
            )
    return dataclasses.replace(psess, px_per_cm=scale, px_per_cm_rel_sd=rel_sd)


def calibration_ratios(calibrations: list[dict[str, Any]] | None) -> list[float]:
    """Pixels per unit from each usable calibration click pair; malformed entries are skipped."""
    ratios: list[float] = []
    for entry in calibrations or []:
        try:
            ax, ay = entry["point_A"]
            bx, by = entry["point_B"]
            distance = float(entry["distance"])
            px = math.hypot(float(bx) - float(ax), float(by) - float(ay))
        except (KeyError, TypeError, ValueError):
            continue
        if distance > 0 and px > 0 and math.isfinite(px) and math.isfinite(distance):
            ratios.append(px / distance)
    return ratios


def session_scale(
    length_unit: float | None,
    calibrations: list[dict[str, Any]] | None,
    stat: str = "mean",
) -> float | None:
    """The pixels-per-unit a session is calibrated with, or None when it has none.

    ``"mean"`` is the session's own ``length_unit`` (idtracker.ai records the mean of its
    calibrations). ``"median"`` is the median of the usable per-calibration ratios, falling back
    to ``length_unit`` when there are none (every non-idtracker.ai session). A session without a
    valid ``length_unit`` is uncalibrated whatever its calibrations hold. Nothing here raises on
    odd input.
    """
    own = (
        float(length_unit)
        if isinstance(length_unit, int | float) and math.isfinite(length_unit) and length_unit > 0
        else None
    )
    if own is None:
        # idtracker.ai writes -1 for "never calibrated"; clicks next to it do not override that.
        return None
    ratios = calibration_ratios(calibrations)
    if stat == "median" and ratios:
        return float(statistics.median(ratios))
    return own


def length_calibration_spread(
    calibrations: list[dict[str, Any]] | None,
) -> tuple[int, float | None]:
    """``(n_usable, relative_sd)`` over a session's calibration clicks.

    ``Session.length_unit`` is the mean of several Validator calibration
    measurements (``length_calibrations``); the scatter between them is the
    only direct uncertainty estimate on every calibrated metric. Each entry
    is ``{"point_A": [x, y], "point_B": [x, y], "distance": d}``; its ratio is
    the pixel distance between the points over ``d``.

    ``relative_sd`` is the sample standard deviation of those ratios divided
    by their mean, or None when fewer than two usable entries exist (one
    click carries no spread). Malformed entries are skipped, never fatal.
    """
    ratios = calibration_ratios(calibrations)
    n = len(ratios)
    if n < 2:
        return n, None
    mean = sum(ratios) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in ratios) / (n - 1))
    return n, sd / mean
