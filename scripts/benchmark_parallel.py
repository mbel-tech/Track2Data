#!/usr/bin/env python
"""Benchmark ``Engine.run`` for sequential vs parallel runs on synthetic sessions.

Why: parallel runs (D-020) were implemented and tested for correctness but never
timed on realistic sessions. This script produces that evidence; it makes no
claim about speed-up by itself. Numbers from a small CI runner or a laptop say
little about a 32-core workstation, so record ``environment`` with every result
and run it on the machine and session sizes you care about.

    python scripts/benchmark_parallel.py --sessions 8 --frames 108000 --animals 10 \\
        --workers 1,2,4,8 --cache off,cold,warm --json bench.json

Each (workers, cache) configuration runs in a fresh subprocess so the reported
peak memory belongs to that configuration alone. Sessions are written once to
``--workdir`` (reused between runs, so keep it on a fast disk); only
``trajectories/trajectories.npy`` plus a small ``session.json`` are needed by
the reader. Real folders can be used instead with ``--sessions-dir``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

FPS = 25.0
SIZE = 1000


# ── synthetic sessions ──────────────────────────────────────────────────────


def make_trajectories(
    n_frames: int, n_animals: int, seed: int, *, gaps: bool = True
) -> np.ndarray:
    """Seeded random walks inside the arena, with a few tracking gaps and jumps.

    Pure random walks are more ambiguous than real tracks (animals cross far
    more often), so identity-switch timing from this data is pessimistic.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 4.0, size=(n_frames, n_animals, 2))
    xy = np.empty((n_frames, n_animals, 2))
    xy[0] = rng.uniform(100, SIZE - 100, size=(n_animals, 2))
    # reflect at the walls without a Python loop over frames: fold the free walk
    free = xy[0] + np.cumsum(steps, axis=0)
    period = 2.0 * (SIZE - 200)
    folded = np.abs(((free - 100) % period) - (SIZE - 200)) + 100
    xy[:] = SIZE - folded
    if gaps and n_frames > 200:
        for a in range(n_animals):
            start = int(rng.integers(50, n_frames - 100))
            xy[start : start + int(rng.integers(3, 20)), a] = np.nan
        jump_frame = int(rng.integers(50, n_frames - 50))
        xy[jump_frame, 0] += 150.0
    return xy


def write_session(folder: Path, n_frames: int, n_animals: int, seed: int) -> Path:
    """Write the minimum an idtracker.ai 6.x npy session needs."""
    traj_dir = folder / "trajectories"
    traj_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "trajectories": make_trajectories(n_frames, n_animals, seed),
        "id_probabilities": np.full((n_frames, n_animals, 1), 0.95),
        "version": "6.0.13",
        "height": SIZE,
        "width": SIZE,
        "video_paths": [],
        "frames_per_second": FPS,
        "body_length": 30.0,
        "setup_points": {},
        "identities_labels": [str(i + 1) for i in range(n_animals)],
        "identities_groups": [],
        "length_unit": None,
    }
    np.save(traj_dir / "trajectories.npy", payload, allow_pickle=True)
    (folder / "session.json").write_text(
        json.dumps(
            {
                "version": "6.0.13",
                "number_of_animals": n_animals,
                "frames_per_second": FPS,
                "number_of_frames": n_frames,
                "width": SIZE,
                "height": SIZE,
                "track_wo_identities": False,
            }
        ),
        encoding="utf-8",
    )
    return folder


def ensure_sessions(
    workdir: Path, n_sessions: int, n_frames: int, n_animals: int, jitter: float
) -> list[Path]:
    """Create (or reuse) ``n_sessions`` folders; ``jitter`` varies their lengths."""
    rng = np.random.default_rng(12345)
    folders = []
    for i in range(n_sessions):
        frames = max(60, int(n_frames * (1.0 + jitter * rng.uniform(-1.0, 1.0))))
        folder = workdir / f"bench_{i:03d}_{frames}f_{n_animals}a"
        if not (folder / "trajectories" / "trajectories.npy").exists():
            write_session(folder, frames, n_animals, seed=i)
        folders.append(folder)
    return folders


# ── manifest ────────────────────────────────────────────────────────────────


def build_manifest(folders: list[Path], *, identity_switch: bool, zones: bool) -> Any:
    from track2data import metrics
    from track2data.core.models import (
        ROI,
        CalibrationConfig,
        IdSwitchCfg,
        MetricSelection,
        PreprocessConfig,
        ProjectManifest,
        SceneConfig,
        SecurityConfig,
        SessionRef,
        ZoneSet,
    )

    metrics._load_builtins()
    individual = sorted(c.id for c in metrics.list_for_level("individual"))
    group = sorted(c.id for c in metrics.list_for_level("group"))
    zone_ids: list[str] = []
    zone_set = ZoneSet()
    if zones:
        zone_ids = sorted(c.id for c in metrics.list_for_level("zone"))
        half = SIZE / 2
        zone_set = ZoneSet(
            rois=[
                ROI(name="left", vertices=[(0, 0), (half, 0), (half, SIZE), (0, SIZE)]),
                ROI(name="right", vertices=[(half, 0), (SIZE, 0), (SIZE, SIZE), (half, SIZE)]),
            ]
        )
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="benchmark",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=f.name, folder=f, sha256="x") for f in folders],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        # write_session() pickles its own synthetic trajectories, so the engine's pickle
        # gate would otherwise refuse every session: this project trusts files this very
        # script wrote.
        security=SecurityConfig(allow_pickle_trajectories=True),
        zones=zone_set,
        # IL-15 only runs for a declared side view; the benchmark selects every metric.
        scene=SceneConfig(camera_view="side"),
        preprocess=PreprocessConfig(identity_switch=IdSwitchCfg(enabled=identity_switch)),
        metrics=MetricSelection(individual=individual, group=group, zone=zone_ids),
    )


# ── measuring ───────────────────────────────────────────────────────────────


def peak_rss_mb() -> dict[str, float | None]:
    """Peak resident memory of this process and of its (reaped) children, in MB.

    ``children`` is the largest single child, not a sum. None where the stdlib
    ``resource`` module does not exist (Windows).
    """
    try:
        import resource
    except ImportError:
        return {"self": None, "children": None}
    scale = 1.0 / (1024.0 * 1024.0) if sys.platform == "darwin" else 1.0 / 1024.0
    return {
        "self": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale,
        "children": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * scale,
    }


def single_run(args: argparse.Namespace) -> dict[str, Any]:
    """One timed ``Engine.run`` (executed inside a fresh subprocess)."""
    from track2data.api import Engine

    folders = [Path(p) for p in args._folders]
    manifest = build_manifest(folders, identity_switch=args.identity_switch, zones=args.zones)
    cache_dir = Path(args._cache_dir) if args._cache_dir else None
    out_dir = Path(tempfile.mkdtemp(prefix="t2d_bench_out_"))
    exporters = [e for e in args.exporters.split(",") if e]
    engine = Engine(manifest, cache_dir=cache_dir)
    start = time.perf_counter()
    result = engine.run(out_dir, exporters=exporters, n_workers=args._workers)
    wall = time.perf_counter() - start
    errors = [s.error for s in result.sessions if s.error]
    return {"wall_s": wall, "errors": errors, "peak_rss_mb": peak_rss_mb()}


def stage_timings(args: argparse.Namespace, folder: Path) -> dict[str, Any]:
    """Sequential per-stage and per-metric cost for one session."""
    from track2data import metrics
    from track2data.api import Engine

    manifest = build_manifest([folder], identity_switch=args.identity_switch, zones=args.zones)
    engine = Engine(manifest)
    out: dict[str, Any] = {"session": folder.name}

    def timed(label: str, fn: Any) -> Any:
        t0 = time.perf_counter()
        value = fn()
        out[label] = round(time.perf_counter() - t0, 4)
        return value

    session = timed("import_s", lambda: engine.import_session(folder))
    psess = timed("preprocess_s", lambda: engine.preprocess(session))
    per_metric: dict[str, float] = {}
    for mid in [*manifest.metrics.individual, *manifest.metrics.group, *manifest.metrics.zone]:
        cls = metrics.get(mid)
        if cls is None:
            continue
        cfg = engine._effective_cfg(cls, psess)
        t0 = time.perf_counter()
        try:
            cls().compute(psess, cfg)
        except Exception:  # a metric that cannot run on this data is not a benchmark failure
            continue
        per_metric[mid] = round(time.perf_counter() - t0, 4)
    out["metrics_s"] = round(sum(per_metric.values()), 4)
    out["per_metric_s"] = dict(sorted(per_metric.items(), key=lambda kv: -kv[1]))
    results = engine.compute_metrics(psess)
    payload = timed("build_payload_s", lambda: engine.build_payload(psess, results))
    out_dir = Path(tempfile.mkdtemp(prefix="t2d_bench_stage_"))
    timed("export_s", lambda: engine.export(payload, out_dir, ["csv_long"]))
    return out


def _spawn_single(
    args: argparse.Namespace, folders: list[Path], workers: int, cache_dir: Path | None
) -> dict[str, Any]:
    cmd = [
        sys.executable, str(Path(__file__).resolve()), "--_single",
        "--_workers", str(workers), "--exporters", args.exporters,
        "--_folders", *map(str, folders),
    ]
    if cache_dir is not None:
        cmd += ["--_cache-dir", str(cache_dir)]
    if args.identity_switch:
        cmd.append("--identity-switch")
    if args.zones:
        cmd.append("--zones")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"benchmark subprocess failed:\n{proc.stderr[-2000:]}")
    line = next(ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{"))
    return json.loads(line)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="t2d_bench_"))
    workdir.mkdir(parents=True, exist_ok=True)
    if args.sessions_dir:
        folders = sorted(p for p in Path(args.sessions_dir).iterdir() if p.is_dir())
    else:
        folders = ensure_sessions(workdir, args.sessions, args.frames, args.animals, args.jitter)
    workers_list = [int(w) for w in args.workers.split(",")]
    cache_modes = [c for c in args.cache.split(",") if c]

    report: dict[str, Any] = {
        "environment": {
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "started": datetime.now(tz=UTC).isoformat(),
        },
        "args": {k: v for k, v in vars(args).items() if not k.startswith("_")},
        "n_sessions": len(folders),
        "stage_timings": stage_timings(args, folders[0]) if not args.no_stages else None,
        "runs": [],
    }
    for cache_mode in cache_modes:
        baseline: float | None = None
        for workers in workers_list:
            walls: list[float] = []
            rss: dict[str, float | None] = {}
            errors: list[str] = []
            for _ in range(args.repeat):
                cache_dir = None
                if cache_mode != "off":
                    cache_dir = Path(tempfile.mkdtemp(prefix="t2d_bench_cache_", dir=workdir))
                    if cache_mode == "warm":
                        _spawn_single(args, folders, 1, cache_dir)  # fill the cache, untimed
                res = _spawn_single(args, folders, workers, cache_dir)
                walls.append(res["wall_s"])
                rss = res["peak_rss_mb"]
                errors += res["errors"]
            median = statistics.median(walls)
            if baseline is None:
                baseline = median
            report["runs"].append(
                {
                    "cache": cache_mode,
                    "workers": workers,
                    "wall_s": round(median, 3),
                    "all_wall_s": [round(w, 3) for w in walls],
                    "speedup": round(baseline / median, 3) if median else None,
                    "efficiency": round(baseline / median / workers, 3) if median else None,
                    "peak_rss_mb": rss,
                    "errors": errors,
                }
            )
    return report


def format_table(report: dict[str, Any]) -> str:
    lines = [
        f"sessions={report['n_sessions']}  cpu_count={report['environment']['cpu_count']}",
        f"{'cache':<6} {'workers':>7} {'wall_s':>9} {'speedup':>8} {'effic.':>7} "
        f"{'rss_self_MB':>12} {'rss_child_MB':>13}",
    ]
    for r in report["runs"]:
        rss = r["peak_rss_mb"]
        fmt = lambda v: "n/a" if v is None else f"{v:.0f}"  # noqa: E731
        lines.append(
            f"{r['cache']:<6} {r['workers']:>7} {r['wall_s']:>9.2f} {r['speedup']:>8.2f} "
            f"{r['efficiency']:>7.2f} {fmt(rss.get('self')):>12} {fmt(rss.get('children')):>13}"
        )
    st = report.get("stage_timings")
    if st:
        lines.append("")
        lines.append(
            f"one session ({st['session']}), sequential: import {st['import_s']}s, "
            f"preprocess {st['preprocess_s']}s, metrics {st['metrics_s']}s, "
            f"build_payload {st['build_payload_s']}s, export {st['export_s']}s"
        )
        top = list(st["per_metric_s"].items())[:5]
        lines.append("slowest metrics: " + ", ".join(f"{k} {v}s" for k, v in top))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sessions", type=int, default=4, help="number of synthetic sessions")
    ap.add_argument("--frames", type=int, default=20000, help="frames per session")
    ap.add_argument("--animals", type=int, default=10)
    ap.add_argument("--jitter", type=float, default=0.0,
                    help="vary session length by +/- this fraction (exposes load imbalance)")
    ap.add_argument("--workers", default="1,2,4", help="comma list of n_workers to try")
    ap.add_argument("--cache", default="off", help="comma list of: off, cold, warm")
    ap.add_argument("--exporters", default="csv_long", help="comma list (excel is slow)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--identity-switch", action="store_true",
                    help="enable identity-switch correction (slow, opt-in in the app)")
    ap.add_argument("--zones", action="store_true", help="add two zones and the zone metrics")
    ap.add_argument("--sessions-dir", help="use these real session folders instead of synthetic")
    ap.add_argument("--workdir", help="where synthetic sessions are written and reused")
    ap.add_argument("--no-stages", action="store_true", help="skip the per-stage breakdown")
    ap.add_argument("--json", help="write the full report to this file")
    ap.add_argument("--_single", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--_workers", type=int, default=1, help=argparse.SUPPRESS)
    ap.add_argument("--_cache-dir", dest="_cache_dir", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--_folders", nargs="*", default=[], help=argparse.SUPPRESS)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args._single:
        print(json.dumps(single_run(args)))
        return 0
    report = run_benchmark(args)
    print(format_table(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
