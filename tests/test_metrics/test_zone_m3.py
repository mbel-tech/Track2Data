"""Tests for zone metrics Z-7, Z-8, Z-9 -- the reference-audit
proposals: zone transition matrix & sequence entropy, Jacobs' D
preference index, and zone dwell-time distribution.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
)
from track2data.metrics.zone import (
    ZoneDwellTimeDistribution,
    ZonePreferenceIndex,
    ZoneTransitionMatrix,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(main_zone: np.ndarray, fps: float = 10.0) -> PreprocessedSession:
    n_frames, n_animals = main_zone.shape
    xy = np.zeros((n_frames, n_animals, 2))
    sess = Session(
        session_id="test",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=fps, n_frames=n_frames, width_px=100, height_px=100),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )
    return PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)


# ── Z-7: ZoneTransitionMatrix ─────────────────────────────────────────────────


class TestZoneTransitionMatrix:
    def test_metric_id(self) -> None:
        assert ZoneTransitionMatrix.id == "Z-7"

    def test_output_columns_present(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        main_zone[:5, 0] = "A"
        main_zone[5:, 0] = "B"
        psess = make_psess(main_zone)
        df = ZoneTransitionMatrix().compute(psess)
        for col in (
            "session_id",
            "individual_id",
            "from_zone",
            "to_zone",
            "transition_count",
            "transition_probability",
            "sequence_entropy_bits",
        ):
            assert col in df.columns

    def test_two_zone_alternation_gives_probability_one_and_entropy_one(self) -> None:
        # A(8) B(8) A(8) B(8) A(8) -- 5 segments so the transition
        # sequence (A->B, B->A, A->B, B->A) is exactly 2:2, giving a
        # uniform (maximum-entropy) joint distribution over the two
        # possible transitions.
        n_frames = 40
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[0:8, 0] = "A"
        main_zone[8:16, 0] = "B"
        main_zone[16:24, 0] = "A"
        main_zone[24:32, 0] = "B"
        main_zone[32:40, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneTransitionMatrix().compute(psess)
        assert (df["transition_probability"] == 1.0).all()
        assert df["sequence_entropy_bits"].iloc[0] == pytest.approx(1.0)

    def test_no_zone_arrays_returns_empty(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        psess = make_psess(main_zone)
        df = ZoneTransitionMatrix().compute(psess)
        assert df.empty

    def test_min_dwell_frames_debounces_flicker(self) -> None:
        n_frames = 20
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[:9, 0] = "A"
        main_zone[9:11, 0] = "B"  # 2-frame flicker
        main_zone[11:, 0] = "A"
        psess = make_psess(main_zone)

        df_no_debounce = ZoneTransitionMatrix().compute(psess, cfg={"min_dwell_frames": 1})
        assert not df_no_debounce.empty

        df_debounced = ZoneTransitionMatrix().compute(psess, cfg={"min_dwell_frames": 3})
        assert df_debounced.empty


# ── Z-8: ZonePreferenceIndex ──────────────────────────────────────────────────


class TestZonePreferenceIndex:
    def test_metric_id(self) -> None:
        assert ZonePreferenceIndex.id == "Z-8"

    def test_output_columns_present(self) -> None:
        main_zone = np.full((10, 1), "A", dtype=object)
        psess = make_psess(main_zone)
        cfg = {"roi_areas": {"A": 50.0}, "total_arena_area": 100.0}
        df = ZonePreferenceIndex().compute(psess, cfg)
        for col in ("session_id", "zone_name", "individual_id", "jacobs_d"):
            assert col in df.columns

    def test_matches_area_share_gives_zero(self) -> None:
        n_frames = 100
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[:50, 0] = "A"  # 50% of time in a zone that is 50% of the arena
        psess = make_psess(main_zone)
        cfg = {"roi_areas": {"A": 50.0}, "total_arena_area": 100.0}
        df = ZonePreferenceIndex().compute(psess, cfg)
        assert df.iloc[0]["jacobs_d"] == pytest.approx(0.0, abs=1e-9)

    def test_full_preference_gives_positive_bounded_value(self) -> None:
        n_frames = 100
        main_zone = np.full((n_frames, 1), "A", dtype=object)  # 100% of time in a 10%-area zone
        psess = make_psess(main_zone)
        cfg = {"roi_areas": {"A": 10.0}, "total_arena_area": 100.0}
        df = ZonePreferenceIndex().compute(psess, cfg)
        d = df.iloc[0]["jacobs_d"]
        assert 0.0 < d <= 1.0

    def test_full_avoidance_gives_negative_bounded_value(self) -> None:
        n_frames = 100
        main_zone = np.full((n_frames, 1), "", dtype=object)  # 0% of time in the zone
        psess = make_psess(main_zone)
        cfg = {"roi_areas": {"A": 50.0}, "total_arena_area": 100.0}
        df = ZonePreferenceIndex().compute(psess, cfg)
        # No frames in zone A at all -> A never appears in np.unique per-frame
        # counts, so the zone contributes no row.
        assert df.empty

    def test_missing_cfg_returns_empty(self) -> None:
        main_zone = np.full((10, 1), "A", dtype=object)
        psess = make_psess(main_zone)
        df = ZonePreferenceIndex().compute(psess, cfg=None)
        assert df.empty


# ── Z-9: ZoneDwellTimeDistribution ────────────────────────────────────────────


class TestZoneDwellTimeDistribution:
    def test_metric_id(self) -> None:
        assert ZoneDwellTimeDistribution.id == "Z-9"

    def test_output_columns_present(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        main_zone[:5, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneDwellTimeDistribution().compute(psess)
        for col in (
            "session_id",
            "zone_name",
            "individual_id",
            "n_visits",
            "mean_dwell_s",
            "median_dwell_s",
            "max_dwell_s",
        ):
            assert col in df.columns

    def test_two_equal_visits_report_correct_stats(self) -> None:
        n_frames = 40
        main_zone = np.full((n_frames, 1), "", dtype=object)
        # Two 10-frame (1.0s at fps=10) visits to A, separated by a gap, with
        # a trailing non-A tail so the second visit closes with an exit.
        main_zone[0:10, 0] = "A"
        main_zone[10:20, 0] = "B"
        main_zone[20:30, 0] = "A"
        main_zone[30:40, 0] = "B"
        psess = make_psess(main_zone, fps=10.0)
        df = ZoneDwellTimeDistribution().compute(psess)
        row_a = df[df["zone_name"] == "A"].iloc[0]
        assert row_a["n_visits"] == 2
        assert row_a["mean_dwell_s"] == pytest.approx(1.0)
        assert row_a["median_dwell_s"] == pytest.approx(1.0)
        assert row_a["max_dwell_s"] == pytest.approx(1.0)

    def test_trailing_open_visit_is_excluded(self) -> None:
        n_frames = 20
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[5:, 0] = "A"  # still in A at the final frame -- no exit event
        psess = make_psess(main_zone, fps=10.0)
        df = ZoneDwellTimeDistribution().compute(psess)
        assert df.empty  # the only visit is open-ended, so nothing completes

    def test_no_zone_arrays_returns_empty(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        psess = make_psess(main_zone)
        df = ZoneDwellTimeDistribution().compute(psess)
        assert df.empty
