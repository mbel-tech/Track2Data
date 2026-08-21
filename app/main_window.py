"""
Main application window.

Implements the QMainWindow shell described in UI_DESIGN.md §3:
  • QMenuBar    (File / Edit / Run / View / Help)
  • QToolBar    (Back / Next / Run / Export)
  • LeftDock    WizardSidebar — 7 stage tiles, completion ticks
  • Central     QStackedWidget — 10 placeholder wizard pages
  • BottomDock  RunLogDock — scrollable Markdown run log
  • StatusBar   project name · worker count · cache info
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.navigation import WizardSidebar
from app.state import ProjectStore
from ui.calibration_screen import CalibrationScreen
from ui.export_screen import ExportScreen
from ui.import_screen import ImportScreen
from ui.metadata_screen import MetadataScreen
from ui.metrics_screen import MetricsScreen
from ui.preprocessing_screen import PreprocessingScreen
from ui.preview_screen import PreviewScreen
from ui.processing_screen import ProcessingScreen

# Placeholder screen imports — all 10 wizard pages.
from ui.project_screen import ProjectScreen
from ui.zones_screen import ZonesScreen

APP_NAME = "Track2Data"
APP_VERSION = "0.1.0"


class RunLogDock(QWidget):
    """Scrollable Markdown run-log viewer (bottom dock)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        self._label = QLabel("No activity yet.")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._label.setStyleSheet("color: #ddd; font-size: 11px; font-family: monospace;")
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        scroll = QScrollArea()
        scroll.setWidget(self._label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: #1a1a2e; border: none;")
        layout.addWidget(scroll)

        self._lines: list[str] = []

    def append(self, text: str) -> None:
        self._lines.append(text)
        # Keep last 200 lines to avoid unbounded growth.
        if len(self._lines) > 200:
            self._lines = self._lines[-200:]
        self._label.setText("\n".join(self._lines))


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1200, 720)

        # ── project state ──────────────────────────────────────────────────
        self._store = ProjectStore(parent=self)

        # ── central stacked widget ─────────────────────────────────────────
        self._stack = QStackedWidget()
        pages: list[QWidget] = [
            ProjectScreen(self._store),      # 0 — stage 0
            ImportScreen(self._store),       # 1 — stage 1
            CalibrationScreen(self._store),  # 2 — stage 2
            ZonesScreen(self._store),        # 3 — stage 3
            MetadataScreen(self._store),     # 4 — stage 4
            PreprocessingScreen(self._store),# 5 — stage 5 (first)
            MetricsScreen(self._store),      # 6 — stage 5
            ProcessingScreen(self._store),   # 7 — stage 5 (last)
            PreviewScreen(self._store),      # 8 — stage 6 (first)
            ExportScreen(self._store),       # 9 — stage 6 (last)
        ]
        # Direct reference (not a self._stack index lookup) so _action_run()
        # has exactly one call path into the real run, shared with this
        # screen's own Run button (issue #22).
        self._processing_screen = pages[7]
        for page in pages:
            self._stack.addWidget(page)
        self.setCentralWidget(self._stack)

        # ── sidebar ────────────────────────────────────────────────────────
        self._sidebar = WizardSidebar()
        sidebar_dock = QDockWidget("Workflow", self)
        sidebar_dock.setWidget(self._sidebar)
        sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        sidebar_dock.setTitleBarWidget(self._make_sidebar_header())
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, sidebar_dock)

        # ── run log dock ───────────────────────────────────────────────────
        self._run_log = RunLogDock()
        self._log_dock = QDockWidget("Run Log", self)
        self._log_dock.setWidget(self._run_log)
        self._log_dock.setMinimumHeight(100)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        # ── chrome ────────────────────────────────────────────────────────
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        # ── wire signals ──────────────────────────────────────────────────
        self._sidebar.stage_page_selected.connect(self._go_to_page)
        self._store.projectChanged.connect(self._update_statusbar)
        self._store.runLogAppended.connect(self._run_log.append)
        # taskStarted/taskCancelled are deliberately NOT forwarded onto
        # ProjectStore's own signals (see ProjectStore's docstring) --
        # connect to store.tasks directly for the toolbar Cancel action.
        self._store.tasks.taskStarted.connect(self._on_task_started)
        self._store.tasks.taskCancelled.connect(self._on_task_cancelled)
        self._store.taskFinished.connect(self._on_task_finished)

        # Start on page 0.
        self._go_to_page(0)

    # ── sidebar header ──────────────────────────────────────────────────────

    def _make_sidebar_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: #1a252f;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        lbl = QLabel("Track2Data")
        lbl.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 14px;")
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        layout.addWidget(lbl)
        layout.addWidget(ver)
        return w

    # ── menu bar ────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        file_menu.addAction(
            QAction("&New project…", self,
                    shortcut=QKeySequence.StandardKey.New,
                    triggered=self._action_new_project)
        )
        file_menu.addAction(
            QAction("&Open project…", self,
                    shortcut=QKeySequence.StandardKey.Open,
                    triggered=self._action_open_project)
        )
        file_menu.addAction(
            QAction("&Save project", self,
                    shortcut=QKeySequence.StandardKey.Save,
                    triggered=self._action_save_project)
        )
        file_menu.addSeparator()
        file_menu.addAction(
            QAction("&Quit", self,
                    shortcut=QKeySequence.StandardKey.Quit,
                    triggered=self.close)
        )

        # Edit
        edit_menu = mb.addMenu("&Edit")
        edit_menu.addAction(QAction("&Preferences…", self))  # Phase 3

        # Run
        run_menu = mb.addMenu("&Run")
        run_menu.addAction(
            QAction("&Validate pipeline", self, triggered=self._action_validate)
        )
        run_menu.addAction(
            QAction("&Run pipeline", self,
                    shortcut="Ctrl+R",
                    triggered=self._action_run)
        )
        run_menu.addSeparator()
        run_menu.addAction(QAction("&Export…", self, triggered=self._action_export))

        # View
        view_menu = mb.addMenu("&View")
        toggle_log = QAction("Toggle &Run Log", self,
                             triggered=lambda: self._log_dock.setVisible(
                                 not self._log_dock.isVisible()))
        toggle_log.setCheckable(True)
        toggle_log.setChecked(True)
        view_menu.addAction(toggle_log)

        # Help
        help_menu = mb.addMenu("&Help")
        help_menu.addAction(
            QAction("&About Track2Data", self, triggered=self._action_about)
        )
        help_menu.addAction(
            QAction("Open &documentation", self)  # Phase 4: open browser
        )

    # ── toolbar ─────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main toolbar", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        self._back_action = QAction("◀  Back", self, triggered=self._go_back)
        self._next_action = QAction("Next  ▶", self, triggered=self._go_next)
        self._run_action  = QAction("▶  Run pipeline", self, triggered=self._action_run)
        self._run_action.setEnabled(False)
        self._cancel_action = QAction("■  Cancel", self, triggered=self._action_cancel)
        self._cancel_action.setEnabled(False)

        tb.addAction(self._back_action)
        tb.addAction(self._next_action)
        tb.addSeparator()
        tb.addAction(self._run_action)
        tb.addAction(self._cancel_action)

    # ── status bar ──────────────────────────────────────────────────────────

    def _build_statusbar(self) -> None:
        self._status_project = QLabel("No project open")
        self._status_workers = QLabel("Workers: —")
        self.statusBar().addWidget(self._status_project, stretch=1)
        self.statusBar().addPermanentWidget(self._status_workers)

    def _update_statusbar(self) -> None:
        info = self._store.status_summary()
        if info["status"] == "no_project":
            self._status_project.setText("No project open")
            self._run_action.setEnabled(False)
        else:
            name = info["name"]
            n = info["n_sessions"]
            self._status_project.setText(f"Project: {name}  |  Sessions: {n}")
            self._run_action.setEnabled(n > 0)

    # ── navigation ──────────────────────────────────────────────────────────

    def _go_to_page(self, page_index: int) -> None:
        """Switch the stacked widget to *page_index* and sync the sidebar."""
        n = self._stack.count()
        if not (0 <= page_index < n):
            return
        self._stack.setCurrentIndex(page_index)
        self._sidebar.sync_to_page(page_index)
        self._back_action.setEnabled(page_index > 0)
        self._next_action.setEnabled(page_index < n - 1)

    def _go_back(self) -> None:
        self._go_to_page(self._stack.currentIndex() - 1)

    def _go_next(self) -> None:
        self._go_to_page(self._stack.currentIndex() + 1)

    # ── actions ─────────────────────────────────────────────────────────────

    def _action_new_project(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New project", "Project name:"
        )
        if not ok or not name.strip():
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose project directory"
        )
        if not directory:
            return
        from pathlib import Path
        self._store.new_project(name.strip(), Path(directory))
        self._go_to_page(0)

    def _action_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Track2Data project (*.t2d.json)"
        )
        if not path:
            return
        from pathlib import Path
        self._store.open_project(Path(path))
        self._go_to_page(0)

    def _action_save_project(self) -> None:
        saved = self._store.save_project()
        if saved:
            self.statusBar().showMessage(f"Saved: {saved}", 3000)
        else:
            self.statusBar().showMessage("Nothing to save — open or create a project first.", 3000)

    def _action_validate(self) -> None:
        if not self._store.has_project:
            QMessageBox.warning(self, "Validate pipeline", "No project is open.")
            return

        from track2data.api import Engine

        issues = Engine(self._store.manifest).validate()
        if issues:
            self._store.append_log(
                "### Validation failed\n" + "\n".join(f"- {i}" for i in issues) + "\n"
            )
            QMessageBox.warning(
                self,
                "Pipeline validation",
                "Fix these issues first:\n\n" + "\n".join(issues),
            )
        else:
            self._store.append_log("### Validation passed\nReady to run.\n")
            QMessageBox.information(self, "Pipeline validation", "Ready to run.")
        self._run_action.setEnabled(not issues)

    def _action_run(self) -> None:
        if not self._store.has_project:
            QMessageBox.warning(self, "Run pipeline", "No project is open.")
            return
        # Navigate to Processing and delegate to its own start_run() --
        # the one real run code path, shared with its Run button, per
        # issue #22's explicit design goal.
        self._go_to_page(7)
        self._processing_screen.start_run()

    def _action_cancel(self) -> None:
        self._store.tasks.cancel_all()

    def _action_export(self) -> None:
        # Phase 2+: calls exporters
        self._go_to_page(9)  # jump to Export screen

    def _action_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME} v{APP_VERSION}</b><br/><br/>"
            "Open-source desktop application for processing "
            "<tt>idtracker.ai</tt> output folders into "
            "analysis-ready behavioural datasets.<br/><br/>"
            "License: MIT · "
            "<a href='https://github.com'>GitHub</a>",
        )

    # ── background task signals ────────────────────────────────────────────────

    def _on_task_started(self, task_id: str) -> None:
        self._cancel_action.setEnabled(True)

    def _on_task_finished(self, task_id: str, result: object) -> None:
        self._cancel_action.setEnabled(False)
        if isinstance(result, Exception):
            self._show_run_failure(result)

    def _on_task_cancelled(self, task_id: str) -> None:
        self._cancel_action.setEnabled(False)

    def _show_run_failure(self, exc: Exception) -> None:
        """Modal failure dialog for a taskFinished(..., Exception). The
        message (str(exc)) already carries a Track2DataError's code/subject/
        remediation baked in by its own __str__ when the failure originated
        from one; the full traceback sits behind "Show Details..." rather
        than inline, since it can be long."""
        box = QMessageBox(
            QMessageBox.Icon.Critical,
            "Pipeline run failed",
            str(exc),
            QMessageBox.StandardButton.Ok,
            self,
        )
        traceback_text = getattr(exc, "traceback", "")
        if traceback_text:
            box.setDetailedText(traceback_text)
        box.exec()

    # ── close ───────────────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 -- Qt override, must match QWidget's exact name
        """Drain the background TaskRunner before the window -- and every
        widget a still-running task's signals might emit into -- is torn
        down. See ui/store/task_runner.py's docstring and DECISIONS.md for
        the pool-thread-into-mid-GC-object access-violation crash this
        prevents (issue #20)."""
        self._store.tasks.shutdown(5000)
        super().closeEvent(event)
