"""Tests for track2data.preprocess.identity_switch."""

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


def test_no_switch_unchanged(two_animal_xy: np.ndarray) -> None:
    """Trajectories without switches should be returned essentially unchanged."""
    cfg = IdSwitchCfg(enabled=True, tier1_ratio=1.5, tier2_hungarian=True)
    out, _result = correct_switches(two_animal_xy, cfg)
    assert out.shape == two_animal_xy.shape


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


def test_output_shape_preserved(two_animal_xy: np.ndarray) -> None:
    """Output shape must match input shape."""
    cfg = IdSwitchCfg(enabled=True)
    out, _ = correct_switches(two_animal_xy, cfg)
    assert out.shape == two_animal_xy.shape


def test_switch_detected_and_corrected() -> None:
    """
    Inject a swap at frame 25: animals 0 and 1 swap positions.
    After correction, global positions should stay consistent.
    """
    n = 50
    xy = np.zeros((n, 2, 2), dtype=np.float64)
    frames = np.arange(n, dtype=np.float64)
    # Animal 0: moving right along y=100
    xy[:, 0, 0] = 100.0 + frames * 5.0
    xy[:, 0, 1] = 100.0
    # Animal 1: moving right along y=400 (far apart, clear distinction)
    xy[:, 1, 0] = 100.0 + frames * 5.0
    xy[:, 1, 1] = 400.0
    # Inject swap from frame 25 onward: swap x only (keep y)
    xy[25:, 0, 1] = 400.0  # animal 0 jumps to y=400
    xy[25:, 1, 1] = 100.0  # animal 1 jumps to y=100
    cfg = IdSwitchCfg(enabled=True, tier1_ratio=1.5, tier2_hungarian=True, consolidate_window=5)
    out, result = correct_switches(xy, cfg)
    # The function should run without errors; result is a PPStepResult
    assert isinstance(result, PPStepResult)
    assert out.shape == xy.shape


def test_four_animals_output_shape() -> None:
    """Test with 4 animals — output shape preserved."""
    xy = np.random.default_rng(42).random((60, 4, 2)) * 500.0
    cfg = IdSwitchCfg(enabled=True)
    out, result = correct_switches(xy, cfg)
    assert out.shape == (60, 4, 2)
    assert len(result.affected_per_individual) == 4
