"""IL-1 and IL-7: no usable data is unavailable (NaN), never a measured zero.

A distance of zero says the animal did not move; zero freezing bouts says none was detected in
usable observations. An animal with no valid positions or speeds supports neither statement.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_metrics.test_individual import make_psess
from track2data.metrics.individual import FreezingBouts, PathLength

N = 20


def _xy(*tracks: np.ndarray) -> np.ndarray:
    return np.stack(tracks, axis=1)


def _track(kind: str) -> np.ndarray:
    xy = np.full((N, 2), np.nan)
    if kind == "all_missing":
        return xy
    if kind == "one_position":
        xy[5] = (3.0, 4.0)
    elif kind == "isolated":  # valid points, never two in a row
        xy[[2, 5, 9, 14]] = [[0, 0], [10, 0], [20, 0], [30, 0]]
    elif kind == "stationary":
        xy[:] = (7.0, 7.0)
    elif kind == "moving":
        xy[:, 0] = np.arange(N) * 2.0
        xy[:, 1] = 0.0
    elif kind == "gappy":  # moving, with frames 8-11 missing
        xy[:, 0] = np.arange(N) * 2.0
        xy[:, 1] = 0.0
        xy[8:12] = np.nan
    return xy


def _path(kind: str, **kw: object) -> pd.Series:
    psess = make_psess(xy=_xy(_track(kind)), **kw)
    return PathLength().compute(psess).iloc[0]


class TestPathLength:
    @pytest.mark.parametrize("kind", ["all_missing", "one_position", "isolated"])
    def test_no_valid_consecutive_pair_is_unavailable(self, kind: str) -> None:
        row = _path(kind, px_per_cm=10.0, body_length_px=np.array([20.0]))
        assert np.isnan(row["path_length_px"])
        assert np.isnan(row["path_length_cm"])
        assert np.isnan(row["path_length_bl"])

    def test_a_stationary_animal_with_valid_pairs_is_exactly_zero(self) -> None:
        row = _path("stationary", px_per_cm=10.0, body_length_px=np.array([20.0]))
        assert row["path_length_px"] == 0.0
        assert row["path_length_cm"] == 0.0 and row["path_length_bl"] == 0.0

    @pytest.mark.parametrize("calibrated", [False, True])
    def test_a_moving_path_keeps_its_distance(self, calibrated: bool) -> None:
        row = _path("moving", px_per_cm=10.0 if calibrated else None)
        assert row["path_length_px"] == pytest.approx(2.0 * (N - 1))
        if calibrated:
            assert row["path_length_cm"] == pytest.approx(2.0 * (N - 1) / 10.0)

    def test_a_gap_is_not_bridged_but_the_observed_path_is_kept(self) -> None:
        row = _path("gappy")
        # steps 0-1 ... 6-7 (7 steps) and 12-13 ... 18-19 (7 steps); the 4 missing frames add none
        assert row["path_length_px"] == pytest.approx(2.0 * 14)

    def test_animals_are_judged_independently(self) -> None:
        xy = _xy(_track("all_missing"), _track("stationary"), _track("moving"))
        df = PathLength().compute(make_psess(xy=xy)).set_index("individual_id")
        assert np.isnan(df.loc[0, "path_length_px"])
        assert df.loc[1, "path_length_px"] == 0.0
        assert df.loc[2, "path_length_px"] == pytest.approx(2.0 * (N - 1))


def _bouts(*kinds: str, **cfg: object) -> pd.DataFrame:
    xy = _xy(*(_track(k) for k in kinds))
    speed = np.full((N, len(kinds)), np.nan)
    for i, kind in enumerate(kinds):
        if kind == "stationary":
            speed[:, i] = 0.0
        elif kind == "moving":
            speed[:, i] = 50.0
    return FreezingBouts().compute(make_psess(xy=xy, speed=speed), dict(cfg) or None)


UNAVAILABLE = ["freezing_bout_count", "mean_freezing_duration_s", "total_freezing_duration_s"]


class TestFreezingBouts:
    def test_all_missing_speeds_are_unavailable(self) -> None:
        row = _bouts("all_missing").iloc[0]
        assert row[UNAVAILABLE].isna().all()
        # configuration fields stay populated
        assert row["min_bout_frames_used"] == 5
        assert row["bout_criterion_effective"] == "fixed"

    def test_observed_speeds_with_no_qualifying_bout_stay_zero(self) -> None:
        row = _bouts("moving").iloc[0]  # active throughout, so no inactive run
        assert row["freezing_bout_count"] == 0
        assert row["total_freezing_duration_s"] == 0.0
        assert row["mean_freezing_duration_s"] == 0.0  # historical convention, unchanged

    def test_a_measured_bout_has_its_count_and_duration(self) -> None:
        row = _bouts("stationary").iloc[0]
        assert row["freezing_bout_count"] == 1
        assert row["total_freezing_duration_s"] == pytest.approx(N / 25.0)

    def test_missing_rows_break_a_bout_rather_than_join_it(self) -> None:
        xy = _xy(_track("stationary"))
        speed = np.zeros((N, 1))
        speed[9:11] = np.nan  # splits 20 frames into runs of 9 and 9
        row = FreezingBouts().compute(make_psess(xy=xy, speed=speed)).iloc[0]
        assert row["freezing_bout_count"] == 2
        assert row["total_freezing_duration_s"] == pytest.approx(18 / 25.0)

    def test_animals_are_judged_independently(self) -> None:
        df = _bouts("all_missing", "moving", "stationary").set_index("individual_id")
        assert df.loc[0, UNAVAILABLE].isna().all()
        assert df.loc[1, "freezing_bout_count"] == 0
        assert df.loc[2, "freezing_bout_count"] == 1


class TestTimeBins:
    """A window with nothing estimable follows the whole-session policy."""

    def test_an_empty_window_is_unavailable_and_an_observed_one_is_not(self) -> None:
        from track2data.metrics.binning import bin_windows, slice_psess

        xy = _xy(np.vstack([_track("moving")[:10], np.full((10, 2), np.nan)]))
        psess = make_psess(xy=xy)
        windows = bin_windows(psess, bin_seconds=10 / 25.0)
        assert len(windows) >= 2
        values = [
            PathLength().compute(slice_psess(psess, w.start_row, w.stop_row)).iloc[0][
                "path_length_px"
            ]
            for w in windows
        ]
        assert values[0] > 0
        assert np.isnan(values[-1])


# ── nothing coerces the NaN back to zero on the way out ──────────────────────


@pytest.mark.parametrize("exporter", ["csv_long", "csv_wide", "feather", "excel"])
def test_exports_keep_unavailable_and_zero_apart(
    exporter: str, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.api import Engine
    from track2data.core.models import (
        CalibrationConfig,
        MetricSelection,
        ProjectManifest,
        SessionRef,
    )

    folder = tmp_path / "sess"
    shutil.copytree(tiny_real_session, folder)
    real = Engine.import_ref

    def tampered(self: Engine, ref: SessionRef):  # type: ignore[no-untyped-def]
        session = real(self, ref)
        raw = session.raw_xy.copy()
        raw[:, 0, :] = np.nan  # animal 0: never tracked
        raw[:, 1, :] = (50.0, 50.0)  # animal 1: tracked, never moves
        return session.model_copy(update={"raw_xy": raw})

    monkeypatch.setattr(Engine, "import_ref", tampered)
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p", created_at=now, updated_at=now,
        sessions=[SessionRef(session_id="sess", folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-7"]),
    )
    out = tmp_path / "out"
    result = Engine(manifest).run(out, exporters=[exporter])
    assert result.sessions[0].error is None

    if exporter == "csv_wide":
        df = pd.read_csv(next(out.rglob("trial_summary_wide.csv")))
    elif exporter == "csv_long":
        df = pd.read_csv(next(out.rglob("trial_activity_summary.csv")))
    elif exporter == "feather":
        df = pd.read_feather(next(out.rglob("trial_activity_summary.feather")))
    else:
        df = pd.read_excel(next(out.rglob("*.xlsx")), sheet_name="Activity Summary")
    df = df.set_index("individual_id")
    assert np.isnan(df.loc[0, "path_length_px"])
    # the preprocessing smoother leaves ~1e-14 of round-off on a motionless track
    assert df.loc[1, "path_length_px"] == pytest.approx(0.0, abs=1e-9)
    assert np.isnan(df.loc[0, "freezing_bout_count"])
