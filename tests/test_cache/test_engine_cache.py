"""PERF-02: Engine reuses preprocessed sessions from the on-disk cache."""

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
    SmoothCfg,
)


def _manifest(folder: Path, **kw) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=folder.name, folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"]),
        **kw,
    )


@pytest.fixture()
def folder(tiny_real_session: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "sess"
    shutil.copytree(tiny_real_session, dst)
    return dst


@pytest.fixture()
def pp_calls(monkeypatch):
    import track2data.preprocess.pipeline as pl

    calls: list[int] = []
    real = pl.run

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(pl, "run", counting)
    return calls


def _run(manifest, cache_dir, out):
    return Engine(manifest, cache_dir=cache_dir).run(out, exporters=["csv_long"])


def test_second_run_hits_the_cache_and_matches(folder, tmp_path, pp_calls) -> None:
    cache = tmp_path / "cache"
    r1 = _run(_manifest(folder), cache, tmp_path / "o1")
    assert len(pp_calls) == 1
    r2 = _run(_manifest(folder), cache, tmp_path / "o2")
    assert len(pp_calls) == 1  # no second preprocess
    assert not r1.sessions[0].error and not r2.sessions[0].error
    a = pd.read_csv(tmp_path / "o1" / folder.name / "master_fish_by_frame.csv")
    b = pd.read_csv(tmp_path / "o2" / folder.name / "master_fish_by_frame.csv")
    pd.testing.assert_frame_equal(a, b)


def test_changed_preprocess_config_misses(folder, tmp_path, pp_calls) -> None:
    cache = tmp_path / "cache"
    _run(_manifest(folder), cache, tmp_path / "o1")
    m2 = _manifest(folder)
    m2 = m2.model_copy(
        update={
            "preprocess": m2.preprocess.model_copy(
                update={"smoothing": SmoothCfg(method="moving_avg", window=7)}
            )
        }
    )
    _run(m2, cache, tmp_path / "o2")
    assert len(pp_calls) == 2


def test_changed_calibration_misses(folder, tmp_path, pp_calls) -> None:
    cache = tmp_path / "cache"
    _run(_manifest(folder), cache, tmp_path / "o1")
    m2 = _manifest(folder).model_copy(
        update={"calibration": CalibrationConfig(mode="scalar", px_per_cm=20.0)}
    )
    _run(m2, cache, tmp_path / "o2")
    assert len(pp_calls) == 2


def test_modified_session_file_misses(folder, tmp_path, pp_calls) -> None:
    import os

    cache = tmp_path / "cache"
    _run(_manifest(folder), cache, tmp_path / "o1")
    victim = next(p for p in sorted(folder.rglob("*")) if p.is_file())
    st = victim.stat()
    os.utime(victim, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    _run(_manifest(folder), cache, tmp_path / "o2")
    assert len(pp_calls) == 2


def test_no_cache_dir_never_caches(folder, tmp_path, pp_calls) -> None:
    Engine(_manifest(folder)).run(tmp_path / "o1", exporters=["csv_long"])
    Engine(_manifest(folder)).run(tmp_path / "o2", exporters=["csv_long"])
    assert len(pp_calls) == 2


def test_corrupt_cache_entry_falls_back_to_recompute(folder, tmp_path, pp_calls) -> None:
    cache = tmp_path / "cache"
    _run(_manifest(folder), cache, tmp_path / "o1")
    for f in cache.rglob("*.pkl"):
        f.write_bytes(b"junk")
    r = _run(_manifest(folder), cache, tmp_path / "o2")
    assert len(pp_calls) == 2
    assert not r.sessions[0].error
