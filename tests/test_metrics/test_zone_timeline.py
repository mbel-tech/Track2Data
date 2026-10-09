"""Zone events, latency and dwell on the original video clock.

Z-5 used to report the stored row index as ``frame`` and ``row / fps`` as ``t_s``, while the
per-frame table reported the true video frame. With tracking that starts after frame 0, or in
disjoint intervals, the same observation then had two different clocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track2data.api import Engine
from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    PreprocessReport,
    ProjectManifest,
    Session,
    VideoInfo,
)
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.zone import (
    Z5EntryExitEvents,
    Z6LatencyToFirstEntry,
    ZoneDwellTimeDistribution,
)

FPS = 25.0


def _psess(
    in_zone_rows: list[int],
    *,
    intervals: list[tuple[int, int]] | None,
    n: int = 20,
) -> PreprocessedSession:
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = np.arange(n)
    zone = np.full((n, 1), "", dtype=object)
    zone[in_zone_rows, 0] = "A"
    sess = Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="t",
        video=VideoInfo(fps=FPS, n_frames=5000, width_px=100, height_px=100),
        n_animals=1,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        tracking_intervals=intervals,
    )
    kin = KinematicsArrays(
        speed_px_s=np.zeros((n, 1)), accel_px_s2=np.zeros((n, 1)), heading_rad=np.zeros((n, 1))
    )
    return PreprocessedSession(
        session=sess, xy=xy, kinematics=kin, main_zone=zone, report=PreprocessReport()
    )


def _engine() -> Engine:
    now = datetime.now(tz=UTC)
    return Engine(ProjectManifest(project_name="p", created_at=now, updated_at=now))


class TestEventsMatchTheTrajectoryTable:
    def test_the_bug_report_case(self) -> None:
        psess = _psess(list(range(10, 20)), intervals=[(1000, 1020)])
        events = Z5EntryExitEvents().compute(psess)
        enter = events[events["event"] == "enter"].iloc[0]
        assert enter["frame"] == 1010
        assert enter["t_s"] == pytest.approx(40.4)

        table = _engine().build_fish_by_frame(psess)
        row = table[table["frame"] == 1010].iloc[0]
        assert row["time_s"] == pytest.approx(enter["t_s"])
        assert row["main_zone"] == "A"

    def test_a_contiguous_session_from_frame_zero_is_unchanged(self) -> None:
        psess = _psess([4, 5, 6], intervals=None)
        events = Z5EntryExitEvents().compute(psess)
        assert list(events["event"]) == ["enter", "exit"]
        assert list(events["frame"]) == [4, 7]
        assert list(events["t_s"]) == pytest.approx([4 / FPS, 7 / FPS])

    def test_disjoint_intervals_keep_the_real_offsets(self) -> None:
        # rows 0-9 are frames 0-9; rows 10-19 are frames 1000-1009
        psess = _psess([2, 3, 12, 13], intervals=[(0, 10), (1000, 1010)])
        events = Z5EntryExitEvents().compute(psess)
        assert list(events["frame"]) == [2, 4, 1002, 1004]
        assert events["t_s"].iloc[2] == pytest.approx(1002 / FPS)

    def test_a_malformed_timeline_falls_back_to_row_position(self) -> None:
        psess = _psess([4, 5], intervals=[(0, 5), (3, 8)])  # overlapping
        events = Z5EntryExitEvents().compute(psess)
        assert list(events["frame"]) == [4, 6]


class TestObservationGaps:
    def test_a_stay_across_a_gap_is_cut_not_joined(self) -> None:
        # inside the zone at the end of interval 1 and the start of interval 2
        psess = _psess(list(range(7, 13)), intervals=[(0, 10), (1000, 1010)])
        events = Z5EntryExitEvents().compute(psess).reset_index(drop=True)
        assert list(events["event"]) == ["enter", "enter", "exit"]
        assert list(events["frame"]) == [7, 1000, 1003]
        # No measured exit at the end of interval 1; the second entry is not a measured one.
        assert list(events["after_gap"]) == [False, True, False]

    def test_a_visit_inside_one_interval_keeps_its_dwell(self) -> None:
        psess = _psess([2, 3, 4, 5], intervals=[(0, 10), (1000, 1010)])
        dwell = ZoneDwellTimeDistribution().compute(psess).iloc[0]
        assert dwell["n_visits"] == 1
        assert dwell["mean_dwell_s"] == pytest.approx(4 / FPS)

    def test_no_dwell_is_fabricated_across_the_gap(self) -> None:
        psess = _psess(list(range(7, 13)), intervals=[(0, 10), (1000, 1010)])
        dwell = ZoneDwellTimeDistribution().compute(psess)
        assert dwell.empty  # neither half is a complete observed visit; none spans ~40 s

    def test_contiguous_adjacent_intervals_have_no_cut(self) -> None:
        psess = _psess(list(range(7, 13)), intervals=[(0, 10), (10, 20)])
        events = Z5EntryExitEvents().compute(psess)
        assert list(events["event"]) == ["enter", "exit"]
        assert not events["after_gap"].any()


class TestLatency:
    def test_it_is_time_since_the_start_of_tracking_and_says_where_that_is(self) -> None:
        psess = _psess(list(range(10, 20)), intervals=[(1000, 1020)])
        row = Z6LatencyToFirstEntry().compute(psess).iloc[0]
        assert row["first_entry_t_s"] == pytest.approx(10 / FPS)  # 0.4 s after tracking began
        assert row["origin_frame"] == 1000
        assert not row["first_entry_after_gap"]

    def test_a_contiguous_session_keeps_its_old_values(self) -> None:
        row = Z6LatencyToFirstEntry().compute(_psess([6, 7], intervals=None)).iloc[0]
        assert row["first_entry_t_s"] == pytest.approx(6 / FPS)
        assert row["origin_frame"] == 0

    def test_omitted_time_between_intervals_is_elapsed_time_not_zero(self) -> None:
        psess = _psess([12, 13], intervals=[(0, 10), (1000, 1010)])
        row = Z6LatencyToFirstEntry().compute(psess).iloc[0]
        assert row["first_entry_t_s"] == pytest.approx(1002 / FPS)
        assert not row["first_entry_after_gap"]  # a real entry inside the second interval

    def test_being_inside_at_the_first_frame_after_a_gap_is_flagged_as_an_upper_bound(self) -> None:
        psess = _psess([10, 11], intervals=[(0, 10), (1000, 1010)])
        row = Z6LatencyToFirstEntry().compute(psess).iloc[0]
        assert row["first_entry_t_s"] == pytest.approx(1000 / FPS)
        assert row["first_entry_after_gap"]

    def test_never_entering_is_still_inf(self) -> None:
        psess = _psess([], intervals=None)
        psess.main_zone[0, 0] = "A"  # keep one zone name so the grid exists
        assert Z6LatencyToFirstEntry().compute(psess).iloc[0]["first_entry_t_s"] == 0.0


class TestBins:
    def test_a_later_bin_reports_original_frames_without_a_second_offset(self) -> None:
        psess = _psess([12, 13, 14], intervals=[(1000, 1020)])
        whole = Z5EntryExitEvents().compute(psess)
        windows = bin_windows(psess, bin_seconds=10 / FPS)
        assert len(windows) == 2
        later = Z5EntryExitEvents().compute(slice_psess(psess, windows[1].start_row, 20))
        assert list(later["frame"]) == list(whole["frame"]) == [1012, 1015]

    def test_the_engine_does_not_offset_events_a_second_time(self) -> None:
        psess = _psess([12, 13, 14], intervals=[(1000, 1020)])
        windows = bin_windows(psess, bin_seconds=10 / FPS)
        out = _engine()._compute_windowed(Z5EntryExitEvents, psess, {}, windows, False)
        in_second_bin = out[out["bin_index"] == windows[1].index]
        assert list(in_second_bin["frame"]) == [1012, 1015]

    def test_latency_in_a_window_is_from_the_windows_first_frame(self) -> None:
        psess = _psess([12, 13, 14], intervals=[(1000, 1020)])
        windows = bin_windows(psess, bin_seconds=10 / FPS)
        late = Z6LatencyToFirstEntry().compute(slice_psess(psess, windows[1].start_row, 20))
        assert late.iloc[0]["origin_frame"] == 1010
        assert late.iloc[0]["first_entry_t_s"] == pytest.approx(2 / FPS)


def test_events_survive_every_exporter_unshifted() -> None:
    """The exported frame is the value the metric produced: nothing re-maps it afterwards."""
    psess = _psess(list(range(10, 20)), intervals=[(1000, 1020)])
    events = Z5EntryExitEvents().compute(psess)
    assert isinstance(events, pd.DataFrame)
    from track2data.exporters._merge import merge_metric_frames

    merged = merge_metric_frames({"Z-5": events})
    assert list(merged["frame"]) == [1010]
