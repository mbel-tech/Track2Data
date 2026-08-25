"""Tests for zone metrics Z-2 (AreaCorrectedOccupancy), Z-4 (ZoneTransitions),
Z-5 (Z5EntryExitEvents) and Z-6 (Z6LatencyToFirstEntry) — TDD RED."""

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
from track2data.metrics.zone import (
    AreaCorrectedOccupancy,
    Z5EntryExitEvents,
    Z6LatencyToFirstEntry,
    ZoneTransitions,
)

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

    def test_declares_derived_parameters(self) -> None:
        params = {p.name: p for p in AreaCorrectedOccupancy.parameters}
        assert params.keys() == {"roi_areas", "total_arena_area"}
        assert all(p.derived for p in params.values())

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

    def test_declares_configurable_parameters(self) -> None:
        params = {p.name: p for p in ZoneTransitions.parameters}
        assert params.keys() == {"min_dwell_frames"}
        assert params["min_dwell_frames"].default == 1

    def test_min_dwell_frames_debounces_a_brief_flicker(self) -> None:
        """A (9 frames) -> B (2-frame flicker) -> A (9 frames). With the
        default min_dwell_frames=1 this is 2 transitions (A->B, B->A).
        With min_dwell_frames=3 the 2-frame B run is too short to count
        as a real visit, so the two A runs either side of it collapse
        into one continuous stay -- 0 transitions, not 2."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:9, 0] = "zone_A"
        main_zone[9:11, 0] = "zone_B"
        main_zone[11:20, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        default_df = ZoneTransitions().compute(psess)
        assert default_df["transition_count"].sum() == 2

        debounced_df = ZoneTransitions().compute(psess, cfg={"min_dwell_frames": 3})
        assert len(debounced_df) == 0

    def test_min_dwell_frames_does_not_invent_a_transition_across_a_dropout(self) -> None:
        """Regression: the debounce filtered short runs of the EMPTY-zone
        sentinel too, splicing the zones either side of a tracking
        dropout into adjacent sequence entries. A one-frame gap between
        two non-adjacent zones was then reported as a direct crossing --
        so raising min_dwell_frames INCREASED the transition count it is
        documented to reduce."""
        n_frames, n_animals = 21, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:10, 0] = "zone_A"
        main_zone[10, 0] = ""  # one-frame tracking dropout
        main_zone[11:21, 0] = "zone_B"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        # A->(nothing)->B is not a zone-to-zone transition: crossings via
        # the empty zone are not counted (see Z-4's own compute()).
        default_df = ZoneTransitions().compute(psess)
        assert default_df["transition_count"].sum() == 0

        # Raising the debounce must not manufacture one.
        debounced_df = ZoneTransitions().compute(psess, cfg={"min_dwell_frames": 2})
        assert debounced_df["transition_count"].sum() == 0

    def test_min_dwell_frames_still_debounces_a_flicker_between_two_stays(self) -> None:
        """The dropout fix must not disable the real debounce: a short
        run of a NAMED zone is still dropped, merging the stays either
        side of it."""
        n_frames, n_animals = 21, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:10, 0] = "zone_A"
        main_zone[10, 0] = "zone_B"  # one-frame flicker into a real zone
        main_zone[11:21, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        assert ZoneTransitions().compute(psess)["transition_count"].sum() == 2
        debounced_df = ZoneTransitions().compute(psess, cfg={"min_dwell_frames": 2})
        assert len(debounced_df) == 0

    def test_min_dwell_frames_keeps_a_transition_that_meets_the_threshold(self) -> None:
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:9, 0] = "zone_A"
        main_zone[9:15, 0] = "zone_B"  # 6-frame dwell -- meets the threshold
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        df = ZoneTransitions().compute(psess, cfg={"min_dwell_frames": 3})

        row = df[
            (df["from_zone"] == "zone_A")
            & (df["to_zone"] == "zone_B")
            & (df["individual_id"] == 0)
        ]
        assert len(row) == 1
        assert row["transition_count"].values[0] == 1

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


# ── Z-5: Z5EntryExitEvents ────────────────────────────────────────────────────


class TestZ5EntryExitEvents:
    def test_metric_id(self) -> None:
        assert Z5EntryExitEvents.id == "Z-5"

    def test_declares_configurable_parameters(self) -> None:
        params = {p.name: p for p in Z5EntryExitEvents.parameters}
        assert params.keys() == {"min_dwell_frames"}
        assert params["min_dwell_frames"].default == 1

    def test_min_dwell_frames_drops_a_brief_flicker_entirely(self) -> None:
        """A 2-frame flicker into zone_A produces no enter/exit events
        at all once it's shorter than min_dwell_frames -- the animal is
        treated as never having visited."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[10:12, 0] = "zone_A"  # 2-frame flicker
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        df = Z5EntryExitEvents().compute(psess, cfg={"min_dwell_frames": 3})

        assert len(df) == 0

    def test_min_dwell_frames_keeps_a_run_meeting_the_threshold(self) -> None:
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[10:16, 0] = "zone_A"  # 6-frame dwell
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        df = Z5EntryExitEvents().compute(psess, cfg={"min_dwell_frames": 3})

        enters = df[df["event"] == "enter"]
        exits = df[df["event"] == "exit"]
        assert enters["frame"].values[0] == 10
        assert exits["frame"].values[0] == 16

    def test_output_columns_present(self) -> None:
        psess = make_psess_with_zones()
        df = Z5EntryExitEvents().compute(psess)
        for col in ["session_id", "zone_name", "individual_id", "event", "t_s", "frame"]:
            assert col in df.columns

    def test_no_zones_returns_empty_with_correct_columns(self) -> None:
        psess = make_psess_no_zones()
        df = Z5EntryExitEvents().compute(psess)
        assert len(df) == 0
        for col in ["session_id", "zone_name", "individual_id", "event", "t_s", "frame"]:
            assert col in df.columns

    def test_single_enter_and_exit(self) -> None:
        """Animal enters zone_A at frame 5, exits at frame 15: one enter + one exit."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[5:15, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z5EntryExitEvents().compute(psess)
        enters = df[
            (df["event"] == "enter") & (df["zone_name"] == "zone_A") & (df["individual_id"] == 0)
        ]
        exits = df[
            (df["event"] == "exit") & (df["zone_name"] == "zone_A") & (df["individual_id"] == 0)
        ]
        assert len(enters) == 1
        assert len(exits) == 1
        assert enters["frame"].values[0] == 5
        assert enters["t_s"].values[0] == pytest.approx(0.5)  # fps=10.0
        assert exits["frame"].values[0] == 15
        assert exits["t_s"].values[0] == pytest.approx(1.5)

    def test_enter_at_frame_zero_when_starting_inside_zone(self) -> None:
        """Animal already inside zone_A at frame 0 gets an enter event at frame 0."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[0:8, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z5EntryExitEvents().compute(psess)
        enters = df[
            (df["event"] == "enter") & (df["zone_name"] == "zone_A") & (df["individual_id"] == 0)
        ]
        assert len(enters) == 1
        assert enters["frame"].values[0] == 0
        assert enters["t_s"].values[0] == pytest.approx(0.0)

    def test_enter_with_no_exit_when_never_leaves(self) -> None:
        """Animal enters zone_A at frame 10 and is still inside at the last frame."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[10:20, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z5EntryExitEvents().compute(psess)
        enters = df[
            (df["event"] == "enter") & (df["zone_name"] == "zone_A") & (df["individual_id"] == 0)
        ]
        exits = df[
            (df["event"] == "exit") & (df["zone_name"] == "zone_A") & (df["individual_id"] == 0)
        ]
        assert len(enters) == 1
        assert enters["frame"].values[0] == 10
        assert len(exits) == 0

    def test_session_id_propagated(self) -> None:
        psess = make_psess_with_zones()
        df = Z5EntryExitEvents().compute(psess)
        if len(df) > 0:
            assert (df["session_id"] == "t").all()

    def test_t_s_equals_frame_over_fps(self) -> None:
        psess = make_psess_with_zones()
        df = Z5EntryExitEvents().compute(psess)
        if len(df) > 0:
            expected = df["frame"].to_numpy() / 10.0  # fps=10.0
            assert np.allclose(df["t_s"].to_numpy(), expected)

    def test_empty_zone_name_excluded_from_output(self) -> None:
        psess = make_psess_with_zones()
        df = Z5EntryExitEvents().compute(psess)
        if len(df) > 0:
            assert "" not in df["zone_name"].values

    def test_multiple_animals_independent(self) -> None:
        """Each animal's enter/exit events are tracked independently."""
        n_frames, n_animals = 20, 2
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:10, 0] = "zone_A"
        main_zone[5:15, 1] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z5EntryExitEvents().compute(psess)
        a0 = df[df["individual_id"] == 0]
        a1 = df[df["individual_id"] == 1]
        assert set(a0["event"]) == {"enter", "exit"}
        assert set(a1["event"]) == {"enter", "exit"}
        assert a0[a0["event"] == "enter"]["frame"].values[0] == 0
        assert a1[a1["event"] == "enter"]["frame"].values[0] == 5


# ── Z-6: Z6LatencyToFirstEntry ────────────────────────────────────────────────


class TestZ6LatencyToFirstEntry:
    def test_metric_id(self) -> None:
        assert Z6LatencyToFirstEntry.id == "Z-6"

    def test_declares_configurable_parameters(self) -> None:
        params = {p.name: p for p in Z6LatencyToFirstEntry.parameters}
        assert params.keys() == {"min_dwell_frames"}
        assert params["min_dwell_frames"].default == 1

    def test_min_dwell_frames_forwards_to_z5_and_skips_a_brief_flicker(self) -> None:
        """Z-6 is defined purely in terms of Z-5's 'enter' events
        (see its own docstring) and already forwards cfg to
        Z5EntryExitEvents.compute() -- a 2-frame flicker into zone_A
        debounced away by Z-5 must mean Z-6 reports the *later*, real
        6-frame entry as the first one, not the flicker."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[2:4, 0] = "zone_A"  # 2-frame flicker, debounced away
        main_zone[10:16, 0] = "zone_A"  # 6-frame real entry
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        df = Z6LatencyToFirstEntry().compute(psess, cfg={"min_dwell_frames": 3})

        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)]
        assert row["first_entry_t_s"].values[0] == pytest.approx(1.0)  # 10 / fps=10.0

    def test_output_columns_present(self) -> None:
        psess = make_psess_with_zones()
        df = Z6LatencyToFirstEntry().compute(psess)
        for col in ["session_id", "zone_name", "individual_id", "first_entry_t_s"]:
            assert col in df.columns

    def test_no_zones_returns_empty_with_correct_columns(self) -> None:
        psess = make_psess_no_zones()
        df = Z6LatencyToFirstEntry().compute(psess)
        assert len(df) == 0
        for col in ["session_id", "zone_name", "individual_id", "first_entry_t_s"]:
            assert col in df.columns

    def test_correct_first_entry_latency(self) -> None:
        """First entry at frame 5; a later re-entry at frame 12 must not win."""
        n_frames, n_animals = 20, 1
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[5:8, 0] = "zone_A"
        main_zone[12:15, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z6LatencyToFirstEntry().compute(psess)
        row = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)]
        assert len(row) == 1
        assert row["first_entry_t_s"].values[0] == pytest.approx(0.5)  # 5 / fps=10.0

    def test_never_entered_gives_inf(self) -> None:
        """Animal 0 enters zone_A; animal 1 never enters any zone -> inf for animal 1."""
        n_frames, n_animals = 20, 2
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[5:10, 0] = "zone_A"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z6LatencyToFirstEntry().compute(psess)
        row0 = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 0)]
        row1 = df[(df["zone_name"] == "zone_A") & (df["individual_id"] == 1)]
        assert len(row0) == 1
        assert len(row1) == 1
        assert row0["first_entry_t_s"].values[0] == pytest.approx(0.5)
        assert row1["first_entry_t_s"].values[0] == float("inf")

    def test_session_id_propagated(self) -> None:
        psess = make_psess_with_zones()
        df = Z6LatencyToFirstEntry().compute(psess)
        if len(df) > 0:
            assert (df["session_id"] == "t").all()

    def test_full_grid_all_zones_times_all_animals(self) -> None:
        """2 zones x 2 animals -> 4 rows, even though each animal only visits one zone."""
        n_frames, n_animals = 20, 2
        main_zone = np.full((n_frames, n_animals), "", dtype=object)
        main_zone[:5, 0] = "zone_A"
        main_zone[5:10, 1] = "zone_B"
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )
        df = Z6LatencyToFirstEntry().compute(psess)
        assert len(df) == 4
        # animal 0 never entered zone_B -> inf
        row = df[(df["zone_name"] == "zone_B") & (df["individual_id"] == 0)]
        assert row["first_entry_t_s"].values[0] == float("inf")


class TestZ2NonPositiveArea:
    def test_negative_total_arena_area_produces_no_rows_rather_than_negative_occupancy(
        self,
    ) -> None:
        """Z-2 guarded `== 0` but not `< 0`. A signed-area zone set whose
        exclusion polygons outweigh their parent gave a negative total,
        which sailed past the guard and exported negative occupancy
        fractions that look like real measurements."""
        n_frames, n_animals = 10, 1
        main_zone = np.full((n_frames, n_animals), "arena", dtype=object)
        psess = make_psess_with_zones(
            zone_pattern=main_zone, n_frames=n_frames, n_animals=n_animals
        )

        df = AreaCorrectedOccupancy().compute(
            psess, cfg={"roi_areas": {"arena": -50.0}, "total_arena_area": -50.0}
        )

        assert len(df) == 0
