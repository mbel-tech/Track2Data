"""PP-5 coverage validation gate — warn on animals with excessive NaN frames."""

from __future__ import annotations

import logging

import numpy as np

from track2data.core.models import PPStepResult, ValidateCfg

logger = logging.getLogger(__name__)


def validate_coverage(
    xy: np.ndarray,
    cfg: ValidateCfg,
    session_id: str = "",
) -> PPStepResult:
    """Check per-animal NaN coverage and warn if any animal exceeds the threshold.

    This function does **not** modify *xy*.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
    cfg:
        Validation configuration including ``max_pct_na_per_individual``.
    session_id:
        Optional identifier included in log messages.

    Returns
    -------
    PPStepResult
        ``affected_frames`` = total NaN frames for animals that exceed the
        threshold.  ``notes`` contains a human-readable summary of failures.
    """
    n_frames, n_animals, _ = xy.shape

    nan_mask = np.isnan(xy[:, :, 0])  # (n_frames, n_animals)
    nan_counts = nan_mask.sum(axis=0)  # (n_animals,)
    pct_nan = nan_counts / n_frames  # (n_animals,)

    threshold = cfg.max_pct_na_per_individual
    failures: list[str] = []
    affected_per_individual: list[int] = []
    total_affected = 0

    for k in range(n_animals):
        pct = float(pct_nan[k])
        if pct > threshold:
            msg = (
                f"Animal {k} has {pct:.1%} NaN frames "
                f"(threshold {threshold:.1%})"
                + (f" in session '{session_id}'" if session_id else "")
            )
            logger.warning(msg)
            failures.append(f"animal {k}: {pct:.1%} NaN")
            affected_per_individual.append(int(nan_counts[k]))
            total_affected += int(nan_counts[k])
        else:
            affected_per_individual.append(0)

    notes = "; ".join(failures)

    return PPStepResult(
        step_name="validate_coverage",
        affected_frames=total_affected,
        affected_per_individual=affected_per_individual,
        notes=notes,
    )
