"""
Stage 6c — Pipeline run screen (M3 real widgets, issue #23).

Widgets:
  • validate_btn   QPushButton — shows QMessageBox with a hand-rolled
                    validation summary (kept as-is; separate from
                    start_run()'s own Engine.validate() gate below)
  • run_btn        QPushButton — calls start_run()
  • cancel_btn     QPushButton — cancels the in-flight run
  • progress_bar   QProgressBar — driven by ProjectStore.taskProgress
  • status_table   QTableWidget — Session | Status | Frames | Duration,
                    one row per manifest.sessions, updated live from
                    ProjectStore.tasks.taskEvent's ProgressEvent.stage
  • status_label   QLabel  ("Ready" / …)
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: ProgressEvent.stage -> friendly per-session status label. Stages not
#: listed here (e.g. "import", "run") aren't session-scoped in the same
#: way and don't drive this table.
_STAGE_LABELS = {
    "import": "Importing",
    "preprocess": "Preprocessing",
    "metrics": "Computing metrics",
    "export": "Exporting",
    "session": "Done",
}


class ProcessingScreen(QWidget):
    """Stage 6c — Validate and run the preprocessing + metrics pipeline."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._current_task_id: str | None = None
        self._session_rows: dict[str, int] = {}  # session_id -> table row
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)
            store.sessionsChanged.connect(self._rebuild_status_table)
            store.taskProgress.connect(self._on_task_progress)
            store.taskFinished.connect(self._on_task_finished)
            store.tasks.taskEvent.connect(self._on_task_event)
            # taskCancelled is NOT forwarded onto ProjectStore.taskFinished
            # (only taskProgress/taskFailed->taskFinished/taskLog are) --
            # connect it directly via the tasks property for this one case.
            store.tasks.taskCancelled.connect(self._on_task_cancelled)
            self._on_project_changed()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Processing")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Validate the pipeline configuration and run preprocessing + "
            "metric extraction across all sessions."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._validate_btn = QPushButton("Validate pipeline")
        self._validate_btn.clicked.connect(self._validate)
        self._run_btn = QPushButton("Run pipeline")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self.start_run)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(self._validate_btn)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── progress + status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("font-size: 13px; color: #555;")
        root.addWidget(self._status_label)

        self._status_table = QTableWidget(0, 4)
        self._status_table.setHorizontalHeaderLabels(
            ["Session", "Status", "Frames", "Duration"]
        )
        self._status_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._status_table)

        root.addStretch()

    # ── run orchestration ────────────────────────────────────────────────────

    def start_run(self) -> None:
        """
        Validate the current manifest via Engine.validate(), then submit
        the full pipeline run in the background. Public so both this
        screen's own Run button and MainWindow._action_run share the
        one code path.
        """
        if self._store is None or self._store.manifest is None:
            QMessageBox.warning(self, "Run pipeline", "No project is open.")
            return

        from track2data.api import Engine

        manifest = self._store.manifest
        engine = Engine(manifest)
        issues = engine.validate()
        if issues:
            QMessageBox.warning(
                self, "Cannot run pipeline", "Fix these issues first:\n\n" + "\n".join(issues)
            )
            return

        out_dir = self._default_out_dir()
        self._rebuild_status_table()
        self._progress.setValue(0)
        self._status_label.setText(f"Running… writing to {out_dir}")
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._store.append_log(f"### Run started\n_Output: `{out_dir}`_\n")

        run_fn = functools.partial(engine.run, out_dir)
        self._current_task_id = self._store.tasks.submit_with_progress(run_fn)

    def _default_out_dir(self) -> Path:
        project_dir = self._store.project_dir or Path(".")
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        return Path(project_dir) / "exports" / timestamp

    def _cancel_run(self) -> None:
        if self._store is not None:
            self._store.tasks.cancel_all()
        self._status_label.setText("Cancelling…")

    # ── slots ──────────────────────────────────────────────────────────────

    def _validate(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.warning(self, "Validation", "No project is open.")
            return
        m = self._store.manifest
        lines: list[str] = []
        ok = True
        n_sessions = len(m.sessions)
        if n_sessions == 0:
            lines.append("✗  No sessions imported")
            ok = False
        else:
            lines.append(f"✓  {n_sessions} session(s) imported")
        if m.calibration.mode == "scalar" and (
            m.calibration.px_per_cm is None or m.calibration.px_per_cm <= 0
        ):
            lines.append("✗  Scalar calibration: px_per_cm not set")
            ok = False
        else:
            lines.append(f"✓  Calibration: {m.calibration.mode}")
        if m.metrics.individual or m.metrics.group or m.metrics.zone:
            total = len(m.metrics.individual) + len(m.metrics.group) + len(m.metrics.zone)
            lines.append(f"✓  {total} metric(s) selected")
        else:
            lines.append("⚠  No metrics selected")
        summary = "\n".join(lines)
        icon = QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning
        box = QMessageBox(icon, "Pipeline validation", summary, QMessageBox.StandardButton.Ok, self)
        box.exec()

    def _on_project_changed(self) -> None:
        has = self._store is not None and self._store.has_project
        self._validate_btn.setEnabled(has)
        self._run_btn.setEnabled(has)
        self._rebuild_status_table()

    def _rebuild_status_table(self) -> None:
        self._session_rows.clear()
        if self._store is None or self._store.manifest is None:
            self._status_table.setRowCount(0)
            return
        sessions = self._store.manifest.sessions
        self._status_table.setRowCount(len(sessions))
        for row, ref in enumerate(sessions):
            self._session_rows[ref.session_id] = row
            self._status_table.setItem(row, 0, QTableWidgetItem(ref.session_id))
            self._status_table.setItem(row, 1, QTableWidgetItem("Queued"))
            # No frame count is available before a session finishes preprocessing
            # (neither ProgressEvent nor SessionRunResult carries it today).
            self._status_table.setItem(row, 2, QTableWidgetItem("—"))
            self._status_table.setItem(row, 3, QTableWidgetItem("—"))

    def _on_task_progress(self, task_id: str, percent: int) -> None:
        if task_id != self._current_task_id:
            return
        self._progress.setValue(percent)

    def _on_task_event(self, task_id: str, event) -> None:
        if task_id != self._current_task_id:
            return
        if event.session_id is None or event.session_id not in self._session_rows:
            return
        label = _STAGE_LABELS.get(event.stage)
        if label is None:
            return
        row = self._session_rows[event.session_id]
        self._status_table.setItem(row, 1, QTableWidgetItem(label))

    def _on_task_finished(self, task_id: str, result: object) -> None:
        if task_id != self._current_task_id:
            return
        self._current_task_id = None
        self._run_btn.setEnabled(self._store is not None and self._store.has_project)
        self._cancel_btn.setEnabled(False)

        from track2data.core.models import RunResult

        if isinstance(result, RunResult):
            self._store.set_run_results(result)
            for session_result in result.sessions:
                row = self._session_rows.get(session_result.session_id)
                if row is None:
                    continue
                status = "Failed" if session_result.error else "Done"
                self._status_table.setItem(row, 1, QTableWidgetItem(status))
                self._status_table.setItem(
                    row, 3, QTableWidgetItem(f"{session_result.duration_s:.1f}s")
                )
            n_failed = sum(1 for s in result.sessions if s.error)
            if n_failed:
                self._status_label.setText(f"Finished with {n_failed} failed session(s).")
            else:
                self._status_label.setText("Finished.")
            self._store.append_log(
                f"### Run finished\n{len(result.sessions)} session(s), "
                f"{n_failed} failed.\n"
            )
        elif isinstance(result, Exception):
            self._status_label.setText("Failed — see log for details.")
            self._store.append_log(f"### Run failed\n```\n{result}\n```\n")

    def _on_task_cancelled(self, task_id: str) -> None:
        if task_id != self._current_task_id:
            return
        self._current_task_id = None
        self._run_btn.setEnabled(self._store is not None and self._store.has_project)
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("Cancelled.")
        for row in self._session_rows.values():
            item = self._status_table.item(row, 1)
            if item is not None and item.text() not in ("Done", "Failed"):
                self._status_table.setItem(row, 1, QTableWidgetItem("Cancelled"))
        if self._store is not None:
            self._store.append_log("### Run cancelled\n")
