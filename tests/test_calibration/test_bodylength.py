"""Tests for calibration.bodylength — TDD RED phase.

All tests are written before implementation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.calibration.bodylength import apply_bodylength_calibration
from track2data.core.errors import CalibrationError
from track2data.core.models import (
    CalibrationConfig,
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
)

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _make_session(
    n_frames: int = 50,
    n_animals: int = 2,
    body_length_px: np.ndarray | None = None,
    length_unit: float | None = None,
    tmp_path: Path | None = None,
) -> Session:
    xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    return Session(
        session_id="test_bl",
        folder=tmp_path or Path("/tmp/test_bl"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=1920, height_px=1080),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        body_length_px=body_length_px,
        length_unit=length_unit,
    )


def _make_kinematics(n_frames: int = 50, n_animals: int = 2) -> KinematicsArrays:
    z = np.zeros((n_frames, n_animals), dtype=np.float64)
    return KinematicsArrays(speed_px_s=z, accel_px_s2=z, heading_rad=z)


@pytest.fixture()
def session_with_bl(tmp_path: Path) -> Session:
    """Session with body_length_px set (no length_unit — pixel mode)."""
    bl = np.array([50.0, 60.0])
    return _make_session(n_frames=50, n_animals=2, body_length_px=bl, tmp_path=tmp_path)


@pytest.fixture()
def session_with_bl_and_unit(tmp_path: Path) -> Session:
    """Session with body_length_px AND length_unit set -- bodylength mode
    ignores length_unit entirely (see calibration/bodylength.py's module
    docstring), so this fixture exercises that length_unit's presence
    makes no difference to the output."""
    bl = np.array([100.0, 120.0])
    return _make_session(
        n_frames=50, n_animals=2, body_length_px=bl, length_unit=10.0, tmp_path=tmp_path
    )


@pytest.fixture()
def session_no_bl(tmp_path: Path) -> Session:
    """Session with no body_length_px at all."""
    return _make_session(n_frames=50, n_animals=2, tmp_path=tmp_path)


@pytest.fixture()
def psess_with_bl(session_with_bl: Session) -> PreprocessedSession:
    return PreprocessedSession(
        session=session_with_bl,
        xy=session_with_bl.raw_xy,
        kinematics=_make_kinematics(),
    )


@pytest.fixture()
def psess_with_bl_and_unit(session_with_bl_and_unit: Session) -> PreprocessedSession:
    return PreprocessedSession(
        session=session_with_bl_and_unit,
        xy=session_with_bl_and_unit.raw_xy,
        kinematics=_make_kinematics(),
    )


@pytest.fixture()
def psess_no_bl(session_no_bl: Session) -> PreprocessedSession:
    return PreprocessedSession(
        session=session_no_bl,
        xy=session_no_bl.raw_xy,
        kinematics=_make_kinematics(),
    )


# ── Tests: pixel-mode (no length_unit) ────────────────────────────────────────


class TestApplyBodylengthCalibrationPixelMode:
    """When length_unit is None, body_length_cm stores values in pixels."""

    def test_returns_preprocessed_session(self, psess_with_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        assert isinstance(out, PreprocessedSession)

    def test_body_length_cm_set(self, psess_with_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        assert out.body_length_cm is not None

    def test_body_length_cm_length_matches_n_animals(
        self, psess_with_bl: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        assert len(out.body_length_cm) == psess_with_bl.session.n_animals  # type: ignore[arg-type]

    def test_body_length_cm_values_are_bl_px(self, psess_with_bl: PreprocessedSession) -> None:
        """Without length_unit, body_length_cm should equal body_length_px."""
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        np.testing.assert_allclose(
            out.body_length_cm,
            psess_with_bl.session.body_length_px,
        )

    def test_px_per_cm_remains_none_without_unit(
        self, psess_with_bl: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        assert out.px_per_cm is None

    def test_session_preserved(self, psess_with_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        assert out.session is psess_with_bl.session

    def test_xy_preserved(self, psess_with_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl, cfg)
        np.testing.assert_array_equal(out.xy, psess_with_bl.xy)


# ── Tests: length_unit is ignored even when present ────────────────────────


class TestApplyBodylengthCalibrationIgnoresLengthUnit:
    """A session's length_unit must make no difference to bodylength
    mode's output -- see calibration/bodylength.py's module docstring
    for why this mode stopped consuming it (that's now 'session' mode,
    calibration/session_unit.py, with a required user confirmation)."""

    def test_body_length_cm_stays_in_pixels(
        self, psess_with_bl_and_unit: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl_and_unit, cfg)
        # bl=[100,120], length_unit=10 -- but length_unit is not consumed,
        # so body_length_cm equals body_length_px unchanged.
        np.testing.assert_allclose(out.body_length_cm, [100.0, 120.0])

    def test_px_per_cm_stays_none_despite_length_unit(
        self, psess_with_bl_and_unit: PreprocessedSession
    ) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl_and_unit, cfg)
        assert out.px_per_cm is None

    def test_body_length_cm_shape(self, psess_with_bl_and_unit: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess_with_bl_and_unit, cfg)
        assert out.body_length_cm is not None
        assert out.body_length_cm.shape == (psess_with_bl_and_unit.session.n_animals,)

    def test_single_animal(self, tmp_path: Path) -> None:
        session = _make_session(
            n_frames=50, n_animals=1,
            body_length_px=np.array([80.0]),
            length_unit=8.0,
            tmp_path=tmp_path,
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy, kinematics=_make_kinematics(n_animals=1)
        )
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess, cfg)
        np.testing.assert_allclose(out.body_length_cm, [80.0])
        assert out.px_per_cm is None


# ── Tests: error cases ─────────────────────────────────────────────────────────


class TestApplyBodylengthCalibrationErrors:
    def test_raises_when_no_body_length_px(self, psess_no_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="bodylength")
        with pytest.raises((CalibrationError, ValueError)):
            apply_bodylength_calibration(psess_no_bl, cfg)

    def test_raises_calibration_error_type(self, psess_no_bl: PreprocessedSession) -> None:
        """Should raise CalibrationError specifically (not a generic exception)."""
        cfg = CalibrationConfig(mode="bodylength")
        with pytest.raises(CalibrationError):
            apply_bodylength_calibration(psess_no_bl, cfg)

    def test_raises_when_wrong_mode(self, psess_with_bl: PreprocessedSession) -> None:
        cfg = CalibrationConfig(mode="scalar", px_per_cm=5.0)
        with pytest.raises((ValueError, CalibrationError, Exception)):
            apply_bodylength_calibration(psess_with_bl, cfg)

    def test_raises_when_length_unit_zero(self, tmp_path: Path) -> None:
        session = _make_session(
            n_frames=50, n_animals=2,
            body_length_px=np.array([50.0, 60.0]),
            length_unit=0.0,
            tmp_path=tmp_path,
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy, kinematics=_make_kinematics()
        )
        cfg = CalibrationConfig(mode="bodylength")
        with pytest.raises((CalibrationError, ValueError, ZeroDivisionError)):
            apply_bodylength_calibration(psess, cfg)

    def test_raises_when_bl_min_samples_not_met(self, tmp_path: Path) -> None:
        """With very few frames (< bl_min_samples), should raise CalibrationError."""
        # 3 frames, but bl_min_samples = 10
        session = _make_session(
            n_frames=3, n_animals=2,
            body_length_px=np.array([50.0, 60.0]),
            tmp_path=tmp_path,
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy, kinematics=_make_kinematics(n_frames=3)
        )
        cfg = CalibrationConfig(mode="bodylength", bl_min_samples=10)
        with pytest.raises((CalibrationError, ValueError)):
            apply_bodylength_calibration(psess, cfg)

    def test_no_error_when_bl_min_samples_met(self, tmp_path: Path) -> None:
        """With exactly bl_min_samples frames, should succeed."""
        n = 10
        session = _make_session(
            n_frames=n, n_animals=2,
            body_length_px=np.array([50.0, 60.0]),
            tmp_path=tmp_path,
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy, kinematics=_make_kinematics(n_frames=n)
        )
        cfg = CalibrationConfig(mode="bodylength", bl_min_samples=10)
        out = apply_bodylength_calibration(psess, cfg)
        assert out.body_length_cm is not None


# ── Tests: edge cases ──────────────────────────────────────────────────────────


class TestApplyBodylengthEdgeCases:
    def test_many_animals(self, tmp_path: Path) -> None:
        n_animals = 10
        bl = np.arange(1, n_animals + 1, dtype=np.float64) * 10.0
        session = _make_session(
            n_frames=50, n_animals=n_animals, body_length_px=bl, tmp_path=tmp_path
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy,
            kinematics=_make_kinematics(n_animals=n_animals),
        )
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess, cfg)
        assert out.body_length_cm is not None
        assert len(out.body_length_cm) == n_animals

    def test_body_length_cm_dtype_float(self, tmp_path: Path) -> None:
        session = _make_session(
            n_frames=50, n_animals=2,
            body_length_px=np.array([50.0, 60.0]),
            tmp_path=tmp_path,
        )
        psess = PreprocessedSession(
            session=session, xy=session.raw_xy, kinematics=_make_kinematics()
        )
        cfg = CalibrationConfig(mode="bodylength")
        out = apply_bodylength_calibration(psess, cfg)
        assert out.body_length_cm is not None
        assert np.issubdtype(out.body_length_cm.dtype, np.floating)
