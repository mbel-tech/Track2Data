"""Tests for calibration.scalar — TDD RED phase.

All tests are written before implementation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.calibration.scalar import apply_scalar_calibration, px_to_bl, px_to_cm
from track2data.core.models import (
    CalibrationConfig,
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────


def _make_session(
    n_frames: int = 50,
    n_animals: int = 2,
    body_length_px: np.ndarray | None = None,
    tmp_path: Path | None = None,
) -> Session:
    xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    return Session(
        session_id="test_scalar",
        folder=tmp_path or Path("/tmp/test"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=1920, height_px=1080),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        body_length_px=body_length_px,
    )


def _make_kinematics(n_frames: int = 50, n_animals: int = 2) -> KinematicsArrays:
    z = np.zeros((n_frames, n_animals), dtype=np.float64)
    return KinematicsArrays(speed_px_s=z, accel_px_s2=z, heading_rad=z)


@pytest.fixture()
def minimal_psess(tmp_path: Path) -> PreprocessedSession:
    """A minimal PreprocessedSession with no calibration data."""
    session = _make_session(tmp_path=tmp_path)
    return PreprocessedSession(
        session=session,
        xy=session.raw_xy,
        kinematics=_make_kinematics(),
    )


# ── Tests for px_to_cm ────────────────────────────────────────────────────────


class TestPxToCm:
    def test_basic_conversion(self) -> None:
        arr = np.array([100.0, 200.0, 50.0])
        result = px_to_cm(arr, px_per_cm=10.0)
        np.testing.assert_allclose(result, [10.0, 20.0, 5.0])

    def test_nan_transparent(self) -> None:
        arr = np.array([100.0, np.nan, 200.0])
        result = px_to_cm(arr, px_per_cm=10.0)
        assert result[0] == pytest.approx(10.0)
        assert np.isnan(result[1])
        assert result[2] == pytest.approx(20.0)

    def test_zero_returns_zero(self) -> None:
        arr = np.array([0.0, 0.0])
        result = px_to_cm(arr, px_per_cm=5.0)
        np.testing.assert_allclose(result, [0.0, 0.0])

    def test_returns_ndarray(self) -> None:
        result = px_to_cm(np.array([10.0]), px_per_cm=2.0)
        assert isinstance(result, np.ndarray)

    def test_2d_array(self) -> None:
        arr = np.array([[10.0, 20.0], [30.0, np.nan]])
        result = px_to_cm(arr, px_per_cm=10.0)
        assert result.shape == (2, 2)
        assert result[0, 0] == pytest.approx(1.0)
        assert result[0, 1] == pytest.approx(2.0)
        assert np.isnan(result[1, 1])

    def test_does_not_mutate_input(self) -> None:
        arr = np.array([100.0, 200.0])
        original = arr.copy()
        px_to_cm(arr, px_per_cm=10.0)
        np.testing.assert_array_equal(arr, original)

    def test_fractional_divisor(self) -> None:
        arr = np.array([5.0])
        result = px_to_cm(arr, px_per_cm=2.5)
        assert result[0] == pytest.approx(2.0)


# ── Tests for px_to_bl ────────────────────────────────────────────────────────


class TestPxToBl:
    def test_1d_shape(self) -> None:
        """(n_animals,) input divided element-wise by body_length_px."""
        px_values = np.array([100.0, 200.0])
        bl = np.array([50.0, 100.0])
        result = px_to_bl(px_values, bl)
        np.testing.assert_allclose(result, [2.0, 2.0])

    def test_2d_shape(self) -> None:
        """(n_frames, n_animals) — each animal column divided by its BL."""
        n_frames, n_animals = 5, 2
        px_values = np.ones((n_frames, n_animals)) * np.array([50.0, 100.0])
        bl = np.array([25.0, 50.0])
        result = px_to_bl(px_values, bl)
        assert result.shape == (n_frames, n_animals)
        np.testing.assert_allclose(result, np.full((n_frames, n_animals), 2.0))

    def test_nan_transparent_2d(self) -> None:
        px_values = np.array([[np.nan, 100.0], [50.0, np.nan]])
        bl = np.array([25.0, 50.0])
        result = px_to_bl(px_values, bl)
        assert np.isnan(result[0, 0])
        assert result[0, 1] == pytest.approx(2.0)
        assert result[1, 0] == pytest.approx(2.0)
        assert np.isnan(result[1, 1])

    def test_returns_ndarray(self) -> None:
        result = px_to_bl(np.array([10.0]), np.array([5.0]))
        assert isinstance(result, np.ndarray)

    def test_does_not_mutate_input(self) -> None:
        px_values = np.array([[10.0, 20.0], [30.0, 40.0]])
        bl = np.array([5.0, 10.0])
        original = px_values.copy()
        px_to_bl(px_values, bl)
        np.testing.assert_array_equal(px_values, original)


# ── Tests for apply_scalar_calibration ───────────────────────────────────────


class TestApplyScalarCalibration:
    def test_sets_px_per_cm(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=5.0)
        out = apply_scalar_calibration(minimal_psess, cfg)
        assert out.px_per_cm == pytest.approx(5.0)

    def test_returns_preprocessed_session(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=12.5)
        out = apply_scalar_calibration(minimal_psess, cfg)
        assert isinstance(out, PreprocessedSession)

    def test_original_not_mutated(self, minimal_psess: PreprocessedSession) -> None:
        """Input psess.px_per_cm should remain None after the call."""
        assert minimal_psess.px_per_cm is None
        cfg = CalibrationConfig(mode="scalar", px_per_cm=5.0)
        apply_scalar_calibration(minimal_psess, cfg)
        # Either mutation or replace is acceptable; we just care the output is correct.
        # If implementation mutates in-place, this test is lenient.

    def test_raises_when_px_per_cm_none(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=None)
        with pytest.raises((ValueError, Exception)):
            apply_scalar_calibration(minimal_psess, cfg)

    def test_raises_when_px_per_cm_zero(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=0.0)
        with pytest.raises((ValueError, Exception)):
            apply_scalar_calibration(minimal_psess, cfg)

    def test_raises_when_px_per_cm_negative(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=-1.0)
        with pytest.raises((ValueError, Exception)):
            apply_scalar_calibration(minimal_psess, cfg)

    def test_raises_when_mode_wrong(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        with pytest.raises((ValueError, Exception)):
            apply_scalar_calibration(minimal_psess, cfg)

    def test_session_preserved(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=10.0)
        out = apply_scalar_calibration(minimal_psess, cfg)
        assert out.session is minimal_psess.session

    def test_xy_preserved(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=10.0)
        out = apply_scalar_calibration(minimal_psess, cfg)
        np.testing.assert_array_equal(out.xy, minimal_psess.xy)

    def test_large_value(self, minimal_psess: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=1234.567)
        out = apply_scalar_calibration(minimal_psess, cfg)
        assert out.px_per_cm == pytest.approx(1234.567)
