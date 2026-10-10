"""Running a 3-D project: one run unit per fusable pair, serially and across worker processes."""

from __future__ import annotations

import re
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from track2data.api import Engine
from track2data.core.models import ProjectMode
from track2data.core.progress import OperationCancelled, ProgressEvent
from track2data.core.runplan import FusionRunInfo

from .scene import DEPTHS, TANK_CM, build_scene, fusion_settings, pair

EXPORTERS = ["csv_long", "readme"]


def _skips(result: Any) -> list[tuple[str, str]]:
    return [(s.session_id, s.reason) for s in result.skipped]


_STAMP = re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+\+00:00")


def _files(root: Path) -> dict[str, bytes]:
    """Every written file's bytes, with the "generated at" time stamps masked (the only thing two
    runs of the same project may differ in)."""
    return {
        str(p.relative_to(root)): _STAMP.sub(b"<time>", p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_serial_run_writes_one_folder_per_pair(tmp_path: Path) -> None:
    engine = Engine(build_scene(tmp_path / "data"))
    out = tmp_path / "out"
    result = engine.run(out, exporters=EXPORTERS)

    assert [r.session_id for r in result.sessions] == ["t1+s1", "t2+s2"]
    assert [r.error for r in result.sessions] == [None, None]
    assert (out / "t1+s1").is_dir() and (out / "t2+s2").is_dir()
    for name in ("t1", "s1", "t2", "s2", "lone"):
        assert not (out / name).exists()
    assert _skips(result) == [("lone", "not in a fusable pair")]

    il15 = result.sessions[0].metric_previews["IL-15"]
    assert set(il15["depth_extent_source"]) == {"fusion"}
    np.testing.assert_allclose(il15["mean_depth_fraction"], DEPTHS)
    np.testing.assert_allclose(il15["mean_depth_cm"], np.array(DEPTHS) * TANK_CM)
    assert set(il15["session_id"]) == {"t1+s1"}


def test_pair_units_carry_the_fusion_provenance(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data")
    result = Engine(manifest).run(tmp_path / "out", exporters=EXPORTERS)
    info = result.sessions[0].fusion
    assert isinstance(info, FusionRunInfo)
    fs = manifest.view_pairs[0].fusion
    assert info.unit_kind == "pair"
    assert (info.top_session_id, info.side_session_id) == ("t1", "s1")
    assert info.fusion_frame_offset == fs.frame_offset
    assert info.fusion_axis == fs.horizontal_axis
    assert info.fusion_flip == fs.flip
    assert info.fusion_surface_row == fs.surface_row
    assert info.fusion_floor_row == fs.floor_row
    assert info.fusion_tank_height_cm == fs.tank_height_cm
    assert info.fusion_overlap_frames == 100
    assert info.fusion_fused_fish == 3
    assert info.fusion_unmatched_top == ""
    assert info.fusion_unmatched_side == ""
    assert info.fusion_outside_column == 0
    assert info.fusion_agreement_rms_cm == pytest.approx(0.0, abs=1e-9)
    assert info.fusion_agreement_warning is False
    assert info.fusion_agreement_skipped is None
    # exactly the provenance fields of the plan's Global Constraints, in that order
    assert list(info.as_row()) == [
        "unit_kind", "top_session_id", "side_session_id", "fusion_frame_offset", "fusion_axis",
        "fusion_flip", "fusion_surface_row", "fusion_floor_row", "fusion_tank_height_cm",
        "fusion_overlap_frames", "fusion_fused_fish", "fusion_unmatched_top",
        "fusion_unmatched_side", "fusion_outside_column", "fusion_agreement_rms_cm",
        "fusion_agreement_warning", "fusion_agreement_skipped",
    ]


def test_parallel_run_gives_identical_results_and_files(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data")
    serial = Engine(manifest).run(tmp_path / "seq", exporters=EXPORTERS)
    par = Engine(manifest).run(tmp_path / "par", exporters=EXPORTERS, n_workers=2)

    assert [r.session_id for r in par.sessions] == ["t1+s1", "t2+s2"]
    assert [r.error for r in par.sessions] == [None, None]
    assert _skips(par) == _skips(serial)
    for a, b in zip(serial.sessions, par.sessions, strict=True):
        assert a.metric_previews.keys() == b.metric_previews.keys()
        for key in a.metric_previews:
            pd.testing.assert_frame_equal(a.metric_previews[key], b.metric_previews[key])
        assert a.fusion == b.fusion
    seq_files, par_files = _files(tmp_path / "seq"), _files(tmp_path / "par")
    assert seq_files.keys() == par_files.keys()
    differ = [name for name in seq_files if seq_files[name] != par_files[name]]
    assert differ == []


def test_a_failing_pair_is_skipped_and_does_not_abort(tmp_path: Path) -> None:
    engine = Engine(build_scene(tmp_path / "data", side2_fps=10.0))
    result = engine.run(tmp_path / "out", exporters=EXPORTERS)
    assert [r.session_id for r in result.sessions] == ["t1+s1"]
    assert result.sessions[0].error is None
    reason = "pair t2+s2: frame rates differ: 25 vs 10 fps"
    assert _skips(result) == [
        ("t2", reason),
        ("s2", reason),
        ("lone", "not in a fusable pair"),
    ]


def test_every_pair_failing_refuses_before_writing(tmp_path: Path) -> None:
    pairs = [pair("t1", "s1", fusion=fusion_settings(frame_offset=1000)), pair("t2", "s2")]
    engine = Engine(build_scene(tmp_path / "data", side2_fps=10.0, pairs=pairs))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="no pair is ready to fuse: pair t1\\+s1: "):
        engine.run(out, exporters=EXPORTERS)
    assert not out.exists()


def test_the_plan_is_built_once_per_run(tmp_path: Path, monkeypatch) -> None:
    engine = Engine(build_scene(tmp_path / "data"))
    calls: list[str] = []
    real = engine.fuse_pair
    monkeypatch.setattr(engine, "fuse_pair", lambda p: (calls.append(p.top_session_id), real(p))[1])
    engine.run(tmp_path / "out", exporters=EXPORTERS)
    assert calls == ["t1", "t2"]


def test_run_reuses_a_plan_the_caller_already_checked(tmp_path: Path, monkeypatch) -> None:
    engine = Engine(build_scene(tmp_path / "data"))
    plan = engine.require_computable()
    assert [u.unit_id for u in plan.units] == ["t1+s1", "t2+s2"]

    def boom(*a: Any) -> None:
        raise AssertionError("plan rebuilt")

    monkeypatch.setattr(engine, "run_units", boom)
    monkeypatch.setattr(engine, "fuse_pair", boom)
    result = engine.run(tmp_path / "out", exporters=EXPORTERS, plan=plan)
    assert [r.error for r in result.sessions] == [None, None]


def test_progress_counts_units(tmp_path: Path) -> None:
    events: list[ProgressEvent] = []
    Engine(build_scene(tmp_path / "data")).run(
        tmp_path / "out", exporters=EXPORTERS, progress=events.append
    )
    runs = [e for e in events if e.stage == "run"]
    assert [(e.current, e.total) for e in runs] == [(0, 2), (2, 2)]
    done = [e for e in events if e.stage == "session"]
    assert [(e.session_id, e.current, e.total) for e in done] == [
        ("t1+s1", 1, 2),
        ("t2+s2", 2, 2),
    ]
    assert {e.session_id for e in events if e.stage == "import"} == {"t1+s1", "t2+s2"}


def test_cancel_is_checked_between_units(tmp_path: Path) -> None:
    out = tmp_path / "out"

    def cancel_after_the_first_unit() -> None:
        if (out / "t1+s1" / "README.md").exists():
            raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        Engine(build_scene(tmp_path / "data")).run(
            out, exporters=EXPORTERS, cancel_check=cancel_after_the_first_unit
        )
    assert not (out / "t2+s2").exists()


# ── what crosses the process boundary ─────────────────────────────────────────


class _InlinePool:
    """Stands in for ProcessPoolExecutor: records every submission and runs it in-process."""

    submitted: list[tuple[Any, ...]] = []

    def __init__(self, *a: Any, initializer: Any = None, initargs: tuple = (), **k: Any) -> None:
        if initializer is not None:
            initializer(*initargs)

    def __enter__(self) -> _InlinePool:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def submit(self, fn: Any, *args: Any) -> Future:
        type(self).submitted.append(args)
        fut: Future = Future()
        try:
            fut.set_result(fn(*args))
        except BaseException as exc:  # handed back like a real pool would
            fut.set_exception(exc)
        return fut


def _plain(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_plain(v) for v in value)
    return False


def test_workers_receive_no_fused_arrays(tmp_path: Path, monkeypatch) -> None:
    import track2data.api as api

    _InlinePool.submitted = []
    monkeypatch.setattr(api, "ProcessPoolExecutor", _InlinePool)
    manifest = build_scene(tmp_path / "data")
    result = Engine(manifest).run(tmp_path / "out", exporters=EXPORTERS, n_workers=2)

    assert len(_InlinePool.submitted) == 2
    for args in _InlinePool.submitted:
        assert _plain(args), [type(a).__name__ for a in args]
        assert not any(isinstance(a, np.ndarray) for a in args)
    assert [r.session_id for r in result.sessions] == ["t1+s1", "t2+s2"]
    assert [r.error for r in result.sessions] == [None, None]
    il15 = result.sessions[1].metric_previews["IL-15"]
    np.testing.assert_allclose(il15["mean_depth_fraction"], DEPTHS)


def test_worker_function_runs_a_pair_unit(tmp_path: Path, monkeypatch) -> None:
    import multiprocessing

    import track2data.api as api

    manifest = build_scene(tmp_path / "data")
    api._parallel_init(multiprocessing.get_context("spawn").Queue(), multiprocessing.Event())
    res = api._parallel_run_one(
        manifest.model_dump_json(), "pair", 1, str(tmp_path / "out"), EXPORTERS, None
    )
    assert res is not None and res.error is None
    assert res.session_id == "t2+s2"
    assert res.fusion is not None and res.fusion.top_session_id == "t2"
    assert (tmp_path / "out" / "t2+s2" / "README.md").exists()


# ── 2-D is unchanged ─────────────────────────────────────────────────────────


def test_2d_run_has_no_skips_and_no_fusion(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": []}
    )
    result = Engine(manifest).run(tmp_path / "out", exporters=EXPORTERS)
    assert [r.session_id for r in result.sessions] == ["t1", "s1", "t2", "s2", "lone"]
    assert result.skipped == []
    assert all(r.fusion is None for r in result.sessions)


# ── validate ─────────────────────────────────────────────────────────────────


def test_validate_lists_an_unfusable_pair_without_blocking(tmp_path: Path) -> None:
    engine = Engine(build_scene(tmp_path / "data", side2_fps=10.0))
    blocking, notes = engine.validation_issues()
    assert blocking == []
    assert notes == [
        "pair t2+s2: frame rates differ: 25 vs 10 fps",
        "session lone: not in a fusable pair",
    ]
    assert engine.validate() == []


def test_validate_blocks_when_no_pair_fuses(tmp_path: Path) -> None:
    pairs = [pair("t1", "s1", fusion=fusion_settings(frame_offset=1000)), pair("t2", "s2")]
    engine = Engine(build_scene(tmp_path / "data", side2_fps=10.0, pairs=pairs))
    blocking, notes = engine.validation_issues()
    assert len(blocking) == 1 and blocking[0].startswith("no pair is ready to fuse: ")
    assert notes[0].startswith("pair t1+s1: ")
    assert engine.validate() == blocking
