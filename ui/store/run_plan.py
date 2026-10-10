"""The run plan of a 3-D project, computed in the background and shared by the pages.

``Engine.run_units()`` fuses every pair with fusion settings, which is far too slow for the GUI
thread. ``RunPlanWatcher`` (one per store, ``ProjectStore.run_plan``) builds it on the store's
worker pool whenever the inputs it depends on change, keeps the latest result, and drops results
computed for older inputs -- the same pattern as ``ui/widgets/fusion_section.py``, whose key it
shares (``fusion_settings_key``). Processing, Export and Preview read the same result.

Nothing here writes to the store: ``snapshot()`` only reads the manifest and may submit a task.
A 2-D project never builds a plan here (its plan is one unit per session, and the 2-D pages keep
their own synchronous path).
"""

from __future__ import annotations

import dataclasses
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from track2data.core.models import MODE_3D_BLOCK_REASON

if TYPE_CHECKING:
    from track2data.core.models import ProjectManifest
    from track2data.core.runplan import RunPlan

CHECKING_TEXT = "Checking which pairs can run…"


def fusion_settings_key(manifest: ProjectManifest, session_ids) -> tuple:
    """The project settings ``Engine.fuse_pair`` depends on for these sessions, besides the
    pair and the session entries themselves (see ``Engine._cache_key``)."""
    m = manifest
    ids = tuple(session_ids)
    return (
        m.preprocess.model_dump_json(),
        m.calibration.model_dump_json(),
        m.zones.model_dump_json(),
        m.security.allow_pickle_trajectories,
        m.blob_diagnostics,
        tuple(str(m.video_overrides.get(sid)) for sid in ids),
        tuple(m.video_overrides[sid].exists() if sid in m.video_overrides else None for sid in ids),
    )


def plan_key(manifest: ProjectManifest, facts_of, cache_dir: Path | None) -> object:
    """Everything the plan depends on: the mode, every session entry and its derived facts,
    every pair with its settings, the fusion-relevant project settings and the cache folder.
    Metric and export choices are left out: they do not change what runs."""
    ids = [r.session_id for r in manifest.sessions]
    return (
        manifest.mode.model_dump_json(),
        tuple(r.model_dump_json() for r in manifest.sessions),
        tuple(p.model_dump_json() for p in manifest.view_pairs),
        tuple(facts_of(sid) for sid in ids),
        fusion_settings_key(manifest, ids),
        str(cache_dir),
    )


@dataclass(frozen=True)
class PlanOutcome:
    """What the worker returns: the plan, and why nothing can run when it has no unit."""

    plan: RunPlan | None
    gate: str | None = None


def compute_plan(manifest: ProjectManifest, cache_dir: Path | None) -> PlanOutcome:
    """Build the run plan. Runs on a worker thread and never raises (a raise would reach the
    main window's "Pipeline run failed" dialog); a failure becomes the gate text."""
    from track2data.api import Engine

    try:
        engine = Engine(manifest, cache_dir=cache_dir)
        plan = engine.run_units()
        # Keep no fusion arrays for the GUI's lifetime: a serial run fuses each unit again.
        plan.units = [dataclasses.replace(u, fused=None) for u in plan.units]
        gate = None
        if not plan.units:
            # In 3-D the gate's refusal is the first blocking issue (see validation_issues).
            blocking, _notes = engine.validation_issues(plan)
            gate = blocking[0] if blocking else MODE_3D_BLOCK_REASON
        return PlanOutcome(plan, gate)
    except Exception as exc:  # the plan must not crash a page
        name = type(exc).__name__
        return PlanOutcome(None, f"{name}: {exc}" if str(exc) else name)


@dataclass(frozen=True)
class PlanState:
    """The plan as a page sees it right now."""

    applies: bool  # a 3-D project is open
    checking: bool = False  # the plan for the current inputs is being built
    plan: RunPlan | None = None  # the plan for the current inputs, once known
    gate: str | None = None  # why nothing can run (plan with no unit, or a failure)

    @property
    def runnable(self) -> bool:
        return self.plan is not None and bool(self.plan.units) and self.gate is None

    @property
    def blocked_reason(self) -> str | None:
        """What a page shows instead of running: the gate, or the checking text."""
        if not self.applies:
            return None
        if self.checking:
            return CHECKING_TEXT
        return self.gate


def will_run_line(plan: RunPlan) -> str:
    return "Will run: " + ", ".join(u.unit_id for u in plan.units)


def skipped_lines(plan: RunPlan) -> list[str]:
    return [f"Skipped: {s.session_id} — {s.reason}" for s in plan.skipped]


class RunPlanWatcher(QObject):
    """Builds and keeps the run plan of the store's 3-D project (see the module docstring).

    ``changed`` fires when a new plan is being built and when its result arrives.
    """

    changed = Signal()

    def __init__(self, store) -> None:
        super().__init__(store)
        self._store_ref = weakref.ref(store)  # the store owns this object: no strong cycle
        self._key: object = None  # inputs of the plan being built / held
        self._outcome: PlanOutcome | None = None  # result for self._key once known
        self._pending: dict[str, object] = {}  # task id -> key
        for signal in (
            store.projectChanged, store.sessionsChanged, store.calibrationChanged,
            store.zonesChanged, store.preprocessChanged, store.modeChanged,
            store.viewsChanged, store.sessionFactsChanged,
        ):
            signal.connect(self._on_inputs_changed)
        store.taskFinished.connect(self._on_task_finished)
        store.tasks.taskCancelled.connect(self._on_task_cancelled)

    def _store(self):
        return self._store_ref()

    def _current_key(self) -> object:
        store = self._store()
        m = None if store is None else store.manifest
        if m is None or m.mode.dimension != "3d":
            return None
        return plan_key(m, store.session_facts, store.cache_dir)

    def refresh(self) -> None:
        """Start building the plan when its inputs changed since the last one. Never writes."""
        key = self._current_key()
        if key == self._key:
            return
        self._key = key
        self._outcome = None
        store = self._store()
        if store is not None and store.tasks.closed:
            return  # shutting down: build nothing more
        if store is not None:
            # A newer request supersedes the older ones: a queued build never starts (one
            # already running finishes, and its result is ignored).
            for task_id in self._pending:
                store.tasks.cancel(task_id)
        self._pending = {}
        if key is not None and store is not None:
            manifest = store.manifest.model_copy(deep=True)
            cache_dir = store.cache_dir
            self._pending[store.tasks.submit(lambda: compute_plan(manifest, cache_dir))] = key
        self.changed.emit()

    def snapshot(self) -> PlanState:
        """The plan for the current manifest (starts building it when the inputs changed)."""
        self.refresh()
        if self._key is None:
            return PlanState(applies=False)
        if self._outcome is None:
            return PlanState(applies=True, checking=True)
        return PlanState(applies=True, plan=self._outcome.plan, gate=self._outcome.gate)

    def current_plan(self) -> RunPlan | None:
        """The plan for the current inputs when it is known and has units, else None."""
        state = self.snapshot()
        return state.plan if state.runnable else None

    # ── slots ──────────────────────────────────────────────────────────────

    def _on_inputs_changed(self) -> None:
        self.refresh()

    def _on_task_finished(self, task_id: str, result: object) -> None:
        key = self._pending.pop(task_id, None)
        if key is None or key != self._key:
            return  # not ours, or computed for inputs that changed meanwhile
        if isinstance(result, PlanOutcome):
            self._outcome = result
        else:  # compute_plan never raises; anything else is a failure of the task itself
            self._outcome = PlanOutcome(None, str(result) or type(result).__name__)
        self.changed.emit()

    def _on_task_cancelled(self, task_id: str) -> None:
        if self._pending.pop(task_id, None) is None:
            return
        # A Cancel of the run lane (or shutdown) dropped the plan task: forget it and tell the
        # pages, whose snapshot() then builds it again. Not after shutdown: the runner is
        # closed, refresh() submits nothing, and nothing is announced while the window closes.
        self._key = None
        self._outcome = None
        store = self._store()
        if store is not None and not store.tasks.closed:
            self.changed.emit()
