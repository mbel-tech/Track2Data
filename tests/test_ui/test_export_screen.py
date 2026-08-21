"""
Tests for ui/export_screen.py (issue #24) -- real export via the
exporter registry: dynamic checkboxes driven by
track2data.exporters.list_exporters(), a forced-on README provenance
record, an output-directory overwrite guard, and a real end-to-end
Engine.run() submitted through TaskRunner, ending in a receipt table.

Mirrors tests/test_ui/test_processing_screen.py's pattern for the
store/screen setup and the submit -> qtbot.waitSignal(taskFinished) ->
waitUntil(button re-enabled) shape, since that is the established,
tested convention for this exact "submit an Engine.run() and react to
the result" flow in this codebase.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.hashing import file_sha256
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)
from track2data.exporters import list_exporters


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
    """A ProjectStore whose manifest is valid and points at a real,
    importable session folder -- identical in shape to
    test_processing_screen.py's helper of the same name."""
    from app.state import ProjectStore

    store = ProjectStore()
    store._manifest = _make_manifest(session_folder)
    store._project_dir = tmp_path
    return store


def _make_empty_store(tmp_path: Path):
    from app.state import ProjectStore

    store = ProjectStore()
    store.new_project("empty", tmp_path)
    return store


# ── construction ─────────────────────────────────────────────────────────────


def test_screen_constructs_without_a_store(qtbot) -> None:
    from ui.export_screen import ExportScreen

    screen = ExportScreen()
    assert screen is not None


def test_export_button_disabled_until_a_project_is_open(qtbot, tmp_path: Path) -> None:
    from app.state import ProjectStore
    from ui.export_screen import ExportScreen

    store = ProjectStore()
    screen = ExportScreen(store)
    assert screen._export_btn.isEnabled() is False

    store.new_project("p", tmp_path)
    assert screen._export_btn.isEnabled() is True


def test_cancel_button_disabled_until_an_export_is_in_flight(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    assert screen._cancel_btn.isEnabled() is False


# ── dynamic checkboxes from the registry ────────────────────────────────────


def test_checkbox_list_reflects_registered_exporters(qtbot) -> None:
    from ui.export_screen import ExportScreen

    screen = ExportScreen()
    assert set(screen._checks.keys()) == set(list_exporters())
    # A known exporter gets its pretty label, not the bare registry name.
    assert screen._checks["csv_long"].text() == "CSV Long"


# ── readme forced-on ─────────────────────────────────────────────────────────


def test_readme_forced_on_and_disabled_when_another_format_checked(qtbot) -> None:
    from ui.export_screen import ExportScreen

    screen = ExportScreen()
    readme_cb = screen._checks["readme"]
    assert readme_cb.isEnabled() is True  # free when nothing else is checked

    other_name = next(n for n in screen._checks if n != "readme")
    screen._checks[other_name].setChecked(True)

    assert readme_cb.isChecked() is True
    assert readme_cb.isEnabled() is False

    screen._checks[other_name].setChecked(False)
    assert readme_cb.isEnabled() is True


# ── output dir + overwrite confirmation ─────────────────────────────────────


def test_export_button_disabled_when_output_dir_nonempty_until_overwrite_confirmed(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    assert screen._export_btn.isEnabled() is True  # nothing to overwrite yet

    existing_dir = tmp_path / "already_has_stuff"
    existing_dir.mkdir()
    (existing_dir / "old.csv").write_text("x", encoding="utf-8")

    screen._set_output_dir(str(existing_dir))

    assert screen._overwrite_checkbox.isVisible() is True
    assert screen._export_btn.isEnabled() is False

    screen._overwrite_checkbox.setChecked(True)
    assert screen._export_btn.isEnabled() is True


def test_export_uses_project_dir_exports_timestamp_default(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()
    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=2000)

    export_dirs = list((tmp_path / "exports").iterdir())
    assert len(export_dirs) == 1
    # ISO-8601 compact-ish: starts with a 4-digit year, no ":" (illegal on Windows).
    assert export_dirs[0].name[:4].isdigit()
    assert ":" not in export_dirs[0].name


# ── _run_export(): guard ────────────────────────────────────────────────────


def test_run_export_without_a_project_shows_warning_and_does_not_submit(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.state import ProjectStore
    from ui.export_screen import ExportScreen

    warnings: list[str] = []
    monkeypatch.setattr(
        "ui.export_screen.QMessageBox.warning",
        staticmethod(lambda *a, **k: warnings.append(a[2]) or None),
    )

    store = ProjectStore()
    screen = ExportScreen(store)
    started: list[object] = []
    store.tasks.taskStarted.connect(started.append)

    screen._run_export()

    assert len(warnings) == 1
    assert started == []


# ── _run_export(): happy path, end-to-end ───────────────────────────────────


def test_export_runs_end_to_end_and_writes_real_files(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    """The test that proves the GUI<->engine seam actually works end to end."""
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)  # forces readme on too

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()
        assert screen._export_btn.isEnabled() is False
        assert screen._cancel_btn.isEnabled() is True

    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=2000)
    assert screen._cancel_btn.isEnabled() is False

    out_dir = screen._last_out_dir
    assert out_dir is not None
    session_dir = out_dir / tiny_real_session.name
    assert (session_dir / "master_fish_by_frame.csv").exists()
    assert (session_dir / "README.md").exists()
    assert (session_dir / "manifest.json").exists()

    assert store.run_results is not None
    assert len(store.run_results.sessions) == 1
    assert store.run_results.sessions[0].error is None


def test_export_persists_selected_targets_via_update_export_targets(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)  # forces readme on too

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()

    names = {t.exporter_name for t in store.manifest.export_targets}
    assert names == {"csv_long", "readme"}


def test_export_logs_genuine_rerun_note_before_submitting(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)

    logs: list[str] = []
    store.runLogAppended.connect(logs.append)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()

    assert any("re-run" in line.lower() for line in logs)


# ── receipt table ────────────────────────────────────────────────────────────


def test_receipt_action_buttons_disabled_until_a_successful_export(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    assert screen._open_folder_btn.isEnabled() is False
    assert screen._copy_cli_btn.isEnabled() is False


def test_receipt_table_populated_with_correct_file_size_and_hash(
    qtbot, tmp_path: Path, tiny_real_session: Path
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()
    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=2000)

    written = store.run_results.written
    assert len(written) > 0
    assert screen._receipt_table.rowCount() == len(written)
    for row, path in enumerate(written):
        assert screen._receipt_table.item(row, 0).text() == str(path)
        assert screen._receipt_table.item(row, 1).text() == str(path.stat().st_size)
        digest = screen._receipt_table.item(row, 2).text()
        assert digest == file_sha256(path)[: len(digest)]
        assert 8 <= len(digest) <= 12

    assert screen._open_folder_btn.isEnabled() is True
    assert screen._copy_cli_btn.isEnabled() is True


def test_open_folder_button_opens_last_output_directory(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()
    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=2000)

    opened: list[str] = []
    monkeypatch.setattr(
        "ui.export_screen.QDesktopServices.openUrl",
        staticmethod(lambda url: opened.append(url.toLocalFile())),
    )

    screen._open_folder_btn.click()

    assert len(opened) == 1
    assert Path(opened[0]) == screen._last_out_dir


def test_copy_cli_equivalent_builds_expected_command_and_sets_clipboard(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.export_screen import ExportScreen

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)  # forces readme on too

    with qtbot.waitSignal(store.taskFinished, timeout=15000):
        screen._run_export()
    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=2000)

    copied: list[str] = []

    class _FakeClipboard:
        def setText(self, text: str) -> None:  # noqa: N802 -- mirrors Qt's QClipboard API
            copied.append(text)

    fake_clipboard = _FakeClipboard()
    monkeypatch.setattr(
        "ui.export_screen.QApplication.clipboard",
        staticmethod(lambda: fake_clipboard),
    )

    screen._copy_cli_btn.click()

    assert len(copied) == 1
    cmd = copied[0]
    assert cmd.startswith("track2data run ")
    assert "--out-dir" in cmd
    assert str(screen._last_out_dir) in cmd
    assert "--exporter csv_long" in cmd
    assert "--exporter readme" in cmd


# ── cancellation ─────────────────────────────────────────────────────────────


def test_cancel_button_stops_an_in_flight_export(
    qtbot, tmp_path: Path, tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from track2data.api import Engine
    from ui.export_screen import ExportScreen

    real_preprocess = Engine.preprocess

    def slow_preprocess(self, session):
        time.sleep(0.3)
        return real_preprocess(self, session)

    monkeypatch.setattr(Engine, "preprocess", slow_preprocess)

    store = _make_ready_store(tmp_path, tiny_real_session)
    screen = ExportScreen(store)
    screen._checks["csv_long"].setChecked(True)

    screen._run_export()
    qtbot.waitUntil(lambda: screen._cancel_btn.isEnabled(), timeout=2000)
    screen._cancel_btn.click()

    qtbot.waitUntil(lambda: screen._export_btn.isEnabled(), timeout=5000)
    assert screen._cancel_btn.isEnabled() is False
