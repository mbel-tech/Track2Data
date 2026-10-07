"""PP-3 identity-switch correction: constant-velocity prediction + Hungarian assignment.

Off by default (IdSwitchCfg.enabled=False) -- see the docstring on
IdSwitchCfg in core/models.py for why. This module still exists so callers
who understand the risk can opt in, and so a fragment-boundary-aware
replacement (planned) has somewhere to land, but it must not run
unconditionally in the default pipeline.

The correction rests on one physical fact: an identity switch is a
*persistent* relabelling from the switch point onward, and it can only
happen where two animals were confusable -- at an idtracker.ai fragment
boundary. Both halves of that are load-bearing here:

* the relabelling persists. It is tracked as a running permutation that
  stays in effect until some later frame changes it, not applied to one
  frame at a time. A single-frame permutation converts one discontinuity
  into two, which is worse for speed, acceleration and IL-1 than leaving
  the switch in place.
* when ``swap_boundaries`` is supplied from
  ``readers.idtrackerai.fragments.fragment_swap_boundaries``, only those
  frames are considered at all. Everywhere else a swap is physically
  impossible, so evaluating it can only manufacture false positives.

Without fragment data the search falls back to every frame, which is why
the feature stays opt-in: geometry alone cannot distinguish "these two
animals crossed and were relabelled" from "these two animals crossed".

Cost note: the running permutation is materialised into the output array
once, as one disjoint slice assignment per switch, so the whole pass is
O(n_frames x n_animals) no matter how many switches are found. Physically
permuting the remaining tail at each accepted switch instead would be
quadratic, which on a dense fragment-less session does not terminate in
any useful time.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.optimize import linear_sum_assignment

from track2data.core.models import IdSwitchCfg, PPStepResult

logger = logging.getLogger(__name__)


def _predict_next(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Constant-velocity prediction of the next frame from two known frames.

    Constant *velocity*, not constant position: a crossing is exactly the
    case where two animals are close together and moving, so a
    constant-position prediction fails precisely where this step exists to
    help.

    Falls back to constant position wherever the previous frame is missing
    -- a NaN velocity would otherwise poison a prediction whose current
    frame is perfectly usable.

    Parameters
    ----------
    previous, current:
        Positions at frames *t-1* and *t*, each shape ``(n_animals, 2)``.

    Returns
    -------
    np.ndarray
        Predicted positions at *t+1*, shape ``(n_animals, 2)``.
    """
    velocity = current - previous
    return current + np.where(np.isnan(velocity), 0.0, velocity)


def _prediction_cost(pred: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """Distances from each predicted position to each observed position.

    ``cost[k, j]`` is how far identity *k* would have to travel to reach
    observation *j*. Rows are identity slots, columns are observations, so
    the diagonal is the cost of believing the tracker.

    This is the matrix the module docstring has always described. The
    previous implementation instead computed distances *among conspecifics
    within a single frame*, which is a proximity detector rather than an
    assignment-ambiguity detector -- and, because self-distance had to be
    excluded from it, left only one finite distance for a dyad and so could
    never fire at ``n_animals == 2``.

    Parameters
    ----------
    pred:
        Predicted positions, shape ``(n_animals, 2)``.
    obs:
        Observed positions, shape ``(n_animals, 2)``.

    Returns
    -------
    np.ndarray
        Cost matrix of shape ``(n_animals, n_animals)``.
    """
    diff = pred[:, np.newaxis, :] - obs[np.newaxis, :, :]  # (n, n, 2)
    return np.sqrt((diff ** 2).sum(axis=-1))


def correct_switches(
    xy: np.ndarray,
    cfg: IdSwitchCfg,
    swap_boundaries: set[int] | None = None,
) -> tuple[np.ndarray, PPStepResult]:
    """Correct identity switches in multi-animal trajectory data.

    For each candidate frame *t*, positions at *t+1* are predicted from
    *t-1* and *t* by constant velocity, and a cost matrix is built between
    those predictions and the observations at *t+1*.

    Tier-1 (cheap gate): when the tracker's own labelling is already each
    identity's nearest observation, the frame is skipped without further
    work.

    Tier-2: on flagged frames, Hungarian assignment
    (``scipy.optimize.linear_sum_assignment``) finds the globally optimal
    permutation. It is accepted only when it beats the tracker's labelling
    by a factor of at least ``cfg.tier1_ratio``, so ties and noise-level
    differences leave the data alone. An accepted permutation is composed
    into the running relabelling and stays in effect for every later frame
    until another accepted permutation changes it.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Identity-switch correction configuration. ``cfg.tier1_ratio`` is the
        margin by which a permutation must beat the identity assignment
        before it is accepted. ``cfg.consolidate_window`` is no longer read:
        a switch persists until superseded rather than for a fixed window.
    swap_boundaries:
        Frames at which an identity swap is physically possible, from
        ``readers.idtrackerai.fragments.fragment_swap_boundaries``. Those are
        fragment ``end_frame`` values, which idtracker.ai stores *exclusive*,
        so a boundary *b* is the first frame of the following fragment and
        the permutation it licenses applies from *b* onward. When ``None``,
        every frame is a candidate -- correct, but far more
        false-positive-prone, so prefer supplying it.

    Returns
    -------
    out:
        New array (input not mutated) with corrected identities.
    result:
        ``PPStepResult`` describing corrected frames.
    """
    n_frames, n_animals, _ = xy.shape

    if not cfg.enabled or n_animals < 2 or n_frames < 3:
        return xy.copy(), PPStepResult(
            step_name="identity_switch",
            affected_frames=0,
            affected_per_individual=[0] * n_animals,
        )

    logger.warning(
        "Identity-switch correction is enabled (preprocess.identity_switch.enabled) "
        "and re-labels trajectories from %s. Review the corrected output before "
        "publishing numbers computed from it.",
        "geometry within idtracker.ai fragment boundaries"
        if swap_boundaries
        else "geometry alone, with no fragment boundaries to constrain it",
    )

    identity = np.arange(n_animals)

    # ``active[k]`` is the column of the *input* array that currently holds
    # identity k. Segments record the frame from which each successive value
    # of it takes effect; the array is rebuilt from them in one pass at the
    # end, which is what keeps this linear.
    active = identity.copy()
    segments: list[tuple[int, np.ndarray]] = [(0, active.copy())]

    # *t* is the last frame believed correct, so any permutation applies
    # from t+1 onward.
    #
    # fragment_swap_boundaries() reports each fragment's ``end_frame``, which
    # is EXCLUSIVE (fragments.py defensive-parsing rule 5): a fragment with
    # end_frame=21 covers frames 0..20, so frame 21 is the first frame of
    # whatever follows and a swap there shows up between 20 and 21. The
    # candidate is therefore b-1, not b -- evaluating b directly corrects one
    # frame late and leaves the switch itself in the data.
    if swap_boundaries is None:
        candidates: list[int] = list(range(1, n_frames - 1))
    else:
        candidates = sorted(
            b - 1 for b in swap_boundaries if 1 <= b - 1 < n_frames - 1
        )

    for t in candidates:
        previous = xy[t - 1][active]
        current = xy[t][active]
        obs = xy[t + 1][active]

        pred = _predict_next(previous, current)
        if np.any(np.isnan(pred)) or np.any(np.isnan(obs)):
            continue

        cost = _prediction_cost(pred, obs)

        # Tier-1: the tracker's labelling is already each identity's nearest
        # observation, so there is nothing to reassign.
        if np.array_equal(np.argmin(cost, axis=1), identity):
            continue

        if cfg.tier2_hungarian:
            _, perm = linear_sum_assignment(cost)
        else:
            # Greedy row-wise nearest, usable only when it happens to come out
            # a valid permutation -- the honest meaning of "no Hungarian".
            perm = np.argmin(cost, axis=1)
            if np.unique(perm).size != n_animals:
                continue

        if np.array_equal(perm, identity):
            continue

        # Accept only a decisive improvement. Equal costs (two animals at the
        # same point mid-crossing) must leave the data untouched: permuting on
        # a tie invents a switch the geometry does not evidence.
        cost_identity = float(cost[identity, identity].sum())
        cost_perm = float(cost[identity, perm].sum())
        if cost_identity <= cfg.tier1_ratio * cost_perm:
            continue

        active = active[perm]
        segments.append((t + 1, active.copy()))

    # ── materialise ───────────────────────────────────────────────────────────
    out = xy.copy()
    # Frames whose identity assignment ends up differing from the tracker's --
    # NOT "every animal, every time a swap happened anywhere" (behaviour
    # removed earlier, which overstated corrections by ~4x on real data and
    # fed that inflated number straight into the exported README's
    # provenance).
    affected_frames = 0
    affected_per_individual = [0] * n_animals

    for i, (start, perm) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else n_frames
        if np.array_equal(perm, identity):
            continue
        out[start:end] = xy[start:end][:, perm, :]
        span = end - start
        affected_frames += span
        for k in range(n_animals):
            if perm[k] != k:
                affected_per_individual[k] += span

    return out, PPStepResult(
        step_name="identity_switch",
        affected_frames=affected_frames,
        affected_per_individual=affected_per_individual,
    )
