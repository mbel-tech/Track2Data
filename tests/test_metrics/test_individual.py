"""
Tests for individual-level metrics: IL-1, IL-2, IL-4, IL-5.

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
from track2data.metrics.individual import Activity, PathLength, Speed, Tortuosity

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_session(n_frames: int, n_animals: int, xy: np.ndarray) -> Session:
    """Build a minimal Session wrapping *xy*."""
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
    n_frames: int = 100,
    n_animals: int = 2,
    px_per_cm: float | None = None,
    body_length_cm: np.ndarray | None = None,
) -> PreprocessedSession:
    """Build a minimal PreprocessedSession for testing."""
    if xy is None:
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
        # animal 0 moves 5 px/frame along x
        xy[:, 0, 0] = np.arange(n_frames, dtype=np.float64) * 5.0

    actual_frames = xy.shape[0]
    actual_animals = xy.shape[1]

    if speed is None:
        dx = np.diff(xy[:, :, 0], axis=0, prepend=np.nan)
        dy = np.diff(xy[:, :, 1], axis=0, prepend=np.nan)
        speed = np.sqrt(dx**2 + dy**2) * 25.0  # fps=25

    sess = _make_session(actual_frames, actual_animals, xy)
    kine = KinematicsArrays(
        speed_px_s=speed,
        accel_px_s2=np.zeros((actual_frames, actual_animals)),
        heading_rad=np.zeros((actual_frames, actual_animals)),
    )
    return PreprocessedSession(
        session=sess,
        xy=xy,
        kinematics=kine,
        px_per_cm=px_per_cm,
        body_length_cm=body_length_cm,
        report=PreprocessReport(),
    )


# ── IL-1: PathLength ───────────────────────────────────────────────────────────


class TestPathLength:
    def test_straight_line(self) -> None:
        """Animal 0 moves 5 px/frame for 100 frames → path_length_px = 5*99 = 495."""
        psess = make_psess()
        df = PathLength().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["path_length_px"] == pytest.approx(5.0 * 99, rel=1e-3)

    def test_static_animal(self) -> None:
        """A static animal has path_length_px = 0."""
        xy = np.zeros((50, 2, 2), dtype=np.float64)
        psess = make_psess(xy=xy)
        df = PathLength().compute(psess)
        for aid in [0, 1]:
            assert df[df["individual_id"] == aid]["path_length_px"].values[0] == pytest.approx(0.0)

    def test_nan_frames_skipped(self) -> None:
        """NaN gap frames are skipped; result must be finite and non-NaN."""
        xy = np.zeros((10, 2, 2), dtype=np.float64)
        xy[:, 0, 0] = np.arange(10, dtype=np.float64) * 5.0
        xy[3:6, 0, :] = np.nan  # gap in animal 0
        psess = make_psess(xy=xy)
        df = PathLength().compute(psess)
        val = df[df["individual_id"] == 0]["path_length_px"].values[0]
        assert np.isfinite(val)
        assert val > 0

    def test_nan_gap_reduces_path(self) -> None:
        """Path length with a gap must be strictly less than the complete path."""
        xy_full = np.zeros((10, 1, 2), dtype=np.float64)
        xy_full[:, 0, 0] = np.arange(10, dtype=np.float64) * 5.0
        psess_full = make_psess(xy=xy_full)
        full_path = PathLength().compute(psess_full)["path_length_px"].values[0]

        xy_gap = xy_full.copy()
        xy_gap[4, 0, :] = np.nan  # remove one frame
        psess_gap = make_psess(xy=xy_gap)
        gap_path = PathLength().compute(psess_gap)["path_length_px"].values[0]

        assert gap_path < full_path

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = PathLength().compute(psess)
        for col in ["session_id", "metric_id", "individual_id", "path_length_px"]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess()
        df = PathLength().compute(psess)
        assert (df["session_id"] == "test").all()

    def test_metric_id_column(self) -> None:
        df = PathLength().compute(make_psess())
        assert (df["metric_id"] == "IL-1").all()

    def test_path_length_cm_when_calibrated(self) -> None:
        """path_length_cm is present and correct when px_per_cm is set."""
        psess = make_psess(px_per_cm=10.0)
        df = PathLength().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        expected_px = 5.0 * 99
        assert row0["path_length_cm"] == pytest.approx(expected_px / 10.0, rel=1e-3)

    def test_path_length_cm_none_when_uncalibrated(self) -> None:
        """path_length_cm column is absent or NaN when px_per_cm is None."""
        psess = make_psess(px_per_cm=None)
        df = PathLength().compute(psess)
        # Either column missing or all NaN
        if "path_length_cm" in df.columns:
            assert df["path_length_cm"].isna().all()

    def test_path_length_bl_when_body_length_available(self) -> None:
        """path_length_bl is present and correct when body_length_cm is set."""
        psess = make_psess(
            px_per_cm=10.0,
            body_length_cm=np.array([5.0, 5.0]),
        )
        df = PathLength().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        expected_px = 5.0 * 99
        expected_cm = expected_px / 10.0
        expected_bl = expected_cm / 5.0
        assert row0["path_length_bl"] == pytest.approx(expected_bl, rel=1e-3)

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=3)
        df = PathLength().compute(psess)
        assert len(df) == 3


# ── IL-2: Speed ────────────────────────────────────────────────────────────────


class TestSpeed:
    def test_static_animal_mean_speed(self) -> None:
        """Completely static animal → mean/median/max speed all 0."""
        xy = np.zeros((100, 2, 2), dtype=np.float64)
        psess = make_psess(xy=xy, speed=np.zeros((100, 2)))
        df = Speed().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_speed_px_s"] == pytest.approx(0.0)
        assert row0["median_speed_px_s"] == pytest.approx(0.0)
        assert row0["max_speed_px_s"] == pytest.approx(0.0)

    def test_constant_speed_animal(self) -> None:
        """Animal always at 50 px/s → mean/median/max all 50."""
        speed = np.full((100, 2), 50.0)
        psess = make_psess(speed=speed)
        df = Speed().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_speed_px_s"] == pytest.approx(50.0)
        assert row0["median_speed_px_s"] == pytest.approx(50.0)
        assert row0["max_speed_px_s"] == pytest.approx(50.0)

    def test_nan_frames_excluded(self) -> None:
        """NaN speed frames are excluded from the statistics."""
        speed = np.full((100, 2), 50.0)
        speed[5:10, 0] = np.nan
        psess = make_psess(speed=speed)
        df = Speed().compute(psess)
        assert df["mean_speed_px_s"].values[0] == pytest.approx(50.0)

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = Speed().compute(psess)
        for col in ["session_id", "metric_id", "individual_id",
                    "mean_speed_px_s", "median_speed_px_s", "max_speed_px_s"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        df = Speed().compute(make_psess())
        assert (df["metric_id"] == "IL-2").all()

    def test_mean_speed_cm_s_when_calibrated(self) -> None:
        """mean_speed_cm_s is present and correct when px_per_cm is set."""
        speed = np.full((100, 2), 100.0)  # 100 px/s
        psess = make_psess(speed=speed, px_per_cm=10.0)
        df = Speed().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_speed_cm_s"] == pytest.approx(10.0)

    def test_mean_speed_cm_s_absent_when_uncalibrated(self) -> None:
        psess = make_psess(px_per_cm=None)
        df = Speed().compute(psess)
        if "mean_speed_cm_s" in df.columns:
            assert df["mean_speed_cm_s"].isna().all()

    def test_mean_speed_bl_s_when_body_length(self) -> None:
        """mean_speed_bl_s is correct when body_length_cm is set."""
        speed = np.full((100, 2), 100.0)  # 100 px/s → 10 cm/s → 2 BL/s
        psess = make_psess(speed=speed, px_per_cm=10.0, body_length_cm=np.array([5.0, 5.0]))
        df = Speed().compute(psess)
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["mean_speed_bl_s"] == pytest.approx(2.0)

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=4)
        df = Speed().compute(psess)
        assert len(df) == 4


# ── IL-4: Activity ─────────────────────────────────────────────────────────────


class TestActivity:
    def test_active_fraction_explicit_threshold(self) -> None:
        """Speed alternates 0 / 200 px/s → 50% active with threshold=100."""
        speed = np.zeros((100, 2))
        speed[::2, 0] = 200.0  # even frames: fast
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_px_s": 100.0})
        frac = df[df["individual_id"] == 0]["active_fraction"].values[0]
        assert frac == pytest.approx(0.5, abs=0.05)

    def test_fully_active(self) -> None:
        """Speed always above threshold → active_fraction = 1.0."""
        speed = np.full((100, 2), 200.0)
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_px_s": 50.0})
        assert df[df["individual_id"] == 0]["active_fraction"].values[0] == pytest.approx(1.0)

    def test_fully_frozen(self) -> None:
        """Speed always zero → freezing_fraction = 1.0."""
        speed = np.zeros((100, 2))
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_px_s": 1.0})
        row0 = df[df["individual_id"] == 0].iloc[0]
        assert row0["freezing_fraction"] == pytest.approx(1.0)
        assert row0["active_fraction"] == pytest.approx(0.0)

    def test_active_plus_freezing_equals_one(self) -> None:
        """active_fraction + freezing_fraction must equal 1 for non-NaN frames."""
        speed = np.random.default_rng(42).uniform(0, 300, (100, 3))
        speed[0, :] = np.nan  # add some NaN
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_px_s": 100.0})
        for _, row in df.iterrows():
            assert row["active_fraction"] + row["freezing_fraction"] == pytest.approx(1.0, abs=1e-6)

    def test_nan_speed_excluded(self) -> None:
        """Frames with NaN speed are excluded from active_fraction."""
        speed = np.full((100, 2), 200.0)
        speed[0:50, 0] = np.nan
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_px_s": 100.0})
        assert df["active_fraction"].values[0] == pytest.approx(1.0, abs=1e-6)

    def test_threshold_returned_in_output(self) -> None:
        """The applied threshold must be returned in the output DataFrame."""
        psess = make_psess(speed=np.ones((100, 2)) * 50.0)
        df = Activity().compute(psess, cfg={"threshold_px_s": 10.0})
        assert "threshold_px_s" in df.columns
        assert df["threshold_px_s"].values[0] == pytest.approx(10.0)

    def test_auto_threshold_without_cfg(self) -> None:
        """When cfg is None, a threshold is still computed and returned."""
        speed = np.full((100, 2), 100.0)
        psess = make_psess(speed=speed)
        df = Activity().compute(psess)
        assert "threshold_px_s" in df.columns
        assert df["threshold_px_s"].notna().all()

    def test_auto_threshold_multiplier_defaults_to_0_1(self) -> None:
        """The data-driven fallback is mean(speed) * threshold_multiplier
        -- 0.1 is the historical hardcoded value, preserved as the
        default rather than changed silently."""
        speed = np.full((100, 2), 100.0)
        psess = make_psess(speed=speed)
        df = Activity().compute(psess)
        assert df["threshold_px_s"].values[0] == pytest.approx(10.0)  # 100 * 0.1

    def test_threshold_multiplier_is_configurable(self) -> None:
        """cfg['threshold_multiplier'] scales the auto threshold when no
        explicit threshold_px_s is given."""
        speed = np.full((100, 2), 100.0)
        psess = make_psess(speed=speed)
        df = Activity().compute(psess, cfg={"threshold_multiplier": 0.2})
        assert df["threshold_px_s"].values[0] == pytest.approx(20.0)  # 100 * 0.2

    def test_threshold_multiplier_ignored_when_explicit_threshold_given(self) -> None:
        speed = np.full((100, 2), 100.0)
        psess = make_psess(speed=speed)
        df = Activity().compute(
            psess, cfg={"threshold_px_s": 5.0, "threshold_multiplier": 0.2}
        )
        assert df["threshold_px_s"].values[0] == pytest.approx(5.0)

    def test_declares_configurable_parameters(self) -> None:
        names = {p.name for p in Activity.parameters}
        assert names == {"threshold_px_s", "threshold_multiplier"}

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = Activity().compute(psess, cfg={"threshold_px_s": 10.0})
        for col in ["session_id", "metric_id", "individual_id",
                    "active_fraction", "freezing_fraction", "threshold_px_s"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        df = Activity().compute(make_psess())
        assert (df["metric_id"] == "IL-4").all()


# ── IL-5: Tortuosity ───────────────────────────────────────────────────────────


class TestTortuosity:
    def test_straight_line(self) -> None:
        """Straight line → tortuosity ≈ 1.0."""
        xy = np.zeros((100, 1, 2), dtype=np.float64)
        xy[:, 0, 0] = np.arange(100, dtype=np.float64)
        psess = make_psess(xy=xy)
        df = Tortuosity().compute(psess)
        assert df["tortuosity"].values[0] == pytest.approx(1.0, abs=0.01)

    def test_zigzag_increases_tortuosity(self) -> None:
        """A zigzag path has tortuosity > 1."""
        n = 100
        xy = np.zeros((n, 1, 2), dtype=np.float64)
        xy[:, 0, 0] = np.arange(n, dtype=np.float64)
        xy[::2, 0, 1] = 10.0   # alternating y offset
        psess = make_psess(xy=xy)
        df = Tortuosity().compute(psess)
        assert df["tortuosity"].values[0] > 1.0

    def test_static_animal_eps_guard(self) -> None:
        """Static animal (start == end) must return a finite tortuosity, not inf/NaN."""
        xy = np.zeros((50, 1, 2), dtype=np.float64)
        psess = make_psess(xy=xy)
        df = Tortuosity().compute(psess)
        val = df["tortuosity"].values[0]
        assert np.isfinite(val)

    def test_nan_gap_handled(self) -> None:
        """Path with NaN frames must return a finite tortuosity."""
        xy = np.zeros((20, 1, 2), dtype=np.float64)
        xy[:, 0, 0] = np.arange(20, dtype=np.float64) * 2.0
        xy[5:8, 0, :] = np.nan
        psess = make_psess(xy=xy)
        df = Tortuosity().compute(psess)
        assert np.isfinite(df["tortuosity"].values[0])

    def test_output_columns_present(self) -> None:
        psess = make_psess()
        df = Tortuosity().compute(psess)
        for col in ["session_id", "metric_id", "individual_id", "tortuosity"]:
            assert col in df.columns

    def test_metric_id_column(self) -> None:
        df = Tortuosity().compute(make_psess())
        assert (df["metric_id"] == "IL-5").all()

    def test_row_count_equals_n_animals(self) -> None:
        psess = make_psess(n_animals=5)
        df = Tortuosity().compute(psess)
        assert len(df) == 5
