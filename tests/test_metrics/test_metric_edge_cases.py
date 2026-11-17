"""Edge-case behaviour of GL-4, GL-13, GL-15 and IL-11 (decision D-054).

Each metric reports ``n_frames_used`` and a ``note`` column; a metric that
cannot give a trustworthy number returns NaN and says why in the note.
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
    ConvexHullArea,
    GroupElongation,
    TopologicalNeighbourCounts,
)
from track2data.metrics.individual import CircularHeadingStats


def make_psess(
    xy: np.ndarray,
    *,
    heading: np.ndarray | None = None,
    speed: np.ndarray | None = None,
    px_per_cm: float | None = None,
    fps: float = 25.0,
) -> PreprocessedSession:
    n_frames, n_animals = xy.shape[0], xy.shape[1]
    if speed is None:
        speed = np.ones((n_frames, n_animals))
    if heading is None:
        heading = np.zeros((n_frames, n_animals))
    sess = Session(
        session_id="test",
        folder=Path("/tmp/t"),
        reader="test",
        video=VideoInfo(fps=fps, n_frames=n_frames, width_px=512, height_px=512),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(speed_px_s=speed, accel_px_s2=np.zeros_like(speed), heading_rad=heading)
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kine, report=PreprocessReport(), px_per_cm=px_per_cm
    )


def _square(n_frames: int, side: float = 100.0) -> np.ndarray:
    xy = np.zeros((n_frames, 4, 2))
    for k, c in enumerate([[0, 0], [side, 0], [side, side], [0, side]]):
        xy[:, k, :] = c
    return xy


# ── GL-4 ──────────────────────────────────────────────────────────────────────


class TestHullEdgeCases:
    def test_columns_and_frames_used(self) -> None:
        df = ConvexHullArea().compute(make_psess(_square(20)))
        assert list(df.columns) == ConvexHullArea.output_columns
        assert df["n_frames_used"].iloc[0] == 20
        assert df["note"].iloc[0] == ""

    def test_cm2_when_calibrated_nan_otherwise(self) -> None:
        cal = ConvexHullArea().compute(make_psess(_square(20), px_per_cm=10.0))
        assert cal["mean_hull_area_cm2"].iloc[0] == pytest.approx(100.0)
        assert cal["median_hull_area_cm2"].iloc[0] == pytest.approx(100.0)
        unc = ConvexHullArea().compute(make_psess(_square(20)))
        assert np.isnan(unc["mean_hull_area_cm2"].iloc[0])

    def test_missing_animal_uses_visible_animals(self) -> None:
        xy = _square(20)
        xy[:, 3, :] = np.nan  # triangle of the remaining three: area 5000
        df = ConvexHullArea().compute(make_psess(xy))
        assert df["mean_hull_area_px2"].iloc[0] == pytest.approx(5000.0)
        assert df["n_frames_used"].iloc[0] == 20

    def test_frame_with_fewer_than_three_visible_is_skipped(self) -> None:
        xy = _square(20)
        xy[:5, 1:, :] = np.nan  # one visible animal in the first 5 frames
        df = ConvexHullArea().compute(make_psess(xy))
        assert df["n_frames_used"].iloc[0] == 15
        assert df["mean_hull_area_px2"].iloc[0] == pytest.approx(10000.0)

    def test_collinear_frames_count_as_zero_area_and_note_at_five_percent(self) -> None:
        xy = _square(20)
        xy[:2, :, 1] = 7.0  # 2/20 = 10% collinear
        xy[:2, :, 0] = [0.0, 10.0, 20.0, 30.0]
        df = ConvexHullArea().compute(make_psess(xy))
        assert df["n_frames_used"].iloc[0] == 20
        assert df["mean_hull_area_px2"].iloc[0] == pytest.approx(0.9 * 10000.0)
        assert "collinear" in df["note"].iloc[0]

    def test_collinear_below_five_percent_has_no_note(self) -> None:
        xy = _square(40)
        xy[:1, :, 1] = 7.0
        xy[:1, :, 0] = [0.0, 10.0, 20.0, 30.0]  # 2.5 %
        df = ConvexHullArea().compute(make_psess(xy))
        assert df["note"].iloc[0] == ""

    def test_too_few_usable_frames_is_nan_with_note(self) -> None:
        df = ConvexHullArea().compute(make_psess(_square(2)))
        assert np.isnan(df["mean_hull_area_px2"].iloc[0])
        assert df["n_frames_used"].iloc[0] == 2
        assert "usable frames" in df["note"].iloc[0]

    def test_fewer_than_three_animals_keeps_full_schema(self) -> None:
        df = ConvexHullArea().compute(make_psess(np.zeros((10, 2, 2))))
        assert list(df.columns) == ConvexHullArea.output_columns
        assert df["n_frames_used"].iloc[0] == 0
        assert df["note"].iloc[0] != ""


# ── GL-13 ─────────────────────────────────────────────────────────────────────


def _random_xy(n_frames: int = 20, n_animals: int = 6, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(0, 500, size=(n_frames, n_animals, 2))


class TestKnnEdgeCases:
    def test_columns_and_frames_used(self) -> None:
        df = TopologicalNeighbourCounts().compute(make_psess(_random_xy()), {"k_max": 3})
        assert list(df.columns) == TopologicalNeighbourCounts.output_columns
        assert (df["n_frames_used"] == 20).all()

    def test_same_frame_set_for_every_k(self) -> None:
        xy = _random_xy(n_frames=20, n_animals=4)
        xy[:10, 3, :] = np.nan  # only 3 visible in the first 10 frames
        df = TopologicalNeighbourCounts().compute(make_psess(xy), {"k_max": 3})
        # k_max+1 = 4 visible are needed, so only the last 10 frames count, for every k
        assert (df["n_frames_used"] == 10).all()

    def test_too_few_frames_is_nan_with_note(self) -> None:
        xy = _random_xy(n_frames=20, n_animals=3)
        df = TopologicalNeighbourCounts().compute(make_psess(xy), {"k_max": 3})
        assert df["mean_kth_nn_distance_px"].isna().all()
        assert df["mean_neighbours_within_radius"].isna().all()
        assert df["note"].str.contains("usable frames").all()

    def test_radius_in_cm_when_calibrated(self) -> None:
        xy = np.zeros((10, 4, 2))
        xy[:] = [[0, 0], [10, 0], [100, 0], [110, 0]]
        psess = make_psess(xy, px_per_cm=5.0)
        df = TopologicalNeighbourCounts().compute(psess, {"k_max": 1, "radius_cm": 4.0})
        # 4 cm * 5 px/cm = 20 px: each animal has exactly one neighbour inside
        assert df["mean_neighbours_within_radius"].iloc[0] == pytest.approx(1.0)
        assert df["radius_px_used"].iloc[0] == pytest.approx(20.0)

    def test_radius_cm_ignored_with_note_when_uncalibrated(self) -> None:
        xy = _random_xy()
        df = TopologicalNeighbourCounts().compute(
            make_psess(xy), {"k_max": 1, "radius_cm": 4.0, "radius_px": 50.0}
        )
        assert df["radius_px_used"].iloc[0] == pytest.approx(50.0)
        assert "radius_cm" in df["note"].iloc[0]

    def test_cm_distance_column(self) -> None:
        df = TopologicalNeighbourCounts().compute(
            make_psess(_random_xy(), px_per_cm=10.0), {"k_max": 2}
        )
        assert df["mean_kth_nn_distance_cm"].to_numpy() == pytest.approx(
            df["mean_kth_nn_distance_px"].to_numpy() / 10.0
        )

    def test_many_zero_distances_kept_and_noted(self) -> None:
        xy = np.zeros((10, 4, 2))
        xy[:] = [[5, 5], [5, 5], [100, 0], [200, 0]]  # a coincident pair
        df = TopologicalNeighbourCounts().compute(make_psess(xy), {"k_max": 1})
        assert df["frac_zero_distance"].iloc[0] == pytest.approx(0.5)
        assert "zero" in df["note"].iloc[0]
        assert np.isfinite(df["mean_kth_nn_distance_px"].iloc[0])

    def test_no_zero_note_when_none(self) -> None:
        df = TopologicalNeighbourCounts().compute(make_psess(_random_xy()), {"k_max": 1})
        assert df["frac_zero_distance"].iloc[0] == 0.0
        assert df["note"].iloc[0] == ""

    @pytest.mark.parametrize("bad", [0, -1])
    def test_k_max_below_one_is_refused(self, bad: int) -> None:
        with pytest.raises(ValueError, match="k_max"):
            TopologicalNeighbourCounts().compute(make_psess(_random_xy()), {"k_max": bad})


# ── GL-15 ─────────────────────────────────────────────────────────────────────


def _elongated(n_frames: int = 20, n_animals: int = 8, minor: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(1)
    xy = np.zeros((n_frames, n_animals, 2))
    xy[:, :, 0] = np.linspace(0, 100, n_animals)
    xy[:, :, 1] = rng.normal(0, minor, size=(n_frames, n_animals))
    return xy


class TestElongationEdgeCases:
    def test_columns_present(self) -> None:
        df = GroupElongation().compute(make_psess(_elongated()))
        assert list(df.columns) == GroupElongation.output_columns
        assert df["n_frames_used"].iloc[0] == 20
        assert df["median_elongation_ratio"].iloc[0] > 3.0

    def test_median_resists_one_near_line_frame(self) -> None:
        xy = _elongated(n_frames=21)
        xy[0, :, 1] = np.linspace(0, 1e-9, xy.shape[1]) ** 2  # near-singular frame
        df = GroupElongation().compute(make_psess(xy))
        assert np.isfinite(df["median_elongation_ratio"].iloc[0])
        assert df["median_elongation_ratio"].iloc[0] < 100.0

    def test_line_like_frames_dropped_and_noted(self) -> None:
        xy = _elongated(n_frames=20)
        xy[:4, :, 1] = 0.0  # 4 exactly-straight frames
        xy[:4, 3, 1] = 1e-7
        df = GroupElongation().compute(make_psess(xy))
        assert df["n_frames_used"].iloc[0] == 16
        assert "line-like" in df["note"].iloc[0]
        assert "4" in df["note"].iloc[0]

    def test_axis_consistency_high_for_stable_axis(self) -> None:
        df = GroupElongation().compute(make_psess(_elongated()))
        assert df["axis_consistency"].iloc[0] > 0.9
        assert np.isfinite(df["mean_major_axis_orientation_rad"].iloc[0])

    def test_orientation_nan_when_axis_consistency_below_point_one(self) -> None:
        xy = _elongated(n_frames=40)
        for t in range(40):  # rotate the group a different angle every frame
            a = np.pi * t / 40
            rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            xy[t] = xy[t] @ rot.T
        df = GroupElongation().compute(make_psess(xy))
        assert df["axis_consistency"].iloc[0] < 0.1
        assert np.isnan(df["mean_major_axis_orientation_rad"].iloc[0])
        assert "axis" in df["note"].iloc[0]

    def test_angle_convention_is_image_coordinates(self) -> None:
        # A group spread along +y in image coordinates (y down) has its major axis at
        # +/- pi/2, reported in (-pi/2, pi/2].
        xy = np.zeros((10, 6, 2))
        xy[:, :, 1] = np.linspace(0, 100, 6)
        xy[:, :, 0] = np.random.default_rng(0).normal(0, 2, size=(10, 6))
        df = GroupElongation().compute(make_psess(xy))
        assert abs(df["mean_major_axis_orientation_rad"].iloc[0]) == pytest.approx(
            np.pi / 2, abs=0.1
        )

    def test_small_group_noted_as_unreliable(self) -> None:
        df = GroupElongation().compute(make_psess(_elongated(n_animals=4)))
        assert "below 6" in df["note"].iloc[0]
        big = GroupElongation().compute(make_psess(_elongated(n_animals=8)))
        assert "below 6" not in big["note"].iloc[0]

    def test_nan_result_states_usable_frames(self) -> None:
        df = GroupElongation().compute(make_psess(np.zeros((10, 2, 2))))
        assert np.isnan(df["mean_elongation_ratio"].iloc[0])
        assert df["n_frames_used"].iloc[0] == 0
        assert "0 usable frames" in df["note"].iloc[0]


# ── IL-11 ─────────────────────────────────────────────────────────────────────


def _hpsess(heading: np.ndarray, speed: np.ndarray | None = None, fps: float = 25.0):
    heading = heading.reshape(-1, 1)
    xy = np.zeros((heading.shape[0], 1, 2))
    return make_psess(xy, heading=heading, speed=speed, fps=fps)


class TestCircularHeadingEdgeCases:
    def test_columns_present(self) -> None:
        df = CircularHeadingStats().compute(_hpsess(np.full(30, 0.7)))
        assert list(df.columns) == CircularHeadingStats.output_columns
        assert df["n_headings"].iloc[0] == 30
        assert df["n_frames_used"].iloc[0] == 30

    def test_min_speed_drops_resting_frames(self) -> None:
        heading = np.full(40, 0.7)
        speed = np.ones(40)
        speed[:10] = 0.1
        psess = _hpsess(heading, speed.reshape(-1, 1))
        df = CircularHeadingStats().compute(psess, {"min_speed_px_s": 0.5})
        assert df["n_frames_used"].iloc[0] == 30

    def test_fewer_than_ten_headings_is_nan_with_note(self) -> None:
        df = CircularHeadingStats().compute(_hpsess(np.full(9, 0.7)))
        assert np.isnan(df["rayleigh_p"].iloc[0])
        assert np.isnan(df["mean_heading_rad"].iloc[0])
        assert df["n_headings"].iloc[0] == 9
        assert "at least 10" in df["note"].iloc[0]

    def test_mean_heading_nan_when_not_significant(self) -> None:
        rng = np.random.default_rng(5)
        df = CircularHeadingStats().compute(_hpsess(rng.uniform(-np.pi, np.pi, 400)))
        assert df["rayleigh_p"].iloc[0] > 0.05
        assert np.isnan(df["mean_heading_rad"].iloc[0])

    def test_mean_heading_nan_when_concentration_below_point_one(self) -> None:
        # Huge n makes a tiny bias significant, but r < 0.1 still blanks the mean.
        rng = np.random.default_rng(6)
        theta = rng.uniform(-np.pi, np.pi, 200_000)
        theta = np.where(rng.random(theta.size) < 0.06, 0.0, theta)
        df = CircularHeadingStats().compute(_hpsess(theta))
        assert df["resultant_length"].iloc[0] < 0.1
        assert df["rayleigh_p"].iloc[0] < 0.05
        assert np.isnan(df["mean_heading_rad"].iloc[0])

    def test_mean_heading_reported_when_concentrated(self) -> None:
        rng = np.random.default_rng(7)
        df = CircularHeadingStats().compute(_hpsess(rng.normal(0.7, 0.2, 300)))
        assert df["mean_heading_rad"].iloc[0] == pytest.approx(0.7, abs=0.05)

    @pytest.mark.parametrize("n", [20, 1000, 100_000, 5_000_000])
    @pytest.mark.parametrize("r_target", [0.0, 0.02, 0.5, 0.999999])
    def test_rayleigh_p_in_unit_interval_for_large_n(self, n: int, r_target: float) -> None:
        from track2data.metrics.individual import rayleigh_p_value

        p = rayleigh_p_value(n, r_target)
        assert 0.0 <= p <= 1.0

    def test_rayleigh_p_known_values(self) -> None:
        from track2data.metrics.individual import rayleigh_p_value

        assert rayleigh_p_value(50, 0.0) == pytest.approx(1.0)
        # Zar (1999) / CircStat circ_rtest: p = exp(sqrt(1 + 4n + 4(n^2 - R^2)) - (1 + 2n))
        n, r = 30, 0.4
        big_r = n * r
        expected = np.exp(np.sqrt(1 + 4 * n + 4 * (n**2 - big_r**2)) - (1 + 2 * n))
        assert rayleigh_p_value(n, r) == pytest.approx(expected)

    def test_turns_counted_and_zero_and_straight_ignored(self) -> None:
        # headings: constant (0 turn), then a +0.3 step, then a reversal (pi), then -0.3
        heading = np.array([0.0] * 5 + [0.3, 0.3, 0.3 + np.pi, 0.3 + np.pi, 0.0, 0.0] * 3)
        df = CircularHeadingStats().compute(_hpsess(np.concatenate([heading, np.zeros(10)])))
        n_turns = df["n_turns"].iloc[0]
        # Only steps that are neither 0 nor 180 degrees are turns.
        diffs = np.diff(np.concatenate([heading, np.zeros(10)]))
        wrapped = np.arctan2(np.sin(diffs), np.cos(diffs))
        keep = (np.abs(wrapped) > 1e-9) & (np.abs(np.abs(wrapped) - np.pi) > 1e-9)
        assert n_turns == int(keep.sum())

    def test_turn_bias_sign_is_pinned_to_increasing_heading(self) -> None:
        # Current convention, deliberately pinned (see docs/dev/IL11_SIGN_CHECK.md): positive
        # bias means the heading angle increases from frame to frame.
        heading = np.cumsum(np.full(30, 0.2))
        df = CircularHeadingStats().compute(_hpsess(heading))
        assert df["left_right_turn_bias"].iloc[0] == pytest.approx(1.0)
        assert df["n_turns"].iloc[0] == 29

    def test_turn_compares_with_previous_valid_heading_within_half_second(self) -> None:
        fps = 10.0  # 0.5 s = 5 frames
        heading = np.full(40, np.nan)
        heading[0] = 0.0
        heading[4] = 0.5  # 4 frames (0.4 s) after the previous valid heading: a turn
        heading[20] = 0.0  # 16 frames later: too far, ignored
        heading[21:30] = np.arange(9) * 0.1 + 0.2
        df = CircularHeadingStats().compute(_hpsess(heading, fps=fps))
        # turns: 0->4 (yes), 4->20 (no), 20->21 (+0.2: yes), then 8 steps of 0.1: yes
        assert df["n_turns"].iloc[0] == 1 + 1 + 8

    def test_nan_note_when_no_headings(self) -> None:
        df = CircularHeadingStats().compute(_hpsess(np.full(30, np.nan)))
        assert df["n_headings"].iloc[0] == 0
        assert np.isnan(df["left_right_turn_bias"].iloc[0])
        assert df["note"].iloc[0] != ""
