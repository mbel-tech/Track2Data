"""Tests for group-level metrics GL-2, GL-4, GL-6, GL-9, GL-10 (TDD RED phase)."""

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
    ConvexHullArea,
    GroupCentroidPosition,
    GroupCohesion,
    GroupSpread,
    InterIndividualDistance,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    n_frames: int = 50,
    n_animals: int = 4,
    xy: np.ndarray | None = None,
    fps: float = 25.0,
) -> PreprocessedSession:
    rng = np.random.default_rng(42)
    if xy is None:
        xy = rng.random((n_frames, n_animals, 2)) * 500
    actual_frames, actual_animals = xy.shape[0], xy.shape[1]
    sess = Session(
        session_id="test",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=fps, n_frames=actual_frames, width_px=1000, height_px=1000),
        n_animals=actual_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    speed = np.zeros((actual_frames, actual_animals))
    accel = np.zeros((actual_frames, actual_animals))
    heading = np.zeros((actual_frames, actual_animals))
    kine = KinematicsArrays(speed_px_s=speed, accel_px_s2=accel, heading_rad=heading)
    return PreprocessedSession(
        session=sess,
        xy=xy,
        kinematics=kine,
        report=PreprocessReport(),
    )


# ── GL-2: InterIndividualDistance ─────────────────────────────────────────────


class TestInterIndividualDistance:
    def test_metric_id(self) -> None:
        assert InterIndividualDistance.id == "GL-2"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = InterIndividualDistance().compute(psess)
        for col in ["session_id", "metric_id", "mean_iid_px", "median_iid_px"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = InterIndividualDistance().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess()
        df = InterIndividualDistance().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = InterIndividualDistance().compute(psess)
        assert (df["metric_id"] == "GL-2").all()

    def test_two_animals_known_distance(self) -> None:
        """Two animals 200 px apart → mean_iid_px = 200."""
        n_frames = 10
        xy = np.zeros((n_frames, 2, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [200.0, 0.0]
        psess = make_psess(xy=xy)
        df = InterIndividualDistance().compute(psess)
        assert df["mean_iid_px"].values[0] == pytest.approx(200.0, rel=1e-6)
        assert df["median_iid_px"].values[0] == pytest.approx(200.0, rel=1e-6)

    def test_four_animals_known_distances(self) -> None:
        """4 animals on a unit square (100 px side) → check mean IID."""
        n_frames = 5
        xy = np.zeros((n_frames, 4, 2))
        # corners of a 100px square
        corners = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        for k, c in enumerate(corners):
            xy[:, k, :] = c
        psess = make_psess(xy=xy)
        df = InterIndividualDistance().compute(psess)
        # 4 sides of 100, 2 diagonals of 100*sqrt(2)
        # pdist gives 6 pairwise: 4x100 + 2x141.4... = 682.8, mean = 113.8
        expected_mean = (4 * 100 + 2 * 100 * np.sqrt(2)) / 6
        assert df["mean_iid_px"].values[0] == pytest.approx(expected_mean, rel=1e-4)

    def test_nan_frames_skipped(self) -> None:
        """Frames where any animal has NaN are skipped gracefully."""
        n_frames, n_animals = 20, 3
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 1, :] = [100.0, 0.0]
        xy[:, 2, :] = [50.0, 50.0]
        xy[5:10, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = InterIndividualDistance().compute(psess)
        assert np.isfinite(df["mean_iid_px"].values[0])

    def test_single_animal_returns_nan(self) -> None:
        """With only 1 animal, IID is undefined."""
        xy = np.zeros((10, 1, 2))
        psess = make_psess(xy=xy)
        df = InterIndividualDistance().compute(psess)
        assert len(df) == 1
        assert np.isnan(df["mean_iid_px"].values[0])

    def test_values_non_negative(self) -> None:
        psess = make_psess()
        df = InterIndividualDistance().compute(psess)
        assert df["mean_iid_px"].values[0] >= 0


# ── GL-4: ConvexHullArea ──────────────────────────────────────────────────────


class TestConvexHullArea:
    def test_metric_id(self) -> None:
        assert ConvexHullArea.id == "GL-4"

    def test_output_columns_present(self) -> None:
        psess = make_psess(n_animals=4)
        df = ConvexHullArea().compute(psess)
        for col in ["session_id", "metric_id", "mean_hull_area_px2", "median_hull_area_px2"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess(n_animals=4)
        df = ConvexHullArea().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess(n_animals=4)
        df = ConvexHullArea().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess(n_animals=4)
        df = ConvexHullArea().compute(psess)
        assert (df["metric_id"] == "GL-4").all()

    def test_four_corners_known_area(self) -> None:
        """4 animals at corners of 100x100 square → hull area = 10000."""
        n_frames = 5
        xy = np.zeros((n_frames, 4, 2))
        corners = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        for k, c in enumerate(corners):
            xy[:, k, :] = c
        psess = make_psess(xy=xy)
        df = ConvexHullArea().compute(psess)
        assert df["mean_hull_area_px2"].values[0] == pytest.approx(10000.0, rel=1e-4)
        assert df["median_hull_area_px2"].values[0] == pytest.approx(10000.0, rel=1e-4)

    def test_fewer_than_3_animals_returns_nan(self) -> None:
        """ConvexHull requires ≥3 animals; with 2 should return NaN."""
        n_frames = 10
        xy = np.zeros((n_frames, 2, 2))
        xy[:, 1, 0] = 100.0
        psess = make_psess(xy=xy)
        df = ConvexHullArea().compute(psess)
        assert len(df) == 1
        assert np.isnan(df["mean_hull_area_px2"].values[0])

    def test_nan_frames_skipped(self) -> None:
        """Frames with NaN positions are skipped."""
        n_frames, n_animals = 20, 4
        xy = np.zeros((n_frames, n_animals, 2))
        corners = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        for k, c in enumerate(corners):
            xy[:, k, :] = c
        xy[3:7, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = ConvexHullArea().compute(psess)
        assert np.isfinite(df["mean_hull_area_px2"].values[0])

    def test_area_non_negative(self) -> None:
        psess = make_psess(n_animals=5)
        df = ConvexHullArea().compute(psess)
        val = df["mean_hull_area_px2"].values[0]
        if not np.isnan(val):
            assert val >= 0.0


# ── GL-6: GroupCohesion ───────────────────────────────────────────────────────


class TestGroupCohesion:
    def test_metric_id(self) -> None:
        assert GroupCohesion.id == "GL-6"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = GroupCohesion().compute(psess)
        for col in ["session_id", "metric_id", "cohesion_index"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = GroupCohesion().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess()
        df = GroupCohesion().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = GroupCohesion().compute(psess)
        assert (df["metric_id"] == "GL-6").all()

    def test_cohesion_is_inverse_of_mean_nnd(self) -> None:
        """cohesion_index = 1 / mean_NND; with 2 animals 100 px apart, cohesion = 1/100."""
        n_frames = 10
        xy = np.zeros((n_frames, 2, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [100.0, 0.0]
        psess = make_psess(xy=xy)
        df = GroupCohesion().compute(psess)
        assert df["cohesion_index"].values[0] == pytest.approx(1.0 / 100.0, rel=1e-4)

    def test_cohesion_positive(self) -> None:
        psess = make_psess()
        df = GroupCohesion().compute(psess)
        val = df["cohesion_index"].values[0]
        if not np.isnan(val):
            assert val > 0.0

    def test_single_animal_cohesion_nan(self) -> None:
        """With 1 animal, NND is undefined → cohesion_index = NaN."""
        xy = np.zeros((10, 1, 2))
        psess = make_psess(xy=xy)
        df = GroupCohesion().compute(psess)
        assert np.isnan(df["cohesion_index"].values[0])


# ── GL-9: GroupCentroidPosition ───────────────────────────────────────────────


class TestGroupCentroidPosition:
    def test_metric_id(self) -> None:
        assert GroupCentroidPosition.id == "GL-9"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = GroupCentroidPosition().compute(psess)
        for col in ["session_id", "metric_id", "mean_centroid_x_px", "mean_centroid_y_px"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = GroupCentroidPosition().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess()
        df = GroupCentroidPosition().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = GroupCentroidPosition().compute(psess)
        assert (df["metric_id"] == "GL-9").all()

    def test_known_centroid(self) -> None:
        """2 animals at fixed positions → centroid = mean."""
        n_frames = 10
        xy = np.zeros((n_frames, 2, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [200.0, 400.0]
        psess = make_psess(xy=xy)
        df = GroupCentroidPosition().compute(psess)
        assert df["mean_centroid_x_px"].values[0] == pytest.approx(100.0, rel=1e-6)
        assert df["mean_centroid_y_px"].values[0] == pytest.approx(200.0, rel=1e-6)

    def test_nan_animals_excluded_from_centroid(self) -> None:
        """NaN animals are excluded from centroid computation per frame."""
        n_frames, n_animals = 10, 3
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [200.0, 0.0]
        xy[:, 2, :] = np.nan  # excluded
        psess = make_psess(xy=xy)
        df = GroupCentroidPosition().compute(psess)
        assert df["mean_centroid_x_px"].values[0] == pytest.approx(100.0, rel=1e-6)
        assert df["mean_centroid_y_px"].values[0] == pytest.approx(0.0, abs=1e-9)

    def test_all_nan_frame_skipped(self) -> None:
        """Frames where all animals are NaN should be skipped (not crash)."""
        n_frames, n_animals = 10, 2
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = [100.0, 100.0]
        xy[:, 1, :] = [300.0, 300.0]
        xy[0, :, :] = np.nan  # all NaN frame
        psess = make_psess(xy=xy)
        df = GroupCentroidPosition().compute(psess)
        assert np.isfinite(df["mean_centroid_x_px"].values[0])


# ── GL-10: GroupSpread ────────────────────────────────────────────────────────


class TestGroupSpread:
    def test_metric_id(self) -> None:
        assert GroupSpread.id == "GL-10"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = GroupSpread().compute(psess)
        for col in ["session_id", "metric_id", "mean_group_spread_px"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = GroupSpread().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess()
        df = GroupSpread().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = GroupSpread().compute(psess)
        assert (df["metric_id"] == "GL-10").all()

    def test_all_animals_at_same_position(self) -> None:
        """All animals at same point → spread = 0."""
        n_frames, n_animals = 10, 4
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, :, :] = [50.0, 50.0]
        psess = make_psess(xy=xy)
        df = GroupSpread().compute(psess)
        assert df["mean_group_spread_px"].values[0] == pytest.approx(0.0, abs=1e-9)

    def test_known_spread(self) -> None:
        """2 animals at (0,0) and (200,0) → centroid at (100,0).
        Distances from centroid: both 100. RMS = 100."""
        n_frames = 10
        xy = np.zeros((n_frames, 2, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [200.0, 0.0]
        psess = make_psess(xy=xy)
        df = GroupSpread().compute(psess)
        assert df["mean_group_spread_px"].values[0] == pytest.approx(100.0, rel=1e-6)

    def test_spread_non_negative(self) -> None:
        psess = make_psess()
        df = GroupSpread().compute(psess)
        val = df["mean_group_spread_px"].values[0]
        if not np.isnan(val):
            assert val >= 0.0

    def test_nan_frames_skipped(self) -> None:
        """Frames with NaN are skipped gracefully."""
        n_frames, n_animals = 20, 2
        xy = np.zeros((n_frames, n_animals, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [200.0, 0.0]
        xy[5:8, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = GroupSpread().compute(psess)
        assert np.isfinite(df["mean_group_spread_px"].values[0])
