"""Tests for zone metrics Z-1 (TimeInZone) and Z-3 (ZoneVisitCount) — TDD RED."""

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
from track2data.metrics.zone import TimeInZone, ZoneVisitCount

# ── helpers ────────────────────────────────────────────────────────────────────


def make_psess_with_zones() -> PreprocessedSession:
    n_frames, n_animals = 20, 2
    xy = np.zeros((n_frames, n_animals, 2))
    main_zone = np.full((n_frames, n_animals), "", dtype=object)
    # Animal 0 in "zone_A" for first 10 frames, "zone_B" for last 10
    main_zone[:10, 0] = "zone_A"
    main_zone[10:, 0] = "zone_B"
    # Animal 1 stays in "" (no zone) throughout
    sess = Session(
        session_id="t",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=10.0, n_frames=20, width_px=100, height_px=100),
        n_animals=2,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=np.zeros((20, 2)),
        accel_px_s2=np.zeros((20, 2)),
        heading_rad=np.zeros((20, 2)),
    )
    return PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)


def make_psess_sec_zone() -> PreprocessedSession:
    """Psess with both main_zone and sec_zone set."""
    n_frames, n_animals = 10, 1
    xy = np.zeros((n_frames, n_animals, 2))
    main_zone = np.full((n_frames, n_animals), "", dtype=object)
    sec_zone = np.full((n_frames, n_animals), "", dtype=object)
    main_zone[:5, 0] = "main_A"
    sec_zone[3:8, 0] = "sec_B"
    sess = Session(
        session_id="s",
        folder=Path("/tmp"),
        reader="test",
        video=VideoInfo(fps=10.0, n_frames=10, width_px=100, height_px=100),
        n_animals=1,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=np.zeros((10, 1)),
        accel_px_s2=np.zeros((10, 1)),
        heading_rad=np.zeros((10, 1)),
    )
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kine, main_zone=main_zone, sec_zone=sec_zone
    )


# ── TimeInZone (Z-1) ──────────────────────────────────────────────────────────


class TestTimeInZone:
    def test_metric_id(self) -> None:
        assert TimeInZone.id == "Z-1"

    def test_columns(self) -> None:
        psess = make_psess_with_zones()
        df = TimeInZone().compute(psess)
        assert set(df.columns) >= {"session_id", "zone_name", "individual_id", "time_s", "time_pct"}

    def test_time_in_zone(self) -> None:
        psess = make_psess_with_zones()
        df = TimeInZone().compute(psess)
        # Animal 0 in zone_A for 10 frames at 10fps = 1.0s
        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)].iloc[0]
        assert row["time_s"] == pytest.approx(1.0)
        assert row["time_pct"] == pytest.approx(0.5)

    def test_time_pct_zone_b(self) -> None:
        psess = make_psess_with_zones()
        df = TimeInZone().compute(psess)
        row = df[(df["zone_name"] == "zone_B") & (df["individual_id"] == 0)].iloc[0]
        assert row["time_s"] == pytest.approx(1.0)
        assert row["time_pct"] == pytest.approx(0.5)

    def test_no_zones_returns_empty(self) -> None:
        n_frames = 10
        xy = np.zeros((n_frames, 1, 2))
        sess = Session(
            session_id="t",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, 1)), np.zeros((n_frames, 1)), np.zeros((n_frames, 1))
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=None)
        df = TimeInZone().compute(psess)
        assert len(df) == 0

    def test_empty_zone_name_excluded(self) -> None:
        """Rows with zone_name=="" (not in any zone) should not appear."""
        psess = make_psess_with_zones()
        df = TimeInZone().compute(psess)
        assert "" not in df["zone_name"].values

    def test_session_id_correct(self) -> None:
        psess = make_psess_with_zones()
        df = TimeInZone().compute(psess)
        assert (df["session_id"] == "t").all()

    def test_sec_zone_included(self) -> None:
        """sec_zone values should be included in result."""
        psess = make_psess_sec_zone()
        df = TimeInZone().compute(psess)
        zone_names = set(df["zone_name"].unique())
        assert "main_A" in zone_names
        assert "sec_B" in zone_names

    def test_all_frames_no_zone(self) -> None:
        """If all frames are empty-string, result should be empty."""
        n_frames, n_animals = 5, 1
        xy = np.zeros((n_frames, n_animals, 2))
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        sess = Session(
            session_id="x",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=5.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=n_animals,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)
        df = TimeInZone().compute(psess)
        assert len(df) == 0


# ── ZoneVisitCount (Z-3) ─────────────────────────────────────────────────────


class TestZoneVisitCount:
    def test_metric_id(self) -> None:
        assert ZoneVisitCount.id == "Z-3"

    def test_declares_configurable_parameters(self) -> None:
        params = {p.name: p for p in ZoneVisitCount.parameters}
        assert params.keys() == {"derive_bout_criterion", "min_visit_frames"}
        # No declared default -- resolved per the derive_bout_criterion
        # switch (fixed 1 when off, fitted when on), same "unset means
        # auto" convention as IL-4's threshold_px_s.
        assert params["min_visit_frames"].default is None
        # Opt-in: off by default, so numbers match earlier releases.
        assert params["derive_bout_criterion"].default is False

    def test_columns(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneVisitCount().compute(psess)
        assert set(df.columns) >= {"session_id", "zone_name", "individual_id", "visit_count"}

    def test_visit_count_single_entry(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneVisitCount().compute(psess)
        # Animal 0 enters zone_A once (frame 0 onwards)
        row_a = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)].iloc[0]
        assert row_a["visit_count"] == 1

    def test_visit_count_zone_b(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneVisitCount().compute(psess)
        row_b = df[(df["zone_name"] == "zone_B") & (df["individual_id"] == 0)].iloc[0]
        assert row_b["visit_count"] == 1

    def test_multiple_visits(self) -> None:
        """Animal enters zone_A 3 times with gaps."""
        n_frames, n_animals = 20, 1
        xy = np.zeros((n_frames, n_animals, 2))
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        # frames 0-2: zone_A; frames 3-5: ""; frames 6-8: zone_A; frames 9-11: ""; 12-14: zone_A
        main_zone[0:3, 0] = "zone_A"
        main_zone[6:9, 0] = "zone_A"
        main_zone[12:15, 0] = "zone_A"
        sess = Session(
            session_id="multi",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=10.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=n_animals,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)
        df = ZoneVisitCount().compute(psess)
        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)].iloc[0]
        assert row["visit_count"] == 3

    def test_min_visit_frames_debounces_boundary_flicker(self) -> None:
        """Same 3-visits fixture as test_multiple_visits (each run is
        exactly 3 frames long), but with min_visit_frames=4 -- every
        run is too short to qualify, so visit_count must drop to 0
        rather than counting all 3 as with the default threshold of 1.
        This is METRICS_SPEC.md §4.2's min_visit_frames, specified but
        never implemented."""
        n_frames, n_animals = 20, 1
        xy = np.zeros((n_frames, n_animals, 2))
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:3, 0] = "zone_A"
        main_zone[6:9, 0] = "zone_A"
        main_zone[12:15, 0] = "zone_A"
        sess = Session(
            session_id="multi",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=10.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=n_animals,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)

        df = ZoneVisitCount().compute(psess, cfg={"min_visit_frames": 4})

        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)].iloc[0]
        assert row["visit_count"] == 0

    def test_min_visit_frames_keeps_runs_meeting_the_threshold(self) -> None:
        n_frames, n_animals = 20, 1
        xy = np.zeros((n_frames, n_animals, 2))
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:3, 0] = "zone_A"  # 3 frames -- too short
        main_zone[6:11, 0] = "zone_A"  # 5 frames -- qualifies
        sess = Session(
            session_id="mixed",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=10.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=n_animals,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
            np.zeros((n_frames, n_animals)),
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)

        df = ZoneVisitCount().compute(psess, cfg={"min_visit_frames": 4})

        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)].iloc[0]
        assert row["visit_count"] == 1

    def test_no_zones_returns_empty(self) -> None:
        n_frames = 10
        xy = np.zeros((n_frames, 1, 2))
        sess = Session(
            session_id="t",
            folder=Path("/tmp"),
            reader="test",
            video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        kine = KinematicsArrays(
            np.zeros((n_frames, 1)), np.zeros((n_frames, 1)), np.zeros((n_frames, 1))
        )
        psess = PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=None)
        df = ZoneVisitCount().compute(psess)
        assert len(df) == 0

    def test_empty_zone_excluded(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneVisitCount().compute(psess)
        assert "" not in df["zone_name"].values

    def test_session_id_correct(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneVisitCount().compute(psess)
        assert (df["session_id"] == "t").all()
