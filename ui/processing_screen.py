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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.parallel import worker_count
from ui.widgets.weak_slot import weak_slot

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

    #: A setup check was clicked: the wizard page to show.
    navigateRequested = Signal(int)

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._current_task_id: str | None = None
        self._run_analysis_hash: str | None = None
        self._run_project_revision: int | None = None
        self._session_rows: dict[str, int] = {}  # session_id -> table row
        self._parallel_run = False
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
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Processing")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Check the setup, then run import → preprocess → metrics for every session."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageLead")
        root.addWidget(subtitle)

        root.addWidget(self._build_setup_check())

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._validate_btn = QPushButton("Validate pipeline")
        self._validate_btn.setProperty("role", "outline")
        self._validate_btn.clicked.connect(self._validate)
        self._run_btn = QPushButton("Run pipeline")
        self._run_btn.setProperty("role", "accent")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self.start_run)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("role", "outline")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(self._validate_btn)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(16)
        btn_row.addWidget(QLabel("Workers:"))
        self._workers = QSpinBox()
        self._workers.setRange(1, max(1, worker_count(None)))
        self._workers.setValue(1)
        self._workers.setToolTip(
            "Sessions processed at the same time. 1 runs them one after another."
        )
        self._workers.hide()  # the segmented control below drives it
        btn_row.addWidget(self._build_workers_segments())
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── progress + status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._status_label = QLabel("Ready")
        self._status_label.setProperty("role", "faint")
        root.addWidget(self._status_label)

        self._status_table = QTableWidget(0, 4)
        self._status_table.setHorizontalHeaderLabels(
            ["Session", "Status", "Frames", "Duration"]
        )
        self._status_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._status_table.verticalHeader().hide()
        self._status_table.verticalHeader().setDefaultSectionSize(40)
        self._status_table.setShowGrid(False)
        root.addWidget(self._status_table)

        root.addWidget(self._build_cli_box())
        root.addStretch()
        self._workers.valueChanged.connect(self._refresh_cli_box)
        self._refresh_setup_check()
        self._refresh_cli_box()

    # ── setup check and headless command ────────────────────────────────────

    #: (check name, wizard page whose status it shows)
    _CHECKS = (
        ("Sessions", 1), ("Calibration", 2), ("Zones", 3),
        ("Metadata", 4), ("Preprocessing", 5), ("Metrics", 6),
    )

    #: Worker counts offered by the segmented control (those above the CPU count are disabled).
    _WORKER_CHOICES = (1, 2, 4, 8)

    def _set_workers(self, n: int) -> None:
        self._workers.setValue(n)

    def _request_page(self, page: int) -> None:
        self.navigateRequested.emit(page)

    def _build_workers_segments(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        group = QButtonGroup(box)
        group.setExclusive(True)
        self._worker_buttons: dict[int, QPushButton] = {}
        top = self._workers.maximum()
        for n in self._WORKER_CHOICES:
            btn = QPushButton(str(n))
            btn.setProperty("role", "segment")
            btn.setCheckable(True)
            btn.setEnabled(n <= top)
            btn.setToolTip(self._workers.toolTip())
            btn.clicked.connect(weak_slot(self._set_workers, n))
            group.addButton(btn)
            row.addWidget(btn)
            self._worker_buttons[n] = btn
        self._workers.valueChanged.connect(self._sync_worker_buttons)
        self._sync_worker_buttons(self._workers.value())
        return box

    def _sync_worker_buttons(self, value: int) -> None:
        for n, btn in self._worker_buttons.items():
            btn.setChecked(n == value)

    def _build_setup_check(self) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(10)
        self._check_title = QLabel("Setup check")
        self._check_title.setObjectName("CardTitle")
        col.addWidget(self._check_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self._check_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for i, (name, _page) in enumerate(self._CHECKS):
            dot = QLabel()
            dot.setFixedSize(18, 18)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setProperty("check", "ok")
            text = QLabel()
            text.setWordWrap(True)
            dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            button = QPushButton()
            button.setObjectName("CheckCell")
            button.setFlat(True)
            button.setMinimumHeight(52)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Go to {name}")
            button.clicked.connect(weak_slot(self._request_page, _page))
            cell = QHBoxLayout(button)
            cell.setContentsMargins(6, 4, 6, 4)
            cell.setSpacing(10)
            cell.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            cell.addWidget(text, 1)
            grid.addWidget(button, i // 3, i % 3)
            self._check_labels[name] = (dot, text)
        col.addLayout(grid)
        if self._store is not None:
            for sig in (
                self._store.projectChanged,
                self._store.sessionsChanged,
                self._store.calibrationChanged,
                self._store.zonesChanged,
                self._store.metadataChanged,
                self._store.preprocessChanged,
                self._store.metricsChanged,
                self._store.runResultsChanged,
            ):
                sig.connect(self._refresh_setup_check)
        return card

    def _refresh_setup_check(self) -> None:
        from ui.store.stage_status import compute_stage_statuses, stage_summaries

        manifest = self._store.manifest if self._store is not None else None
        has_run = self._store is not None and self._store.run_results is not None
        infos = compute_stage_statuses(manifest, has_run_results=has_run)
        summaries = stage_summaries(manifest, has_run_results=has_run)
        problems = 0
        for name, page in self._CHECKS:
            info = infos[page]
            optional = page in (3, 4)  # zones and metadata never block a run
            if info.status == "valid":
                kind, glyph = "ok", "✓"
            elif info.status == "warning" or (info.status == "empty" and optional):
                kind, glyph = "warn", "!"
            else:
                kind, glyph = "err", "!"
                problems += 1
            dot, text = self._check_labels[name]
            dot.setText(glyph)
            dot.setProperty("check", kind)
            dot.style().unpolish(dot)
            dot.style().polish(dot)
            text.setText(f"<b>{name}</b><br>{summaries[page]}")
            text.setToolTip(info.message)
        if manifest is None:
            self._check_title.setText("Setup check")
        elif problems:
            noun = "issue" if problems == 1 else "issues"
            self._check_title.setText(f"{problems} {noun} to fix before running")
        else:
            self._check_title.setText("Ready to run")

    def _build_cli_box(self) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 12, 18, 12)
        col.setSpacing(6)
        head = QHBoxLayout()
        label = QLabel("SAME RUN, HEADLESS")
        label.setObjectName("SectionLabel")
        head.addWidget(label)
        head.addStretch()
        copy = QPushButton("Copy command")
        copy.setProperty("role", "link")
        copy.setFlat(True)
        copy.clicked.connect(self._copy_cli)
        head.addWidget(copy)
        col.addLayout(head)
        self._cli_label = QLabel()
        self._cli_label.setObjectName("CliSnippet")
        self._cli_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self._cli_label)
        return card

    def cli_command(self) -> str:
        name = "<project>"
        if self._store is not None and self._store.manifest is not None:
            name = self._store.manifest.project_name
        return f"track2data run {name}.t2d.json --workers {self._workers.value()}"

    def _refresh_cli_box(self) -> None:
        self._cli_label.setText(self.cli_command())

    def _copy_cli(self) -> None:
        QApplication.clipboard().setText(self.cli_command())

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
        # Do not queue another run while the current one is still finishing.
        if self._current_task_id is not None:
            return

        from track2data.api import Engine

        manifest = self._store.manifest
        self._run_analysis_hash = self._store.analysis_hash()
        self._run_project_revision = self._store.project_revision
        engine = Engine(manifest, cache_dir=self._store.cache_dir)
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

        n_workers = self._workers.value()
        self._parallel_run = n_workers > 1
        run_fn = functools.partial(engine.run, out_dir, n_workers=n_workers)
        self._current_task_id = self._store.tasks.submit_with_progress(
            run_fn, cancel_check=True
        )

    def _default_out_dir(self) -> Path:
        project_dir = self._store.project_dir or Path(".")
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        return Path(project_dir) / "exports" / timestamp

    def _cancel_run(self) -> None:
        if self._store is not None:
            self._store.tasks.cancel_all(lane="run")
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
        if task_id != self._current_task_id or self._parallel_run:
            return  # parallel runs drive the bar from session events instead
        self._progress.setValue(percent)

    def _on_task_event(self, task_id: str, event) -> None:
        if task_id != self._current_task_id:
            return
        if self._parallel_run and event.stage in ("session", "run"):
            # Stage events of concurrent sessions interleave, so the bar
            # follows completed sessions only.
            self._progress.setValue(event.percent)
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
            accepted = self._store.set_run_results(
                result, analysis_hash=self._run_analysis_hash,
                project_revision=self._run_project_revision,
            )
            if not accepted:
                self._status_label.setText("Finished for a previous project.")
                return
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
