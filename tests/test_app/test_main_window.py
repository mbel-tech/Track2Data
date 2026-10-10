"""
Tests for app/main_window.py (issue #22) -- wiring MainWindow._action_run /
_action_validate to the real Engine, with exactly one run code path shared
with ui/processing_screen.py's own Run button (ProcessingScreen.start_run()).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

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


def _make_ready_window(qtbot, tmp_path: Path, session_folder: Path):
    """A MainWindow whose internal store's manifest is valid (Engine.validate()
    -> no issues) and points at a real, importable session folder. Poking
    store._manifest/_project_dir directly mirrors tests/test_ui/test_processing_screen.py's
    own _make_ready_store helper -- accepted test-only practice."""
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._store._manifest = _make_manifest(session_folder)
    win._store._project_dir = tmp_path
    return win


# ── _action_validate ────────────────────────────────────────────────────────


def test_action_validate_with_no_project_shows_warning_and_does_not_crash(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main_window import MainWindow

    warnings: list[str] = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    win = MainWindow()
    qtbot.addWidget(win)

    win._action_validate()  # must not raise

    assert len(warnings) == 1


def test_action_validate_with_issues_disables_run_action_and_shows_warning(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main_window import MainWindow

    warnings: list[str] = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("empty", tmp_path)  # no sessions, no metrics -> issues
    win._run_action.setEnabled(True)  # prove validate() is what disables it

    win._action_validate()

    assert win._run_action.isEnabled() is False
    assert len(warnings) == 1
    assert "No sessions" in warnings[0] or "No metrics" in warnings[0]


def test_action_validate_with_no_issues_enables_run_action_and_shows_message(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main_window import MainWindow

    infos: list[str] = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.information",
        staticmethod(lambda *a, **k: infos.append(a[2]) or None),
    )

    win = MainWindow()
    qtbot.addWidget(win)
    win._store._manifest = _make_manifest(tiny_real_session)
    win._store._project_dir = tmp_path

    win._action_validate()

    assert win._run_action.isEnabled() is True
    assert len(infos) == 1


# ── _action_run ──────────────────────────────────────────────────────────────


def test_action_run_with_no_project_shows_warning_and_does_not_navigate(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main_window import MainWindow

    warnings: list[str] = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    win = MainWindow()
    qtbot.addWidget(win)

    win._action_run()

    assert len(warnings) == 1
    assert win._stack.currentIndex() == 0


def test_action_run_navigates_to_processing_page_and_runs_real_pipeline(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    """Proves the GUI<->engine seam end to end through MainWindow, and that
    _action_run shares ProcessingScreen's one real run code path."""
    win = _make_ready_window(qtbot, tmp_path, tiny_real_session)
    assert win._stack.currentIndex() == 0

    with qtbot.waitSignal(win._store.taskFinished, timeout=15000):
        win._action_run()
        assert win._stack.currentIndex() == 7
        assert win._stack.currentWidget() is win._processing_screen

    # ProcessingScreen's own Run button re-enables itself on completion --
    # this is a defensive readiness check (see test_processing_screen.py's
    # equivalent assertions), not something MainWindow._run_action does;
    # nothing in issue #22 asks the toolbar action to resync post-run.
    qtbot.waitUntil(lambda: win._processing_screen._run_btn.isEnabled(), timeout=2000)

    out_dirs = list(tmp_path.glob("exports/*/"))
    assert len(out_dirs) == 1
    session_dir = out_dirs[0] / tiny_real_session.name
    assert (session_dir / "master_fish_by_frame.csv").exists()


# ── toolbar Cancel action ─────────────────────────────────────────────────────


def test_cancel_action_exists_and_starts_disabled(qtbot) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    assert win._cancel_action.isEnabled() is False


def test_cancel_action_enabled_on_start_and_disabled_on_finish(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Slow the pipeline down enough to reliably observe the in-flight state --
    # same technique as test_cancel_action_disabled_after_cancellation below.
    # Without this, a fast enough run can finish within the same GUI-thread
    # event-loop pass that delivers taskStarted: qtbot.waitSignal's exec()
    # loop drains every already-queued event (started AND finished) before
    # returning, so _cancel_action is back to disabled by the time the
    # assertion below runs -- reproduced on Linux/macOS CI, not locally on
    # Windows, where thread scheduling happened to never win that race.
    import time

    from track2data.api import Engine

    real_preprocess = Engine.preprocess

    def slow_preprocess(self, session):
        time.sleep(0.3)
        return real_preprocess(self, session)

    monkeypatch.setattr(Engine, "preprocess", slow_preprocess)

    win = _make_ready_window(qtbot, tmp_path, tiny_real_session)
    assert win._cancel_action.isEnabled() is False

    with qtbot.waitSignal(win._store.tasks.taskStarted, timeout=5000):
        win._action_run()

    qtbot.waitUntil(lambda: win._cancel_action.isEnabled(), timeout=2000)
    assert win._cancel_action.isEnabled() is True

    qtbot.waitUntil(lambda: not win._cancel_action.isEnabled(), timeout=15000)


def test_cancel_action_disabled_after_cancellation(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Slow the pipeline down enough to reliably trigger Cancel mid-run --
    # same technique as test_processing_screen.py::test_cancel_button_stops_an_in_flight_run.
    import time

    from track2data.api import Engine

    real_preprocess = Engine.preprocess

    def slow_preprocess(self, session):
        time.sleep(0.3)
        return real_preprocess(self, session)

    monkeypatch.setattr(Engine, "preprocess", slow_preprocess)

    win = _make_ready_window(qtbot, tmp_path, tiny_real_session)

    win._action_run()
    qtbot.waitUntil(lambda: win._cancel_action.isEnabled(), timeout=2000)

    win._cancel_action.trigger()

    qtbot.waitUntil(lambda: not win._cancel_action.isEnabled(), timeout=5000)


# ── task failure dialog ────────────────────────────────────────────────────────


def test_task_failure_shows_a_dialog_with_message_and_traceback(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine.run is patched directly, not a sub-step: a session-level
    exception from import/preprocess/metrics/export is caught by
    Engine._run_one_unit into SessionRunResult.error and still yields
    a *successful* RunResult, never a taskFinished(..., Exception) --
    that's the whole point of #7's fix, extending the same per-session
    resilience that already covered preprocess/metrics/export to import
    too. Only a failure outside that per-session try/except -- something
    breaking Engine.run() itself, not any one session's pipeline --
    actually reaches TaskRunner's `failed` signal, so this patches run()
    at the top level rather than trying to find an internal call that's
    still "outside the net"."""
    from track2data.api import Engine
    from track2data.core.errors import ProcessingError

    def boom(self, *args, **kwargs):
        raise ProcessingError(
            "synthetic run failure",
            code="E-999",
            subject="engine",
            remediation="retry the run",
        )

    monkeypatch.setattr(Engine, "run", boom)

    boxes: list = []
    monkeypatch.setattr("app.main_window.QMessageBox.exec", lambda self: boxes.append(self))

    win = _make_ready_window(qtbot, tmp_path, tiny_real_session)

    with qtbot.waitSignal(win._store.taskFinished, timeout=15000):
        win._action_run()

    assert len(boxes) == 1
    text = boxes[0].text()
    assert "synthetic run failure" in text
    assert "[E-999]" in text
    assert "subject: engine" in text
    assert "fix: retry the run" in text
    assert boxes[0].detailedText() != ""
    assert "ProcessingError" in boxes[0].detailedText()


def test_successful_run_does_not_show_the_failure_dialog(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boxes: list = []
    monkeypatch.setattr("app.main_window.QMessageBox.exec", lambda self: boxes.append(self))

    win = _make_ready_window(qtbot, tmp_path, tiny_real_session)

    with qtbot.waitSignal(win._store.taskFinished, timeout=15000):
        win._action_run()

    assert boxes == []


# ── closeEvent ─────────────────────────────────────────────────────────────────


def test_close_event_shuts_down_the_task_runner(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    calls: list[int] = []
    monkeypatch.setattr(win._store.tasks, "shutdown", lambda msecs=5000: calls.append(msecs))

    win.close()

    assert calls == [5000]


def test_leaving_a_parameter_screen_commits_pending_edits(qtbot, tmp_path: Path) -> None:
    """GUI-01: an edit made just before navigating must not be lost."""
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("p", tmp_path)

    pre = win._stack.widget(5)  # Preprocessing
    win._go_to_page(5)
    pre._gap_max.setValue(91)
    assert win._store.manifest.preprocess.gap_fill.max_gap_frames != 91  # still debounced

    win._go_to_page(6)  # leave without waiting for the debounce
    assert win._store.manifest.preprocess.gap_fill.max_gap_frames == 91


# ── GUI-03: stage badges, Next gating, advance after create ──────────────────


def test_creating_a_project_advances_to_sessions(qtbot, tmp_path: Path) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert win._stack.currentIndex() == 0
    win._store.new_project("p", tmp_path)
    assert win._stack.currentIndex() == 1


def test_next_is_disabled_until_the_page_is_complete(qtbot, tmp_path: Path) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert not win._next_action.isEnabled()  # no project yet
    assert "project" in win._next_action.toolTip().lower()

    win._store.new_project("p", tmp_path)  # now on Sessions, which is empty
    assert not win._next_action.isEnabled()
    assert "session" in win._next_action.toolTip().lower()

    ref = SessionRef(session_id="s1", folder=tmp_path, sha256="x")
    win._store.update_sessions([ref])
    assert win._next_action.isEnabled()


def test_sidebar_shows_status_badges(qtbot, tmp_path: Path) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert win._sidebar.status(1) == "blocked"  # no project
    win._store.new_project("p", tmp_path)
    assert win._sidebar.status(0) == "valid"
    assert win._sidebar.status(1) == "empty"
    assert win._sidebar.item(0).data(Qt.ItemDataRole.UserRole) == "valid"
    win._store.update_sessions([SessionRef(session_id="s1", folder=tmp_path, sha256="x")])
    assert win._sidebar.status(1) == "valid"


def test_status_bar_session_count_follows_added_sessions(qtbot, tmp_path: Path) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("p", tmp_path)
    assert "Sessions: 0" in win._status_project.text()
    win._store.update_sessions([SessionRef(session_id="s1", folder=tmp_path, sha256="x")])
    assert "Sessions: 1" in win._status_project.text()


def test_help_menu_opens_the_user_guide(qtbot, monkeypatch) -> None:
    from app import main_window
    from app.main_window import GUIDE_URL, MainWindow

    opened = []
    monkeypatch.setattr(
        main_window.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url))
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win._action_open_guide()
    assert opened[0].toString() == GUIDE_URL
    assert GUIDE_URL.endswith("/docs/guide/USER_GUIDE.md")


# ── probes must not drive the run-oriented chrome ─────────────────────────────


def test_failed_probe_shows_no_failure_dialog(qtbot, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from app.main_window import MainWindow

    shown: list[int] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1) or 0)
    monkeypatch.setattr(
        "track2data.readers.probe_session",
        lambda folder: (_ for _ in ()).throw(RuntimeError("bad folder")),
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("p", tmp_path)
    folder = tmp_path / "s"
    folder.mkdir()
    logged: list[str] = []
    win._store.runLogAppended.connect(logged.append)
    win._store.add_session(folder)
    qtbot.waitUntil(lambda: any("Identity probe failed" in x for x in logged), timeout=3000)
    qtbot.wait(100)
    assert shown == []


def test_probe_finishing_during_a_run_does_not_disable_cancel(qtbot, tmp_path: Path) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._cancel_action.setEnabled(True)  # as if a run were in flight
    win._store.tasks.probeFinished.emit("t", object())
    win._store.tasks.probeFailed.emit("t", "x", "tb")
    win._store.tasks.probeCancelled.emit("t")
    assert win._cancel_action.isEnabled()
