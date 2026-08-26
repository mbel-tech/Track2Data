"""Tests for the Sibly et al. 1990 log-survivorship bout-criterion
interval (BCI) wiring in Z-3, Z-4, Z-5 (Z-6 and Z-9 inherit it by
forwarding cfg to Z-5's compute() -- see test_zone_m2.py's existing
forwarding tests for those two).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from track2data.core.models import PreprocessedSession, Session, VideoInfo
from track2data.metrics.zone import (
    Z5EntryExitEvents,
    ZoneTransitions,
    ZoneVisitCount,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_psess(main_zone: np.ndarray, fps: float = 25.0) -> PreprocessedSession:
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
    kine = _zero_kinematics(n_frames, n_animals)
    return PreprocessedSession(session=sess, xy=xy, kinematics=kine, main_zone=main_zone)


def _zero_kinematics(n_frames: int, n_animals: int):
    from track2data.core.models import KinematicsArrays

    return KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )


def _bimodal_zone_column(rng: np.random.Generator) -> list[str]:
    """A long ['', 'A', ''] run sequence -- many brief 1-3 frame flickers
    into A (noise) and several genuine 25-40 frame visits -- as a plain
    Python list of per-frame zone-name strings, ready to become one
    column of a main_zone array."""
    frames: list[str] = []
    for _ in range(30):
        frames += ["A"] * int(rng.integers(1, 4))
        frames += [""] * int(rng.integers(5, 15))
    for _ in range(12):
        frames += ["A"] * int(rng.integers(25, 40))
        frames += [""] * int(rng.integers(20, 40))
    return frames


class TestZoneVisitCountBoutCriterion:
    def test_switch_is_off_by_default(self) -> None:
        params = {p.name: p for p in ZoneVisitCount.parameters}
        assert params["derive_bout_criterion"].default is False

    def test_default_run_uses_the_fixed_threshold_and_says_so(self) -> None:
        """Switch off (the default) on data the fit *could* have used:
        the fixed 1 must still win, and be reported as 'fixed' -- not
        'fixed_fallback', which would wrongly imply a fit was tried."""
        frames = _bimodal_zone_column(np.random.default_rng(0))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)
        df = ZoneVisitCount().compute(psess)
        row = df.iloc[0]
        assert row["min_visit_frames_used"] == 1
        assert row["bout_criterion_effective"] == "fixed"

    def test_explicit_min_visit_frames_reports_fixed(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        main_zone[:5, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneVisitCount().compute(psess, cfg={"min_visit_frames": 3})
        assert df.iloc[0]["bout_criterion_effective"] == "fixed"
        assert df.iloc[0]["min_visit_frames_used"] == 3

    def test_switch_overrides_an_explicit_min_visit_frames(self) -> None:
        """Ticking the switch means "let the data decide", which a typed
        threshold would contradict -- so the switch wins."""
        frames = _bimodal_zone_column(np.random.default_rng(0))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)
        df = ZoneVisitCount().compute(
            psess, cfg={"derive_bout_criterion": True, "min_visit_frames": 3}
        )
        assert df.iloc[0]["min_visit_frames_used"] != 3
        assert df.iloc[0]["bout_criterion_effective"] == "log_survivorship"

    def test_explicit_min_visit_frames_applies_again_once_the_switch_is_off(self) -> None:
        """The switch overrides the typed threshold but must not destroy
        it -- the same config with the switch off uses the 3 again."""
        frames = _bimodal_zone_column(np.random.default_rng(0))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)
        df = ZoneVisitCount().compute(
            psess, cfg={"derive_bout_criterion": False, "min_visit_frames": 3}
        )
        assert df.iloc[0]["min_visit_frames_used"] == 3
        assert df.iloc[0]["bout_criterion_effective"] == "fixed"

    def test_switch_on_falls_back_when_the_fit_cannot_converge(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        main_zone[:5, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneVisitCount().compute(psess, cfg={"derive_bout_criterion": True})
        assert df.iloc[0]["min_visit_frames_used"] == 1
        assert df.iloc[0]["bout_criterion_effective"] == "fixed_fallback"

    def test_switch_on_converges_on_a_bimodal_session(self) -> None:
        frames = _bimodal_zone_column(np.random.default_rng(0))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)

        df = ZoneVisitCount().compute(psess, cfg={"derive_bout_criterion": True})
        row = df.iloc[0]
        assert row["bout_criterion_effective"] == "log_survivorship"
        # Should separate the 1-3-frame noise population from the
        # 25-39-frame genuine population, not sit at either extreme.
        assert 3 <= row["min_visit_frames_used"] <= 35
        # All 30 brief flickers must be excluded; most (possibly not
        # quite all, if the threshold lands just above 25) of the 12
        # genuine visits should qualify.
        assert 8 <= row["visit_count"] <= 12

    def test_switch_on_reduces_visit_count_versus_the_default(self) -> None:
        """The whole point of the opt-in: on flickery data the fitted
        threshold discards the noise visits the fixed 1 counts."""
        frames = _bimodal_zone_column(np.random.default_rng(0))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)

        default_count = ZoneVisitCount().compute(psess).iloc[0]["visit_count"]
        derived_count = (
            ZoneVisitCount()
            .compute(psess, cfg={"derive_bout_criterion": True})
            .iloc[0]["visit_count"]
        )
        assert derived_count < default_count


class TestZoneTransitionsBoutCriterion:
    def test_switch_is_off_by_default(self) -> None:
        params = {p.name: p for p in ZoneTransitions.parameters}
        assert params["derive_bout_criterion"].default is False

    def test_default_run_uses_the_fixed_threshold_and_says_so(self) -> None:
        n_frames = 40
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[0:8, 0] = "A"
        main_zone[8:16, 0] = "B"
        main_zone[16:24, 0] = "A"
        main_zone[24:32, 0] = "B"
        main_zone[32:40, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneTransitions().compute(psess)
        assert (df["bout_criterion_effective"] == "fixed").all()
        assert (df["min_dwell_frames_used"] == 1).all()

    def test_explicit_min_dwell_frames_reports_fixed(self) -> None:
        n_frames = 40
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[0:8, 0] = "A"
        main_zone[8:16, 0] = "B"
        main_zone[16:24, 0] = "A"
        psess = make_psess(main_zone)
        df = ZoneTransitions().compute(psess, cfg={"min_dwell_frames": 2})
        assert (df["bout_criterion_effective"] == "fixed").all()
        assert (df["min_dwell_frames_used"] == 2).all()


class TestZ5EntryExitEventsBoutCriterion:
    def test_switch_is_off_by_default(self) -> None:
        params = {p.name: p for p in Z5EntryExitEvents.parameters}
        assert params["derive_bout_criterion"].default is False

    def test_default_run_uses_the_fixed_threshold_and_says_so(self) -> None:
        main_zone = np.full((10, 1), "", dtype=object)
        main_zone[:5, 0] = "A"
        psess = make_psess(main_zone)
        df = Z5EntryExitEvents().compute(psess)
        assert (df["bout_criterion_effective"] == "fixed").all()
        assert (df["min_dwell_frames_used"] == 1).all()

    def test_switch_on_converges_and_reduces_the_event_count(self) -> None:
        frames = _bimodal_zone_column(np.random.default_rng(1))
        main_zone = np.array(frames, dtype=object).reshape(-1, 1)
        psess = make_psess(main_zone)

        default_df = Z5EntryExitEvents().compute(psess)
        derived_df = Z5EntryExitEvents().compute(
            psess, cfg={"derive_bout_criterion": True}
        )

        assert (default_df["bout_criterion_effective"] == "fixed").all()
        assert (derived_df["bout_criterion_effective"] == "log_survivorship").all()
        # The debounced event log must have fewer enter/exit events than
        # the default (min_dwell=1) one, since it drops the ~30 brief
        # flickers entirely.
        assert len(derived_df) < len(default_df)


# ── The opt-in's core promise ─────────────────────────────────────────────────


class TestSwitchOffReproducesHistoricalBehaviour:
    """The whole reason this feature is a switch rather than a new
    default: with it off, every affected metric must produce exactly
    what it produced before the feature existed. "Before" is pinned
    here as the explicit historical threshold (1 frame for the zone
    metrics), so this catches a regression in the resolution logic --
    e.g. the fit being attempted anyway, or the fixed default drifting
    -- rather than merely re-asserting today's behaviour.
    """

    def _busy_session(self) -> PreprocessedSession:
        rng = np.random.default_rng(42)
        frames = _bimodal_zone_column(rng)
        return make_psess(np.array(frames, dtype=object).reshape(-1, 1))

    def test_z3_visit_count_matches_explicit_min_visit_frames_1(self) -> None:
        psess = self._busy_session()
        off = ZoneVisitCount().compute(psess).reset_index(drop=True)
        historical = ZoneVisitCount().compute(
            psess, cfg={"min_visit_frames": 1}
        ).reset_index(drop=True)
        assert off["visit_count"].equals(historical["visit_count"])

    def test_z4_transition_counts_match_explicit_min_dwell_frames_1(self) -> None:
        n_frames = 40
        main_zone = np.full((n_frames, 1), "", dtype=object)
        main_zone[0:8, 0] = "A"
        main_zone[8:16, 0] = "B"
        main_zone[16:24, 0] = "A"
        psess = make_psess(main_zone)
        off = ZoneTransitions().compute(psess).reset_index(drop=True)
        historical = ZoneTransitions().compute(
            psess, cfg={"min_dwell_frames": 1}
        ).reset_index(drop=True)
        assert off["transition_count"].equals(historical["transition_count"])

    def test_z5_event_log_matches_explicit_min_dwell_frames_1(self) -> None:
        psess = self._busy_session()
        off = Z5EntryExitEvents().compute(psess).reset_index(drop=True)
        historical = Z5EntryExitEvents().compute(
            psess, cfg={"min_dwell_frames": 1}
        ).reset_index(drop=True)
        assert len(off) == len(historical)
        assert off["frame"].equals(historical["frame"])
        assert off["event"].equals(historical["event"])
