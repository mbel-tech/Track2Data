"""Tests for individual-level metrics IL-9, IL-10, IL-11, IL-14 -- the
reference-audit proposals: home-base occupancy, roaming entropy,
circular heading statistics, and wall-distance thigmotaxis.
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
from track2data.metrics.derived import derive_metric_params
from track2data.metrics.individual import (
    CircularHeadingStats,
    HomeBaseOccupancy,
    RoamingEntropy,
    WallDistanceThigmotaxis,
)

pytest.importorskip("shapely")

from track2data.core.models import ROI, ZoneSet

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    n_frames: int = 50,
    n_animals: int = 2,
    xy: np.ndarray | None = None,
    heading: np.ndarray | None = None,
    speed: np.ndarray | None = None,
    main_zone: np.ndarray | None = None,
    width_px: int = 200,
    height_px: int = 200,
) -> PreprocessedSession:
    if xy is None:
        xy = np.zeros((n_frames, n_animals, 2))
    actual_frames, actual_animals = xy.shape[0], xy.shape[1]
    if heading is None:
        heading = np.zeros((actual_frames, actual_animals))
    if speed is None:
        speed = np.ones((actual_frames, actual_animals))
    sess = Session(
        session_id="test",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=actual_frames, width_px=width_px, height_px=height_px),
        n_animals=actual_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=speed,
        accel_px_s2=np.zeros((actual_frames, actual_animals)),
        heading_rad=heading,
    )
    return PreprocessedSession(
        session=sess,
        xy=xy,
        kinematics=kine,
        main_zone=main_zone,
        report=PreprocessReport(),
    )


# ── IL-9: HomeBaseOccupancy ───────────────────────────────────────────────────


class TestHomeBaseOccupancy:
    def test_metric_id(self) -> None:
        assert HomeBaseOccupancy.id == "IL-9"

    def test_output_columns_present(self) -> None:
        xy = np.zeros((50, 2, 2))
        psess = make_psess(xy=xy)
        df = HomeBaseOccupancy().compute(psess)
        for col in ("session_id", "individual_id", "home_base_time_pct", "home_base_stable"):
            assert col in df.columns

    def test_corner_hugging_animal_has_high_home_base_pct(self) -> None:
        n_frames = 100
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, :] = 5.0  # stays in one tiny cell the whole session
        psess = make_psess(n_frames=n_frames, n_animals=1, xy=xy)
        df = HomeBaseOccupancy().compute(psess)
        assert df.iloc[0]["home_base_time_pct"] == pytest.approx(1.0)
        assert df.iloc[0]["home_base_stable"] is True or df.iloc[0]["home_base_stable"] == True  # noqa: E712

    def test_roaming_animal_has_low_home_base_pct(self) -> None:
        rng = np.random.default_rng(0)
        n_frames = 500
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, :] = rng.uniform(0, 500, size=(n_frames, 2))
        psess = make_psess(n_frames=n_frames, n_animals=1, xy=xy)
        df = HomeBaseOccupancy().compute(psess)
        assert df.iloc[0]["home_base_time_pct"] < 0.5

    def test_all_nan_animal_returns_nan(self) -> None:
        xy = np.full((20, 1, 2), np.nan)
        psess = make_psess(n_frames=20, n_animals=1, xy=xy)
        df = HomeBaseOccupancy().compute(psess)
        assert np.isnan(df.iloc[0]["home_base_time_pct"])

    def test_bin_size_px_is_configurable(self) -> None:
        xy = np.zeros((50, 1, 2))
        psess = make_psess(n_frames=50, n_animals=1, xy=xy)
        df = HomeBaseOccupancy().compute(psess, cfg={"bin_size_px": 5.0})
        assert df.iloc[0]["home_base_time_pct"] == pytest.approx(1.0)

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        psess.session.session_id  # noqa: B018
        df = HomeBaseOccupancy().compute(psess)
        assert (df["session_id"] == "test").all()


# ── IL-10: RoamingEntropy ─────────────────────────────────────────────────────


class TestRoamingEntropy:
    def test_metric_id(self) -> None:
        assert RoamingEntropy.id == "IL-10"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = RoamingEntropy().compute(psess)
        for col in (
            "session_id",
            "individual_id",
            "roaming_entropy_bits",
            "roaming_entropy_normalised",
            "n_visited_cells",
        ):
            assert col in df.columns

    def test_single_cell_has_zero_entropy_and_one_visited_cell(self) -> None:
        xy = np.full((50, 1, 2), 5.0)
        psess = make_psess(n_frames=50, n_animals=1, xy=xy)
        df = RoamingEntropy().compute(psess)
        assert df.iloc[0]["roaming_entropy_bits"] == pytest.approx(0.0)
        assert df.iloc[0]["n_visited_cells"] == 1
        assert np.isnan(df.iloc[0]["roaming_entropy_normalised"])

    def test_roaming_animal_has_higher_entropy_than_stationary(self) -> None:
        rng = np.random.default_rng(1)
        n_frames = 500
        xy_roam = np.zeros((n_frames, 1, 2))
        xy_roam[:, 0, :] = rng.uniform(0, 500, size=(n_frames, 2))
        xy_still = np.full((n_frames, 1, 2), 5.0)

        entropy_roam = RoamingEntropy().compute(
            make_psess(n_frames=n_frames, n_animals=1, xy=xy_roam)
        ).iloc[0]["roaming_entropy_bits"]
        entropy_still = RoamingEntropy().compute(
            make_psess(n_frames=n_frames, n_animals=1, xy=xy_still)
        ).iloc[0]["roaming_entropy_bits"]

        assert entropy_roam > entropy_still

    def test_all_nan_animal_returns_nan(self) -> None:
        xy = np.full((20, 1, 2), np.nan)
        psess = make_psess(n_frames=20, n_animals=1, xy=xy)
        df = RoamingEntropy().compute(psess)
        assert np.isnan(df.iloc[0]["roaming_entropy_bits"])
        assert df.iloc[0]["n_visited_cells"] == 0


# ── IL-11: CircularHeadingStats ───────────────────────────────────────────────


class TestCircularHeadingStats:
    def test_metric_id(self) -> None:
        assert CircularHeadingStats.id == "IL-11"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = CircularHeadingStats().compute(psess)
        for col in (
            "session_id",
            "individual_id",
            "mean_heading_rad",
            "resultant_length",
            "rayleigh_p",
            "left_right_turn_bias",
        ):
            assert col in df.columns

    def test_identical_headings_give_resultant_length_one(self) -> None:
        n_frames = 30
        heading = np.full((n_frames, 1), 0.7)
        psess = make_psess(n_frames=n_frames, n_animals=1, heading=heading)
        df = CircularHeadingStats().compute(psess)
        assert df.iloc[0]["resultant_length"] == pytest.approx(1.0, abs=1e-6)
        assert df.iloc[0]["mean_heading_rad"] == pytest.approx(0.7, abs=1e-6)

    def test_uniform_headings_reject_low_r_and_high_p(self) -> None:
        rng = np.random.default_rng(2)
        n_frames = 2000
        heading = rng.uniform(-np.pi, np.pi, size=(n_frames, 1))
        psess = make_psess(n_frames=n_frames, n_animals=1, heading=heading)
        df = CircularHeadingStats().compute(psess)
        assert df.iloc[0]["resultant_length"] < 0.15
        assert df.iloc[0]["rayleigh_p"] > 0.05

    def test_concentrated_headings_reject_uniformity(self) -> None:
        rng = np.random.default_rng(3)
        n_frames = 500
        heading = rng.normal(0.0, 0.1, size=(n_frames, 1))
        psess = make_psess(n_frames=n_frames, n_animals=1, heading=heading)
        df = CircularHeadingStats().compute(psess)
        assert df.iloc[0]["rayleigh_p"] < 0.01

    def test_fewer_than_two_valid_headings_returns_nan(self) -> None:
        heading = np.full((5, 1), np.nan)
        heading[0, 0] = 0.5
        psess = make_psess(n_frames=5, n_animals=1, heading=heading)
        df = CircularHeadingStats().compute(psess)
        assert np.isnan(df.iloc[0]["resultant_length"])
        assert np.isnan(df.iloc[0]["rayleigh_p"])


# ── IL-14: WallDistanceThigmotaxis ────────────────────────────────────────────


class TestWallDistanceThigmotaxis:
    def test_metric_id(self) -> None:
        assert WallDistanceThigmotaxis.id == "IL-14"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        zone_set = ZoneSet(rois=[])
        cfg = derive_metric_params("IL-14", psess, zone_set)
        df = WallDistanceThigmotaxis().compute(psess, cfg)
        for col in (
            "session_id",
            "individual_id",
            "mean_wall_distance_px",
            "wall_contact_time_pct",
        ):
            assert col in df.columns

    def test_falls_back_to_video_frame_rectangle_with_no_zones(self) -> None:
        xy = np.array([[[50.0, 50.0]]])  # centre of a 100x100 frame
        psess = make_psess(n_frames=1, n_animals=1, xy=xy, width_px=100, height_px=100)
        zone_set = ZoneSet(rois=[])
        cfg = derive_metric_params("IL-14", psess, zone_set)
        df = WallDistanceThigmotaxis().compute(psess, cfg)
        assert df.iloc[0]["mean_wall_distance_px"] == pytest.approx(50.0)

    def test_uses_defined_arena_polygon_over_video_frame(self) -> None:
        xy = np.array([[[50.0, 50.0]]])
        main_zone = np.full((1, 1), "arena1", dtype=object)
        psess = make_psess(
            n_frames=1, n_animals=1, xy=xy, main_zone=main_zone, width_px=1000, height_px=1000
        )
        zone_set = ZoneSet(
            rois=[
                ROI(
                    name="arena1",
                    level="main",
                    vertices=[(0, 0), (100, 0), (100, 100), (0, 100)],
                    sign="+",
                )
            ]
        )
        cfg = derive_metric_params("IL-14", psess, zone_set)
        df = WallDistanceThigmotaxis().compute(psess, cfg)
        assert df.iloc[0]["mean_wall_distance_px"] == pytest.approx(50.0)

    def test_wall_contact_threshold_is_configurable(self) -> None:
        xy = np.array([[[5.0, 50.0]]])  # 5px from the left wall of a 100x100 frame
        psess = make_psess(n_frames=1, n_animals=1, xy=xy, width_px=100, height_px=100)
        zone_set = ZoneSet(rois=[])
        cfg = derive_metric_params("IL-14", psess, zone_set)
        cfg["wall_contact_threshold_px"] = 10.0
        df = WallDistanceThigmotaxis().compute(psess, cfg)
        assert df.iloc[0]["wall_contact_time_pct"] == pytest.approx(1.0)

        cfg["wall_contact_threshold_px"] = 1.0
        df = WallDistanceThigmotaxis().compute(psess, cfg)
        assert df.iloc[0]["wall_contact_time_pct"] == pytest.approx(0.0)

    def test_no_cfg_returns_nan(self) -> None:
        psess = make_psess()
        df = WallDistanceThigmotaxis().compute(psess, cfg=None)
        assert df["mean_wall_distance_px"].isna().all()
