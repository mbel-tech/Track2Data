"""Tests for track2data.preprocess.smoothing."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import PPStepResult, SmoothCfg
from track2data.preprocess.smoothing import smooth_trajectories


@pytest.fixture()
def noisy_xy() -> np.ndarray:
    """60 frames, 2 animals. Animal 0 has additive noise on a linear trend."""
    rng = np.random.default_rng(0)
    xy = np.zeros((60, 2, 2), dtype=np.float64)
    frames = np.arange(60, dtype=np.float64)
    xy[:, 0, 0] = frames * 5.0 + rng.normal(0, 20, 60)
    xy[:, 0, 1] = 200.0 + rng.normal(0, 20, 60)
    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 3.0
    return xy


def test_none_method_is_noop(noisy_xy: np.ndarray) -> None:
    """method='none' returns array unchanged."""
    cfg = SmoothCfg(enabled=True, method="none", window=5, polyorder=2)
    original = noisy_xy.copy()
    out, result = smooth_trajectories(noisy_xy, cfg)
    np.testing.assert_array_equal(out, original)
    assert result.affected_frames == 0


def test_disabled_is_noop(noisy_xy: np.ndarray) -> None:
    """enabled=False returns array unchanged."""
    cfg = SmoothCfg(enabled=False, method="savgol", window=5, polyorder=2)
    original = noisy_xy.copy()
    out, result = smooth_trajectories(noisy_xy, cfg)
    np.testing.assert_array_equal(out, original)
    assert result.affected_frames == 0


def test_savgol_smooths_noise(noisy_xy: np.ndarray) -> None:
    """Savgol filter reduces the std of noise compared to original."""
    cfg = SmoothCfg(enabled=True, method="savgol", window=11, polyorder=2)
    out, _ = smooth_trajectories(noisy_xy, cfg)
    # Variance of animal 0 x-residuals should decrease
    residuals_in = noisy_xy[:, 0, 0] - np.arange(60) * 5.0
    residuals_out = out[:, 0, 0] - np.arange(60) * 5.0
    assert np.std(residuals_out) < np.std(residuals_in)


def test_moving_avg_smooths_noise(noisy_xy: np.ndarray) -> None:
    """Moving average filter reduces noise variance."""
    cfg = SmoothCfg(enabled=True, method="moving_avg", window=11, polyorder=2)
    out, _ = smooth_trajectories(noisy_xy, cfg)
    residuals_in = noisy_xy[:, 0, 0] - np.arange(60) * 5.0
    residuals_out = out[:, 0, 0] - np.arange(60) * 5.0
    assert np.std(residuals_out) < np.std(residuals_in)


def test_output_shape_preserved(noisy_xy: np.ndarray) -> None:
    """Output shape matches input shape."""
    cfg = SmoothCfg(enabled=True, method="savgol", window=5, polyorder=2)
    out, _ = smooth_trajectories(noisy_xy, cfg)
    assert out.shape == noisy_xy.shape


def test_returns_pp_step_result(noisy_xy: np.ndarray) -> None:
    """smooth_trajectories returns a PPStepResult."""
    cfg = SmoothCfg(enabled=True, method="savgol", window=5, polyorder=2)
    _, result = smooth_trajectories(noisy_xy, cfg)
    assert isinstance(result, PPStepResult)
    assert result.step_name == "smoothing"


def test_original_not_mutated(noisy_xy: np.ndarray) -> None:
    """smooth_trajectories must not mutate the input array."""
    original = noisy_xy.copy()
    cfg = SmoothCfg(enabled=True, method="savgol", window=5, polyorder=2)
    smooth_trajectories(noisy_xy, cfg)
    np.testing.assert_array_equal(noisy_xy, original)


def test_nan_frames_preserved_savgol() -> None:
    """NaN frames survive smoothing — they must not be filled by the smoother."""
    xy = np.zeros((30, 2, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(30, dtype=np.float64) * 5.0
    xy[:, 0, 1] = 100.0
    xy[10:15, 0, :] = np.nan
    xy[:, 1, 0] = 100.0
    xy[:, 1, 1] = 200.0
    cfg = SmoothCfg(enabled=True, method="savgol", window=5, polyorder=2)
    out, _ = smooth_trajectories(xy, cfg)
    # The NaN gap should still be NaN after smoothing
    assert np.all(np.isnan(out[10:15, 0, :]))


def test_window_1_is_noop_moving_avg() -> None:
    """Moving average with window=1 is a no-op."""
    xy = np.ones((20, 2, 2), dtype=np.float64) * 5.0
    cfg = SmoothCfg(enabled=True, method="moving_avg", window=1, polyorder=0)
    out, _ = smooth_trajectories(xy, cfg)
    np.testing.assert_allclose(out, xy, rtol=1e-12)


def test_savgol_affected_frames(noisy_xy: np.ndarray) -> None:
    """Savgol reports affected_frames = n_frames (all frames processed)."""
    cfg = SmoothCfg(enabled=True, method="savgol", window=5, polyorder=2)
    _, result = smooth_trajectories(noisy_xy, cfg)
    assert result.affected_frames == 60
