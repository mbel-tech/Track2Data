"""
Tests for ui/processing_screen.py (issue #23) -- the primary screen
where a user watches their batch run execute: validate -> submit via
TaskRunner -> progress bar + per-session status table -> cancel.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)


def _make_manifest(session_folder: Path) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    sha = hashlib.sha256(str(session_folder).encode()).hexdigest()
    return ProjectManifest(
        project_name="test_project",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(session_id=session_folder.name, folder=session_folder, sha256=sha)
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
    )


def _make_ready_store(tmp_path: Path, session_folder: Path):
    """A ProjectStore whose manifest is valid (Engine.validate() ->
    no issues) and points at a real, importable session folder."""
    from app.state import ProjectStore

    store = ProjectStore()
    store._manifest = _make_manifest(session_folder)
    store._project_dir = tmp_path
    return store


def _make_empty_store(tmp_path: Path):
    """A ProjectStore with an open but empty project -- Engine.validate()
    returns issues (no sessions, no metrics)."""
    from app.state import ProjectStore

    store = ProjectStore()
    store.new_project("empty", tmp_path)
    return store


# ── construction ─────────────────────────────────────────────────────────────


def test_screen_constructs_without_a_store(qtbot) -> None:
    from ui.processing_screen import ProcessingScreen

    screen = ProcessingScreen()
    qtbot.addWidget(screen)
    assert screen is not None


def test_run_button_disabled_until_a_project_is_open(qtbot) -> None:
    from app.state import ProjectStore
    from ui.processing_screen import ProcessingScreen

    store = ProjectStore()
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    assert screen._run_btn.isEnabled() is False

    store.new_project("p", Path("."))
    assert screen._run_btn.isEnabled() is True


def test_cancel_button_disabled_until_a_run_is_in_flight(qtbot, tmp_path: Path) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_empty_store(tmp_path)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    assert screen._cancel_btn.isEnabled() is False


# ── start_run(): validation gate ────────────────────────────────────────────


def test_start_run_without_a_project_shows_warning_and_does_not_submit(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.state import ProjectStore
    from ui.processing_screen import ProcessingScreen

    warnings: list[str] = []
    monkeypatch.setattr(
        "ui.processing_screen.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    store = ProjectStore()
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    started: list[object] = []
    store.tasks.taskStarted.connect(started.append)

    screen.start_run()

    assert len(warnings) == 1
    assert started == []  # nothing submitted to the pool


def test_start_run_with_validation_issues_shows_them_and_does_not_submit(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.processing_screen import ProcessingScreen

    warnings: list[str] = []
    monkeypatch.setattr(
        "ui.processing_screen.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    store = _make_empty_store(tmp_path)  # no sessions, no metrics -> issues
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    started: list[object] = []
    store.tasks.taskStarted.connect(started.append)

    screen.start_run()

    assert len(warnings) == 1
    assert "No sessions" in warnings[0] or "No metrics" in warnings[0]
    assert started == []


# ── start_run(): happy path ──────────────────────────────────────────────────


def test_start_run_happy_path_toggles_buttons_and_sets_run_results(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen.start_run()
        assert screen._run_btn.isEnabled() is False
        assert screen._cancel_btn.isEnabled() is True

    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=2000)
    assert screen._cancel_btn.isEnabled() is False
    assert store.run_results is not None
    assert len(store.run_results.sessions) == 1
    assert store.run_results.sessions[0].error is None


def test_start_run_writes_real_output_files_and_pumps_progress(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    """The test that proves the GUI<->engine seam actually works end to end."""
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)

    percents: list[int] = []
    store.taskProgress.connect(lambda _tid, pct: percents.append(pct))

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen.start_run()

    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=2000)

    out_dirs = list(tmp_path.glob("exports/*/"))
    assert len(out_dirs) == 1
    session_dir = out_dirs[0] / tiny_real_session.name
    assert (session_dir / "master_fish_by_frame.csv").exists()
    assert len(percents) > 0
    assert percents[-1] == 100


def test_start_run_updates_per_session_status_table(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)

    assert screen._status_table.rowCount() == 1  # one row per manifest session

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen.start_run()

    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=2000)
    status_item = screen._status_table.item(0, 1)  # Session | Status | Frames | Duration
    assert status_item.text() in ("Done", "done", "Complete", "Finished")


def test_start_run_uses_project_dir_exports_timestamp_default(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen.start_run()
    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=2000)

    export_dirs = list((tmp_path / "exports").iterdir())
    assert len(export_dirs) == 1
    # ISO-8601 compact-ish: starts with a 4-digit year, no ":" (illegal on Windows).
    assert export_dirs[0].name[:4].isdigit()
    assert ":" not in export_dirs[0].name


# ── cancellation ─────────────────────────────────────────────────────────────


def test_cancel_button_stops_an_in_flight_run(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Slow the pipeline down enough to reliably click Cancel mid-run: patch
    # Engine.preprocess to sleep before delegating to the real implementation.
    import time

    from track2data.api import Engine
    from ui.processing_screen import ProcessingScreen

    real_preprocess = Engine.preprocess

    def slow_preprocess(self, session):
        time.sleep(0.3)
        return real_preprocess(self, session)

    monkeypatch.setattr(Engine, "preprocess", slow_preprocess)

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)

    screen.start_run()
    qtbot.waitUntil(lambda: screen._cancel_btn.isEnabled(), timeout=2000)
    screen._cancel_btn.click()

    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=5000)
    assert screen._cancel_btn.isEnabled() is False


def test_workers_spinbox_is_passed_to_engine_run(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    assert screen._workers.value() == 1  # sequential by default

    submitted = []
    store.tasks.submit_with_progress = lambda fn, **kw: submitted.append(fn) or "t1"  # type: ignore[method-assign]
    screen._workers.setMaximum(4)
    screen._workers.setValue(3)
    screen.start_run()
    assert submitted[0].keywords["n_workers"] == 3


def test_parallel_run_bar_follows_session_events_only(qtbot) -> None:
    from track2data.core.progress import ProgressEvent
    from ui.processing_screen import ProcessingScreen

    screen = ProcessingScreen()
    qtbot.addWidget(screen)
    screen._current_task_id = "t"
    screen._parallel_run = True
    screen._progress.setValue(0)

    screen._on_task_progress("t", 75)  # a per-session stage percent: ignored
    assert screen._progress.value() == 0
    screen._on_task_event("t", ProgressEvent(stage="session", current=1, total=4))
    assert screen._progress.value() == 25


def test_workers_segments_drive_the_spin_box_and_the_cli_command(qtbot) -> None:
    from ui.processing_screen import ProcessingScreen
    from ui.store.project_store import ProjectStore

    screen = ProcessingScreen(ProjectStore())
    qtbot.addWidget(screen)
    assert screen._worker_buttons[1].isChecked()
    top = screen._workers.maximum()
    assert screen._worker_buttons[1].isEnabled()
    assert screen._worker_buttons[8].isEnabled() == (top >= 8)

    if top >= 2:
        screen._worker_buttons[2].click()
        assert screen._workers.value() == 2
        assert screen._worker_buttons[2].isChecked()
        assert screen.cli_command().endswith("--workers 2")


def test_clicking_a_setup_check_asks_to_navigate_to_its_page(qtbot) -> None:
    from PySide6.QtWidgets import QPushButton

    from ui.processing_screen import ProcessingScreen
    from ui.store.project_store import ProjectStore

    screen = ProcessingScreen(ProjectStore())
    qtbot.addWidget(screen)
    cells = screen.findChildren(QPushButton, "CheckCell")
    assert len(cells) == 6
    with qtbot.waitSignal(screen.navigateRequested) as blocker:
        cells[0].click()
    assert blocker.args == [1]  # Sessions
    with qtbot.waitSignal(screen.navigateRequested) as blocker:
        cells[5].click()
    assert blocker.args == [6]  # Metrics


def test_main_window_follows_a_setup_check_click(qtbot) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._processing_screen.navigateRequested.emit(3)
    assert win._stack.currentIndex() == 3
    win.close()


# ── 3-D mode ─────────────────────────────────────────────────────────────────


def _set_3d(store) -> None:
    from track2data.core.models import ProjectMode

    store._manifest = store._manifest.model_copy(
        update={"mode": ProjectMode(dimension="3d", layout="two_videos")}
    )


def test_run_button_disabled_in_3d(qtbot, tmp_path: Path, tiny_real_session: Path) -> None:
    from track2data.core.models import MODE_3D_BLOCK_REASON
    from ui.processing_screen import ProcessingScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    assert screen._run_btn.isEnabled() is True

    _set_3d(store)
    store.modeChanged.emit()
    assert screen._run_btn.isEnabled() is False
    # the plan is built in the background; with no pair it refuses with the block reason
    qtbot.waitUntil(lambda: screen._status_label.text() == MODE_3D_BLOCK_REASON, timeout=5000)
    assert screen._run_btn.isEnabled() is False

    # A finishing task must not re-enable Run in a 3-D project.
    screen._current_task_id = "t"
    screen._on_task_finished("t", RuntimeError("x"))
    assert screen._run_btn.isEnabled() is False
    screen._current_task_id = "t"
    screen._on_task_cancelled("t")
    assert screen._run_btn.isEnabled() is False

    store._manifest = store._manifest.model_copy(
        update={"mode": store._manifest.mode.model_copy(update={"dimension": "2d"})}
    )
    store.modeChanged.emit()
    assert screen._run_btn.isEnabled() is True


def test_start_run_refuses_3d(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.core.models import MODE_3D_BLOCK_REASON
    from ui.processing_screen import ProcessingScreen

    warnings: list[str] = []
    monkeypatch.setattr(
        "ui.processing_screen.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )
    store = _make_ready_store(tmp_path, tiny_real_session)
    _set_3d(store)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    qtbot.waitUntil(lambda: screen._status_label.text() == MODE_3D_BLOCK_REASON, timeout=5000)
    started: list[object] = []
    store.tasks.taskStarted.connect(started.append)

    screen.start_run()

    assert len(warnings) == 1
    assert MODE_3D_BLOCK_REASON in warnings[0]
    assert started == []


# ── 3-D: the run plan built in the background ────────────────────────────────

import threading  # noqa: E402

import track2data.api  # noqa: E402,F401  (preloaded: see tests/test_ui/test_fusion_section.py)
from tests.test_ui.plan3d import (  # noqa: E402
    GATE,
    OTHER,
    install_planner,
    make_plan,
    store_3d,
)


def _screen_3d(qtbot, tmp_path, monkeypatch, outcome=None, **kw):
    from ui.processing_screen import ProcessingScreen

    fake = install_planner(monkeypatch)
    if outcome is not None:
        fake.outcome = outcome
    store = store_3d(tmp_path, **kw)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    return store, screen, fake


def _plan_ready(screen) -> bool:
    return "Will run" in screen._plan_label.text() or "Nothing" in screen._plan_label.text()


def test_3d_setup_check_lists_will_run_and_skipped(qtbot, tmp_path, monkeypatch) -> None:
    from ui.store.run_plan import PlanOutcome

    outcome = PlanOutcome(make_plan(("t1+s1", "t2+s2"), (("x", "not in a fusable pair"),)))
    _store, screen, fake = _screen_3d(qtbot, tmp_path, monkeypatch, outcome)
    qtbot.waitUntil(lambda: _plan_ready(screen), timeout=3000)
    text = screen._plan_label.text()
    assert "Will run: t1+s1, t2+s2" in text
    assert "Skipped: x — not in a fusable pair" in text
    assert not screen._plan_label.isHidden()
    assert screen._plan_dot.property("check") == "warn"  # a skip is a warning, not a problem
    assert screen._run_btn.isEnabled()
    assert screen._check_title.text() == "Ready to run"
    assert all(t is not threading.main_thread() for t in fake.threads)


def test_3d_start_disabled_while_checking(qtbot, tmp_path, monkeypatch) -> None:
    from ui.processing_screen import ProcessingScreen
    from ui.store.run_plan import CHECKING_TEXT

    fake = install_planner(monkeypatch)
    fake.hold = threading.Event()
    store = store_3d(tmp_path)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    assert not screen._run_btn.isEnabled()
    assert screen._status_label.text() == CHECKING_TEXT
    fake.hold.set()
    qtbot.waitUntil(screen._run_btn.isEnabled, timeout=3000)
    assert screen._status_label.text() == "Ready"


def test_3d_empty_plan_disables_start_with_the_gate(qtbot, tmp_path, monkeypatch) -> None:
    from ui.store.run_plan import PlanOutcome

    fake = install_planner(monkeypatch)
    fake.outcome = PlanOutcome(make_plan((), (("t1", "pair t1+s1: x"),)), gate=GATE)
    from ui.processing_screen import ProcessingScreen

    store = store_3d(tmp_path)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    qtbot.waitUntil(lambda: screen._status_label.text() == GATE, timeout=3000)
    assert not screen._run_btn.isEnabled()
    assert "Nothing will run" in screen._plan_label.text()
    assert "Skipped: t1 — pair t1+s1: x" in screen._plan_label.text()
    assert screen._plan_dot.property("check") == "err"


def test_3d_stale_plan_result_is_ignored(qtbot, tmp_path, monkeypatch) -> None:
    from ui.store.run_plan import CHECKING_TEXT, PlanOutcome

    store, screen, fake = _screen_3d(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: _plan_ready(screen), timeout=3000)

    def answer(manifest):
        offset = manifest.view_pairs[0].fusion.frame_offset
        return PlanOutcome(make_plan(("t1+s1",) if offset == 0 else ("t2+s2",)))

    fake.outcome = answer
    fake.hold = threading.Event()
    store.update_fusion("t1", "s1", OTHER.model_copy(update={"frame_offset": 0, "flip": True}))
    qtbot.waitUntil(lambda: len(fake.calls) == 2, timeout=3000)  # the stale one is running
    store.update_fusion("t1", "s1", OTHER)  # inputs change again while it runs
    seen: list[str] = []
    store.taskFinished.connect(lambda *_: seen.append(screen._plan_label.text()))
    fake.hold.set()
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=3000)
    assert CHECKING_TEXT in seen[0]  # the stale result left the page checking
    assert "Will run: t2+s2" in screen._plan_label.text()


def test_3d_start_submits_the_plan_and_never_fuses_on_the_gui_thread(
    qtbot, tmp_path, monkeypatch
) -> None:
    from track2data.api import Engine
    from track2data.core.models import RunResult

    store, screen, _fake = _screen_3d(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(screen._run_btn.isEnabled, timeout=3000)
    plan = store.run_plan.current_plan()
    assert plan is not None

    gui_calls: list[str] = []
    for name in ("run_units", "validate", "fuse_pair", "require_computable"):
        orig = getattr(Engine, name)

        def spy(self, *a, _orig=orig, _name=name, **k):
            if threading.current_thread() is threading.main_thread():
                gui_calls.append(_name)
            return _orig(self, *a, **k)

        monkeypatch.setattr(Engine, name, spy)
    runs: list[dict] = []

    def fake_run(self, out_dir, exporters=None, **kw):
        runs.append(kw)
        return RunResult(sessions=[])

    monkeypatch.setattr(Engine, "run", fake_run)
    with qtbot.waitSignal(store.taskFinished, timeout=5000):
        screen.start_run()
    assert gui_calls == []
    assert len(runs) == 1 and runs[0]["plan"] is plan
    table = screen._status_table
    assert [table.item(r, 0).text() for r in range(table.rowCount())] == ["t1+s1"]


def test_3d_start_refuses_while_the_plan_is_unknown(qtbot, tmp_path, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "ui.processing_screen.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )
    fake = install_planner(monkeypatch)
    fake.hold = threading.Event()
    from ui.processing_screen import ProcessingScreen

    store = store_3d(tmp_path)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    started: list[object] = []
    store.tasks.taskStarted.connect(started.append)
    screen.start_run()
    assert len(warnings) == 1 and "Checking" in warnings[0]
    fake.hold.set()
    qtbot.waitUntil(screen._run_btn.isEnabled, timeout=3000)


def test_3d_session_removed_while_the_plan_runs(qtbot, tmp_path, monkeypatch) -> None:
    from ui.store.run_plan import PlanOutcome

    store, screen, fake = _screen_3d(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: _plan_ready(screen), timeout=3000)
    fake.hold = threading.Event()
    fake.outcome = lambda m: PlanOutcome(
        make_plan(("t1+s1",) if any(r.session_id == "x" for r in m.sessions) else ("t2+s2",))
    )
    store.update_fusion("t1", "s1", OTHER)
    qtbot.waitUntil(lambda: len(fake.calls) == 2, timeout=3000)
    store.update_sessions([r for r in store.manifest.sessions if r.session_id != "x"])
    fake.hold.set()
    qtbot.waitUntil(lambda: "t2+s2" in screen._plan_label.text(), timeout=3000)
    screen._refresh_setup_check()


def test_compute_plan_with_a_dangling_pair_does_not_raise(tmp_path) -> None:
    from track2data.core.models import ViewPair
    from ui.store.run_plan import compute_plan

    store = store_3d(tmp_path)
    m = store.manifest
    m = m.model_copy(
        update={
            "sessions": [r for r in m.sessions if r.session_id != "t1"],
            "view_pairs": [
                ViewPair(top_session_id="t1", side_session_id="s1", fusion=OTHER),
            ],
        }
    )
    outcome = compute_plan(m, None)
    assert outcome.plan is not None and outcome.plan.units == []
    assert outcome.gate and outcome.gate.startswith("no pair is ready to fuse")


def test_3d_rebuild_writes_nothing(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, _fake = _screen_3d(qtbot, tmp_path, monkeypatch)
    qtbot.waitUntil(lambda: _plan_ready(screen), timeout=3000)
    before = store.manifest
    dump = before.model_dump_json()
    emitted: list[str] = []
    for name in (
        "projectChanged", "sessionsChanged", "viewsChanged", "metricsChanged", "modeChanged",
        "calibrationChanged", "exportChanged", "persistenceChanged",
    ):
        getattr(store, name).connect(lambda *_, n=name: emitted.append(n))
    for _ in range(3):
        screen._on_project_changed()
        screen._refresh_setup_check()
        store.run_plan.refresh()
    qtbot.wait(50)
    assert store.manifest is before and store.manifest.model_dump_json() == dump
    assert emitted == []


def test_2d_never_builds_a_plan(qtbot, tmp_path, monkeypatch, tiny_real_session) -> None:
    from ui.processing_screen import ProcessingScreen

    fake = install_planner(monkeypatch)
    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ProcessingScreen(store)
    qtbot.addWidget(screen)
    qtbot.wait(50)
    assert fake.calls == []
    assert screen._plan_label.isHidden()
    assert screen._run_btn.isEnabled()
