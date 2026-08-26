"""Tests for track2data.metrics.bouts -- the Sibly et al. 1990
log-survivorship bout-criterion interval (BCI) estimator.
"""

from __future__ import annotations

import numpy as np

from track2data.metrics.bouts import (
    DEFAULT_MIN_INTERVALS,
    BoutCriterionResult,
    compute_bout_criterion_interval,
)


def _bimodal_durations(seed: int, n_short: int = 200, n_long: int = 100) -> list[int]:
    """Synthetic run-length distribution with a clear short/noise
    population and a clear long/genuine population, separated by a gap."""
    rng = np.random.default_rng(seed)
    short = rng.poisson(2, n_short) + 1  # 1..~10
    long = rng.poisson(30, n_long) + 20  # ~20..~55
    return np.concatenate([short, long]).tolist()


def _unimodal_durations(seed: int, n: int = 300) -> list[int]:
    rng = np.random.default_rng(seed)
    return (rng.poisson(10, n) + 1).tolist()


class TestComputeBoutCriterionInterval:
    def test_returns_bout_criterion_result(self) -> None:
        result = compute_bout_criterion_interval(_bimodal_durations(0))
        assert isinstance(result, BoutCriterionResult)

    def test_bimodal_distribution_converges(self) -> None:
        result = compute_bout_criterion_interval(_bimodal_durations(0))
        assert result.converged is True

    def test_bimodal_threshold_separates_the_two_populations(self) -> None:
        durations = _bimodal_durations(0, n_short=200, n_long=100)
        result = compute_bout_criterion_interval(durations)
        assert result.converged is True
        # The synthetic short population caps out around 1 + Poisson(2)'s
        # right tail; the long population starts at 20. The fitted
        # threshold should land somewhere in that gap, not at either
        # extreme of the pooled range.
        assert 5 <= result.threshold_frames <= 22

    def test_unimodal_distribution_does_not_converge(self) -> None:
        """A single Poisson population has no genuine short/long split;
        the fit must not manufacture one. Checked across several seeds
        since this is a statistical test, not a deterministic one."""
        non_converged = sum(
            not compute_bout_criterion_interval(_unimodal_durations(seed)).converged
            for seed in range(20)
        )
        assert non_converged >= 18, (
            "unimodal data converged too often (false-positive rate too high)"
        )

    def test_below_min_intervals_does_not_converge(self) -> None:
        result = compute_bout_criterion_interval([5] * (DEFAULT_MIN_INTERVALS - 1))
        assert result.converged is False
        assert result.threshold_frames == 0

    def test_all_identical_durations_does_not_converge(self) -> None:
        result = compute_bout_criterion_interval([5] * 50)
        assert result.converged is False
        assert result.threshold_frames == 0

    def test_not_converged_result_has_zero_threshold(self) -> None:
        """threshold_frames is a deliberately unusable sentinel when
        converged is False -- callers must fall back rather than trust it."""
        result = compute_bout_criterion_interval([1] * 5)
        assert result.converged is False
        assert result.threshold_frames == 0

    def test_n_intervals_counts_only_positive_durations(self) -> None:
        durations = [0, -1, 3, 4, 5] + [1] * 20
        result = compute_bout_criterion_interval(durations)
        assert result.n_intervals == 23  # 25 inputs minus the 0 and the -1

    def test_empty_input_does_not_converge(self) -> None:
        result = compute_bout_criterion_interval([])
        assert result.converged is False
        assert result.n_intervals == 0

    def test_deterministic_for_the_same_input(self) -> None:
        durations = _bimodal_durations(1)
        result_a = compute_bout_criterion_interval(durations)
        result_b = compute_bout_criterion_interval(durations)
        assert result_a == result_b

    def test_threshold_frames_is_a_positive_integer_when_converged(self) -> None:
        result = compute_bout_criterion_interval(_bimodal_durations(2))
        assert result.converged is True
        assert isinstance(result.threshold_frames, int)
        assert result.threshold_frames >= 1

    def test_min_improvement_can_be_tightened_to_reject_a_weak_split(self) -> None:
        durations = _bimodal_durations(3)
        lenient = compute_bout_criterion_interval(durations, min_improvement=0.0)
        strict = compute_bout_criterion_interval(durations, min_improvement=0.999)
        assert lenient.converged is True
        assert strict.converged is False

    def test_min_intervals_is_configurable(self) -> None:
        durations = [1] * 8
        assert compute_bout_criterion_interval(durations).converged is False
        # Same data now clears a lowered floor, though it still won't find
        # a genuine split (identical values) -- this checks the floor is
        # actually being read, not that identical data suddenly converges.
        result = compute_bout_criterion_interval(durations, min_intervals=5)
        assert result.n_intervals == 8
