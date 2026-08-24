"""
Stage 7b — Export screen (issue #24): real export via the exporter
registry.

Widgets:
  • QCheckBox per exporter, built dynamically from
    track2data.exporters.list_exporters() -- registry-driven, so
    entry-point-registered plug-in exporters show up automatically.
  • README is forced checked + disabled whenever any other format is
    checked (it's the run's provenance record, not an optional format).
  • browse_btn / dir_label -- output directory, defaulting to
    <project_dir>/exports/<timestamp>/ (same convention as
    ui/processing_screen.py's start_run()).
  • overwrite_list / overwrite_checkbox -- shown when the resolved
    output directory already exists and is non-empty; the checkbox
    must be ticked before Export enables.
  • export_btn / cancel_btn -- submit/cancel the run via
    ProjectStore.tasks (TaskRunner), mirroring
    ui/processing_screen.py's start_run()/_cancel_run() structure.
  • receipt_table -- File | Size (bytes) | SHA-256, one row per path
    written by the last successful run, plus "Open folder" and
    "Copy CLI equivalent" actions.
"""

from __future__ import annotations

import contextlib
import functools
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.hashing import file_sha256
from track2data.core.models import ExportTarget, RunResult
from track2data.exporters import list_exporters
from ui.widgets.labels import label_for

#: registry name -> pretty label. Anything not listed here falls back
#: to a title-cased version of the raw name (ui/widgets/labels.py), so
#: future entry-point exporters still show up with *some* reasonable
#: label automatically.
_LABELS = {
    "csv_long": "CSV Long",
    "csv_wide": "CSV Wide",
    "excel": "Excel",
    "feather": "Feather",
    "readme": "README",
}

_README_TOOLTIP = (
    "README.md + manifest.json are this run's provenance record, not an "
    "optional export format -- kept on whenever any other format is selected."
)

#: length (hex chars) of the short hash shown in the receipt table.
_SHORT_HASH_LEN = 10


def _label_for(name: str) -> str:
    return label_for(name, _LABELS)


class ExportScreen(QWidget):
    """Stage 7b — select export formats, choose an output directory, and
    run the real pipeline export via the Engine/TaskRunner seam."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._output_dir: str = ""
        self._default_dir_cache: Path | None = None
        self._current_task_id: str | None = None
        self._last_out_dir: Path | None = None
        self._last_selected_exporters: list[str] = []
        self._checks: dict[str, QCheckBox] = {}
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)
            store.taskFinished.connect(self._on_task_finished)
            store.tasks.taskCancelled.connect(self._on_task_cancelled)
            self._on_project_changed()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Export")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel("Choose export formats and target directory.")
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── exporter checkboxes ───────────────────────────────────────────
        fmt_group = QGroupBox("Export formats")
        fmt_layout = QVBoxLayout(fmt_group)
        for name in list_exporters():
            cb = QCheckBox(_label_for(name))
            cb.setChecked(name == "readme")
            if name == "readme":
                cb.setToolTip(_README_TOOLTIP)
            else:
                cb.stateChanged.connect(self._recompute_readme_forced)
            self._checks[name] = cb
            fmt_layout.addWidget(cb)
        root.addWidget(fmt_group)
        self._recompute_readme_forced()

        # ── output directory ──────────────────────────────────────────────
        dir_row = QHBoxLayout()
        browse_btn = QPushButton("Browse output directory…")
        browse_btn.clicked.connect(self._browse_dir)
        self._dir_label = QLabel("(defaults to project exports directory)")
        self._dir_label.setStyleSheet("color: #666; font-style: italic;")
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(self._dir_label, 1)
        root.addLayout(dir_row)

        # ── overwrite warning + confirmation ────────────────────────────────
        self._overwrite_list = QListWidget()
        self._overwrite_list.setMaximumHeight(90)
        self._overwrite_list.setVisible(False)
        root.addWidget(self._overwrite_list)

        self._overwrite_checkbox = QCheckBox(
            "I understand this will overwrite existing files"
        )
        self._overwrite_checkbox.setVisible(False)
        self._overwrite_checkbox.stateChanged.connect(self._update_export_enabled)
        root.addWidget(self._overwrite_checkbox)

        # ── export / cancel buttons ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._run_export)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_export)
        btn_row.addWidget(self._export_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 13px; color: #555;")
        root.addWidget(self._status_label)

        # ── receipt table ────────────────────────────────────────────────
        receipt_group = QGroupBox("Last export receipt")
        receipt_layout = QVBoxLayout(receipt_group)
        self._receipt_table = QTableWidget(0, 3)
        self._receipt_table.setHorizontalHeaderLabels(["File", "Size (bytes)", "SHA-256"])
        self._receipt_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._receipt_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        receipt_layout.addWidget(self._receipt_table)

        receipt_btn_row = QHBoxLayout()
        self._open_folder_btn = QPushButton("Open folder")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        self._copy_cli_btn = QPushButton("Copy CLI equivalent")
        self._copy_cli_btn.setEnabled(False)
        self._copy_cli_btn.clicked.connect(self._copy_cli_equivalent)
        receipt_btn_row.addWidget(self._open_folder_btn)
        receipt_btn_row.addWidget(self._copy_cli_btn)
        receipt_btn_row.addStretch()
        receipt_layout.addLayout(receipt_btn_row)

        root.addWidget(receipt_group)

        root.addStretch()

    # ── readme forced-on ─────────────────────────────────────────────────────

    def _recompute_readme_forced(self, _state: int | None = None) -> None:
        readme_cb = self._checks.get("readme")
        if readme_cb is None:
            return
        others_checked = any(
            cb.isChecked() for name, cb in self._checks.items() if name != "readme"
        )
        if others_checked:
            readme_cb.setChecked(True)
            readme_cb.setEnabled(False)
        else:
            readme_cb.setEnabled(True)

    # ── output directory / overwrite guard ──────────────────────────────────

    def _browse_dir(self) -> None:
        has_project = self._store is not None and self._store.has_project
        default = str(self._resolved_out_dir()) if has_project else ""
        directory = QFileDialog.getExistingDirectory(
            self, "Select output directory", default
        )
        if directory:
            self._set_output_dir(directory)

    def _set_output_dir(self, directory: str) -> None:
        self._output_dir = directory
        self._dir_label.setText(directory)
        self._dir_label.setStyleSheet("color: #2c3e50;")
        self._check_overwrite()

    def _default_dir(self) -> Path:
        """The timestamped default output directory, computed once and
        cached so the overwrite check and the actual run agree on the
        same path (a fresh datetime.now() on every access could let the
        two drift apart)."""
        if self._default_dir_cache is None:
            project_dir = self._store.project_dir if self._store is not None else None
            project_dir = Path(project_dir) if project_dir is not None else Path(".")
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            self._default_dir_cache = project_dir / "exports" / timestamp
        return self._default_dir_cache

    def _resolved_out_dir(self) -> Path:
        if self._output_dir:
            return Path(self._output_dir)
        return self._default_dir()

    def _check_overwrite(self) -> None:
        out_dir = self._resolved_out_dir()
        existing: list[str] = []
        if out_dir.exists() and out_dir.is_dir():
            existing = sorted(p.name for p in out_dir.iterdir())

        self._overwrite_list.clear()
        if existing:
            self._overwrite_list.addItems(existing)
        self._overwrite_list.setVisible(bool(existing))
        self._overwrite_checkbox.setVisible(bool(existing))
        self._overwrite_checkbox.setChecked(False)
        self._update_export_enabled()

    # ── export / cancel ──────────────────────────────────────────────────────

    def _update_export_enabled(self, _state: int | None = None) -> None:
        has_project = self._store is not None and self._store.has_project
        running = self._current_task_id is not None
        needs_overwrite_ack = (
            self._overwrite_checkbox.isVisible() and not self._overwrite_checkbox.isChecked()
        )
        self._export_btn.setEnabled(has_project and not running and not needs_overwrite_ack)
        self._cancel_btn.setEnabled(running)

    def _run_export(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.warning(self, "Export", "No project is open.")
            return

        from track2data.api import Engine

        selected = [name for name, cb in self._checks.items() if cb.isChecked()]
        out_dir = self._resolved_out_dir()

        self._store.update_export_targets(
            [ExportTarget(exporter_name=name) for name in selected]
        )

        self._store.append_log(
            "### Export started\n"
            f"_Output: `{out_dir}`_\n\n"
            "Export re-runs the full pipeline (preprocess, metrics, and "
            "export) for every session -- per-session results are never "
            "cached between runs, so this is a genuine re-run rather than "
            "a re-export of previously computed results.\n"
        )

        engine = Engine(self._store.manifest)
        run_fn = functools.partial(engine.run, out_dir, exporters=selected)

        self._last_out_dir = out_dir
        self._last_selected_exporters = selected
        self._status_label.setText(f"Exporting… writing to {out_dir}")
        self._current_task_id = self._store.tasks.submit_with_progress(run_fn)
        self._update_export_enabled()

    def _cancel_export(self) -> None:
        if self._store is not None:
            self._store.tasks.cancel_all()
        self._status_label.setText("Cancelling…")

    # ── slots ──────────────────────────────────────────────────────────────

    def _on_project_changed(self) -> None:
        self._default_dir_cache = None
        self._output_dir = ""
        has_project = self._store is not None and self._store.has_project
        if has_project:
            self._dir_label.setText(str(self._resolved_out_dir()))
            self._dir_label.setStyleSheet("color: #555;")
        else:
            self._dir_label.setText("(defaults to project exports directory)")
            self._dir_label.setStyleSheet("color: #666; font-style: italic;")
        self._check_overwrite()

    def _on_task_finished(self, task_id: str, result: object) -> None:
        if task_id != self._current_task_id:
            return
        self._current_task_id = None
        self._update_export_enabled()

        if isinstance(result, RunResult):
            self._store.set_run_results(result)
            self._populate_receipt_table(result)
            n_failed = sum(1 for s in result.sessions if s.error)
            if n_failed:
                self._status_label.setText(f"Finished with {n_failed} failed session(s).")
            else:
                self._status_label.setText("Finished.")
            self._store.append_log(
                f"### Export finished\n{len(result.sessions)} session(s), "
                f"{n_failed} failed.\n"
            )
            self._open_folder_btn.setEnabled(True)
            self._copy_cli_btn.setEnabled(True)
        elif isinstance(result, Exception):
            self._status_label.setText("Failed — see log for details.")
            self._store.append_log(f"### Export failed\n```\n{result}\n```\n")

    def _on_task_cancelled(self, task_id: str) -> None:
        if task_id != self._current_task_id:
            return
        self._current_task_id = None
        self._update_export_enabled()
        self._status_label.setText("Cancelled.")
        if self._store is not None:
            self._store.append_log("### Export cancelled\n")

    # ── receipt table ────────────────────────────────────────────────────────

    def _populate_receipt_table(self, result: RunResult) -> None:
        written = result.written
        self._receipt_table.setRowCount(len(written))
        for row, path in enumerate(written):
            self._receipt_table.setItem(row, 0, QTableWidgetItem(str(path)))

            size_text = "—"
            with contextlib.suppress(OSError):
                size_text = str(path.stat().st_size)
            self._receipt_table.setItem(row, 1, QTableWidgetItem(size_text))

            hash_text = "—"
            with contextlib.suppress(OSError):
                hash_text = file_sha256(path)[:_SHORT_HASH_LEN]
            self._receipt_table.setItem(row, 2, QTableWidgetItem(hash_text))

    def _open_output_folder(self) -> None:
        if self._last_out_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_out_dir)))

    def _cli_equivalent(self) -> str:
        manifest = self._store.manifest
        project_dir = self._store.project_dir or Path(".")
        manifest_path = Path(project_dir) / f"{manifest.project_name}.t2d.json"
        out_dir = self._last_out_dir or self._resolved_out_dir()

        parts = ["track2data", "run", f'"{manifest_path}"', "--out-dir", f'"{out_dir}"']
        for name in self._last_selected_exporters:
            parts += ["--exporter", name]
        return " ".join(parts)

    def _copy_cli_equivalent(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        QApplication.clipboard().setText(self._cli_equivalent())
