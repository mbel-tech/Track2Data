"""Tests for calibration.session_unit — TDD RED phase.

All tests are written before implementation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.calibration.session_unit import apply_session_calibration
from track2data.core.errors import CalibrationError
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
    length_unit: float | None = None,
    tmp_path: Path | None = None,
) -> Session:
    xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    return Session(
        session_id="test_session_unit",
        folder=tmp_path or Path("/tmp/test"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=1920, height_px=1080),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        length_unit=length_unit,
    )


def _make_kinematics(n_frames: int = 50, n_animals: int = 2) -> KinematicsArrays:
    z = np.zeros((n_frames, n_animals), dtype=np.float64)
    return KinematicsArrays(speed_px_s=z, accel_px_s2=z, heading_rad=z)


@pytest.fixture()
def psess_calibrated(tmp_path: Path) -> PreprocessedSession:
    """A session with its own length_unit already set (12.5 px/cm)."""
    session = _make_session(length_unit=12.5, tmp_path=tmp_path)
    return PreprocessedSession(session=session, xy=session.raw_xy, kinematics=_make_kinematics())


@pytest.fixture()
def psess_uncalibrated(tmp_path: Path) -> PreprocessedSession:
    """A session that was never run through the validator's calibration tool."""
    session = _make_session(length_unit=None, tmp_path=tmp_path)
    return PreprocessedSession(session=session, xy=session.raw_xy, kinematics=_make_kinematics())


# ── Tests for apply_session_calibration ──────────────────────────────────────


class TestApplySessionCalibration:
    def test_sets_px_per_cm_from_session_length_unit(
        self, psess_calibrated: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="session")
        out = apply_session_calibration(psess_calibrated, cfg)
        assert out.px_per_cm == pytest.approx(12.5)

    def test_returns_preprocessed_session(self, psess_calibrated: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="session")
        out = apply_session_calibration(psess_calibrated, cfg)
        assert isinstance(out, PreprocessedSession)

    def test_session_preserved(self, psess_calibrated: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="session")
        out = apply_session_calibration(psess_calibrated, cfg)
        assert out.session is psess_calibrated.session

    def test_xy_preserved(self, psess_calibrated: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="session")
        out = apply_session_calibration(psess_calibrated, cfg)
        np.testing.assert_array_equal(out.xy, psess_calibrated.xy)

    def test_different_sessions_use_their_own_ratio(self, tmp_path: Path) -> None:
        """The whole point of session mode: two sessions calibrated at
        different times get their own px_per_cm, unlike scalar mode's
        one project-wide value."""
        session_a = _make_session(length_unit=10.0, tmp_path=tmp_path / "a")
        session_b = _make_session(length_unit=20.0, tmp_path=tmp_path / "b")
        psess_a = PreprocessedSession(
            session=session_a, xy=session_a.raw_xy, kinematics=_make_kinematics()
        )
        psess_b = PreprocessedSession(
            session=session_b, xy=session_b.raw_xy, kinematics=_make_kinematics()
        )
        cfg = CalibrationConfig(mode="session")
        out_a = apply_session_calibration(psess_a, cfg)
        out_b = apply_session_calibration(psess_b, cfg)
        assert out_a.px_per_cm == pytest.approx(10.0)
        assert out_b.px_per_cm == pytest.approx(20.0)


class TestApplySessionCalibrationErrors:
    def test_raises_when_mode_wrong(self, psess_calibrated: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=5.0)
        with pytest.raises(CalibrationError):
            apply_session_calibration(psess_calibrated, cfg)

    def test_raises_calibration_error_type(self, psess_uncalibrated: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="session")
        with pytest.raises(CalibrationError):
            apply_session_calibration(psess_uncalibrated, cfg)

    def test_error_names_the_session(self, psess_uncalibrated: PreprocessedSession) -> None:
        """The error must name which session is missing length_unit --
        this is what makes 'fail loudly, name the sessions' possible at
        the Engine.validate() layer above this function."""
        cfg = CalibrationConfig(mode="session")
        with pytest.raises(CalibrationError) as exc_info:
            apply_session_calibration(psess_uncalibrated, cfg)
        assert psess_uncalibrated.session.session_id in str(exc_info.value)

    def test_error_code_is_cal_session_missing(
        self, psess_uncalibrated: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="session")
        with pytest.raises(CalibrationError) as exc_info:
            apply_session_calibration(psess_uncalibrated, cfg)
        assert exc_info.value.code == "CAL-SESSION-MISSING"
