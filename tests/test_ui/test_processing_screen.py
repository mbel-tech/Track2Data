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
    assert screen is not None


def test_run_button_disabled_until_a_project_is_open(qtbot) -> None:
    from app.state import ProjectStore
    from ui.processing_screen import ProcessingScreen

    store = ProjectStore()
    screen = ProcessingScreen(store)
    assert screen._run_btn.isEnabled() is False

    store.new_project("p", Path("."))
    assert screen._run_btn.isEnabled() is True


def test_cancel_button_disabled_until_a_run_is_in_flight(qtbot, tmp_path: Path) -> None:
    from ui.processing_screen import ProcessingScreen

    store = _make_empty_store(tmp_path)
    screen = ProcessingScreen(store)
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

    screen.start_run()
    qtbot.waitUntil(lambda: screen._cancel_btn.isEnabled(), timeout=2000)
    screen._cancel_btn.click()

    qtbot.waitUntil(lambda: screen._run_btn.isEnabled(), timeout=5000)
    assert screen._cancel_btn.isEnabled() is False
