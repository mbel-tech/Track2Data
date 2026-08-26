"""
Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion interval
(BCI) estimation.

Several metrics debounce a boolean state series (a zone-membership
flag, a speed-below-threshold "inactive" flag) by dropping runs
shorter than some minimum length -- IL-7's ``min_bout_frames``, Z-3's
``min_visit_frames``, Z-4/Z-5's ``min_dwell_frames`` (Z-6 and Z-9
inherit it by forwarding their own cfg to Z-5's ``compute()``). Each of
these used to be a fixed, hand-picked round number. This module
derives that number from the session's own data instead: pool the
observed run-length distribution, fit a two-segment ("broken-stick")
line to its log-survivorship curve, and take the duration at the
segments' crossover as the criterion -- runs shorter than it are
within-bout noise (tracking flicker, a brief pause), runs at or above
it are genuine.

This is the classic technique from Sibly et al. 1990 ("Splitting
behaviour into bouts", Anim. Behav. 39:63-69), applied here to
run-DURATION distributions rather than the paper's own worked example
of GAP durations between successive events -- the same statistical
question (does this duration distribution separate into a short,
spurious population and a long, genuine one, and where is the
boundary?), asked of a different quantity. Metrics that use this
module say so in their own documentation rather than implying the
citation covers this exact use case.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Below this many observed intervals there is not enough data to trust
# a two-segment fit -- the log-survivorship curve of a handful of
# points can "look" broken by chance. Sibly et al. 1990 themselves
# note the method needs a reasonably large sample; this is a
# conservative floor, not a value taken from the paper.
DEFAULT_MIN_INTERVALS = 10

# Each of the two fitted line segments needs enough points of its own
# to be a meaningful regression rather than a line through a handful of
# points at the extreme tail, which is trivially near-zero-residual --
# a naive search is drawn to exactly that spurious "fit" even on
# genuinely unimodal data. Expressed as a fraction of the number of
# distinct duration values (floored by DEFAULT_MIN_SEGMENT_POINTS_ABS),
# so a candidate breakpoint is only considered in the interior of the
# curve, never within shouting distance of either end.
DEFAULT_MIN_SEGMENT_FRACTION = 0.2
DEFAULT_MIN_SEGMENT_POINTS_ABS = 3

# The two-segment fit must reduce total squared error versus a single
# line by at least this fraction, or the "bimodal" structure the
# method depends on isn't actually there -- accepting a break point on
# an essentially straight log-survivorship curve would return a
# criterion that doesn't separate two real populations. This threshold
# is an engineering choice documented here, not a value from the paper.
DEFAULT_MIN_IMPROVEMENT = 0.05


@dataclass(frozen=True)
class BoutCriterionResult:
    """Result of one BCI fit.

    ``converged`` is False whenever the fit should not be trusted --
    too few intervals, too few distinct duration values, or a
    two-segment fit that doesn't meaningfully beat a single line.
    Callers must fall back to a fixed default when this is False, and
    should record that the fallback happened rather than silently
    using ``threshold_frames`` (which is 0, a deliberately unusable
    sentinel, whenever ``converged`` is False).
    """

    threshold_frames: int
    converged: bool
    n_intervals: int


def _log_survivorship(durations: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unique sorted duration values and log(count of intervals >= that
    value) at each -- the log-survivorship curve Sibly et al. 1990 fit
    their broken-stick model to."""
    unique_d = np.unique(durations)
    counts_at_or_above = np.array(
        [np.sum(durations >= d) for d in unique_d], dtype=np.float64
    )
    return unique_d, np.log(counts_at_or_above)


def _line_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Least-squares (slope, sse) of the best-fit line through (x, y)."""
    if len(x) < 2 or float(np.ptp(x)) == 0.0:
        return 0.0, 0.0
    design = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    predicted = design @ coef
    return float(coef[0]), float(np.sum((y - predicted) ** 2))


def compute_bout_criterion_interval(
    durations: Sequence[int],
    *,
    min_intervals: int = DEFAULT_MIN_INTERVALS,
    min_segment_fraction: float = DEFAULT_MIN_SEGMENT_FRACTION,
    min_segment_points_abs: int = DEFAULT_MIN_SEGMENT_POINTS_ABS,
    min_improvement: float = DEFAULT_MIN_IMPROVEMENT,
) -> BoutCriterionResult:
    """Fit a two-segment log-survivorship model to *durations* (frame
    counts, or any positive-integer interval unit) and return the
    duration at the segments' crossover as the bout-criterion interval.

    Searches every INTERIOR candidate breakpoint in the unique sorted
    duration values -- each segment must hold at least
    ``min_segment_fraction`` of the distinct values (floored by
    ``min_segment_points_abs``), which rules out the otherwise
    irresistible "fit" of carving off a handful of points at the
    extreme tail, near-zero-residual by construction regardless of
    whether the data is genuinely bimodal. Among valid candidates,
    keeps only those where the second segment's slope is shallower
    (less negative) than the first's -- the actual signature of a
    genuine bout/pause split: many short, spurious intervals decay
    quickly, few long, genuine ones decay slowly -- and picks the one
    minimising combined sum of squared residuals. Accepts it only if
    that combined fit reduces total error by at least
    ``min_improvement`` relative to a single line through the whole
    curve; otherwise the fit is reported as not converged.
    """
    values = np.asarray([d for d in durations if d and d > 0], dtype=np.float64)
    n = values.size

    if n < min_intervals:
        return BoutCriterionResult(threshold_frames=0, converged=False, n_intervals=n)

    x, y = _log_survivorship(values)
    k = x.size
    min_segment_points = max(min_segment_points_abs, round(min_segment_fraction * k))
    if k < 2 * min_segment_points:
        return BoutCriterionResult(threshold_frames=0, converged=False, n_intervals=n)

    _baseline_slope, baseline_sse = _line_fit(x, y)

    best_bp: int | None = None
    best_sse = np.inf
    for bp in range(min_segment_points, k - min_segment_points + 1):
        slope1, sse1 = _line_fit(x[:bp], y[:bp])
        slope2, sse2 = _line_fit(x[bp:], y[bp:])
        if slope2 <= slope1:
            continue  # wrong-direction or no bend -- not a genuine split
        sse = sse1 + sse2
        if sse < best_sse:
            best_sse = sse
            best_bp = bp

    if best_bp is None:
        return BoutCriterionResult(threshold_frames=0, converged=False, n_intervals=n)

    improvement = (baseline_sse - best_sse) / baseline_sse if baseline_sse > 0 else 0.0
    converged = bool(improvement >= min_improvement)

    if not converged:
        return BoutCriterionResult(threshold_frames=0, converged=False, n_intervals=n)

    bci = round(float(x[best_bp]))
    return BoutCriterionResult(threshold_frames=max(bci, 1), converged=True, n_intervals=n)
