"""Tests for track2data.preprocess.identity_switch.

Several tests here used to assert only ``out.shape == xy.shape`` and
``isinstance(result, PPStepResult)`` -- including one that injected a real
identity swap and then never checked whether it had been corrected. That is
how PP-3 shipped as a silent no-op for dyads and a partial, discontinuity-
introducing correction for everything else. Every test below now asserts
what the step actually did to the data.

The canonical crossing cases live in
``test_identity_switch_crossing_regression.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import IdSwitchCfg, PPStepResult
from track2data.preprocess.identity_switch import correct_switches


@pytest.fixture()
def two_animal_xy() -> np.ndarray:
    """50 frames, 2 animals moving in parallel (no switches)."""
    xy = np.zeros((50, 2, 2), dtype=np.float64)
    frames = np.arange(50, dtype=np.float64)
    xy[:, 0, 0] = 100.0 + frames * 2.0
    xy[:, 0, 1] = 100.0
    xy[:, 1, 0] = 200.0 + frames * 2.0
    xy[:, 1, 1] = 200.0
    return xy


def test_no_switch_is_left_bit_for_bit_unchanged(two_animal_xy: np.ndarray) -> None:
    """Unambiguous parallel tracks must come back untouched, not merely same-shaped."""
    cfg = IdSwitchCfg(enabled=True, tier1_ratio=1.5, tier2_hungarian=True)
    out, result = correct_switches(two_animal_xy, cfg)
    np.testing.assert_array_equal(out, two_animal_xy)
    assert result.affected_frames == 0


def test_disabled_returns_unchanged(two_animal_xy: np.ndarray) -> None:
    """When cfg.enabled=False, return array unchanged."""
    cfg = IdSwitchCfg(enabled=False)
    original = two_animal_xy.copy()
    out, result = correct_switches(two_animal_xy, cfg)
    np.testing.assert_array_equal(out, original)
    assert result.affected_frames == 0


def test_returns_pp_step_result(two_animal_xy: np.ndarray) -> None:
    """correct_switches must return a PPStepResult."""
    cfg = IdSwitchCfg(enabled=True)
    _, result = correct_switches(two_animal_xy, cfg)
    assert isinstance(result, PPStepResult)
    assert result.step_name == "identity_switch"


def test_original_not_mutated(two_animal_xy: np.ndarray) -> None:
    """correct_switches must not mutate the input array."""
    original = two_animal_xy.copy()
    cfg = IdSwitchCfg(enabled=True)
    correct_switches(two_animal_xy, cfg)
    np.testing.assert_array_equal(two_animal_xy, original)


def test_affected_per_individual_length(two_animal_xy: np.ndarray) -> None:
    """affected_per_individual must have n_animals entries."""
    cfg = IdSwitchCfg(enabled=True)
    _, result = correct_switches(two_animal_xy, cfg)
    assert len(result.affected_per_individual) == 2


def test_switch_detected_and_corrected() -> None:
    """Inject a persistent swap at frame 25 and require it to be undone.

    Two animals on well-separated parallel tracks, so the assignment is never
    genuinely ambiguous -- only mislabelled. The corrector must restore the
    original trajectories exactly and report the frames it touched.
    """
    n = 50
    truth = np.zeros((n, 2, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    truth[:, 0, 0] = 100.0 + frames * 5.0
    truth[:, 0, 1] = 100.0
    truth[:, 1, 0] = 100.0 + frames * 5.0
    truth[:, 1, 1] = 400.0

    obs = truth.copy()
    obs[25:, 0, 1] = 400.0
    obs[25:, 1, 1] = 100.0

    cfg = IdSwitchCfg(enabled=True, tier1_ratio=1.5, tier2_hungarian=True)
    out, result = correct_switches(obs, cfg)

    np.testing.assert_allclose(out, truth)
    assert result.affected_frames == n - 25


def test_correction_persists_to_end_of_session() -> None:
    """A persistent relabelling gets a persistent correction, not a windowed one.

    Pins the specific defect where the permutation was applied frame-by-frame
    inside ``consolidate_window`` and then reverted, leaving most of the
    session on the wrong identity.
    """
    n = 80
    switch_at = 30
    truth = np.zeros((n, 2, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    truth[:, 0, 0] = frames * 3.0
    truth[:, 0, 1] = 50.0
    truth[:, 1, 0] = frames * 3.0
    truth[:, 1, 1] = 250.0

    obs = truth.copy()
    obs[switch_at:, 0, :] = truth[switch_at:, 1, :]
    obs[switch_at:, 1, :] = truth[switch_at:, 0, :]

    cfg = IdSwitchCfg(enabled=True, consolidate_window=5)
    out, _ = correct_switches(obs, cfg)

    # Far beyond consolidate_window, where the old implementation reverted.
    np.testing.assert_allclose(out[-1], truth[-1])
    np.testing.assert_allclose(out, truth)


def test_swap_boundaries_restrict_where_correction_may_happen() -> None:
    """With fragment boundaries supplied, no other frame may be touched.

    A swap is physically possible only at a fragment boundary, so a boundary
    set that excludes the real switch must leave the data alone rather than
    inventing a correction elsewhere.

    Boundaries are fragment ``end_frame`` values, which idtracker.ai stores
    exclusive -- so the boundary naming the switch is the switch frame
    itself, not the frame before it. Getting that off by one corrects one
    frame late and leaves the discontinuity in the data.
    """
    n = 60
    switch_at = 21
    truth = np.zeros((n, 2, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    truth[:, 0, 0] = frames * 2.0
    truth[:, 0, 1] = 100.0
    truth[:, 1, 0] = 120.0 - frames * 2.0
    truth[:, 1, 1] = 100.0

    obs = truth.copy()
    obs[switch_at:, 0, :] = truth[switch_at:, 1, :]
    obs[switch_at:, 1, :] = truth[switch_at:, 0, :]

    cfg = IdSwitchCfg(enabled=True)

    # end_frame == switch_at means the next fragment starts there.
    out_hit, res_hit = correct_switches(obs, cfg, swap_boundaries={switch_at})
    np.testing.assert_allclose(out_hit, truth)
    assert res_hit.affected_frames > 0

    # One frame late is not close enough: the switch survives.
    out_late, _ = correct_switches(obs, cfg, swap_boundaries={switch_at + 1})
    assert not np.allclose(out_late, truth)

    # A boundary set that does not contain it must change nothing.
    out_miss, res_miss = correct_switches(obs, cfg, swap_boundaries={45})
    np.testing.assert_array_equal(out_miss, obs)
    assert res_miss.affected_frames == 0


def test_nan_frames_are_skipped_not_corrupted() -> None:
    """Missing positions must neither crash the step nor be filled in by it."""
    n = 40
    xy = np.zeros((n, 3, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    for k in range(3):
        xy[:, k, 0] = frames * 2.0
        xy[:, k, 1] = 100.0 * k
    xy[10:14, 1, :] = np.nan

    cfg = IdSwitchCfg(enabled=True)
    out, _ = correct_switches(xy, cfg)

    assert np.isnan(out[10:14, 1, :]).all()
    assert not np.isnan(out[:10]).any()
    assert not np.isnan(out[14:]).any()


def test_four_animals_clean_input_untouched() -> None:
    """Four unambiguous tracks: no correction, and the array is unchanged."""
    n = 60
    xy = np.zeros((n, 4, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    for k in range(4):
        xy[:, k, 0] = 50.0 + frames * 1.5
        xy[:, k, 1] = 100.0 * (k + 1)

    cfg = IdSwitchCfg(enabled=True)
    out, result = correct_switches(xy, cfg)

    np.testing.assert_array_equal(out, xy)
    assert result.affected_frames == 0
    assert len(result.affected_per_individual) == 4


def test_greedy_assignment_without_hungarian() -> None:
    """tier2_hungarian=False must still correct an unambiguous swap.

    Without the solver the step falls back to row-wise nearest, which is only
    usable when it happens to come out a valid permutation. On a clean,
    well-separated swap it does.
    """
    n = 50
    truth = np.zeros((n, 2, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    truth[:, 0, 0] = frames * 4.0
    truth[:, 0, 1] = 0.0
    truth[:, 1, 0] = frames * 4.0
    truth[:, 1, 1] = 300.0

    obs = truth.copy()
    obs[25:, 0, :] = truth[25:, 1, :]
    obs[25:, 1, :] = truth[25:, 0, :]

    out, result = correct_switches(obs, IdSwitchCfg(enabled=True, tier2_hungarian=False))

    np.testing.assert_allclose(out, truth)
    assert result.affected_frames == n - 25


def test_greedy_assignment_declines_when_not_a_permutation() -> None:
    """Row-wise nearest that maps two identities onto one observation is not a
    permutation, and must be declined rather than corrupting the array."""
    n = 30
    xy = np.zeros((n, 3, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    # Three animals converging on the same point: every identity's nearest
    # observation is the same one, so greedy cannot produce a permutation.
    for k in range(3):
        xy[:, k, 0] = 100.0 * k + frames * (5.0 - 5.0 * k / 2.0)
        xy[:, k, 1] = 0.0
    xy[15:, 0, :] = xy[15:, 2, :]

    out, _ = correct_switches(xy, IdSwitchCfg(enabled=True, tier2_hungarian=False))

    assert out.shape == xy.shape
    assert not np.isnan(out).any()
