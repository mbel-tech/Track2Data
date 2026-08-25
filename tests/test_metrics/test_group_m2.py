"""Tests for group-level metrics GL-2, GL-4, GL-6, GL-8, GL-9, GL-10 (TDD RED phase)."""

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
    RotationalOrder,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    n_frames: int = 50,
    n_animals: int = 4,
    xy: np.ndarray | None = None,
    fps: float = 25.0,
    heading: np.ndarray | None = None,
    speed: np.ndarray | None = None,
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
    if speed is None:
        speed = np.zeros((actual_frames, actual_animals))
    accel = np.zeros((actual_frames, actual_animals))
    if heading is None:
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

    def test_declares_configurable_parameters(self) -> None:
        params = {p.name: p for p in GroupCohesion.parameters}
        assert params.keys() == {"cohesion_source"}
        assert params["cohesion_source"].choices == ["nnd", "iid"]
        assert params["cohesion_source"].default == "nnd"

    def test_cohesion_source_defaults_to_nnd(self) -> None:
        """Three animals in a line: NND-based cohesion differs from
        IID-based cohesion, so this proves the default is really NND
        (matching the historical, only-ever behaviour) rather than
        happening to coincide."""
        n_frames = 5
        xy = np.zeros((n_frames, 3, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [10.0, 0.0]
        xy[:, 2, :] = [100.0, 0.0]
        psess = make_psess(xy=xy)

        df = GroupCohesion().compute(psess)

        # mean_NND = (10 + 10 + 90) / 3 = 36.667 -> cohesion = 1/36.667
        assert df["cohesion_index"].values[0] == pytest.approx(1.0 / (110.0 / 3.0), rel=1e-4)

    def test_cohesion_source_iid_uses_mean_pairwise_distance(self) -> None:
        n_frames = 5
        xy = np.zeros((n_frames, 3, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [10.0, 0.0]
        xy[:, 2, :] = [100.0, 0.0]
        psess = make_psess(xy=xy)

        df = GroupCohesion().compute(psess, cfg={"cohesion_source": "iid"})

        # mean_IID = (10 + 100 + 90) / 3 = 66.667 -> cohesion = 1/66.667
        assert df["cohesion_index"].values[0] == pytest.approx(1.0 / (200.0 / 3.0), rel=1e-4)

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


# ── GL-8: RotationalOrder ─────────────────────────────────────────────────────


class TestRotationalOrder:
    def test_metric_id(self) -> None:
        assert RotationalOrder.id == "GL-8"

    def test_declares_configurable_parameters(self) -> None:
        names = {p.name for p in RotationalOrder.parameters}
        assert names == {"stationary_threshold_px_s"}

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = RotationalOrder().compute(psess)
        for col in [
            "session_id",
            "metric_id",
            "mean_rotational_order",
            "median_rotational_order",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = RotationalOrder().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_single_row_output(self) -> None:
        psess = make_psess()
        df = RotationalOrder().compute(psess)
        assert len(df) == 1

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = RotationalOrder().compute(psess)
        assert (df["metric_id"] == "GL-8").all()

    def test_milling_configuration_gives_m_near_one(self) -> None:
        """4 animals equally spaced on a circle around the centroid, each moving
        tangentially in the same (CCW) sense -> perfect milling, M = 1 exactly.

        Hand-derivation: positions at angles 0, 90, 180, 270 degrees on a
        radius-100 circle centred on the origin sum to (0, 0), so C[t] = (0, 0)
        and r_hat_k equals the unit position vector for every animal. Setting
        each heading to (position_angle + 90 deg) makes e_hat_k perpendicular
        to r_hat_k in the same rotational sense, so r_hat_k x e_hat_k = 1 for
        every animal in every frame.
        """
        n_frames, n_animals = 10, 4
        positions = np.array([[100.0, 0.0], [0.0, 100.0], [-100.0, 0.0], [0.0, -100.0]])
        xy = np.tile(positions, (n_frames, 1, 1))
        headings_vals = np.array([np.pi / 2, np.pi, 3 * np.pi / 2, 0.0])
        heading = np.tile(headings_vals, (n_frames, 1))
        speed = np.full((n_frames, n_animals), 50.0)
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess)
        assert df["mean_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)
        assert df["median_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)

    def test_polarised_configuration_gives_m_near_zero(self) -> None:
        """Same 4 positions as the milling test, but every animal shares the same
        heading (pure translation, non-rotational) -> M = 0 exactly.

        Hand-derivation: with all e_hat_k = (1, 0), the cross products
        r_hat_k x e_hat_k = -r_hat_k.y for the four symmetric r_hat_k vectors
        (0, 1), (1, 0)... -> (0, 1, 0, -1 as the y components) sum to zero, so
        the mean is exactly 0.
        """
        n_frames, n_animals = 10, 4
        positions = np.array([[100.0, 0.0], [0.0, 100.0], [-100.0, 0.0], [0.0, -100.0]])
        xy = np.tile(positions, (n_frames, 1, 1))
        heading = np.zeros((n_frames, n_animals))  # every animal heads +x
        speed = np.full((n_frames, n_animals), 50.0)
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess)
        assert df["mean_rotational_order"].values[0] == pytest.approx(0.0, abs=1e-9)
        assert df["median_rotational_order"].values[0] == pytest.approx(0.0, abs=1e-9)

    def test_stationary_animals_excluded(self) -> None:
        """2 extra stationary animals, placed symmetrically opposite each other so
        they do not perturb the centroid, must be excluded from M; the remaining
        4 milling animals should still give M = 1 exactly.

        (50, 50) and (-50, -50) sum to (0, 0), so C[t] stays at the origin with
        all 6 positions included. If the stationary pair were wrongly kept in the
        average, M would drop to 4/6 = 0.6667 instead of 1.0 (their own cross
        terms of -1/sqrt(2) and +1/sqrt(2) cancel, leaving the divisor changed
        from 4 to 6).
        """
        n_frames, n_animals = 10, 6
        positions = np.array(
            [
                [100.0, 0.0],
                [0.0, 100.0],
                [-100.0, 0.0],
                [0.0, -100.0],
                [50.0, 50.0],
                [-50.0, -50.0],
            ]
        )
        xy = np.tile(positions, (n_frames, 1, 1))
        headings_vals = np.array([np.pi / 2, np.pi, 3 * np.pi / 2, 0.0, 0.0, 0.0])
        heading = np.tile(headings_vals, (n_frames, 1))
        speed = np.full((n_frames, n_animals), 50.0)
        speed[:, 4:] = 0.0  # the extra pair is stationary
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess)
        assert df["mean_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)
        assert df["median_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)

    def test_animal_exactly_at_centroid_is_excluded(self) -> None:
        """An animal sitting exactly on the group centroid has an undefined radial
        direction and must be excluded (not divide by zero / corrupt the mean).

        A = (-100, 0), B = (100, 0), C = (0, 0). Centroid of the 3 = (0, 0), so
        animal C sits exactly on it and must be dropped. With tangential (CCW)
        headings for A and B only, both remaining cross terms equal 1, so
        M = 1 exactly if C is correctly excluded (a crash or NaN/inf leak would
        fail this assertion).
        """
        n_frames, n_animals = 8, 3
        positions = np.array([[-100.0, 0.0], [100.0, 0.0], [0.0, 0.0]])
        xy = np.tile(positions, (n_frames, 1, 1))
        headings_vals = np.array([3 * np.pi / 2, np.pi / 2, 0.0])
        heading = np.tile(headings_vals, (n_frames, 1))
        speed = np.full((n_frames, n_animals), 50.0)
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess)
        assert df["mean_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)
        assert df["median_rotational_order"].values[0] == pytest.approx(1.0, abs=1e-9)

    def test_all_stationary_returns_nan(self) -> None:
        """When every animal is stationary in every frame, no frame reaches the
        2-qualifying-animal minimum -> mean/median are NaN."""
        n_frames, n_animals = 10, 3
        positions = np.array([[0.0, 0.0], [100.0, 0.0], [0.0, 100.0]])
        xy = np.tile(positions, (n_frames, 1, 1))
        heading = np.zeros((n_frames, n_animals))
        speed = np.zeros((n_frames, n_animals))  # nobody moves
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess)
        assert np.isnan(df["mean_rotational_order"].values[0])
        assert np.isnan(df["median_rotational_order"].values[0])

    def test_custom_stationary_threshold_cfg(self) -> None:
        """cfg['stationary_threshold_px_s'] overrides the default 1e-6 px/s
        threshold, mirroring Polarisation's cfg support."""
        n_frames, n_animals = 5, 4
        positions = np.array([[100.0, 0.0], [0.0, 100.0], [-100.0, 0.0], [0.0, -100.0]])
        xy = np.tile(positions, (n_frames, 1, 1))
        headings_vals = np.array([np.pi / 2, np.pi, 3 * np.pi / 2, 0.0])
        heading = np.tile(headings_vals, (n_frames, 1))
        speed = np.full((n_frames, n_animals), 5.0)  # slower than the custom threshold
        psess = make_psess(xy=xy, heading=heading, speed=speed)
        df = RotationalOrder().compute(psess, cfg={"stationary_threshold_px_s": 10.0})
        assert np.isnan(df["mean_rotational_order"].values[0])
