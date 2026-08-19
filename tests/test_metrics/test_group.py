"""
Tests for group-level metrics: GL-1, GL-3, GL-5, GL-7.

TDD RED phase — these tests are written before the implementation.
"""

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
from track2data.metrics.group import (
    CentroidSpeed,
    NearestNeighbourDistance,
    NNMatchedSpeed,
    Polarisation,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_session(n_frames: int, n_animals: int, xy: np.ndarray) -> Session:
    return Session(
        session_id="test",
        folder=Path("/tmp/t"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=200, height_px=200),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )


def make_psess(
    xy: np.ndarray | None = None,
    speed: np.ndarray | None = None,
    heading: np.ndarray | None = None,
    n_frames: int = 50,
    n_animals: int = 2,
    px_per_cm: float | None = None,
    body_length_cm: np.ndarray | None = None,
    fps: float = 25.0,
) -> PreprocessedSession:
    """Build a minimal PreprocessedSession for group metric tests."""
    if xy is None:
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)

    actual_frames, actual_animals = xy.shape[0], xy.shape[1]

    if speed is None:
        speed = np.zeros((actual_frames, actual_animals))

    if heading is None:
        heading = np.zeros((actual_frames, actual_animals))

    sess = Session(
        session_id="test",
        folder=Path("/tmp/t"),
        reader="test",
        video=VideoInfo(fps=fps, n_frames=actual_frames, width_px=512, height_px=512),
        n_animals=actual_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=speed,
        accel_px_s2=np.zeros_like(speed),
        heading_rad=heading,
    )
    return PreprocessedSession(
        session=sess,
        xy=xy,
        kinematics=kine,
        px_per_cm=px_per_cm,
        body_length_cm=body_length_cm,
        report=PreprocessReport(),
    )


# ── GL-1: NearestNeighbourDistance ────────────────────────────────────────────


class TestNearestNeighbourDistance:
    def test_two_animals_constant_distance(self) -> None:
        """Two animals 100 px apart at all times → mean_nnd_px = 100."""
        xy = np.zeros((50, 2, 2), dtype=np.float64)
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [100.0, 0.0]
        psess = make_psess(xy=xy)
        df = NearestNeighbourDistance().compute(psess)
        assert df["mean_nnd_px"].values[0] == pytest.approx(100.0, rel=1e-3)

    def test_median_nnd_constant_distance(self) -> None:
        xy = np.zeros((50, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 80.0
        psess = make_psess(xy=xy)
        df = NearestNeighbourDistance().compute(psess)
        assert df["median_nnd_px"].values[0] == pytest.approx(80.0, rel=1e-3)

    def test_nnd_cm_when_calibrated(self) -> None:
        xy = np.zeros((10, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 200.0
        psess = make_psess(xy=xy, px_per_cm=10.0)
        df = NearestNeighbourDistance().compute(psess)
        assert df["mean_nnd_cm"].values[0] == pytest.approx(20.0, rel=1e-3)

    def test_nnd_cm_absent_when_uncalibrated(self) -> None:
        xy = np.zeros((10, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 50.0
        psess = make_psess(xy=xy, px_per_cm=None)
        df = NearestNeighbourDistance().compute(psess)
        if "mean_nnd_cm" in df.columns:
            assert df["mean_nnd_cm"].isna().all()

    def test_nan_frames_skipped(self) -> None:
        """Frames where any animal has NaN are excluded from NND calculation."""
        xy = np.zeros((20, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 100.0
        xy[5:10, 0, :] = np.nan  # NaN in animal 0
        psess = make_psess(xy=xy)
        df = NearestNeighbourDistance().compute(psess)
        assert np.isfinite(df["mean_nnd_px"].values[0])

    def test_skipped_frame_count_returned(self) -> None:
        """n_skipped_frames must be in output and reflect NaN frame count."""
        xy = np.zeros((20, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 100.0
        xy[5:10, 0, :] = np.nan  # 5 frames skipped
        psess = make_psess(xy=xy)
        df = NearestNeighbourDistance().compute(psess)
        assert "n_skipped_frames" in df.columns
        assert df["n_skipped_frames"].values[0] == 5

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = NearestNeighbourDistance().compute(psess)
        for col in ["session_id", "metric_id", "mean_nnd_px", "median_nnd_px"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = NearestNeighbourDistance().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_metric_id_column(self) -> None:
        xy = np.zeros((10, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 50.0
        df = NearestNeighbourDistance().compute(make_psess(xy=xy))
        assert (df["metric_id"] == "GL-1").all()

    def test_nnd_bl_when_body_length_available(self) -> None:
        xy = np.zeros((10, 2, 2), dtype=np.float64)
        xy[:, 1, 0] = 100.0  # 100 px apart
        # 100 px / 10 px_per_cm = 10 cm / 5 cm_per_bl = 2 BL
        psess = make_psess(xy=xy, px_per_cm=10.0, body_length_cm=np.array([5.0, 5.0]))
        df = NearestNeighbourDistance().compute(psess)
        assert df["mean_nnd_bl"].values[0] == pytest.approx(2.0, rel=1e-3)

    def test_single_animal_returns_nan(self) -> None:
        """With only 1 animal, NND is undefined — output should be NaN or empty."""
        xy = np.zeros((10, 1, 2), dtype=np.float64)
        psess = make_psess(xy=xy)
        df = NearestNeighbourDistance().compute(psess)
        # Either empty df or NaN values are acceptable
        if len(df) > 0:
            assert df["mean_nnd_px"].isna().all() or np.isnan(df["mean_nnd_px"].values[0])


# ── GL-3: Polarisation ────────────────────────────────────────────────────────


class TestPolarisation:
    def test_perfectly_aligned(self) -> None:
        """All animals heading right (0 rad) → polarisation = 1.0."""
        n_frames, n_animals = 100, 4
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        heading = np.zeros((n_frames, n_animals))  # all pointing right
        speed = np.full((n_frames, n_animals), 50.0)  # all moving
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        assert df["mean_polarisation"].values[0] == pytest.approx(1.0, abs=0.05)

    def test_opposite_directions(self) -> None:
        """Half animals head right (0), half head left (π) → polarisation ≈ 0."""
        n_frames, n_animals = 100, 4
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        heading = np.zeros((n_frames, n_animals))
        heading[:, 2:] = np.pi  # last two head left
        speed = np.full((n_frames, n_animals), 50.0)
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        assert df["mean_polarisation"].values[0] == pytest.approx(0.0, abs=0.05)

    def test_stationary_animals_excluded(self) -> None:
        """Stationary animals (speed ≈ 0) must be excluded from heading sum."""
        n_frames, n_animals = 50, 4
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        heading = np.zeros((n_frames, n_animals))
        heading[:, 3] = np.pi  # animal 3 heads opposite
        speed = np.full((n_frames, n_animals), 50.0)
        speed[:, 3] = 0.0  # animal 3 is stationary → excluded
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        # Without animal 3, all moving animals head right → polarisation = 1
        assert df["mean_polarisation"].values[0] == pytest.approx(1.0, abs=0.1)

    def test_skip_frames_with_fewer_than_2_valid(self) -> None:
        """Frames with fewer than 2 valid headings are skipped."""
        n_frames, n_animals = 20, 2
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        heading = np.zeros((n_frames, n_animals))
        speed = np.full((n_frames, n_animals), 50.0)
        speed[0:10, 1] = 0.0   # frames 0-9: only 1 moving animal
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        # Should still return a value (from valid frames 10-19)
        assert np.isfinite(df["mean_polarisation"].values[0])

    def test_output_columns_present(self) -> None:
        n_frames, n_animals = 50, 3
        heading = np.zeros((n_frames, n_animals))
        speed = np.full((n_frames, n_animals), 50.0)
        psess = make_psess(speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        for col in ["session_id", "metric_id", "mean_polarisation", "median_polarisation"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        n_frames, n_animals = 50, 2
        speed = np.full((n_frames, n_animals), 50.0)
        heading = np.zeros((n_frames, n_animals))
        psess = make_psess(speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        assert (df["metric_id"] == "GL-3").all()

    def test_polarisation_range(self) -> None:
        """Polarisation must always be in [0, 1]."""
        rng = np.random.default_rng(99)
        n_frames, n_animals = 200, 6
        heading = rng.uniform(-np.pi, np.pi, (n_frames, n_animals))
        speed = rng.uniform(0, 100, (n_frames, n_animals))
        psess = make_psess(speed=speed, heading=heading)
        df = Polarisation().compute(psess)
        val = df["mean_polarisation"].values[0]
        assert 0.0 <= val <= 1.0 + 1e-9


# ── GL-5: CentroidSpeed ───────────────────────────────────────────────────────


class TestCentroidSpeed:
    def test_static_group(self) -> None:
        """Static group → centroid speed = 0."""
        xy = np.zeros((50, 3, 2), dtype=np.float64)
        psess = make_psess(xy=xy)
        df = CentroidSpeed().compute(psess)
        assert df["mean_centroid_speed_px_s"].values[0] == pytest.approx(0.0, abs=1e-6)

    def test_group_moving_constant_velocity(self) -> None:
        """All animals move 4 px/frame → centroid speed = 4 * fps = 100 px/s."""
        n_frames, n_animals = 100, 3
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
        psess = make_psess(xy=xy, fps=25.0)
        df = CentroidSpeed().compute(psess)
        assert df["mean_centroid_speed_px_s"].values[0] == pytest.approx(100.0, rel=1e-3)

    def test_centroid_speed_cm_s_when_calibrated(self) -> None:
        n_frames, n_animals = 50, 2
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
        psess = make_psess(xy=xy, fps=25.0, px_per_cm=10.0)
        df = CentroidSpeed().compute(psess)
        assert df["mean_centroid_speed_cm_s"].values[0] == pytest.approx(10.0, rel=1e-3)

    def test_centroid_speed_cm_absent_when_uncalibrated(self) -> None:
        psess = make_psess(px_per_cm=None)
        df = CentroidSpeed().compute(psess)
        if "mean_centroid_speed_cm_s" in df.columns:
            assert df["mean_centroid_speed_cm_s"].isna().all()

    def test_nan_animals_excluded_from_centroid(self) -> None:
        """NaN positions for some animals are excluded from centroid computation."""
        n_frames, n_animals = 20, 3
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
        xy[:, 2, :] = np.nan  # animal 2 always NaN
        psess = make_psess(xy=xy, fps=25.0)
        df = CentroidSpeed().compute(psess)
        # Centroid from 2 animals → same speed as if 3 animals all moved identically
        assert df["mean_centroid_speed_px_s"].values[0] == pytest.approx(100.0, rel=1e-3)

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = CentroidSpeed().compute(psess)
        for col in ["session_id", "metric_id", "mean_centroid_speed_px_s"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        df = CentroidSpeed().compute(make_psess())
        assert (df["metric_id"] == "GL-5").all()

    def test_single_row_output(self) -> None:
        """CentroidSpeed must return exactly one row per session."""
        psess = make_psess(n_animals=4)
        df = CentroidSpeed().compute(psess)
        assert len(df) == 1


# ── GL-7: NNMatchedSpeed ──────────────────────────────────────────────────────


class TestNNMatchedSpeed:
    def test_static_group(self) -> None:
        """Static group → matched speed = 0."""
        xy = np.zeros((50, 3, 2), dtype=np.float64)
        psess = make_psess(xy=xy)
        df = NNMatchedSpeed().compute(psess)
        assert df["mean_matched_speed_px_s"].values[0] == pytest.approx(0.0, abs=1e-6)

    def test_constant_velocity_group(self) -> None:
        """All animals move 4 px/frame → matched speed = 4 * fps = 100 px/s."""
        n_frames, n_animals = 100, 3
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
            # offset so animals are distinct
            xy[:, k, 1] = float(k) * 100.0
        psess = make_psess(xy=xy, fps=25.0)
        df = NNMatchedSpeed().compute(psess)
        assert df["mean_matched_speed_px_s"].values[0] == pytest.approx(100.0, rel=1e-3)

    def test_matched_speed_cm_s_when_calibrated(self) -> None:
        n_frames, n_animals = 50, 2
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
            xy[:, k, 1] = float(k) * 100.0
        psess = make_psess(xy=xy, fps=25.0, px_per_cm=10.0)
        df = NNMatchedSpeed().compute(psess)
        assert df["mean_matched_speed_cm_s"].values[0] == pytest.approx(10.0, rel=1e-3)

    def test_matched_speed_cm_absent_when_uncalibrated(self) -> None:
        psess = make_psess(px_per_cm=None)
        df = NNMatchedSpeed().compute(psess)
        if "mean_matched_speed_cm_s" in df.columns:
            assert df["mean_matched_speed_cm_s"].isna().all()

    def test_nan_frame_pairs_skipped(self) -> None:
        """Frame pairs where any animal has NaN are skipped gracefully."""
        n_frames, n_animals = 20, 2
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 0] = np.arange(n_frames, dtype=np.float64) * 4.0
            xy[:, k, 1] = float(k) * 50.0
        xy[5:10, 0, :] = np.nan
        psess = make_psess(xy=xy, fps=25.0)
        df = NNMatchedSpeed().compute(psess)
        assert np.isfinite(df["mean_matched_speed_px_s"].values[0])

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = NNMatchedSpeed().compute(psess)
        for col in ["session_id", "metric_id", "mean_matched_speed_px_s"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        n_frames, n_animals = 20, 2
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        for k in range(n_animals):
            xy[:, k, 1] = float(k) * 50.0
        df = NNMatchedSpeed().compute(make_psess(xy=xy))
        assert (df["metric_id"] == "GL-7").all()

    def test_single_row_output(self) -> None:
        """NNMatchedSpeed must return exactly one row per session."""
        psess = make_psess(n_animals=3)
        df = NNMatchedSpeed().compute(psess)
        assert len(df) == 1
