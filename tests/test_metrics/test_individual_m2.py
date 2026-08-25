"""Tests for individual-level metrics IL-3, IL-6, IL-7, and IL-8.

IL-7 (FreezingBouts) and IL-8 (TurnRate) are added under strict TDD; see
CONTRIBUTING.md §3.
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
from track2data.metrics.individual import (
    Acceleration,
    CentreDistance,
    FreezingBouts,
    TurnRate,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(
    n_frames: int = 50,
    n_animals: int = 4,
    xy: np.ndarray | None = None,
    accel: np.ndarray | None = None,
    speed: np.ndarray | None = None,
    heading: np.ndarray | None = None,
) -> PreprocessedSession:
    rng = np.random.default_rng(42)
    if xy is None:
        # Keep the generated trajectory's shape consistent with any
        # explicitly-passed kinematics array (accel / speed / heading) so
        # session.n_animals (derived from xy) never diverges from that
        # array's shape.
        for custom_arr in (accel, speed, heading):
            if custom_arr is not None:
                n_frames, n_animals = custom_arr.shape[0], custom_arr.shape[1]
                break
        xy = rng.random((n_frames, n_animals, 2)) * 500
    actual_frames, actual_animals = xy.shape[0], xy.shape[1]
    if accel is None:
        accel = np.zeros((actual_frames, actual_animals))
    if speed is None:
        speed = np.zeros((actual_frames, actual_animals))
    if heading is None:
        heading = np.zeros((actual_frames, actual_animals))
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

    def test_inner_radius_fraction_defaults_to_half(self) -> None:
        """Without cfg['inner_radius_fraction'], the inner-radius cutoff
        is arena_radius/2 -- the historical hardcoded behaviour,
        preserved as the default rather than changed silently."""
        n_frames, n_animals = 20, 1
        xy = np.full((n_frames, n_animals, 2), [700.0, 500.0])  # dist 200 from centre
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(
            psess, cfg={"centre": [500.0, 500.0], "arena_radius": 400.0}
        )
        # inner radius = 400/2 = 200; dist=200 is not < 200 -> outside
        assert df.iloc[0]["time_in_centre_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_inner_radius_fraction_is_configurable(self) -> None:
        """cfg['inner_radius_fraction'] overrides the default 0.5 --
        e.g. 0.75 widens the "inner" zone to 3/4 of the arena radius."""
        n_frames, n_animals = 20, 1
        xy = np.full((n_frames, n_animals, 2), [700.0, 500.0])  # dist 200 from centre
        psess = make_psess(xy=xy)
        df = CentreDistance().compute(
            psess,
            cfg={"centre": [500.0, 500.0], "arena_radius": 400.0, "inner_radius_fraction": 0.75},
        )
        # inner radius = 400*0.75 = 300; dist=200 < 300 -> inside
        assert df.iloc[0]["time_in_centre_pct"] == pytest.approx(1.0, abs=1e-6)

    def test_declares_configurable_parameters(self) -> None:
        names = {p.name for p in CentreDistance.parameters}
        assert names == {"centre", "arena_radius", "inner_radius_fraction"}
        derived = {p.name for p in CentreDistance.parameters if p.derived}
        assert derived == {"centre", "arena_radius"}


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


# ── IL-7: FreezingBouts ───────────────────────────────────────────────────────


class TestFreezingBouts:
    def test_metric_id(self) -> None:
        assert FreezingBouts.id == "IL-7"

    def test_declares_configurable_parameters(self) -> None:
        names = {p.name for p in FreezingBouts.parameters}
        assert names == {"threshold_px_s", "min_bout_frames"}

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = FreezingBouts().compute(psess)
        for col in [
            "session_id",
            "metric_id",
            "individual_id",
            "freezing_bout_count",
            "mean_freezing_duration_s",
            "total_freezing_duration_s",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = FreezingBouts().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = FreezingBouts().compute(psess)
        assert (df["metric_id"] == "IL-7").all()

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=5)
        df = FreezingBouts().compute(psess)
        assert len(df) == 5

    def test_clear_freezing_bout_counts_and_durations(self) -> None:
        """5 inactive frames (>= default min_bout_frames=5) then active → 1 bout."""
        n_frames, n_animals = 20, 1
        speed = np.zeros((n_frames, n_animals))
        speed[5:, 0] = 100.0  # frames 0-4 stay 0.0 (inactive); 5.. active
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0})
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 1
        assert row["total_freezing_duration_s"] == pytest.approx(5 / 25.0)
        assert row["mean_freezing_duration_s"] == pytest.approx(5 / 25.0)

    def test_bout_shorter_than_min_not_counted(self) -> None:
        """3 inactive frames (< default min_bout_frames=5) never qualify."""
        n_frames, n_animals = 20, 1
        speed = np.full((n_frames, n_animals), 100.0)
        speed[:3, 0] = 0.0
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0})
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 0
        assert row["mean_freezing_duration_s"] == pytest.approx(0.0)
        assert row["total_freezing_duration_s"] == pytest.approx(0.0)

    def test_zero_bouts_when_all_active(self) -> None:
        n_frames, n_animals = 20, 2
        speed = np.full((n_frames, n_animals), 100.0)
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0})
        for k in range(n_animals):
            row = df[df["individual_id"] == k].iloc[0]
            assert row["freezing_bout_count"] == 0
            assert row["mean_freezing_duration_s"] == pytest.approx(0.0)
            assert row["total_freezing_duration_s"] == pytest.approx(0.0)

    def test_nan_frames_excluded_and_do_not_merge_runs(self) -> None:
        """Two 3-frame inactive runs split by 1 NaN frame must NOT merge into
        a 6-frame run (which would wrongly qualify as a >=5-frame bout)."""
        n_frames, n_animals = 10, 1
        speed = np.zeros((n_frames, n_animals))
        speed[3, 0] = np.nan
        speed[7:10, 0] = 100.0
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0})
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 0
        assert row["total_freezing_duration_s"] == pytest.approx(0.0)
        assert row["mean_freezing_duration_s"] == pytest.approx(0.0)

    def test_nan_frame_inside_run_splits_bout_and_excluded_from_duration(self) -> None:
        """Two qualifying 5-frame runs separated by 1 NaN frame → 2 bouts;
        the NaN frame itself contributes zero duration."""
        n_frames, n_animals = 12, 1
        speed = np.zeros((n_frames, n_animals))
        speed[5, 0] = np.nan
        speed[11, 0] = 100.0
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0})
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 2
        assert row["total_freezing_duration_s"] == pytest.approx(10 / 25.0)
        assert row["mean_freezing_duration_s"] == pytest.approx(5 / 25.0)

    def test_min_bout_frames_override_via_cfg(self) -> None:
        n_frames, n_animals = 10, 1
        speed = np.full((n_frames, n_animals), 100.0)
        speed[:3, 0] = 0.0
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess, cfg={"threshold_px_s": 10.0, "min_bout_frames": 3})
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 1
        assert row["total_freezing_duration_s"] == pytest.approx(3 / 25.0)
        assert row["mean_freezing_duration_s"] == pytest.approx(3 / 25.0)

    def test_default_threshold_replicates_activity_logic(self) -> None:
        """No cfg threshold → mean(speed) * 0.1, the same rule IL-4 Activity uses."""
        n_frames, n_animals = 20, 1
        speed = np.zeros((n_frames, n_animals))
        speed[5:, 0] = 100.0
        # mean(speed) = (5*0 + 15*100) / 20 = 75.0 -> threshold = 7.5
        # frames 0-4 (0.0) are inactive; frames 5.. (100.0) are active
        psess = make_psess(speed=speed)
        df = FreezingBouts().compute(psess)  # no cfg at all
        row = df.iloc[0]
        assert row["freezing_bout_count"] == 1
        assert row["total_freezing_duration_s"] == pytest.approx(5 / 25.0)


# ── IL-8: TurnRate ────────────────────────────────────────────────────────────


class TestTurnRate:
    def test_metric_id(self) -> None:
        assert TurnRate.id == "IL-8"

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = TurnRate().compute(psess)
        for col in [
            "session_id",
            "metric_id",
            "individual_id",
            "mean_turn_rate_rad_per_s",
            "median_turn_rate_rad_per_s",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = TurnRate().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_metric_id_column(self) -> None:
        psess = make_psess()
        df = TurnRate().compute(psess)
        assert (df["metric_id"] == "IL-8").all()

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=5)
        df = TurnRate().compute(psess)
        assert len(df) == 5

    def test_known_90_degree_turn_rate(self) -> None:
        """theta = [0, pi/2, pi, NaN] -> two consecutive 90-degree turns."""
        heading = np.array([[0.0], [np.pi / 2], [np.pi], [np.nan]])
        psess = make_psess(heading=heading)
        df = TurnRate().compute(psess)
        row = df.iloc[0]
        expected = (np.pi / 2) * 25.0  # fps=25.0, from make_psess
        assert row["mean_turn_rate_rad_per_s"] == pytest.approx(expected, rel=1e-6)
        assert row["median_turn_rate_rad_per_s"] == pytest.approx(expected, rel=1e-6)

    def test_wrapped_angle_difference_near_pi_boundary(self) -> None:
        """theta going from 3pi/4 to -3pi/4 is a 90-degree turn the short way,
        NOT the naive (unwrapped) 270-degree difference."""
        heading = np.array([[3 * np.pi / 4], [-3 * np.pi / 4], [np.nan]])
        psess = make_psess(heading=heading)
        df = TurnRate().compute(psess)
        row = df.iloc[0]
        expected = (np.pi / 2) * 25.0
        assert row["mean_turn_rate_rad_per_s"] == pytest.approx(expected, rel=1e-6)

    def test_nan_and_stationary_frames_excluded(self) -> None:
        """NaN (stationary / undefined-heading) frames are dropped from the
        mean/median and do not corrupt the surrounding valid pairs."""
        heading = np.array([[0.0], [0.1], [np.nan], [0.1], [0.4], [np.nan], [0.4], [1.0]])
        psess = make_psess(heading=heading)
        df = TurnRate().compute(psess)
        row = df.iloc[0]
        # valid dtheta pairs: (0.0->0.1)=0.1, (0.1->0.4)=0.3, (0.4->1.0)=0.6
        turn_rates = np.array([0.1, 0.3, 0.6]) * 25.0
        assert row["mean_turn_rate_rad_per_s"] == pytest.approx(float(turn_rates.mean()), rel=1e-6)
        assert row["median_turn_rate_rad_per_s"] == pytest.approx(
            float(np.median(turn_rates)), rel=1e-6
        )

    def test_all_nan_heading_returns_nan(self) -> None:
        """An individual with fully undefined heading -> NaN stats, independent
        of a second individual whose heading is well-defined throughout."""
        n_frames, n_animals = 10, 2
        heading = np.zeros((n_frames, n_animals))
        heading[:, 0] = np.nan
        psess = make_psess(heading=heading)
        df = TurnRate().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        row1 = df[df["individual_id"] == 1].iloc[0]
        assert np.isnan(row0["mean_turn_rate_rad_per_s"])
        assert np.isnan(row0["median_turn_rate_rad_per_s"])
        assert row1["mean_turn_rate_rad_per_s"] == pytest.approx(0.0)
        assert row1["median_turn_rate_rad_per_s"] == pytest.approx(0.0)
