"""Regression tests for saving visible edits and keeping preview provenance current."""

import pytest
from PySide6.QtGui import QCloseEvent

from track2data.core.manifest import read, write
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    ExportTarget,
    RunResult,
    SessionRunResult,
    ZoneSet,
)


def _window(qtbot, tmp_path):
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("experiment", tmp_path)
    return win


def test_save_commits_visible_calibration_without_waiting(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._go_to_page(2)
    screen = win._stack.currentWidget()
    screen._radio_scalar.setChecked(True)
    screen._px_spin.setValue(42)
    assert screen._auto.pending

    win._action_save_project()

    cfg = read(tmp_path / "experiment.t2d.json").calibration
    assert cfg.mode == "scalar"
    assert cfg.px_per_cm == 42
    assert not win._store.dirty


def test_save_interprets_focused_spinbox_text(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.show()
    win._go_to_page(2)
    screen = win._stack.currentWidget()
    screen._radio_scalar.setChecked(True)
    screen._px_spin.setKeyboardTracking(False)
    edit = screen._px_spin.lineEdit()
    edit.setFocus()
    edit.selectAll()
    qtbot.keyClicks(edit, "73")
    win._action_save_project()
    assert read(tmp_path / "experiment.t2d.json").calibration.px_per_cm == 73


def test_changes_autosave_and_report_saved(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=12))
    qtbot.waitUntil(lambda: not win._store.dirty)
    assert read(tmp_path / "experiment.t2d.json").calibration.px_per_cm == 12
    assert win._save_status.text() == "Saved"


def test_close_flushes_and_saves_before_timer_fires(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._go_to_page(2)
    screen = win._stack.currentWidget()
    screen._radio_scalar.setChecked(True)
    screen._px_spin.setValue(31)
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()
    assert read(tmp_path / "experiment.t2d.json").calibration.px_per_cm == 31


def test_project_replacement_saves_old_and_clears_results(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._store.set_run_results(RunResult(sessions=[SessionRunResult(session_id="old")]))
    win._store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=8))
    win._store.new_project("second", tmp_path)
    assert read(tmp_path / "experiment.t2d.json").calibration.px_per_cm == 8
    assert win._store.run_results is None
    assert win._store.manifest.project_name == "second"


def test_save_failure_keeps_changes_and_blocks_close_and_replacement(
    qtbot, tmp_path, monkeypatch,
):
    win = _window(qtbot, tmp_path)
    original = win._store.manifest
    messages = []
    monkeypatch.setattr("app.main_window.QMessageBox.critical", lambda *a: messages.append(a))

    def fail(*args):
        raise OSError("Disk full")

    with monkeypatch.context() as patch:
        patch.setattr(win._store, "save_project", fail)
        event = QCloseEvent()
        win.closeEvent(event)
        assert not event.isAccepted()
        assert win._store.dirty
        assert not win._store.new_project("second", tmp_path)
        assert win._store.manifest is original
        assert messages


def test_atomic_write_failure_preserves_old_manifest(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    path = win._store.save_project()
    original = path.read_bytes()
    win._store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=99))

    def fail(*args):
        raise OSError("Cannot replace")

    with monkeypatch.context() as patch:
        patch.setattr("track2data.core.manifest.os.replace", fail)
        with pytest.raises(OSError):
            write(win._store.manifest, path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
    assert win._store.dirty


def test_reopened_project_saves_to_original_filename(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    path = tmp_path / "renamed.t2d.json"
    write(win._store.manifest, path)
    win._store.open_project(path)
    win._store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=9))
    assert win._store.save_project() == path
    assert read(path).calibration.px_per_cm == 9


def test_changed_analysis_marks_preview_outdated_but_export_formats_do_not(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    store = win._store
    result = RunResult(sessions=[SessionRunResult(session_id="s")])
    store.set_run_results(result)
    original = store.manifest.calibration
    store.update_export_targets([ExportTarget(exporter_name="csv_long")])
    assert not store.results_stale
    store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=10))
    assert store.results_stale
    preview = win._stack.widget(8)
    assert not preview._freshness_banner.isHidden()
    assert "re-run" in win._sidebar.item(8).data(257)
    assert store.run_results is result
    store.update_calibration(original)
    assert not store.results_stale
    assert preview._freshness_banner.isHidden()


def test_late_result_keeps_captured_settings_and_rejects_previous_project(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    store = win._store
    captured = store.analysis_hash()
    revision = store.project_revision
    store.update_zones(ZoneSet(rois=[ROI(name="A", vertices=[(0, 0), (10, 0), (0, 10)])]))
    result = RunResult(sessions=[SessionRunResult(session_id="s")])
    assert store.set_run_results(result, analysis_hash=captured, project_revision=revision)
    assert store.results_stale
    store.new_project("second", tmp_path)
    assert not store.set_run_results(result, analysis_hash=captured, project_revision=revision)
    assert store.run_results is None


def test_all_failed_run_is_not_labelled_ready(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._store.set_run_results(RunResult(sessions=[SessionRunResult(session_id="s", error="bad")]))
    assert win._sidebar.item(8).data(257) == "No successful sessions"


@pytest.mark.parametrize("page", [7, 9])
def test_run_and_export_capture_settings_before_background_work(
    qtbot, tmp_path, monkeypatch, page,
):
    win = _window(qtbot, tmp_path)
    store = win._store
    monkeypatch.setattr("track2data.api.Engine.validate", lambda _: [])
    monkeypatch.setattr(store.tasks, "submit_with_progress", lambda *a, **kw: "pending")
    screen = win._stack.widget(page)
    if page == 7:
        screen.start_run()
    else:
        screen._run_export()
    store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=15))
    screen._on_task_finished("pending", RunResult(sessions=[SessionRunResult(session_id="s")]))
    assert store.results_stale


@pytest.mark.parametrize("page", [7, 9])
def test_previous_project_completion_does_not_replace_current_results(
    qtbot, tmp_path, monkeypatch, page,
):
    win = _window(qtbot, tmp_path)
    store = win._store
    monkeypatch.setattr("track2data.api.Engine.validate", lambda _: [])
    monkeypatch.setattr(store.tasks, "submit_with_progress", lambda *a, **kw: "pending")
    screen = win._stack.widget(page)
    if page == 7:
        screen.start_run()
    else:
        screen._run_export()
    store.new_project("second", tmp_path)
    screen._on_task_finished("pending", RunResult(sessions=[SessionRunResult(session_id="old")]))
    assert store.run_results is None
