"""Tests for individual-level metrics IL-3 and IL-6 (TDD RED phase)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    PreprocessReport,
    Session,
    VideoInfo,
)
from track2data.metrics.individual import CentreDistance, Acceleration


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    n_frames: int = 50,
    n_animals: int = 4,
    xy: np.ndarray | None = None,
    accel: np.ndarray | None = None,
) -> PreprocessedSession:
    rng = np.random.default_rng(42)
    if xy is None:
        xy = rng.random((n_frames, n_animals, 2)) * 500
    actual_frames, actual_animals = xy.shape[0], xy.shape[1]
    if accel is None:
        accel = np.zeros((actual_frames, actual_animals))
    sess = Session(
        session_id="test",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=actual_frames, width_px=1000, height_px=1000),
        n_animals=actual_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    speed = np.zeros((actual_frames, actual_animals))
    heading = np.zeros((actual_frames, actual_animals))
    kine = KinematicsArrays(speed_px_s=speed, accel_px_s2=accel, heading_rad=heading)
    return PreprocessedSession(
        session=sess,
        xy=xy,
        kinematics=kine,
        report=PreprocessReport(),
    )


# ── IL-3: CentreDistance ──────────────────────────────────────────────────────


class TestCentreDistance:
    def test_metric_id(self) -> None:
        assert CentreDistance.id == "IL-3"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = CentreDistance().compute(psess)
        assert "session_id" in df.columns
        assert "individual_id" in df.columns
        assert "mean_centre_distance_px" in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = CentreDistance().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=3)
        df = CentreDistance().compute(psess)
        assert len(df) == 3

    def test_animal_at_centre_has_zero_distance(self) -> None:
        """Animal always at centre (500, 500) → mean_centre_distance_px = 0."""
        n_frames, n_animals = 30, 2
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = [500.0, 500.0]  # animal 0 at centre
        xy[:, 1, :] = [0.0, 0.0]      # animal 1 far from centre
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(psess, cfg={"centre": [500.0, 500.0]})
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_centre_distance_px"] == pytest.approx(0.0, abs=1e-9)

    def test_known_distance_from_explicit_centre(self) -> None:
        """Animal always at (600, 500) with centre (500, 500) → dist = 100."""
        n_frames, n_animals = 10, 1
        xy = np.full((n_frames, n_animals, 2), [600.0, 500.0])
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(psess, cfg={"centre": [500.0, 500.0]})
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_centre_distance_px"] == pytest.approx(100.0, rel=1e-6)

    def test_computed_centre_is_mean_position(self) -> None:
        """Without cfg['centre'], centre = mean of all non-NaN positions."""
        n_frames, n_animals = 4, 1
        # All frames at (200, 300) → computed centre = (200, 300) → distance = 0
        xy = np.full((n_frames, n_animals, 2), [200.0, 300.0])
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(psess)  # no cfg
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_centre_distance_px"] == pytest.approx(0.0, abs=1e-9)

    def test_nan_frames_excluded_from_distance(self) -> None:
        """NaN positions are excluded from the mean distance computation."""
        n_frames, n_animals = 10, 1
        xy = np.full((n_frames, n_animals, 2), [600.0, 500.0])
        xy[3:6, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(psess, cfg={"centre": [500.0, 500.0]})
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert np.isfinite(row0["mean_centre_distance_px"])
        assert row0["mean_centre_distance_px"] == pytest.approx(100.0, rel=1e-6)

    def test_all_nan_returns_nan(self) -> None:
        """Animal with all-NaN positions → mean_centre_distance_px = NaN."""
        n_frames, n_animals = 5, 2
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(psess, cfg={"centre": [0.0, 0.0]})
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert np.isnan(row0["mean_centre_distance_px"])

    def test_time_in_centre_present_when_arena_radius_set(self) -> None:
        """time_in_centre_pct column appears when arena_radius is in cfg."""
        n_frames, n_animals = 20, 2
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = [500.0, 500.0]  # at centre
        xy[:, 1, :] = [900.0, 900.0]  # far from centre
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(
            psess, cfg={"centre": [500.0, 500.0], "arena_radius": 400.0}
        )
        assert "time_in_centre_pct" in df.columns
        # Animal 0 is always inside inner radius (r=200), pct=1.0
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["time_in_centre_pct"] == pytest.approx(1.0, abs=1e-6)
        # Animal 1 is always outside inner radius
        row1 = df[df["individual_id"] == 1].iloc[0]
        assert row1["time_in_centre_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_time_in_centre_absent_without_arena_radius(self) -> None:
        """time_in_centre_pct column is absent when arena_radius is not in cfg."""
        psess = make_psess()
        df = CentreDistance().compute(psess)
        assert "time_in_centre_pct" not in df.columns

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = CentreDistance().compute(psess)
        assert (df["metric_id"] == "IL-3").all()


# ── IL-6: Acceleration ────────────────────────────────────────────────────────


class TestAcceleration:
    def test_metric_id(self) -> None:
        assert Acceleration.id == "IL-6"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = Acceleration().compute(psess)
        for col in [
            "session_id",
            "metric_id",
            "individual_id",
            "mean_abs_accel_px_s2",
            "rms_accel_px_s2",
            "max_accel_px_s2",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = Acceleration().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = Acceleration().compute(psess)
        assert (df["metric_id"] == "IL-6").all()

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=5)
        df = Acceleration().compute(psess)
        assert len(df) == 5

    def test_zero_acceleration(self) -> None:
        """All-zero accel → mean_abs = rms = max = 0."""
        n_frames, n_animals = 30, 2
        accel = np.zeros((n_frames, n_animals))
        psess = make_psess(accel=accel)
        df = Acceleration().compute(psess)
        for k in range(n_animals):
            row = df[df["individual_id"] == k].iloc[0]
            assert row["mean_abs_accel_px_s2"] == pytest.approx(0.0)
            assert row["rms_accel_px_s2"] == pytest.approx(0.0)
            assert row["max_accel_px_s2"] == pytest.approx(0.0)

    def test_constant_acceleration(self) -> None:
        """Constant accel=5 → mean_abs=5, rms=5, max=5."""
        n_frames, n_animals = 40, 1
        accel = np.full((n_frames, n_animals), 5.0)
        psess = make_psess(accel=accel)
        df = Acceleration().compute(psess)
        row = df[df["individual_id"] == 0].iloc[0]
        assert row["mean_abs_accel_px_s2"] == pytest.approx(5.0)
        assert row["rms_accel_px_s2"] == pytest.approx(5.0)
        assert row["max_accel_px_s2"] == pytest.approx(5.0)

    def test_negative_accel_treated_as_abs(self) -> None:
        """Accel with negative values: mean_abs uses absolute value."""
        n_frames, n_animals = 10, 1
        accel = np.full((n_frames, n_animals), -3.0)
        psess = make_psess(accel=accel)
        df = Acceleration().compute(psess)
        row = df.iloc[0]
        assert row["mean_abs_accel_px_s2"] == pytest.approx(3.0)
        assert row["max_accel_px_s2"] == pytest.approx(3.0)

    def test_rms_formula(self) -> None:
        """RMS of [3, 4] = sqrt((9+16)/2) = sqrt(12.5)."""
        n_animals = 1
        accel = np.array([[3.0], [4.0]])
        psess = make_psess(accel=accel, n_frames=2)
        df = Acceleration().compute(psess)
        row = df.iloc[0]
        expected_rms = float(np.sqrt((3**2 + 4**2) / 2))
        assert row["rms_accel_px_s2"] == pytest.approx(expected_rms, rel=1e-6)

    def test_nan_frames_excluded(self) -> None:
        """NaN accel frames are excluded from statistics."""
        n_frames, n_animals = 20, 1
        accel = np.full((n_frames, n_animals), 10.0)
        accel[5:10, 0] = np.nan
        psess = make_psess(accel=accel)
        df = Acceleration().compute(psess)
        row = df.iloc[0]
        assert np.isfinite(row["mean_abs_accel_px_s2"])
        assert row["mean_abs_accel_px_s2"] == pytest.approx(10.0, rel=1e-6)

    def test_all_nan_returns_nan(self) -> None:
        """Animal with all-NaN accel → all statistics are NaN."""
        n_frames, n_animals = 10, 2
        accel = np.full((n_frames, n_animals), 5.0)
        accel[:, 0] = np.nan
        psess = make_psess(accel=accel)
        df = Acceleration().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert np.isnan(row0["mean_abs_accel_px_s2"])
        assert np.isnan(row0["rms_accel_px_s2"])
        assert np.isnan(row0["max_accel_px_s2"])
