"""PERF-01 / GUI-05: parallel Engine.run and fine-grained cancellation."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)
from track2data.core.progress import OperationCancelled, ProgressEvent


def _manifest(folders: list[Path], metrics: MetricSelection | None = None) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=f.name, folder=f, sha256="x") for f in folders],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=metrics or MetricSelection(individual=["IL-1", "IL-2"]),
    )


@pytest.fixture()
def folders(tiny_real_session: Path, tmp_path: Path) -> list[Path]:
    out = []
    for name in ("sess_a", "sess_b", "sess_c"):
        dst = tmp_path / name
        shutil.copytree(tiny_real_session, dst)
        out.append(dst)
    return out


def test_parallel_matches_sequential(folders, tmp_path) -> None:
    m = _manifest(folders)
    Engine(m).run(tmp_path / "seq", exporters=["csv_long"])
    par = Engine(m).run(tmp_path / "par", exporters=["csv_long"], n_workers=2)

    assert [s.session_id for s in par.sessions] == [f.name for f in folders]
    assert all(s.error is None for s in par.sessions), [s.error for s in par.sessions]
    for f in folders:
        for name in ("master_fish_by_frame.csv", "trial_activity_summary.csv"):
            a = pd.read_csv(tmp_path / "seq" / f.name / name)
            b = pd.read_csv(tmp_path / "par" / f.name / name)
            pd.testing.assert_frame_equal(a, b)


def test_parallel_forwards_progress_events(folders, tmp_path) -> None:
    events: list[ProgressEvent] = []
    Engine(_manifest(folders)).run(
        tmp_path / "o", exporters=["csv_long"], n_workers=2, progress=events.append
    )
    assert events[0].stage == "run" and events[0].message == "Run started"
    assert events[-1].stage == "run" and events[-1].message == "Run complete"
    done = [e for e in events if e.stage == "session"]
    assert sorted(e.session_id for e in done) == sorted(f.name for f in folders)
    assert [e.current for e in done] == [1, 2, 3]
    assert {e.stage for e in events} >= {"import", "preprocess", "metrics", "export"}


def test_parallel_run_can_be_cancelled(folders, tmp_path) -> None:
    def cancel_on_first_session_event(event: ProgressEvent) -> None:
        if event.stage in {"import", "preprocess"}:
            raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        Engine(_manifest(folders)).run(
            tmp_path / "o",
            exporters=["csv_long"],
            n_workers=2,
            progress=cancel_on_first_session_event,
        )


def test_single_session_or_one_worker_stays_sequential(folders, tmp_path, monkeypatch) -> None:
    import track2data.api as api

    def boom(*a, **k):
        raise AssertionError("pool must not be created")

    monkeypatch.setattr(api, "ProcessPoolExecutor", boom, raising=False)
    Engine(_manifest(folders[:1])).run(tmp_path / "a", exporters=["csv_long"], n_workers=4)
    Engine(_manifest(folders)).run(tmp_path / "b", exporters=["csv_long"], n_workers=1)


# ── GUI-05: cancellation inside a session ────────────────────────────────────


def test_cancel_is_checked_between_metrics(folders, tmp_path, monkeypatch) -> None:
    computed: list[str] = []
    from track2data import metrics as registry

    for mid in ("IL-1", "IL-2", "IL-3"):
        cls = registry.get(mid)
        real = cls.compute

        def spy(self, session, cfg=None, _real=real, _mid=mid):
            computed.append(_mid)
            return _real(self, session, cfg)

        monkeypatch.setattr(cls, "compute", spy)

    calls = 0

    def cancel_after_first_metric() -> None:
        nonlocal calls
        if computed:  # IL-1 has run
            calls += 1
            raise OperationCancelled()

    m = _manifest(folders[:1], MetricSelection(individual=["IL-1", "IL-2", "IL-3"]))
    with pytest.raises(OperationCancelled):
        Engine(m).run(
            tmp_path / "o", exporters=["csv_long"], cancel_check=cancel_after_first_metric
        )
    assert computed == ["IL-1"]  # IL-2 / IL-3 never started
    assert calls == 1


def test_cancel_is_checked_between_preprocess_steps(folders, tmp_path, monkeypatch) -> None:
    import track2data.preprocess.pipeline as pl

    ran: list[str] = []
    real_fill = pl.fill_gaps

    def spy_fill(*a, **k):
        ran.append("gap")
        return real_fill(*a, **k)

    monkeypatch.setattr(pl, "fill_gaps", spy_fill)

    def cancel_once_gap_fill_ran() -> None:
        if ran:
            raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        Engine(_manifest(folders[:1])).run(
            tmp_path / "o", exporters=["csv_long"], cancel_check=cancel_once_gap_fill_ran
        )
    assert ran == ["gap"]  # stopped before jump detection and the rest


def test_parallel_run_notices_cancel_check_without_any_events(folders, tmp_path) -> None:
    def always() -> None:
        raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        Engine(_manifest(folders)).run(
            tmp_path / "o", exporters=["csv_long"], n_workers=2, cancel_check=always
        )


def test_n_workers_uses_a_spawn_process_pool(folders, tmp_path, monkeypatch) -> None:
    import track2data.api as api

    created: list[dict] = []
    real = api.ProcessPoolExecutor

    def spy(*a, **k):
        created.append(k)
        return real(*a, **k)

    monkeypatch.setattr(api, "ProcessPoolExecutor", spy)
    Engine(_manifest(folders)).run(tmp_path / "o", exporters=["csv_long"], n_workers=2)
    assert len(created) == 1
    assert created[0]["max_workers"] == 2
    assert created[0]["mp_context"].get_start_method() == "spawn"
