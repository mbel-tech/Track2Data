"""Engine-level timepoint binning (MetricSelection.timepoint_minutes)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track2data.api import Engine
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    Session,
    SessionRef,
    VideoInfo,
    ZoneSet,
)

FPS, N_FRAMES = 25.0, 1500  # 60 s


def _session(n_frames: int = N_FRAMES, n_animals: int = 2) -> Session:
    rng = np.random.default_rng(3)
    steps = rng.normal(0, 4, (n_frames, n_animals, 2))
    xy = 250 + np.cumsum(steps, axis=0)
    xy = np.clip(xy, 20, 480)
    return Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="t",
        video=VideoInfo(fps=FPS, n_frames=n_frames, width_px=500, height_px=500),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )


def _engine(minutes: float | None, individual=("IL-1", "IL-2", "IL-4"), group=(), zone=(),
            diagnostic=(), session: Session | None = None):
    now = datetime.now(tz=UTC)
    zones = ZoneSet(
        rois=[
            ROI(name="left", vertices=[(0, 0), (250, 0), (250, 500), (0, 500)]),
            ROI(name="right", vertices=[(250, 0), (500, 0), (500, 500), (250, 500)]),
        ]
    )
    m = ProjectManifest(
        project_name="p", created_at=now, updated_at=now,
        sessions=[SessionRef(session_id="s", folder=Path("/tmp/s"), sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        zones=zones,
        metrics=MetricSelection(
            individual=list(individual), group=list(group), zone=list(zone),
            diagnostic=list(diagnostic), timepoint_minutes=minutes,
        ),
    )
    eng = Engine(m)
    psess = eng.preprocess(session or _session())
    return eng, psess


BIN_COLS = ["bin_index", "bin_start_s", "bin_end_s"]


def test_binned_results_have_one_row_per_animal_per_bin() -> None:
    eng, psess = _engine(0.25)  # 15 s bins -> 4 bins over 60 s
    out = eng.compute_metrics(psess)
    df = out["IL-1"]
    assert list(df["bin_index"].unique()) == [0, 1, 2, 3]
    assert len(df) == 2 * 4
    assert df["bin_start_s"].tolist()[:2] == [0.0, 0.0]
    assert set(df["bin_end_s"]) == {15.0, 30.0, 45.0, 60.0}
    assert (df["session_id"] == "s").all()


def test_unbinned_when_not_requested() -> None:
    for minutes in (None, 0):
        eng, psess = _engine(minutes)
        df = eng.compute_metrics(psess)["IL-1"]
        assert "bin_index" not in df.columns and len(df) == 2


def test_one_bin_covering_the_session_equals_the_unbinned_result() -> None:
    ids = ("IL-1", "IL-2", "IL-3", "IL-4", "IL-6", "IL-7", "IL-8", "IL-10", "IL-11", "IL-14")
    zone = ("Z-1", "Z-2", "Z-3", "Z-4", "Z-5", "Z-6", "Z-7", "Z-8", "Z-9")
    group = ("GL-1", "GL-2", "GL-4", "GL-5", "GL-6", "GL-7", "GL-9", "GL-10")
    whole_eng, psess = _engine(None, ids, group, zone)
    whole = whole_eng.compute_metrics(psess)
    eng, psess2 = _engine(60, ids, group, zone)  # 60 min bins -> a single bin
    binned = eng.compute_metrics(psess2)
    for mid, df in whole.items():
        if mid.startswith("D-"):
            continue
        b = binned[mid]
        assert set(BIN_COLS) <= set(b.columns), mid
        assert (b["bin_index"] == 0).all(), mid
        pd.testing.assert_frame_equal(
            b.drop(columns=BIN_COLS).reset_index(drop=True),
            df.reset_index(drop=True),
            check_dtype=False,
            obj=mid,
        )


def test_additive_metrics_sum_across_bins() -> None:
    eng, psess = _engine(0.25, ("IL-1",), zone=("Z-1",))
    whole_eng, whole_psess = _engine(None, ("IL-1",), zone=("Z-1",))
    whole = whole_eng.compute_metrics(whole_psess)
    out = eng.compute_metrics(psess)
    # path length loses only the boundary steps between bins
    summed = out["IL-1"].groupby("individual_id")["path_length_px"].sum()
    total = whole["IL-1"].set_index("individual_id")["path_length_px"]
    assert (summed <= total + 1e-9).all()
    assert (summed >= total * 0.9).all()
    # time in zone is exactly additive
    z_b = out["Z-1"].groupby(["zone_name", "individual_id"])["time_s"].sum()
    z_w = whole["Z-1"].set_index(["zone_name", "individual_id"])["time_s"]
    pd.testing.assert_series_equal(z_b.sort_index(), z_w.sort_index(), check_names=False)


def test_activity_threshold_is_resolved_on_the_whole_session() -> None:
    eng, psess = _engine(0.25, ("IL-4", "IL-7"))
    out = eng.compute_metrics(psess)
    whole_eng, whole_psess = _engine(None, ("IL-4", "IL-7"))
    whole = whole_eng.compute_metrics(whole_psess)
    t_whole = whole["IL-4"]["threshold_px_s"].iloc[0]
    assert (out["IL-4"]["threshold_px_s"] == t_whole).all()
    assert (
        out["IL-7"]["min_bout_frames_used"] == whole["IL-7"]["min_bout_frames_used"].iloc[0]
    ).all()


def test_derived_bout_criterion_is_resolved_once_not_per_window() -> None:
    from track2data.metrics import get

    il7 = get("IL-7")
    _eng, psess = _engine(None, ("IL-7",))
    cfg = {"derive_bout_criterion": True}
    resolved = il7.resolve_for_windows(psess, cfg)
    whole = il7().compute(psess, cfg)
    assert resolved["_bout"] == (
        int(whole["min_bout_frames_used"].iloc[0]), whole["bout_criterion_effective"].iloc[0]
    )
    # a window given the resolved value reports it verbatim
    from track2data.metrics.binning import bin_windows, slice_psess

    w = bin_windows(psess, 15.0)[1]
    part = il7().compute(slice_psess(psess, w.start_row, w.stop_row), {**cfg, **resolved})
    assert part["min_bout_frames_used"].iloc[0] == whole["min_bout_frames_used"].iloc[0]
    assert part["bout_criterion_effective"].iloc[0] == whole["bout_criterion_effective"].iloc[0]


def test_non_window_safe_metrics_stay_whole_session_with_empty_bin_columns() -> None:
    eng, psess = _engine(0.25, ("IL-1", "IL-5", "IL-9"))
    out = eng.compute_metrics(psess)
    for mid in ("IL-5", "IL-9"):
        df = out[mid]
        assert len(df) == 2, mid
        assert df["bin_index"].isna().all(), mid
    assert out["IL-1"]["bin_index"].notna().all()


def test_diagnostics_are_never_binned() -> None:
    eng, psess = _engine(0.25, ("IL-1",))
    out = eng.compute_metrics(psess)
    for mid, df in out.items():
        if mid.startswith("D-"):
            assert "bin_index" not in df.columns, mid


def test_z5_event_times_are_offset_into_the_session() -> None:
    zone = ("Z-5",)
    whole_eng, whole_psess = _engine(None, (), zone=zone)
    whole = whole_eng.compute_metrics(whole_psess)["Z-5"]
    eng, psess = _engine(0.25, (), zone=zone)
    binned = eng.compute_metrics(psess)["Z-5"]
    assert not whole.empty and not binned.empty
    # every binned event lies inside its own bin on the session time axis
    for _, row in binned.iterrows():
        assert row["bin_start_s"] <= row["t_s"] <= row["bin_end_s"] + 1 / FPS


def test_group_and_pooled_zone_metrics_are_binned_too() -> None:
    eng, psess = _engine(0.5, (), group=("GL-1",), zone=("Z-1",))
    out = eng.compute_metrics(psess)
    assert list(out["GL-1"]["bin_index"]) == [0, 1]
    assert "individual_id" in out["Z-1"].columns and set(out["Z-1"]["bin_index"]) == {0, 1}


def test_metadata_timepoint_and_bin_index_coexist(tmp_path: Path) -> None:
    eng, psess = _engine(0.5, ("IL-1",))
    eng._metadata_fields_for = lambda sid: {"timepoint": "T1", "treatment": "ctrl"}  # type: ignore[method-assign]
    df = eng.compute_metrics(psess)["IL-1"]
    assert set(df["timepoint"]) == {"T1"} and set(df["bin_index"]) == {0, 1}


def test_fish_by_frame_gets_a_bin_index_column_only_when_binned() -> None:
    eng, psess = _engine(0.5)
    fbf = eng.build_fish_by_frame(psess)
    assert "bin_index" in fbf.columns
    assert fbf.groupby("bin_index")["time_s"].min().tolist() == [0.0, 30.0]
    plain_eng, plain_psess = _engine(None)
    assert "bin_index" not in plain_eng.build_fish_by_frame(plain_psess).columns


def test_cancel_check_is_polled_between_windows() -> None:
    from track2data.core.progress import OperationCancelled

    eng, psess = _engine(0.25, ("IL-1",))
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        if len(calls) > 3:
            raise OperationCancelled()

    eng._cancel_check = check
    with pytest.raises(OperationCancelled):
        eng.compute_metrics(psess)


def test_a_failing_window_does_not_lose_the_other_metrics(monkeypatch) -> None:
    from track2data.metrics import get

    cls = get("IL-2")
    def boom(self, s, cfg=None):
        raise ValueError("x")

    monkeypatch.setattr(cls, "compute", boom)
    eng, psess = _engine(0.25, ("IL-1", "IL-2"))
    out = eng.compute_metrics(psess)
    assert "IL-1" in out and "IL-2" not in out


_DEBOUNCE = [("Z-3", "min_visit_frames_used"), ("Z-4", "min_dwell_frames_used")]


@pytest.mark.parametrize("mid,col", _DEBOUNCE)
def test_zone_debounce_criterion_is_the_same_in_every_bin(mid: str, col: str) -> None:
    eng, psess = _engine(0.25, (), zone=(mid,))
    cfg = {mid: {"derive_bout_criterion": True}}
    sel = eng._manifest.metrics.model_copy(update={"config": cfg})
    eng._manifest = eng._manifest.model_copy(update={"metrics": sel})
    binned = eng.compute_metrics(psess)[mid]

    whole_eng, whole_psess = _engine(None, (), zone=(mid,))
    unbinned = sel.model_copy(update={"timepoint_minutes": None})
    whole_eng._manifest = whole_eng._manifest.model_copy(update={"metrics": unbinned})
    whole = whole_eng.compute_metrics(whole_psess)[mid]
    assert set(binned[col]) == set(whole[col])
    assert set(binned["bout_criterion_effective"]) == set(whole["bout_criterion_effective"])


def test_binned_exports_do_not_multiply_rows(tmp_path: Path, tiny_real_session: Path) -> None:
    import shutil

    folder = tmp_path / "sess"
    shutil.copytree(tiny_real_session, folder)
    now = datetime.now(tz=UTC)
    m = ProjectManifest(
        project_name="p", created_at=now, updated_at=now,
        sessions=[SessionRef(session_id="sess", folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(
            individual=["IL-1", "IL-2", "IL-5"], group=["GL-1"], timepoint_minutes=0.004
        ),  # 0.24 s = 6 frames: the 10-frame fixture splits into 2 bins
    )
    out = tmp_path / "out"
    res = Engine(m).run(out, exporters=["csv_long", "csv_wide", "feather"])
    assert res.sessions[0].error is None, res.sessions[0].error
    d = out / "sess"

    long = pd.read_csv(d / "trial_activity_summary.csv")
    binned = long[long["bin_index"].notna()]
    whole = long[long["bin_index"].isna()]
    assert len(binned) == 2 * 2          # 2 animals x 2 bins, IL-1 + IL-2 widened
    assert len(whole) == 2               # IL-5 stays one whole-session row per animal
    assert binned["path_length_px"].notna().all() and binned["mean_speed_px_s"].notna().all()
    assert whole["path_length_px"].isna().all()

    wide = pd.read_csv(d / "trial_summary_wide.csv")
    assert len(wide) == len(long)
    feather = pd.read_feather(d / "trial_activity_summary.feather")
    assert len(feather) == len(long)

    frames = pd.read_csv(d / "master_fish_by_frame.csv")
    assert set(frames["bin_index"]) == {0, 1}
    group = pd.read_csv(d / "group_dynamics_summary.csv")
    assert list(group["bin_index"]) == [0, 1]
