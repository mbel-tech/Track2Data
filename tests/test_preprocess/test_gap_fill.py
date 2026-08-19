"""Tests for track2data.preprocess.gap_fill."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import GapFillCfg, PPStepResult
from track2data.preprocess.gap_fill import fill_gaps


@pytest.fixture()
def xy_with_gaps() -> np.ndarray:
    """100 frames, 4 animals. Animal 0 has a 5-frame gap (frames 20-24)."""
    xy = np.zeros((100, 4, 2), dtype=np.float64)
    frames = np.arange(100, dtype=np.float64)
    xy[:, 0, 0] = 100.0 + frames * 5.0
    xy[:, 0, 1] = 200.0
    xy[20:25, 0, :] = np.nan  # 5-frame gap
    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 4.0
    xy[:, 2, 0] = 800.0
    xy[:, 2, 1] = 600.0
    xy[:, 3, 0] = 500.0
    xy[:, 3, 1] = 500.0
    return xy


def test_short_gap_is_filled(xy_with_gaps: np.ndarray) -> None:
    """A 5-frame gap with max_gap=30 should be linearly interpolated."""
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    out, _result = fill_gaps(xy_with_gaps, cfg)
    assert not np.any(np.isnan(out[:, 0, :]))


def test_filled_values_are_linear(xy_with_gaps: np.ndarray) -> None:
    """Interpolated frames 20-24 should lie on the line between frame 19 and 25."""
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    out, _ = fill_gaps(xy_with_gaps, cfg)
    # frame 19: x=195, frame 25: x=225 → linear over 6 steps
    expected_x = 195.0 + np.arange(1, 6) * (225.0 - 195.0) / 6.0
    np.testing.assert_allclose(out[20:25, 0, 0], expected_x, rtol=1e-9)
    # y stays 200
    np.testing.assert_allclose(out[20:25, 0, 1], 200.0, atol=1e-12)


def test_long_gap_stays_nan() -> None:
    """A gap longer than max_gap_frames must not be filled."""
    xy = np.zeros((50, 2, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(50, dtype=np.float64) * 5.0
    xy[:, 0, 1] = 200.0
    xy[10:25, 0, :] = np.nan  # 15-frame gap
    cfg = GapFillCfg(enabled=True, max_gap_frames=10)
    out, _ = fill_gaps(xy, cfg)
    assert np.all(np.isnan(out[10:25, 0, :]))


def test_disabled_returns_unchanged(xy_with_gaps: np.ndarray) -> None:
    """When cfg.enabled=False, array is returned unchanged."""
    cfg = GapFillCfg(enabled=False, max_gap_frames=30)
    original = xy_with_gaps.copy()
    out, result = fill_gaps(xy_with_gaps, cfg)
    np.testing.assert_array_equal(out, original)
    assert result.affected_frames == 0


def test_returns_pp_step_result(xy_with_gaps: np.ndarray) -> None:
    """fill_gaps must return a PPStepResult."""
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    _, result = fill_gaps(xy_with_gaps, cfg)
    assert isinstance(result, PPStepResult)
    assert result.step_name == "gap_fill"


def test_affected_frames_count(xy_with_gaps: np.ndarray) -> None:
    """affected_frames should count frames that were filled."""
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    _, result = fill_gaps(xy_with_gaps, cfg)
    assert result.affected_frames == 5  # frames 20-24


def test_original_array_not_mutated(xy_with_gaps: np.ndarray) -> None:
    """fill_gaps must return a new array, not mutate the input."""
    original = xy_with_gaps.copy()
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    out, _ = fill_gaps(xy_with_gaps, cfg)
    np.testing.assert_array_equal(xy_with_gaps, original)
    # out should be a different object
    assert out is not xy_with_gaps


def test_no_gaps_returns_zero_affected() -> None:
    """Array with no NaNs should report 0 affected frames."""
    xy = np.ones((50, 3, 2), dtype=np.float64)
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    _, result = fill_gaps(xy, cfg)
    assert result.affected_frames == 0


def test_affected_per_individual_length(xy_with_gaps: np.ndarray) -> None:
    """affected_per_individual should have n_animals entries."""
    cfg = GapFillCfg(enabled=True, max_gap_frames=30)
    _, result = fill_gaps(xy_with_gaps, cfg)
    assert len(result.affected_per_individual) == 4


def test_gap_exactly_at_max_is_filled() -> None:
    """A gap of exactly max_gap_frames frames should be filled."""
    xy = np.zeros((20, 2, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(20, dtype=np.float64)
    xy[:, 0, 1] = 0.0
    xy[5:15, 0, :] = np.nan  # exactly 10 frames
    cfg = GapFillCfg(enabled=True, max_gap_frames=10)
    out, result = fill_gaps(xy, cfg)
    assert not np.any(np.isnan(out[:, 0, :]))
    assert result.affected_frames == 10
