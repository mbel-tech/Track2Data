"""Preprocessing across tracking intervals: real elapsed time, optional bridging of gaps.

A trajectory array can hold only the tracked frames, for example rows 0-9 = video frames 0-9
and rows 10-19 = frames 1000-1009. Treating those rows as consecutive frames made the animal
"jump" 141 px in 1/25 s (about 1,060 px/s) between two stationary stretches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from track2data.api import Engine
from track2data.core.errors import ProcessingError
from track2data.core.models import (
    GapFillCfg,
    JumpCfg,
    KinematicsCfg,
    PreprocessConfig,
    ProjectManifest,
    Session,
    SmoothCfg,
    VideoInfo,
)
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.diagnostic import MetricInputProvenance
from track2data.metrics.individual import PathLength
from track2data.preprocess.pipeline import run

FPS = 25.0
TWO = [(0, 10), (1000, 1010)]


def _session(
    intervals: list[tuple[int, int]] | None = TWO,
    *,
    n_animals: int = 1,
    stable: bool = True,
    declared_free: bool | None = None,
    with_probs: bool = False,
    n: int = 20,
) -> Session:
    xy = np.zeros((n, n_animals, 2))
    xy[n // 2 :] = 100.0  # first half at (0, 0), second half at (100, 100)
    return Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="idtrackerai",
        video=VideoInfo(fps=FPS, n_frames=5000, width_px=200, height_px=200),
        n_animals=n_animals,
        trajectory_variant="with_gaps",
        has_stable_identities=stable,
        track_wo_identities=declared_free,
        raw_xy=xy,
        id_probabilities=np.full((n, n_animals), 0.9) if with_probs else None,
        tracking_intervals=intervals,
    )


def _cfg(*, across: bool = False, limit_s: float = 30.0, **over) -> PreprocessConfig:
    """Everything that would move positions is off, to isolate timing."""
    return PreprocessConfig(
        gap_fill=GapFillCfg(
            enabled=across, across_tracking_intervals=across, max_cross_interval_gap_s=limit_s
        ),
        jump=JumpCfg(enabled=False),
        smoothing=SmoothCfg(enabled=False, method="none"),
        **over,
    )


class TestInterpolationOff:
    def test_no_motion_is_invented_across_the_gap(self) -> None:
        psess = run(_session(), _cfg())
        speed = psess.kinematics.speed_px_s[:, 0]
        assert np.nanmax(speed) < 1e-9  # both stretches are motionless; nothing else exists
        assert np.nanmax(speed) != pytest.approx(1060.66, rel=0.1)

    def test_a_single_unobserved_row_separates_the_stretches(self) -> None:
        psess = run(_session(), _cfg())
        assert psess.xy.shape[0] == 21  # 20 observed + one separator, not 990 rows
        frames, valid = psess.timeline()
        assert valid and list(frames[:9]) == list(range(9)) and frames[-1] == 1009
        assert psess.separator_mask.sum() == 1
        assert np.isnan(psess.xy[psess.separator_mask]).all()
        assert np.isnan(psess.kinematics.speed_px_s[psess.separator_mask]).all()

    def test_observed_positions_are_untouched(self) -> None:
        raw = _session().raw_xy
        psess = run(_session(), _cfg())
        np.testing.assert_array_equal(psess.xy[psess.tracked_mask], raw)

    def test_path_length_does_not_bridge_the_gap(self) -> None:
        psess = run(_session(), _cfg())
        assert PathLength().compute(psess).iloc[0]["path_length_px"] == 0.0  # not 141 px


class TestInterpolationOn:
    def test_the_gap_is_rebuilt_frame_by_frame_between_the_real_anchors(self) -> None:
        psess = run(_session(), _cfg(across=True, limit_s=60.0))
        assert psess.xy.shape[0] == 1010  # frames 0..1009, 990 of them inserted
        frames, _ = psess.timeline()
        assert list(frames) == list(range(1010))
        np.testing.assert_allclose(psess.xy[9, 0], (0.0, 0.0))  # observed endpoints preserved
        np.testing.assert_allclose(psess.xy[1000, 0], (100.0, 100.0))
        step = (100.0 - 0.0) / (1000 - 9)  # the true 991-frame separation
        np.testing.assert_allclose(psess.xy[500, 0], (step * (500 - 9),) * 2)

    def test_interior_speed_is_the_endpoint_displacement_over_the_real_time(self) -> None:
        for cfg in (KinematicsCfg(method="forward_difference"), KinematicsCfg()):
            psess = run(_session(), _cfg(across=True, limit_s=60.0, kinematics=cfg))
            expected = np.hypot(100, 100) / (991 / FPS)  # 3.5676 px/s
            assert expected == pytest.approx(3.56764, abs=1e-4)
            assert psess.kinematics.speed_px_s[500, 0] == pytest.approx(expected, rel=1e-6)

    def test_inserted_frames_are_marked_as_estimated_not_observed(self) -> None:
        psess = run(_session(), _cfg(across=True, limit_s=60.0))
        assert psess.tracked_mask.sum() == 20
        inserted = ~psess.tracked_mask
        assert inserted.sum() == 990
        assert psess.was_interpolated[inserted, 0].all()
        assert not psess.was_interpolated[psess.tracked_mask, 0].any()
        d11 = MetricInputProvenance().compute(psess).iloc[0]
        assert d11["n_interpolated"] == 990  # users can see how much of the data is estimated
        assert d11["n_frames_total"] == 1010

    def test_path_length_counts_the_straight_line_estimate(self) -> None:
        """Policy: interpolated distance is included (and reported by D-11); it is an estimate."""
        psess = run(_session(), _cfg(across=True, limit_s=60.0))
        assert PathLength().compute(psess).iloc[0]["path_length_px"] == pytest.approx(
            np.hypot(100, 100)
        )


class TestTheLimit:
    @pytest.mark.parametrize(
        ("limit_s", "bridged"),
        [(39.0, False), (39.56, False), (39.6, True), (40.0, True)],
    )
    def test_the_limit_counts_real_missing_frames(self, limit_s: float, bridged: bool) -> None:
        """990 frames are missing (39.6 s at 25 fps); the 20 stored rows are irrelevant."""
        psess = run(_session(), _cfg(across=True, limit_s=limit_s))
        assert (psess.xy.shape[0] == 1010) is bridged
        if not bridged:
            assert psess.xy.shape[0] == 21 and psess.separator_mask.sum() == 1

    def test_it_is_off_by_default(self) -> None:
        assert GapFillCfg().across_tracking_intervals is False
        psess = run(_session(), PreprocessConfig())
        assert psess.xy.shape[0] == 21

    def test_each_gap_is_judged_on_its_own(self) -> None:
        session = _session([(0, 5), (15, 20), (2000, 2005)], n=15)  # gaps of 10 and 1980 frames
        psess = run(session, _cfg(across=True, limit_s=1.0))  # 25 frames: bridge only the first
        frames, _ = psess.timeline()
        assert list(frames[:20]) == list(range(20))  # frames 5..14 were rebuilt
        assert psess.separator_mask.sum() == 1  # the long gap is a single separator
        assert psess.xy.shape[0] == 5 + 10 + 5 + 1 + 5


class TestTimelineIntegrity:
    def test_a_nonzero_start_keeps_its_frame_numbers(self) -> None:
        psess = run(_session([(1000, 1020)]), _cfg())
        frames, valid = psess.timeline()
        assert valid and frames[0] == 1000 and frames[-1] == 1019
        assert psess.xy.shape[0] == 20

    def test_adjacent_intervals_add_no_row(self) -> None:
        psess = run(_session([(0, 10), (10, 20)]), _cfg(across=True))
        assert psess.xy.shape[0] == 20
        assert psess.separator_mask is None  # nothing was unobserved, so nothing was added

    def test_an_array_that_already_holds_the_whole_timeline_is_not_expanded_again(self) -> None:
        session = _session([(100, 104), (108, 112)], n=12)  # 12 rows spanning 100..111
        psess = run(session, _cfg(across=True))
        frames, valid = psess.timeline()
        assert psess.xy.shape[0] == 12 and valid and list(frames) == list(range(100, 112))

    def test_malformed_intervals_leave_the_session_as_it_was(self) -> None:
        psess = run(_session([(0, 10), (5, 15)]), _cfg(across=True))
        assert psess.xy.shape[0] == 20
        _, valid = psess.timeline()
        assert valid is False

    def test_no_intervals_means_no_change_at_all(self) -> None:
        session = _session(None)
        psess = run(session, PreprocessConfig())
        assert psess.frame_index is None and psess.tracked_mask is None
        assert psess.xy.shape[0] == 20


class TestIdentities:
    @pytest.mark.parametrize("kwargs", [{"stable": False}, {"declared_free": True}])
    def test_identity_free_sessions_are_never_bridged(self, kwargs) -> None:
        """Without stable identities the rows are detection slots, not animals."""
        psess = run(_session(n_animals=2, **kwargs), _cfg(across=True, limit_s=60.0))
        assert psess.xy.shape[0] == 21
        assert np.isnan(psess.xy[psess.separator_mask]).all()

    def test_a_stable_multi_animal_session_is_bridged_per_animal(self) -> None:
        session = _session(n_animals=2)
        raw = session.raw_xy.copy()
        raw[10:, 1, :] = np.nan  # animal 1 is untracked after the gap: no right-hand anchor
        session = session.model_copy(update={"raw_xy": raw})
        psess = run(session, _cfg(across=True, limit_s=60.0))
        assert not np.isnan(psess.xy[500, 0]).any()
        assert np.isnan(psess.xy[500, 1]).all()  # no anchor, no interpolation


class TestProvenanceAndAlignment:
    def test_every_aligned_array_has_one_row_per_timeline_row(self) -> None:
        psess = run(_session(with_probs=True), _cfg(across=True, limit_s=60.0))
        n = psess.xy.shape[0]
        for arr in (
            psess.kinematics.speed_px_s,
            psess.kinematics.accel_px_s2,
            psess.kinematics.heading_rad,
            psess.raw_xy_aligned,
            psess.id_probabilities_aligned,
            psess.timeline()[0],
            psess.tracked_mask,
        ):
            assert arr.shape[0] == n
        assert psess.jump_replaced is None or psess.jump_replaced.shape[0] == n

    def test_tracker_confidence_is_never_invented(self) -> None:
        psess = run(_session(with_probs=True), _cfg(across=True, limit_s=60.0))
        probs = psess.id_probabilities_aligned
        assert (probs[psess.tracked_mask] == 0.9).all()
        assert np.isnan(probs[~psess.tracked_mask]).all()

    def test_the_session_keeps_the_trackers_own_compact_output(self) -> None:
        session = _session(with_probs=True)
        psess = run(session, _cfg(across=True, limit_s=60.0))
        assert psess.session.raw_xy.shape[0] == 20 and psess.n_frames == 1010

    def test_a_time_bin_keeps_the_original_frames(self) -> None:
        psess = run(_session(), _cfg(across=True, limit_s=60.0))
        windows = bin_windows(psess, bin_seconds=10.0)  # 250 frames
        later = slice_psess(psess, windows[2].start_row, windows[2].stop_row)
        assert later.timeline()[0][0] == windows[2].start_row  # rows are frames here
        assert later.raw_xy_aligned.shape[0] == later.xy.shape[0]


class TestExports:
    def _table(self, across: bool):
        psess = run(_session(with_probs=True), _cfg(across=across, limit_s=60.0))
        now = datetime.now(tz=UTC)
        engine = Engine(ProjectManifest(project_name="p", created_at=now, updated_at=now))
        return engine.build_fish_by_frame(psess)

    def test_without_interpolation_untracked_frames_have_no_rows(self) -> None:
        table = self._table(across=False)
        assert len(table) == 20  # the separator row is not exported
        assert list(table["frame"][:10]) == list(range(10))
        assert list(table["frame"][10:]) == list(range(1000, 1010))
        assert table["time_s"].iloc[10] == pytest.approx(40.0)
        assert table["in_tracking_interval"].all()

    def test_with_interpolation_inserted_frames_are_flagged(self) -> None:
        table = self._table(across=True)
        assert len(table) == 1010
        inserted = table[~table["in_tracking_interval"].astype(bool)]
        assert len(inserted) == 990
        assert inserted["was_interpolated"].all()
        assert inserted["id_probability"].isna().all()
        assert inserted["x_px"].notna().all()
        assert table.loc[table["frame"] == 1000, "time_s"].iloc[0] == pytest.approx(40.0)


class TestResources:
    def test_a_huge_gap_over_the_limit_costs_one_row(self) -> None:
        session = _session([(0, 10), (50_000_000, 50_000_010)])
        psess = run(session, _cfg(across=True, limit_s=30.0))
        assert psess.xy.shape[0] == 21

    def test_a_limit_that_would_allocate_an_absurd_array_is_refused(self) -> None:
        session = _session([(0, 10), (500_000_000, 500_000_010)])
        with pytest.raises(ProcessingError) as err:
            run(session, _cfg(across=True, limit_s=1e9))
        assert "limit" in str(err.value).lower()


class TestTheCacheKnowsAboutIt:
    def test_the_new_settings_are_part_of_the_preprocessing_config(self) -> None:
        a = PreprocessConfig().model_dump(mode="json")
        b = PreprocessConfig(gap_fill=GapFillCfg(across_tracking_intervals=True)).model_dump(
            mode="json"
        )
        assert a != b

    def test_the_schema_moved_past_the_compressed_timeline_results(self) -> None:
        assert Engine._CACHE_SCHEMA >= 6


class TestEventsOnEstimatedFrames:
    def test_a_zone_event_on_a_reconstructed_frame_is_flagged_estimated(self) -> None:
        import dataclasses

        from track2data.core.models import ROI, ZoneSet
        from track2data.metrics.zone import Z5EntryExitEvents
        from track2data.zones.geometry import assign_zones

        psess = run(_session(), _cfg(across=True, limit_s=60.0))
        zones = ZoneSet(
            rois=[ROI(name="late", vertices=[(40, 40), (200, 40), (200, 200), (40, 200)])]
        )
        main, sec = assign_zones(psess.xy, zones)
        psess = dataclasses.replace(psess, main_zone=main, sec_zone=sec)
        events = Z5EntryExitEvents().compute(psess)
        enter = events[events["event"] == "enter"].iloc[0]
        assert 10 <= enter["frame"] < 1000  # inside the reconstructed stretch
        assert enter["estimated"]


class TestTheUsersIdentityFreeOverride:
    def test_an_override_forbids_bridging_even_when_the_file_says_stable(self) -> None:
        from track2data.core.models import SessionRef

        now = datetime.now(tz=UTC)
        ref = SessionRef(
            session_id="s", folder=Path("/tmp/s"), sha256="", identity_free_override=True
        )
        manifest = ProjectManifest(
            project_name="p",
            created_at=now,
            updated_at=now,
            sessions=[ref],
            preprocess=_cfg(across=True, limit_s=60.0),
        )
        psess = Engine(manifest).preprocess(_session())
        assert psess.xy.shape[0] == 21  # the override wins; the gap stays a break
