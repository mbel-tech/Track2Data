"""Shared builders for the UI tests of a 3-D project's run plan (ui/store/run_plan.py)."""

from __future__ import annotations

import threading
from pathlib import Path

from track2data.core.models import (
    CalibrationConfig,
    FusionSettings,
    MetricSelection,
    ProjectMode,
    SessionRef,
    ViewPair,
)
from track2data.core.runplan import RunPlan, RunUnit, SkippedSession

SETTINGS = FusionSettings(surface_row=10, floor_row=110, tank_height_cm=20)
OTHER = FusionSettings(frame_offset=3, surface_row=10, floor_row=110, tank_height_cm=20)
GATE = "no pair is ready to fuse: pair t1+s1: the two views have different frame rates"


def make_plan(units=("t1+s1",), skipped=(("x", "not in a fusable pair"),)) -> RunPlan:
    out = []
    for uid in units:
        top, side = uid.split("+")
        out.append(RunUnit(uid, "pair", pair=ViewPair(top_session_id=top, side_session_id=side)))
    return RunPlan(units=out, skipped=[SkippedSession(*s) for s in skipped])


def store_3d(tmp_path: Path, *, settings: bool = True):
    """A 3-D project: pairs t1+s1 and t2+s2 (settings on t1+s1 only) and a lone session x."""
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path, mode=ProjectMode(dimension="3d", layout="two_videos"))
    names = ("t1", "s1", "t2", "s2", "x")
    store.update_sessions(
        [SessionRef(session_id=n, folder=tmp_path / n, sha256="0" * 64) for n in names]
    )
    for n in names:
        store.update_view_role(n, "top" if n.startswith(("t", "x")) else "side")
    store.update_view_pair(ViewPair(top_session_id="t1", side_session_id="s1"))
    store.update_view_pair(ViewPair(top_session_id="t2", side_session_id="s2"))
    if settings:
        store.update_fusion("t1", "s1", SETTINGS)
    store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=10.0))
    store.update_metrics(MetricSelection(individual=["IL-1"]))
    return store


class FakePlanner:
    """Stands in for ``ui.store.run_plan.compute_plan``: records calls (with the thread they
    ran on), can hold a call until released, and answers from ``self.outcome`` or a callable."""

    def __init__(self) -> None:
        from ui.store.run_plan import PlanOutcome

        self.calls: list[object] = []
        self.threads: list[threading.Thread] = []
        self.hold: threading.Event | None = None
        self.outcome: object = PlanOutcome(make_plan())

    def __call__(self, manifest, cache_dir):
        self.calls.append(manifest)
        self.threads.append(threading.current_thread())
        hold = self.hold
        if hold is not None:
            hold.wait(5)
        out = self.outcome
        return out(manifest) if callable(out) else out


def install_planner(monkeypatch) -> FakePlanner:
    from ui.store import run_plan

    fake = FakePlanner()
    monkeypatch.setattr(run_plan, "compute_plan", fake)
    return fake
