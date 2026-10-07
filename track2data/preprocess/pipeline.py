"""Ordered preprocessing pipeline: gap_fill → jump_detect → identity_switch → smoothing → validate.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from track2data.core.models import (
    PreprocessConfig,
    PreprocessedSession,
    PreprocessReport,
    Session,
)
from track2data.preprocess.gap_fill import fill_gaps
from track2data.preprocess.identity_switch import correct_switches
from track2data.preprocess.jump_detect import detect_jumps
from track2data.preprocess.kinematics import compute_kinematics
from track2data.preprocess.smoothing import smooth_trajectories
from track2data.preprocess.validate import validate_coverage


def run(
    session: Session,
    config: PreprocessConfig,
    *,
    check: Callable[[], None] | None = None,
) -> PreprocessedSession:
    """Run the full preprocessing pipeline on a session.

    Steps applied in order:

    1. Gap fill (linear interpolation of short NaN gaps)
    2. Jump detection (flag and replace anomalous displacements)
    3. Identity-switch correction (Tier-1 ratio + Tier-2 Hungarian)
    4. Smoothing (Savitzky-Golay or moving average)
    5. Coverage validation (warn on excessive NaN)

    After the pipeline, kinematics (speed, acceleration, heading) are
    computed on the final preprocessed array.

    Parameters
    ----------
    session:
        Input session.  ``session.raw_xy`` is never mutated.
    config:
        Full preprocessing configuration.
    check:
        Optional zero-argument callable run before each step so a
        cancellation request is noticed between steps; whatever it raises
        (``OperationCancelled``) propagates.

    Returns
    -------
    PreprocessedSession
        Contains the preprocessed xy array, kinematics, and a full
        ``PreprocessReport`` with one ``PPStepResult`` per step.
    """
    report = PreprocessReport()

    def _checkpoint(_step: str) -> None:
        if check is not None:
            check()

    # Start from a copy of raw_xy so the original is never touched.
    xy: np.ndarray = session.raw_xy.copy()

    # 1. Gap fill
    _checkpoint("gap fill")
    crossing_mask = None
    if session.fragments is not None:
        from track2data.readers.idtrackerai.fragments import crossing_frame_mask
        crossing_mask = crossing_frame_mask(session.fragments, session.n_frames)
    xy, step = fill_gaps(xy, config.gap_fill, crossing_frame_mask=crossing_mask)
    report.steps.append(step)

    # 2. Jump detection
    _checkpoint("jump detection")
    xy, step = detect_jumps(
        xy, config.jump, velocity_threshold_px_frame=session.velocity_threshold_px_frame
    )
    report.steps.append(step)

    # 3. Identity-switch correction
    _checkpoint("identity-switch correction")
    xy, step = correct_switches(xy, config.identity_switch)
    report.steps.append(step)

    # 4. Smoothing
    _checkpoint("smoothing")
    xy, step = smooth_trajectories(xy, config.smoothing)
    report.steps.append(step)

    # 5. Coverage validation
    _checkpoint("coverage validation")
    step = validate_coverage(xy, config.coverage, session_id=session.session_id)
    report.steps.append(step)

    # Compute kinematics on final preprocessed xy
    kinematics = compute_kinematics(xy, fps=session.video.fps)

    return PreprocessedSession(
        session=session,
        xy=xy,
        kinematics=kinematics,
        report=report,
    )
