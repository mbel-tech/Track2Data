"""Tests for group-level metrics GL-11, GL-13, GL-15 -- the reference-
audit proposals: order-state classification, topological k-NN counts,
and group elongation.
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
    GroupElongation,
    OrderStateClassification,
    TopologicalNeighbourCounts,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    xy: np.ndarray | None = None,
    speed: np.ndarray | None = None,
    heading: np.ndarray | None = None,
    n_frames: int = 50,
    n_animals: int = 5,
    fps: float = 25.0,
) -> PreprocessedSession:
    if xy is None:
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    actual_frames, actual_animals = xy.shape[0], xy.shape[1]
    if speed is None:
        speed = np.ones((actual_frames, actual_animals))
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
    return PreprocessedSession(session=sess, xy=xy, kinematics=kine, report=PreprocessReport())


# ── GL-11: OrderStateClassification ───────────────────────────────────────────


class TestOrderStateClassification:
    def test_metric_id(self) -> None:
        assert OrderStateClassification.id == "GL-11"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = OrderStateClassification().compute(psess)
        for col in (
            "session_id",
            "polarised_time_pct",
            "milling_time_pct",
            "swarm_time_pct",
            "n_classified_frames",
        ):
            assert col in df.columns

    def test_identical_headings_classify_as_polarised(self) -> None:
        n_frames, n_animals = 20, 5
        heading = np.full((n_frames, n_animals), 0.3)
        speed = np.ones((n_frames, n_animals))
        xy = np.random.default_rng(0).uniform(0, 500, size=(n_frames, n_animals, 2))
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = OrderStateClassification().compute(psess)
        assert df.iloc[0]["polarised_time_pct"] == pytest.approx(1.0)
        assert df.iloc[0]["n_classified_frames"] == n_frames

    def test_milling_arrangement_classifies_as_milling(self) -> None:
        n_frames, n_animals = 10, 8
        angles = np.linspace(0, 2 * np.pi, n_animals, endpoint=False)
        radius = 50.0
        centre = np.array([100.0, 100.0])
        xy = np.zeros((n_frames, n_animals, 2))
        heading = np.zeros((n_frames, n_animals))
        for t in range(n_frames):
            frame_angles = angles + 0.1 * t
            xy[t, :, 0] = centre[0] + radius * np.cos(frame_angles)
            xy[t, :, 1] = centre[1] + radius * np.sin(frame_angles)
            # Tangential heading (perpendicular to radial direction).
            heading[t, :] = frame_angles + np.pi / 2
        speed = np.ones((n_frames, n_animals)) * 5.0
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        df = OrderStateClassification().compute(psess)
        assert df.iloc[0]["milling_time_pct"] > 0.5

    def test_thresholds_are_configurable(self) -> None:
        n_frames, n_animals = 20, 5
        heading = np.full((n_frames, n_animals), 0.3)
        speed = np.ones((n_frames, n_animals))
        xy = np.random.default_rng(1).uniform(0, 500, size=(n_frames, n_animals, 2))
        psess = make_psess(xy=xy, speed=speed, heading=heading)
        # An impossible polarised threshold (> 1) means no frame can ever qualify.
        df = OrderStateClassification().compute(psess, cfg={"polarised_threshold": 1.5})
        assert df.iloc[0]["polarised_time_pct"] == pytest.approx(0.0)

    def test_no_moving_animals_returns_nan(self) -> None:
        n_frames, n_animals = 5, 3
        speed = np.zeros((n_frames, n_animals))
        psess = make_psess(speed=speed, n_frames=n_frames, n_animals=n_animals)
        df = OrderStateClassification().compute(psess)
        assert np.isnan(df.iloc[0]["polarised_time_pct"])
        assert df.iloc[0]["n_classified_frames"] == 0


# ── GL-13: TopologicalNeighbourCounts ─────────────────────────────────────────


class TestTopologicalNeighbourCounts:
    def test_metric_id(self) -> None:
        assert TopologicalNeighbourCounts.id == "GL-13"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = TopologicalNeighbourCounts().compute(psess)
        for col in (
            "session_id",
            "k",
            "mean_kth_nn_distance_px",
            "mean_neighbours_within_radius",
        ):
            assert col in df.columns

    def test_emits_one_row_per_k(self) -> None:
        rng = np.random.default_rng(2)
        xy = rng.uniform(0, 500, size=(10, 6, 2))
        psess = make_psess(xy=xy, n_frames=10, n_animals=6)
        df = TopologicalNeighbourCounts().compute(psess, cfg={"k_max": 4})
        assert sorted(df["k"].tolist()) == [1, 2, 3, 4]

    def test_kth_distance_increases_with_k(self) -> None:
        rng = np.random.default_rng(3)
        xy = rng.uniform(0, 500, size=(20, 6, 2))
        psess = make_psess(xy=xy, n_frames=20, n_animals=6)
        df = TopologicalNeighbourCounts().compute(psess, cfg={"k_max": 3}).sort_values("k")
        distances = df["mean_kth_nn_distance_px"].to_numpy()
        assert (np.diff(distances) > 0).all()

    def test_two_close_pairs_have_two_neighbours_within_radius(self) -> None:
        n_frames = 3
        xy = np.zeros((n_frames, 4, 2))
        for t in range(n_frames):
            xy[t] = [[0.0, 0.0], [1.0, 0.0], [100.0, 0.0], [101.0, 0.0]]
        psess = make_psess(xy=xy, n_frames=n_frames, n_animals=4)
        df = TopologicalNeighbourCounts().compute(psess, cfg={"k_max": 1, "radius_px": 5.0})
        assert df.iloc[0]["mean_neighbours_within_radius"] == pytest.approx(1.0)


# ── GL-15: GroupElongation ────────────────────────────────────────────────────


class TestGroupElongation:
    def test_metric_id(self) -> None:
        assert GroupElongation.id == "GL-15"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = GroupElongation().compute(psess)
        for col in ("session_id", "mean_elongation_ratio", "mean_major_axis_orientation_rad"):
            assert col in df.columns

    def test_elongated_line_gives_high_ratio(self) -> None:
        n_frames = 5
        xy = np.zeros((n_frames, 5, 2))
        for t in range(n_frames):
            xy[t, :, 0] = [0.0, 10.0, 20.0, 30.0, 40.0]  # spread along x
            xy[t, :, 1] = [50.0, 50.5, 49.5, 50.2, 49.8]  # tight along y
        psess = make_psess(xy=xy, n_frames=n_frames, n_animals=5)
        df = GroupElongation().compute(psess)
        assert df.iloc[0]["mean_elongation_ratio"] > 5.0

    def test_circular_arrangement_gives_ratio_near_one(self) -> None:
        n_animals = 12
        angles = np.linspace(0, 2 * np.pi, n_animals, endpoint=False)
        xy = np.zeros((3, n_animals, 2))
        for t in range(3):
            xy[t, :, 0] = 100 + 50 * np.cos(angles)
            xy[t, :, 1] = 100 + 50 * np.sin(angles)
        psess = make_psess(xy=xy, n_frames=3, n_animals=n_animals)
        df = GroupElongation().compute(psess)
        assert df.iloc[0]["mean_elongation_ratio"] == pytest.approx(1.0, abs=0.15)

    def test_fewer_than_three_animals_returns_nan(self) -> None:
        xy = np.zeros((5, 2, 2))
        xy[:, 0, :] = [0.0, 0.0]
        xy[:, 1, :] = [10.0, 10.0]
        psess = make_psess(xy=xy, n_frames=5, n_animals=2)
        df = GroupElongation().compute(psess)
        assert np.isnan(df.iloc[0]["mean_elongation_ratio"])
