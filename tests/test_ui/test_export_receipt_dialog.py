"""The export receipt: rows are relative, sizes and short hashes are real."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from ui.dialogs.export_receipt_dialog import ExportReceiptDialog, receipt_rows


def _write(tmp_path: Path) -> tuple[Path, list[Path]]:
    out = tmp_path / "exports" / "20261008"
    (out / "s1").mkdir(parents=True)
    a = out / "s1" / "metrics_long.csv"
    a.write_bytes(b"a,b\n1,2\n")
    b = out / "README.md"
    b.write_text("x" * 1500)
    return out, [a, b]


def test_rows_are_relative_to_the_output_folder_with_size_and_short_hash(tmp_path) -> None:
    out, written = _write(tmp_path)
    rows = receipt_rows(written, out)
    assert [r.name for r in rows] == ["s1/metrics_long.csv", "README.md"]
    assert rows[0].size == "8"
    assert rows[1].size == "1\u202f500"
    assert len(rows[0].short_hash.replace("…", "")) == 8


def test_a_missing_file_shows_dashes_instead_of_failing(tmp_path) -> None:
    out, _ = _write(tmp_path)
    (row,) = receipt_rows([out / "gone.csv"], out)
    assert (row.size, row.short_hash) == ("—", "—")


def test_dialog_lists_every_file_and_copies_the_cli_command(qtbot, tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    out, written = _write(tmp_path)
    dialog = ExportReceiptDialog(out, 2, receipt_rows(written, out), "track2data run p.t2d.json")
    qtbot.addWidget(dialog)
    assert dialog.row_names() == ["s1/metrics_long.csv", "README.md"]
    dialog.copy_cli()
    assert QApplication.clipboard().text() == "track2data run p.t2d.json"


def test_export_screen_opens_the_receipt_after_a_successful_export(qtbot, tmp_path) -> None:
    from track2data.core.models import RunResult, SessionRunResult
    from ui.export_screen import ExportScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    screen = ExportScreen(store)
    qtbot.addWidget(screen)
    out, written = _write(tmp_path)
    screen._current_task_id = "t"
    screen._last_out_dir = out
    screen._last_selected_exporters = ["csv_long"]
    screen._on_task_finished(
        "t", RunResult(sessions=[SessionRunResult(session_id="s1", written=written)])
    )

    dialog = screen._receipt_dialog
    assert dialog.isVisible()
    assert dialog.row_names() == ["s1/metrics_long.csv", "README.md"]
    dialog.close()


def test_no_receipt_when_nothing_was_written(qtbot, tmp_path) -> None:
    from track2data.core.models import RunResult, SessionRunResult
    from ui.export_screen import ExportScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    screen = ExportScreen(store)
    qtbot.addWidget(screen)
    screen._current_task_id = "t"
    screen._last_selected_exporters = []
    screen._on_task_finished("t", RunResult(sessions=[SessionRunResult(session_id="s1")]))
    assert getattr(screen, "_receipt_dialog", None) is None
