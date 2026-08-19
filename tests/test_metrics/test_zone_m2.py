"""Tests for zone metrics Z-2 (AreaCorrectedOccupancy) and Z-4 (ZoneTransitions) — TDD RED."""

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
from track2data.metrics.zone import AreaCorrectedOccupancy, ZoneTransitions

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_base_sess(
    n_frames: int = 20,
    n_animals: int = 2,
    fps: float = 10.0,
    session_id: str = "t",
) -> tuple[Session, KinematicsArrays, np.ndarray]:
    xy = np.zeros((n_frames, n_animals, 2))
    sess = Session(
        session_id=session_id,
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
    return sess, kine, xy


def make_psess_with_zones(
    zone_pattern: np.ndarray | None = None,
    n_frames: int = 20,
    n_animals: int = 2,
) -> PreprocessedSession:
    """Build a psess with main_zone set."""
    sess, kine, xy = _make_base_sess(n_frames=n_frames, n_animals=n_animals)
    if zone_pattern is None:
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        main_zone[10:, 0] = "zone_B"
    else:
        main_zone = zone_pattern
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kine, main_zone=main_zone,
        report=PreprocessReport(),
    )


def make_psess_no_zones(n_frames: int = 10) -> PreprocessedSession:
    sess, kine, xy = _make_base_sess(n_frames=n_frames)
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kine, main_zone=None,
        report=PreprocessReport(),
    )


# ── Z-2: AreaCorrectedOccupancy ───────────────────────────────────────────────


class TestAreaCorrectedOccupancy:
    def test_metric_id(self) -> None:
        assert AreaCorrectedOccupancy.id == "Z-2"

    def test_output_columns_present(self) -> None:
        psess = make_psess_with_zones()
        df = AreaCorrectedOccupancy().compute(psess)
        for col in [
            "session_id",
            "zone_name",
            "individual_id",
            "area_corrected_occupancy",
        ]:
            assert col in df.columns

    def test_no_zones_returns_empty_with_correct_columns(self) -> None:
        """Without zone data, returns empty DataFrame with correct columns."""
        psess = make_psess_no_zones()
        df = AreaCorrectedOccupancy().compute(psess)
        assert len(df) == 0
        for col in [
            "session_id",
            "zone_name",
            "individual_id",
            "area_corrected_occupancy",
        ]:
            assert col in df.columns

    def test_no_cfg_returns_empty_with_correct_columns(self) -> None:
        """Without ZoneSet in cfg (no roi_area), returns empty DataFrame."""
        psess = make_psess_with_zones()
        df = AreaCorrectedOccupancy().compute(psess, cfg=None)
        assert len(df) == 0
        for col in [
            "session_id",
            "zone_name",
            "individual_id",
            "area_corrected_occupancy",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        """When cfg with roi_areas is provided, session_id should appear in output."""
        psess = make_psess_with_zones()
        roi_areas = {"zone_A": 2500.0, "zone_B": 2500.0}
        cfg = {"roi_areas": roi_areas, "total_arena_area": 10000.0}
        df = AreaCorrectedOccupancy().compute(psess, cfg=cfg)
        if len(df) > 0:
            assert (df["session_id"] == "t").all()

    def test_known_area_corrected_occupancy(self) -> None:
        """Animal 0 in zone_A for 10/20 frames (50%); zone occupies 25% of arena.
        area_corrected = 0.5 / 0.25 = 2.0."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        roi_areas = {"zone_A": 2500.0}
        cfg = {"roi_areas": roi_areas, "total_arena_area": 10000.0}
        df = AreaCorrectedOccupancy().compute(psess, cfg=cfg)
        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)]
        assert len(row) == 1
        assert row["area_corrected_occupancy"].values[0] == pytest.approx(2.0, rel=1e-6)

    def test_equal_occupancy_equal_area_gives_one(self) -> None:
        """If time_pct = roi_area / total_area, result = 1.0."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:5, 0] = "zone_A"  # 5/20 = 25%
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        roi_areas = {"zone_A": 2500.0}
        cfg = {"roi_areas": roi_areas, "total_arena_area": 10000.0}
        df = AreaCorrectedOccupancy().compute(psess, cfg=cfg)
        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)]
        if len(row) > 0:
            assert row["area_corrected_occupancy"].values[0] == pytest.approx(1.0, rel=1e-4)

    def test_empty_zone_excluded(self) -> None:
        """Empty-string zone names should not appear in output."""
        psess = make_psess_with_zones()
        roi_areas = {"zone_A": 2500.0, "zone_B": 2500.0}
        cfg = {"roi_areas": roi_areas, "total_arena_area": 10000.0}
        df = AreaCorrectedOccupancy().compute(psess, cfg=cfg)
        if len(df) > 0:
            assert "" not in df["zone_name"].values


# ── Z-4: ZoneTransitions ─────────────────────────────────────────────────────


class TestZoneTransitions:
    def test_metric_id(self) -> None:
        assert ZoneTransitions.id == "Z-4"

    def test_output_columns_present(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneTransitions().compute(psess)
        for col in [
            "session_id",
            "from_zone",
            "to_zone",
            "individual_id",
            "transition_count",
        ]:
            assert col in df.columns

    def test_session_id_propagated(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneTransitions().compute(psess)
        if len(df) > 0:
            assert (df["session_id"] == "t").all()

    def test_no_zones_returns_empty(self) -> None:
        psess = make_psess_no_zones()
        df = ZoneTransitions().compute(psess)
        assert len(df) == 0

    def test_single_transition_counted(self) -> None:
        """Animal 0: zone_A → zone_B once → transition_count = 1."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        main_zone[10:, 0] = "zone_B"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = ZoneTransitions().compute(psess)
        row = df[
            (df["from_zone"] == "zone_A")
            & (df["to_zone"] == "zone_B")
            & (df["individual_id"] == 0)
        ]
        assert len(row) == 1
        assert row["transition_count"].values[0] == 1

    def test_multiple_transitions(self) -> None:
        """A → B → A → B → A: 4 transitions total (2 A→B, 2 B→A)."""
        n_frames, n_animals = 10, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        # A, A, B, B, A, A, B, B, A, A
        main_zone[0:2, 0] = "zone_A"
        main_zone[2:4, 0] = "zone_B"
        main_zone[4:6, 0] = "zone_A"
        main_zone[6:8, 0] = "zone_B"
        main_zone[8:10, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = ZoneTransitions().compute(psess)
        ab = df[(df["from_zone"] == "zone_A") & (df["to_zone"] == "zone_B")]
        ba = df[(df["from_zone"] == "zone_B") & (df["to_zone"] == "zone_A")]
        assert ab["transition_count"].sum() == 2
        assert ba["transition_count"].sum() == 2

    def test_no_transitions_when_static(self) -> None:
        """Animal always in zone_A → no transitions."""
        n_frames, n_animals = 10, 1
        main_zone = np.full((n_frames, n_animals), "zone_A", dtype=object)
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = ZoneTransitions().compute(psess)
        assert len(df) == 0

    def test_empty_to_zone_transition_excluded(self) -> None:
        """Transitions from/to empty-string zones should be excluded."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        # Frames 10-20: empty → no zone
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = ZoneTransitions().compute(psess)
        if len(df) > 0:
            assert "" not in df["from_zone"].values
            assert "" not in df["to_zone"].values

    def test_transition_count_positive(self) -> None:
        psess = make_psess_with_zones()
        df = ZoneTransitions().compute(psess)
        if len(df) > 0:
            assert (df["transition_count"] > 0).all()

    def test_multiple_animals_independent(self) -> None:
        """Each animal tracked independently for transitions."""
        n_frames, n_animals = 20, 2
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        main_zone[10:, 0] = "zone_B"
        main_zone[:5, 1] = "zone_A"
        main_zone[5:15, 1] = "zone_B"
        main_zone[15:, 1] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = ZoneTransitions().compute(psess)
        # Animal 0: 1 A→B
        a0 = df[(df["individual_id"] == 0)]
        assert a0["transition_count"].sum() >= 1
        # Animal 1: A→B and B→A
        a1 = df[(df["individual_id"] == 1)]
        assert a1["transition_count"].sum() >= 2
