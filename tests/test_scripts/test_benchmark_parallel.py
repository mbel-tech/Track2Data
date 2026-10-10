"""scripts/benchmark_parallel.py: the generator is deterministic, loadable, and the CLI reports."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_parallel.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("benchmark_parallel", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_parallel"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_same_seed_gives_identical_trajectories(bench) -> None:
    a = bench.make_trajectories(500, 3, seed=7)
    b = bench.make_trajectories(500, 3, seed=7)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, bench.make_trajectories(500, 3, seed=8))


def test_trajectories_stay_in_the_arena_and_have_gaps(bench) -> None:
    xy = bench.make_trajectories(2000, 4, seed=1)
    finite = xy[np.isfinite(xy)]
    assert finite.min() >= 0 and finite.max() <= bench.SIZE + 160  # the one injected jump
    assert np.isnan(xy).any()
    assert not np.isnan(bench.make_trajectories(2000, 4, seed=1, gaps=False)).any()


def test_written_session_loads_through_the_real_reader(bench, tmp_path) -> None:
    from track2data.api import Engine

    folder = bench.write_session(tmp_path / "s", n_frames=300, n_animals=3, seed=2)
    engine = Engine(bench.build_manifest([folder], identity_switch=False, zones=False))
    session = engine.import_session(folder)
    assert session.raw_xy.shape == (300, 3, 2)
    assert session.n_animals == 3 and session.video.fps == bench.FPS
    assert session.identities_labels == ["1", "2", "3"]


def test_jitter_varies_session_lengths_and_sessions_are_reused(bench, tmp_path) -> None:
    folders = bench.ensure_sessions(tmp_path, 4, 1000, 2, jitter=0.5)
    sizes = {int(f.name.split("_")[2].rstrip("f")) for f in folders}
    assert len(sizes) > 1
    mtimes = [(f / "trajectories" / "trajectories.npy").stat().st_mtime_ns for f in folders]
    again = bench.ensure_sessions(tmp_path, 4, 1000, 2, jitter=0.5)
    assert again == folders
    assert mtimes == [(f / "trajectories" / "trajectories.npy").stat().st_mtime_ns for f in again]


def test_manifest_selects_every_individual_and_group_metric(bench, tmp_path) -> None:
    folder = bench.write_session(tmp_path / "s", 100, 2, 0)
    m = bench.build_manifest([folder], identity_switch=False, zones=True)
    assert len(m.metrics.individual) == 14 and len(m.metrics.group) == 13
    assert len(m.metrics.zone) == 9 and len(m.zones.rois) == 2
    switched = bench.build_manifest([folder], identity_switch=True, zones=False)
    assert switched.preprocess.identity_switch.enabled


def test_cli_end_to_end_reports_speedup_and_stages(bench, tmp_path, capsys) -> None:
    out = tmp_path / "bench.json"
    rc = bench.main(
        [
            "--sessions", "2", "--frames", "150", "--animals", "2", "--workers", "1,2",
            "--workdir", str(tmp_path / "w"), "--json", str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text())
    assert {"environment", "args", "n_sessions", "stage_timings", "runs"} <= set(report)
    runs = report["runs"]
    assert [r["workers"] for r in runs] == [1, 2]
    assert runs[0]["speedup"] == 1.0 and runs[0]["efficiency"] == 1.0
    assert all(r["errors"] == [] and r["wall_s"] > 0 for r in runs)
    assert {"wall_s", "speedup", "efficiency", "peak_rss_mb", "cache"} <= set(runs[1])
    st = report["stage_timings"]
    assert {"import_s", "preprocess_s", "metrics_s", "build_payload_s", "export_s"} <= set(st)
    assert "workers" in capsys.readouterr().out


def test_warm_cache_run_uses_the_cache(bench, tmp_path) -> None:
    out = tmp_path / "b.json"
    bench.main(
        [
            "--sessions", "1", "--frames", "150", "--animals", "2", "--workers", "1",
            "--cache", "off,warm", "--no-stages", "--workdir", str(tmp_path / "w"),
            "--json", str(out),
        ]
    )
    runs = json.loads(out.read_text())["runs"]
    assert [r["cache"] for r in runs] == ["off", "warm"]
    # the priming run wrote a preprocessed session the timed run then read
    assert list((tmp_path / "w").glob("t2d_bench_cache_*/*/*.pkl"))
