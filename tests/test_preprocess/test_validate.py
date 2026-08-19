"""Tests for track2data.preprocess.validate."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from track2data.core.models import PPStepResult, ValidateCfg
from track2data.preprocess.validate import validate_coverage


@pytest.fixture()
def clean_xy() -> np.ndarray:
    """100 frames, 3 animals, no NaN — all fully covered."""
    return np.ones((100, 3, 2), dtype=np.float64) * 5.0


def test_no_nan_no_warning(clean_xy: np.ndarray, caplog: pytest.LogCaptureFixture) -> None:
    """All animals fully covered → no warning."""
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    with caplog.at_level(logging.WARNING):
        result = validate_coverage(clean_xy, cfg)
    assert "warning" not in caplog.text.lower() or result.notes == ""


def test_returns_pp_step_result(clean_xy: np.ndarray) -> None:
    """validate_coverage must return a PPStepResult."""
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    result = validate_coverage(clean_xy, cfg)
    assert isinstance(result, PPStepResult)
    assert result.step_name == "validate_coverage"


def test_does_not_modify_xy(clean_xy: np.ndarray) -> None:
    """validate_coverage must not alter the xy array."""
    original = clean_xy.copy()
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    validate_coverage(clean_xy, cfg)
    np.testing.assert_array_equal(clean_xy, original)


def test_high_nan_triggers_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Animal with >10% NaN gets a warning in notes and log."""
    xy = np.ones((100, 2, 2), dtype=np.float64)
    xy[0:15, 0, :] = np.nan  # 15% NaN for animal 0
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    with caplog.at_level(logging.WARNING):
        result = validate_coverage(xy, cfg, session_id="test_session")
    assert len(result.notes) > 0
    assert "0" in result.notes  # animal 0 is mentioned


def test_exactly_at_threshold_no_warning() -> None:
    """Exactly at threshold (10% NaN) → no warning."""
    xy = np.ones((100, 2, 2), dtype=np.float64)
    xy[0:10, 0, :] = np.nan  # exactly 10%
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    result = validate_coverage(xy, cfg)
    # exactly at threshold is OK (not over)
    assert result.notes == "" or "0" not in result.notes


def test_just_over_threshold_warns() -> None:
    """11% NaN → warning in notes."""
    xy = np.ones((100, 2, 2), dtype=np.float64)
    xy[0:11, 0, :] = np.nan  # 11% NaN
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    result = validate_coverage(xy, cfg)
    assert len(result.notes) > 0


def test_affected_frames_count() -> None:
    """affected_frames = number of frames that are NaN for any animal over threshold."""
    xy = np.ones((100, 2, 2), dtype=np.float64)
    xy[0:20, 0, :] = np.nan  # 20% NaN for animal 0
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    result = validate_coverage(xy, cfg)
    assert result.affected_frames == 20


def test_affected_per_individual_length(clean_xy: np.ndarray) -> None:
    """affected_per_individual length equals n_animals."""
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    result = validate_coverage(clean_xy, cfg)
    assert len(result.affected_per_individual) == 3


def test_session_id_in_warning(caplog: pytest.LogCaptureFixture) -> None:
    """session_id should appear in the warning log message."""
    xy = np.ones((100, 2, 2), dtype=np.float64)
    xy[0:20, 0, :] = np.nan
    cfg = ValidateCfg(max_pct_na_per_individual=0.10)
    with caplog.at_level(logging.WARNING):
        validate_coverage(xy, cfg, session_id="my_session")
    assert "my_session" in caplog.text
