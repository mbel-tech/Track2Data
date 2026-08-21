"""PP-3 identity-switch correction using Tier-1 ratio test and Tier-2 Hungarian assignment.

Off by default (IdSwitchCfg.enabled=False) -- see the docstring on
IdSwitchCfg in core/models.py for why. This module still exists so callers
who understand the risk can opt in, and so a fragment-boundary-aware
replacement (planned) has somewhere to land, but it must not run
unconditionally in the default pipeline.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment  # type: ignore[import-untyped]

from track2data.core.models import IdSwitchCfg, PPStepResult


def _pairwise_distances(positions: np.ndarray) -> np.ndarray:
    """Compute pairwise Euclidean distance matrix for n_animals positions.

    Parameters
    ----------
    positions:
        Array of shape ``(n_animals, 2)``.

    Returns
    -------
    np.ndarray
        Distance matrix of shape ``(n_animals, n_animals)``.
    """
    diff = positions[:, np.newaxis, :] - positions[np.newaxis, :, :]  # (n, n, 2)
    return np.sqrt((diff ** 2).sum(axis=-1))


def _apply_permutation(xy: np.ndarray, frame: int, perm: np.ndarray) -> None:
    """Apply an animal-index permutation in-place at a specific frame."""
    xy[frame] = xy[frame][perm]


def correct_switches(xy: np.ndarray, cfg: IdSwitchCfg) -> tuple[np.ndarray, PPStepResult]:
    """Correct identity switches in multi-animal trajectory data.

    Tier-1: For each consecutive pair of frames, build the distance matrix
    between predicted next positions (extrapolated from *t-1* to *t*) and
    observed positions at *t+1*.  If the nearest-neighbour assignment is
    ambiguous (ratio of best to second-best distance < ``cfg.tier1_ratio``),
    flag the frame for Tier-2.

    Tier-2: For flagged regions, run Hungarian assignment
    (``scipy.optimize.linear_sum_assignment``) on the pairwise distance matrix
    within a ``cfg.consolidate_window``-frame window to find the globally optimal
    identity permutation.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Identity-switch correction configuration.

    Returns
    -------
    out:
        New array (input not mutated) with corrected identities.
    result:
        ``PPStepResult`` describing corrected frames.
    """
    n_frames, n_animals, _ = xy.shape
    out = xy.copy()

    if not cfg.enabled or n_animals < 2:
        return out, PPStepResult(
            step_name="identity_switch",
            affected_frames=0,
            affected_per_individual=[0] * n_animals,
        )

    corrected_frames: set[int] = set()
    # Per-identity slot indices that were actually permuted at some frame --
    # NOT "every animal, every time a swap happened anywhere" (the previous
    # behaviour), which overstated corrections in PreprocessReport by ~4x on
    # real data (10,224 reported vs 2,556 actual events on a 4-animal
    # session) and fed that inflated number straight into the exported
    # README's provenance.
    affected_per_individual = [0] * n_animals

    for t in range(1, n_frames - 1):
        # Skip frames with any NaN
        if np.any(np.isnan(out[t])) or np.any(np.isnan(out[t + 1])):
            continue

        # Cost matrix: distance from current position (t) to next positions (t+1)
        cost = _pairwise_distances(out[t])  # (n_animals, n_animals)

        # Tier-1: check each animal's nearest neighbour ratio
        ambiguous = False
        for k in range(n_animals):
            row = cost[k].copy()
            row[k] = np.inf  # exclude self
            if row.min() == np.inf:
                continue
            sorted_dists = np.sort(row[row < np.inf])
            if sorted_dists.size >= 2 and sorted_dists[0] > 0:
                ratio = sorted_dists[1] / sorted_dists[0]
                if ratio < cfg.tier1_ratio:
                    ambiguous = True
                    break

        if not ambiguous:
            continue

        # Tier-2: Hungarian assignment over consolidate_window
        if cfg.tier2_hungarian:
            win_end = min(t + cfg.consolidate_window, n_frames)
            for tf in range(t, win_end):
                if tf + 1 >= n_frames:
                    break
                if np.any(np.isnan(out[tf])) or np.any(np.isnan(out[tf + 1])):
                    continue
                cost_matrix = _pairwise_distances(out[tf + 1])
                # Build cost: distance from predicted position (out[tf]) to candidates
                pred_cost = np.zeros((n_animals, n_animals), dtype=np.float64)
                for ki in range(n_animals):
                    for kj in range(n_animals):
                        pred_cost[ki, kj] = np.sqrt(
                            (out[tf + 1, kj, 0] - out[tf, ki, 0]) ** 2
                            + (out[tf + 1, kj, 1] - out[tf, ki, 1]) ** 2
                        )
                _, col_ind = linear_sum_assignment(pred_cost)
                # col_ind[k] = which observed animal is assigned to identity k
                perm = col_ind  # permutation of observations → identities
                # Only apply if perm is not identity
                if not np.all(perm == np.arange(n_animals)):
                    out[tf + 1] = out[tf + 1][perm]
                    corrected_frames.add(tf + 1)
                    for k in range(n_animals):
                        if perm[k] != k:
                            affected_per_individual[k] += 1
        else:
            # Tier-1 swap: find best swap pair
            cost_matrix = _pairwise_distances(out[t])
            _, col_ind = linear_sum_assignment(cost_matrix)
            if not np.all(col_ind == np.arange(n_animals)):
                out[t + 1] = out[t + 1][col_ind]
                corrected_frames.add(t + 1)
                for k in range(n_animals):
                    if col_ind[k] != k:
                        affected_per_individual[k] += 1

    total_affected = len(corrected_frames)

    return out, PPStepResult(
        step_name="identity_switch",
        affected_frames=total_affected,
        affected_per_individual=affected_per_individual,
    )
