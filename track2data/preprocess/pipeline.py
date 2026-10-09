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
from track2data.preprocess.timeline_expand import bridge_gaps, lay_out, plan_expansion
from track2data.preprocess.validate import validate_coverage


def _replaced_mask(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """(n_frames, n_animals) bool: positions a step changed or removed.

    "Was present and is no longer the same value" -- so a pre-existing NaN
    left alone does not count, and neither does a position the step declined
    to touch. ``equal_nan=True`` keeps an untouched NaN out of the mask; a
    position replaced *by* NaN still lands in it, because it was present
    before.
    """
    was_present = ~np.isnan(before[:, :, 0])
    unchanged = np.isclose(
        before[:, :, 0], after[:, :, 0], equal_nan=True
    ) & np.isclose(before[:, :, 1], after[:, :, 1], equal_nan=True)
    return was_present & ~unchanged


def run(
    session: Session,
    config: PreprocessConfig,
    *,
    check: Callable[[], None] | None = None,
    bridge_allowed: bool = True,
) -> PreprocessedSession:
    """Run the full preprocessing pipeline on a session.

    Steps applied in order:

    1. Gap fill (linear interpolation of short NaN gaps)
    2. Jump detection (flag and replace anomalous displacements)
    3. Identity-switch correction (constant-velocity prediction + Hungarian
       assignment, restricted to fragment boundaries when available)
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
    bridge_allowed:
        False when the caller knows the session must be treated as identity-free (the user's
        own override), which forbids bridging gaps between tracking intervals.

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

    # 0. Real elapsed time. A session stored as tracking intervals gets its unobserved stretches
    # back as rows (bridged) or as one NaN separator row each, so no later step reads two
    # intervals as adjacent frames. None for a session whose rows already are its frames.
    expansion = plan_expansion(session, config.gap_fill, bridge_allowed=bridge_allowed)
    raw_rows = id_prob_rows = None
    if expansion is not None:
        raw_rows = lay_out(expansion, session.raw_xy)
        if session.id_probabilities is not None:
            id_prob_rows = lay_out(expansion, session.id_probabilities)
        xy = raw_rows.copy()
        if expansion.bridged_mask.any():
            _checkpoint("gap fill across tracking intervals")
            xy, step = bridge_gaps(xy, expansion)
            report.steps.append(step)

    # 1. Gap fill
    _checkpoint("gap fill")
    crossing_mask = None
    if session.fragments is not None:
        from track2data.readers.idtrackerai.fragments import crossing_frame_mask
        if expansion is None:
            crossing_mask = crossing_frame_mask(session.fragments, session.n_frames)
        else:
            # fragments are numbered in video frames, so read them off the frame axis
            on_frames = crossing_frame_mask(
                session.fragments, int(expansion.frame_index.max()) + 1
            )
            crossing_mask = on_frames[expansion.frame_index]
    xy, step = fill_gaps(
        xy,
        config.gap_fill,
        crossing_frame_mask=crossing_mask,
        protected_rows=None if expansion is None else ~expansion.tracked_mask,
    )
    report.steps.append(step)

    # 2. Jump detection
    _checkpoint("jump detection")
    # Captured by comparison, the same way PreprocessedSession.was_interpolated
    # compares raw_xy to the final array. It has to happen here rather than at
    # the end: smoothing (step 4) moves every position, so "differs from the
    # input" stops isolating this step once it runs. detect_jumps returns a
    # new array and never mutates its input, so `before_jumps` stays valid.
    before_jumps = xy
    xy, step = detect_jumps(
        xy, config.jump, velocity_threshold_px_frame=session.velocity_threshold_px_frame
    )
    jump_replaced = _replaced_mask(before_jumps, xy)
    report.steps.append(step)

    # 3. Identity-switch correction
    _checkpoint("identity-switch correction")
    # Fragment boundaries are the only frames where a swap is physically
    # possible, so hand them over when the session carries them -- same
    # opportunistic pattern as the crossing mask above. Without them the
    # corrector falls back to scanning every frame, which is why the step
    # stays off by default (IdSwitchCfg's docstring).
    swap_boundaries = None
    if session.fragments is not None:
        from track2data.readers.idtrackerai.fragments import fragment_swap_boundaries
        swap_boundaries = fragment_swap_boundaries(session.fragments)
        if expansion is not None:
            # boundary frames -> the rows that carry those frames
            rows = np.flatnonzero(np.isin(expansion.frame_index, list(swap_boundaries)))
            swap_boundaries = {int(r) for r in rows}
    xy, step = correct_switches(
        xy, config.identity_switch, swap_boundaries=swap_boundaries
    )
    report.steps.append(step)

    # 4. Smoothing
    _checkpoint("smoothing")
    xy, step = smooth_trajectories(xy, config.smoothing)
    report.steps.append(step)

    # 5. Coverage validation
    _checkpoint("coverage validation")
    # Coverage is about what the tracker delivered, so only the stored rows count.
    observed = xy if expansion is None else xy[expansion.tracked_mask]
    step = validate_coverage(observed, config.coverage, session_id=session.session_id)
    report.steps.append(step)

    # Compute kinematics on final preprocessed xy
    kinematics = compute_kinematics(xy, fps=session.video.fps, cfg=config.kinematics)

    extra: dict = {}
    if expansion is not None:
        extra = {
            "frame_index": expansion.frame_index,
            "timeline_valid": True,
            "tracked_mask": expansion.tracked_mask,
            "separator_mask": expansion.separator_mask,
            "raw_xy_rows": raw_rows,
            "id_probabilities_rows": id_prob_rows,
        }
    return PreprocessedSession(
        session=session,
        xy=xy,
        kinematics=kinematics,
        report=report,
        jump_replaced=jump_replaced,
        **extra,
    )
