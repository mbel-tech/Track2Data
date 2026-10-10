"""The run plan (one unit per session in 2-D, per fusable pair in 3-D) and the 3-D gate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from track2data.api import Engine
from track2data.core.models import (
    MODE_3D_BLOCK_REASON,
    ProjectManifest,
    ProjectMode,
    SessionRef,
    ViewPair,
)

from .builders import make_psess, settings, side_xy, top_xy


def _engine(monkeypatch, pairs, psesses, ids, dimension="3d") -> Engine:
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=i, folder=f"/tmp/{i}", sha256="") for i in ids],
        mode=(
            ProjectMode(dimension="3d", layout="two_videos")
            if dimension == "3d"
            else ProjectMode()
        ),
        view_pairs=pairs,
    )
    engine = Engine(manifest)
    monkeypatch.setattr(engine, "preprocess_ref", lambda ref: psesses[ref.session_id])
    return engine


def _two_pairs(monkeypatch, extra_ids=(), **overrides):
    labels = ["a", "b", "c"]
    psesses = {}
    pairs = []
    for t, s in (("t1", "s1"), ("t2", "s2")):
        psesses[t] = make_psess(t, top_xy(), labels=list(labels), px_per_cm=2.0)
        psesses[s] = make_psess(s, side_xy(), labels=list(labels))
        pairs.append(
            ViewPair(
                top_session_id=t,
                side_session_id=s,
                fish_map={x: x for x in labels},
                fusion=settings(),
            )
        )
    for key, value in overrides.items():
        psesses[key] = value
    ids = ("t1", "s1", "t2", "s2", *extra_ids)
    return pairs, psesses, ids


def test_2d_plan_has_one_unit_per_ref(monkeypatch):
    psesses = {i: make_psess(i, top_xy()) for i in ("a", "b", "c")}
    engine = _engine(monkeypatch, [], psesses, ("a", "b", "c"), dimension="2d")
    plan = engine.run_units()
    assert [(u.unit_id, u.kind) for u in plan.units] == [
        ("a", "session"),
        ("b", "session"),
        ("c", "session"),
    ]
    assert [u.ref.session_id for u in plan.units] == ["a", "b", "c"]
    assert all(u.pair is None and u.fused is None for u in plan.units)
    assert plan.skipped == []
    engine.require_computable()  # 2-D never refuses


def test_3d_plan_two_good_pairs(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    plan = _engine(monkeypatch, pairs, psesses, ids).run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1", "t2+s2"]
    assert all(u.kind == "pair" and u.ref is None for u in plan.units)
    assert plan.units[0].pair is pairs[0]
    assert plan.units[0].fused is not None
    assert plan.units[0].fused.session_id == "t1+s1"
    assert plan.skipped == []


def test_pair_without_settings_is_skipped_with_both_sessions(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    pairs[1] = pairs[1].model_copy(update={"fusion": None})
    plan = _engine(monkeypatch, pairs, psesses, ids).run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1"]
    reason = "pair t2+s2: no fusion settings for this pair"
    assert [(s.session_id, s.reason) for s in plan.skipped] == [("t2", reason), ("s2", reason)]


def test_pair_with_mismatched_fps_is_skipped_with_the_fusion_error(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    psesses["s2"] = make_psess("s2", side_xy(), fps=10.0, labels=["a", "b", "c"])
    engine = _engine(monkeypatch, pairs, psesses, ids)
    plan = engine.run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1"]
    with pytest.raises(Exception) as info:
        engine.fuse_pair(pairs[1])
    expected = f"pair t2+s2: {info.value}"
    assert [(s.session_id, s.reason) for s in plan.skipped] == [("t2", expected), ("s2", expected)]


def test_session_in_no_pair_is_skipped(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch, extra_ids=("lone",))
    psesses["lone"] = make_psess("lone", top_xy())
    plan = _engine(monkeypatch, pairs, psesses, ids).run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1", "t2+s2"]
    assert [(s.session_id, s.reason) for s in plan.skipped] == [("lone", "not in a fusable pair")]


def test_skipped_sessions_are_listed_once_in_session_order(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    # s1 also sits in a second, settings-less pair: it is in a fusable pair, so it is not skipped.
    extra = ViewPair(top_session_id="t2", side_session_id="s1")
    plan = _engine(monkeypatch, [*pairs, extra], psesses, ids).run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1", "t2+s2"]
    assert plan.skipped == []
    # both pairs bad: every session once, in session order, first reason wins
    bad = [p.model_copy(update={"fusion": None}) for p in (*pairs, extra)]
    plan = _engine(monkeypatch, bad, psesses, ids).run_units()
    assert [s.session_id for s in plan.skipped] == ["t1", "s1", "t2", "s2"]
    assert plan.skipped[1].reason == "pair t1+s1: no fusion settings for this pair"
    assert plan.skipped[2].reason == "pair t2+s2: no fusion settings for this pair"


def test_a_session_already_in_a_unit_is_not_used_by_a_second_pair(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch, extra_ids=("t3",))
    psesses["t3"] = make_psess("t3", top_xy(), labels=["a", "b", "c"], px_per_cm=2.0)
    # a hand-edited manifest puts s1 in a second, fusable pair: it would be counted twice
    twice = pairs[0].model_copy(update={"top_session_id": "t3"})
    engine = _engine(monkeypatch, [*pairs, twice], psesses, ids)
    calls = []
    real = engine.fuse_pair
    monkeypatch.setattr(engine, "fuse_pair", lambda p: (calls.append(p), real(p))[1])
    plan = engine.run_units()
    assert [u.unit_id for u in plan.units] == ["t1+s1", "t2+s2"]
    assert [(s.session_id, s.reason) for s in plan.skipped] == [
        ("t3", "pair t3+s1: session s1 is already in pair t1+s1")
    ]
    assert len(calls) == 2  # the second use is refused before fusing


def test_a_good_pair_beside_a_bad_one_still_yields_its_unit(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    pairs[0] = pairs[0].model_copy(update={"fusion": settings(frame_offset=1000)})
    engine = _engine(monkeypatch, pairs, psesses, ids)
    assert [u.unit_id for u in engine.run_units().units] == ["t2+s2"]
    engine.require_computable()


def test_3d_project_without_pairs_refuses_with_the_block_reason(monkeypatch):
    psesses = {"x": make_psess("x", top_xy())}
    engine = _engine(monkeypatch, [], psesses, ("x",))
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        engine.require_computable()
    empty = _engine(monkeypatch, [], {}, ())
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        empty.require_computable()
    assert MODE_3D_BLOCK_REASON == "Pair and fuse a top and a side session first"


def test_all_pairs_bad_names_at_most_three_reasons(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch, extra_ids=("lone",))
    psesses["lone"] = make_psess("lone", top_xy())
    bad = [p.model_copy(update={"fusion": None}) for p in pairs]
    engine = _engine(monkeypatch, bad, psesses, ids)
    with pytest.raises(ValueError) as info:
        engine.require_computable()
    message = str(info.value)
    assert message.startswith("no pair is ready to fuse: pair t1+s1: no fusion settings")
    assert len(message.removeprefix("no pair is ready to fuse: ").split("; ")) == 3
    assert "lone" not in message


def test_compute_metrics_in_3d_takes_fused_sessions_only(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)
    with pytest.raises(ValueError, match="3-D projects compute fused sessions only"):
        engine.compute_metrics(psesses["t1"])
    fused = engine.fuse_pair(pairs[0])
    results = engine.compute_metrics(fused.psess)
    assert results  # the diagnostics at least


def test_compute_metrics_does_not_rebuild_the_plan(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)
    fused = engine.fuse_pair(pairs[0])

    def boom():
        raise AssertionError("plan rebuilt")

    monkeypatch.setattr(engine, "run_units", boom)
    engine.compute_metrics(fused.psess)


def test_run_session_is_2d_only(monkeypatch, tmp_path: Path):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)
    with pytest.raises(ValueError, match=r"use run\(\) for a 3-D project"):
        engine.run_session(psesses["t1"].session, tmp_path)


def test_run_session_works_in_2d(monkeypatch, tmp_path: Path):
    psesses = {"a": make_psess("a", top_xy(), px_per_cm=2.0)}
    engine = _engine(monkeypatch, [], psesses, ("a",), dimension="2d")
    monkeypatch.setattr(engine, "preprocess", lambda session: psesses["a"])
    written = engine.run_session(psesses["a"].session, tmp_path)
    assert written


def test_export_does_not_rebuild_the_plan(monkeypatch, tmp_path: Path):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)

    def boom():
        raise AssertionError("plan rebuilt")

    monkeypatch.setattr(engine, "run_units", boom)
    engine._require_not_blocked()  # pairs with settings exist: passes without fusing
    nopairs = _engine(monkeypatch, [], psesses, ids)
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        nopairs.export(object(), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_sensitivity_still_refuses_3d(monkeypatch):
    from track2data.sensitivity import run_sensitivity

    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)
    with pytest.raises(ValueError, match="sensitivity is not supported for 3-D projects yet"):
        run_sensitivity(engine, psesses["t1"].session)


def test_plan_fuses_each_pair_once(monkeypatch):
    pairs, psesses, ids = _two_pairs(monkeypatch)
    engine = _engine(monkeypatch, pairs, psesses, ids)
    calls = []
    real = engine.fuse_pair
    monkeypatch.setattr(engine, "fuse_pair", lambda p: (calls.append(p), real(p))[1])
    engine.run_units()
    assert len(calls) == 2
    assert np.isfinite(engine.fuse_pair(pairs[0]).psess.depth).any()
