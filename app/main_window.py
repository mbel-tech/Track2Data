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

import weakref
from datetime import datetime
from functools import partial

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.navigation import WizardSidebar
from app.state import ProjectStore
from app.theme import RESOURCES, theme
from track2data import __version__
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
from ui.widgets.weak_slot import weak_slot
from ui.zones_screen import ZonesScreen

APP_NAME = "Track2Data"
APP_VERSION = __version__
#: Step-by-step guide with screenshots (docs/guide/USER_GUIDE.md in the repository).
GUIDE_URL = "https://github.com/mbel-tech/Track2Data/blob/main/docs/guide/USER_GUIDE.md"


class RunLogDock(QPlainTextEdit):
    """Run-log drawer: ``HH:MM:SS  message`` lines in a monospace pane."""

    MAX_LINES = 200

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RunLog")
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setPlaceholderText("No activity yet.")
        self.setFixedHeight(150)
        self._n = 0

    @property
    def line_count(self) -> int:
        return self._n

    def append(self, text: str) -> None:  # type: ignore[override]
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in str(text).splitlines():
            if line.strip():
                self.appendPlainText(f"{stamp}  {line}")
                self._n += 1


class Toast(QLabel):
    """Dark pill shown for a couple of seconds near the bottom of the window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 2200) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        x = (parent.width() - self.width()) // 2
        self.move(QPoint(x, parent.height() - 76 - self.height()))
        self.raise_()
        self.show()
        self._timer.start(ms)


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1200, 720)

        # ── project state ──────────────────────────────────────────────────
        self._store = ProjectStore(parent=self)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._autosave)
        # Held weakly: the store outlives no window, and a strong bound method here makes
        # window and store keep each other alive (see ui/widgets/weak_slot.py).
        _save_ref = weakref.WeakMethod(self._save_before_project_change)
        self._store.prepare_project_change = lambda: (m := _save_ref()) is None or m()
        # One prompt per launch, not one per refused session: importing a
        # folder of 70 sessions must not produce 70 identical dialogs.
        self._pickle_consent_asked = False

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
        self._processing_screen.navigateRequested.connect(self._go_to_page)
        for page in pages:
            page.setObjectName("Page")
            self._stack.addWidget(page)

        # page content, run-log drawer (collapsed) and the footer bar
        self._run_log = RunLogDock()
        self._run_log.hide()
        self._footer = self._build_footer()
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._stack, 1)
        col.addWidget(self._run_log)
        col.addWidget(self._footer)
        self.setCentralWidget(central)
        self._toast = Toast(central)

        # ── sidebar ────────────────────────────────────────────────────────
        self._sidebar = WizardSidebar()
        sidebar_dock = QDockWidget("Workflow", self)
        sidebar_dock.setWidget(self._sidebar)
        sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        sidebar_dock.setTitleBarWidget(self._make_sidebar_header())
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, sidebar_dock)

        # ── chrome ────────────────────────────────────────────────────────
        self._build_menu()
        self._build_actions()
        self._build_statusbar()
        self.statusBar().hide()  # superseded by sidebar summaries and toasts

        # ── wire signals ──────────────────────────────────────────────────
        self._sidebar.stage_page_selected.connect(self._go_to_page)
        self._sidebar.locked_clicked.connect(weak_slot(self.show_toast, "Run the pipeline first"))
        theme.changed.connect(self._on_theme_changed)
        self._store.projectChanged.connect(self._update_statusbar)
        self._store.sessionsChanged.connect(self._update_statusbar)
        self._store.projectChanged.connect(self._on_project_opened)
        for sig in (
            self._store.projectChanged,
            self._store.sessionsChanged,
            self._store.calibrationChanged,
            self._store.zonesChanged,
            self._store.sceneChanged,
            self._store.metadataChanged,
            self._store.preprocessChanged,
            self._store.metricsChanged,
            self._store.exportChanged,
            self._store.runResultsChanged,
        ):
            sig.connect(self._refresh_stage_status)
        self._store.runLogAppended.connect(self._run_log.append)
        self._store.runLogAppended.connect(weak_slot(self._update_log_toggle))
        self._store.pickleConsentRequired.connect(self._ask_pickle_consent)
        # taskStarted/taskCancelled are deliberately NOT forwarded onto
        # ProjectStore's own signals (see ProjectStore's docstring) --
        # connect to store.tasks directly for the toolbar Cancel action.
        self._store.tasks.taskStarted.connect(self._on_task_started)
        self._store.tasks.taskCancelled.connect(self._on_task_cancelled)
        self._store.taskFinished.connect(self._on_task_finished)
        self._store.persistenceChanged.connect(self._schedule_autosave)

        theme.apply()
        self.resize(1280, 800)
        # Start on page 0.
        self._go_to_page(0)
        self._refresh_stage_status()

    # ── sidebar header ──────────────────────────────────────────────────────

    def _make_sidebar_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("SidebarHeader")
        row = QHBoxLayout(w)
        row.setContentsMargins(20, 18, 16, 14)
        row.setSpacing(10)
        logo = QLabel()
        icon = RESOURCES / "icon.png"
        if icon.exists():
            logo.setPixmap(
                QPixmap(str(icon)).scaled(
                    32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("Track2Data")
        name.setObjectName("AppName")
        self._project_sub = QLabel(f"v{APP_VERSION}")
        self._project_sub.setObjectName("ProjectSub")
        text.addWidget(name)
        text.addWidget(self._project_sub)
        row.addWidget(logo)
        row.addLayout(text, 1)
        return w

    def _build_footer(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("FooterBar")
        bar.setFixedHeight(56)
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 0, 24, 0)
        row.setSpacing(10)
        self._btn_back = QPushButton("← Back")
        self._btn_back.setProperty("role", "outline")
        self._btn_log = QPushButton("Run log · 0 lines ▴")
        self._btn_log.setProperty("role", "link")
        self._btn_log.setFlat(True)
        self._btn_log.clicked.connect(weak_slot(self._toggle_log))
        self._btn_run = QPushButton("⟶ Run pipeline")
        self._btn_run.setProperty("role", "outline-primary")
        self._btn_next = QPushButton("Next →")
        self._btn_next.setProperty("role", "primary")
        row.addWidget(self._btn_back)
        row.addWidget(self._btn_log)
        self._save_status = QLabel()
        self._save_status.setProperty("role", "faint")
        row.addWidget(self._save_status)
        row.addStretch(1)
        row.addWidget(self._btn_run)
        row.addWidget(self._btn_next)
        return bar

    def palette_commands(self) -> list:
        """Everything the palette offers; each entry runs what the menus run."""
        from app.navigation import STAGES
        from ui.dialogs.command_palette import Command

        has_project = self._store.has_project
        has_run = self._store.run_results is not None
        commands = [
            Command("Go to", label, partial(self._go_to_page, first_page))
            for label, first_page in STAGES
        ]
        commands += [
            Command("Run", "Run pipeline", self._action_run, "Ctrl+R", has_project),
            Command("Run", "Validate", self._action_validate, "Ctrl+Shift+V", has_project),
            Command("Run", "Export…", self._action_export, "Ctrl+E", has_run),
            Command("View", "Show or hide the run log", weak_slot(self._toggle_log), "Ctrl+L"),
            Command("View", "Switch theme", theme.toggle),
            Command("File", "Save project", self._action_save_project, "Ctrl+S", has_project),
            Command("File", "New project…", self._action_new_project, "Ctrl+N"),
            Command("File", "Open project…", self._action_open_project, "Ctrl+O"),
            Command("Help", "Open the user guide", self._action_open_guide),
        ]
        return commands

    def open_palette(self) -> None:
        from ui.dialogs.command_palette import CommandPalette

        self._palette = CommandPalette(self.palette_commands(), self)
        self._palette.open()

    def show_toast(self, text: str) -> None:
        self._toast.show_message(text)

    def _toggle_log(self, visible: bool | None = None) -> None:
        visible = (not self._run_log.isVisible()) if visible is None else visible
        self._run_log.setVisible(visible)
        self._log_action.blockSignals(True)
        self._log_action.setChecked(visible)
        self._log_action.blockSignals(False)
        self._update_log_toggle()

    def _update_log_toggle(self) -> None:
        arrow = "▾" if self._run_log.isVisible() else "▴"
        n = self._run_log.line_count
        self._btn_log.setText(f"Run log · {n} line{'s' if n != 1 else ''} {arrow}")

    def _on_theme_changed(self, name: str) -> None:
        self._theme_pill.setText("◐ Dark" if name == "light" else "☀ Light")
        self._theme_actions[name].setChecked(True)

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
        edit_menu.addAction(
            QAction("&Undo", self, shortcut=QKeySequence.StandardKey.Undo, enabled=False)
        )
        edit_menu.addAction(
            QAction("&Redo", self, shortcut=QKeySequence.StandardKey.Redo, enabled=False)
        )
        edit_menu.addSeparator()
        edit_menu.addAction(QAction("&Preferences…", self))  # Phase 3

        # Run
        run_menu = mb.addMenu("&Run")
        run_menu.addAction(
            QAction("&Validate", self, shortcut="Ctrl+Shift+V", triggered=self._action_validate)
        )
        run_menu.addAction(
            QAction("&Run pipeline", self, shortcut="Ctrl+R", triggered=self._action_run)
        )
        self._menu_cancel = QAction(
            "&Cancel run", self, shortcut="Ctrl+.", enabled=False,
            triggered=weak_slot(self._action_cancel),
        )
        run_menu.addAction(self._menu_cancel)
        run_menu.addSeparator()
        run_menu.addAction(
            QAction("&Export…", self, shortcut="Ctrl+E", triggered=self._action_export)
        )

        # View
        view_menu = mb.addMenu("&View")
        self._log_action = QAction("Run &log", self, shortcut="Ctrl+L", checkable=True)
        self._log_action.toggled.connect(self._on_log_action_toggled)
        view_menu.addAction(self._log_action)
        view_menu.addAction(
            QAction("&Command palette…", self, shortcut="Ctrl+K", triggered=self.open_palette)
        )
        theme_menu = view_menu.addMenu("&Theme")
        group = QActionGroup(self)
        self._theme_actions: dict[str, QAction] = {}
        for key, label in (("light", "Light"), ("dark", "Dark")):
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _c=False, k=key: theme.apply(k))
            group.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[key] = act
        self._theme_actions[theme.initial()].setChecked(True)

        # Help
        help_menu = mb.addMenu("&Help")
        help_menu.addAction(
            QAction("Open &user guide", self, triggered=self._action_open_guide)
        )
        help_menu.addSeparator()
        help_menu.addAction(
            QAction("&About Track2Data", self, triggered=self._action_about)
        )

        # theme pill on the right of the menu bar
        self._theme_pill = QPushButton("◐ Dark")
        self._theme_pill.setObjectName("ThemePill")
        self._theme_pill.setFlat(True)
        self._theme_pill.clicked.connect(theme.toggle)
        mb.setCornerWidget(self._theme_pill, Qt.Corner.TopRightCorner)

    # ── toolbar ─────────────────────────────────────────────────────────────

    def _build_actions(self) -> None:
        """Back / Next / Run / Cancel stay QActions (the tests and the menu
        share them); the footer buttons mirror them."""
        self._back_action = QAction("◀  Back", self, triggered=self._go_back)
        self._next_action = QAction("Next  ▶", self, triggered=self._go_next)
        self._run_action = QAction("▶  Run pipeline", self, triggered=self._action_run)
        self._run_action.setEnabled(False)
        self._cancel_action = QAction("■  Cancel", self, triggered=self._action_cancel)
        self._cancel_action.setEnabled(False)
        for btn, act in (
            (self._btn_back, self._back_action),
            (self._btn_next, self._next_action),
            (self._btn_run, self._run_action),
        ):
            btn.clicked.connect(act.trigger)
            act.changed.connect(
                lambda b=btn, a=act: (b.setEnabled(a.isEnabled()), b.setToolTip(a.toolTip()))
            )
            btn.setEnabled(act.isEnabled())
        self._cancel_action.changed.connect(self._sync_menu_cancel)

    def _on_log_action_toggled(self, on: bool) -> None:
        self._toggle_log(bool(on))

    def _sync_menu_cancel(self) -> None:
        self._menu_cancel.setEnabled(self._cancel_action.isEnabled())

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
        self._flush_current_page()
        self._stack.setCurrentIndex(page_index)
        self._sidebar.sync_to_page(page_index)
        self._back_action.setEnabled(page_index > 0)
        self._update_next_action()

    def _on_project_opened(self) -> None:
        """Creating/opening a project moves on to Sessions instead of leaving
        the user on a screen whose only change is a small status label."""
        if self._store.has_project and self._stack.currentIndex() == 0:
            self._go_to_page(1)

    def _refresh_stage_status(self) -> None:
        from app.navigation import STAGES
        from ui.store.stage_status import compute_stage_statuses, stage_summaries

        self._page_statuses = compute_stage_statuses(
            self._store.manifest, has_run_results=self._store.run_results is not None
        )
        has_run = self._store.run_results is not None
        summaries = stage_summaries(self._store.manifest, has_run_results=has_run)
        if self._store.results_stale:
            summaries[7] = summaries[8] = "Settings changed · re-run"
        elif has_run:
            results = self._store.run_results.sessions
            failed = sum(bool(s.error) for s in results)
            if not results or failed == len(results):
                summaries[7] = summaries[8] = "No successful sessions"
            elif failed:
                summaries[7] = summaries[8] = f"{len(results) - failed} succeeded · {failed} failed"
        for stage_index, (_label, first_page) in enumerate(STAGES):
            info = self._page_statuses[first_page]
            self._sidebar.set_status(
                stage_index, info.status, info.message, summary=summaries[stage_index]
            )
            if stage_index in (7, 8) and has_run:
                if self._store.results_stale or any(
                    s.error for s in self._store.run_results.sessions
                ):
                    self._sidebar.set_status(stage_index, "warning", summary=summaries[stage_index])
                elif not self._store.run_results.sessions:
                    self._sidebar.set_status(stage_index, "empty", summary=summaries[stage_index])
        self._sidebar.set_locked(len(STAGES) - 1, not has_run)
        manifest = self._store.manifest
        self._project_sub.setText(manifest.project_name if manifest else f"v{APP_VERSION}")
        self._update_next_action()

    def _update_next_action(self) -> None:
        from ui.store.stage_status import next_blocker

        page = self._stack.currentIndex()
        last = self._stack.count() - 1
        statuses = getattr(self, "_page_statuses", None)
        reason = next_blocker(statuses, page) if statuses else None
        self._next_action.setEnabled(page < last and reason is None)
        self._next_action.setToolTip(reason or "Go to the next step")
        self._refresh_footer_labels(page)

    def _refresh_footer_labels(self, page: int) -> None:
        from app.navigation import PAGE_TO_STAGE, STAGES

        if page > 0:
            self._btn_back.setText(f"← {STAGES[PAGE_TO_STAGE[page - 1]][0]}".replace("&", "&&"))
        else:
            self._btn_back.setText("← Back")
        if page == 8:
            text, role = "Export dataset →", "accent"
        elif page >= self._stack.count() - 1:
            text, role = "Done", "primary"
        else:
            text = f"Next: {STAGES[PAGE_TO_STAGE[page + 1]][0]} →".replace("&", "&&")
            role = "primary"
        self._btn_next.setText(text)
        if self._btn_next.property("role") != role:
            self._btn_next.setProperty("role", role)
            self._btn_next.style().unpolish(self._btn_next)
            self._btn_next.style().polish(self._btn_next)
        ran = self._store.run_results is not None
        self._btn_run.setText("⟶ Re-run pipeline" if ran else "⟶ Run pipeline")
        self._btn_run.setVisible(page < 8)

    def _flush_current_page(self) -> None:
        """Commit the outgoing screen's debounced edits before leaving it."""
        # Keyboard tracking may be disabled, so visible text has not yet
        # become a numeric value. Commit it even when Save has moved focus.
        for spin in self._stack.currentWidget().findChildren(QAbstractSpinBox):
            spin.interpretText()
        flush = getattr(self._stack.currentWidget(), "flush", None)
        if callable(flush):
            flush()

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
        try:
            if not self._store.new_project(name.strip(), Path(directory)):
                return
        except Exception as exc:
            QMessageBox.critical(self, "Project not created", str(exc))
            return
        self._go_to_page(0)

    def _action_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Track2Data project (*.t2d.json)"
        )
        if not path:
            return
        from pathlib import Path
        try:
            if not self._store.open_project(Path(path)):
                return
        except Exception as exc:
            QMessageBox.critical(self, "Project not opened", str(exc))
            return
        self._go_to_page(0)

    def _action_save_project(self) -> None:
        self._flush_current_page()
        if not self._store.has_project:
            self.show_toast("Nothing to save — open or create a project first.")
        elif self._save_project_safely():
            self.show_toast("Saved")

    def _schedule_autosave(self) -> None:
        if self._store.dirty:
            self._save_status.setText("Unsaved changes")
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()
            self._save_status.setText("Saved" if self._store.has_project else "")

    def _save_project_safely(self, *, show_error: bool = True) -> bool:
        self._autosave_timer.stop()
        try:
            self._store.save_project()
        except Exception as exc:
            self._save_status.setText("Not saved — use File → Save")
            self._save_status.setToolTip(str(exc))
            if show_error:
                QMessageBox.critical(
                    self, "Project not saved",
                    f"Your changes are still open. Fix the save problem and try again.\n\n{exc}",
                )
            return False
        self._save_status.setToolTip("")
        return True

    def _autosave(self) -> None:
        self._flush_current_page()
        if self._store.dirty:
            self._save_project_safely(show_error=False)

    def _save_before_project_change(self) -> bool:
        self._flush_current_page()
        return not self._store.dirty or self._save_project_safely()

    def _ask_pickle_consent(self, session_id: str, folder: str) -> None:
        """Ask once per project whether to load trajectories that execute code.

        Names the folder, because "do you trust this data?" is not a question
        anyone can answer in the abstract. Asked only when it actually
        matters: a folder carrying an h5 or csv trajectory alongside the
        pickled one never reaches here, because the reader quietly uses that
        instead.

        Defaults to No, and the answer is stored in the project so a user who
        says yes for their own data is not asked again on every launch.
        """
        if self._pickle_consent_asked:
            return
        self._pickle_consent_asked = True

        answer = QMessageBox.question(
            self,
            "Load trajectories that can run code?",
            f"<b>{session_id}</b> can only be read from a pickled trajectory "
            f"file.<br><br>Loading it runs whatever code the file contains, so "
            f"only do this for data you trust.<br><br><code>{folder}</code>"
            "<br><br>The safer alternative is to re-export the session as HDF5 "
            "(<code>idtrackerai_format &lt;session&gt; --formats h5</code>) and "
            "import it again.<br><br>Load pickled trajectories for this project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._store.append_log(
                f"_Declined to load pickled trajectories for `{session_id}`._\n"
            )
            return

        self._store.set_allow_pickle_trajectories(True)
        QMessageBox.information(
            self,
            "Re-import needed",
            "Enabled for this project. Remove and re-add the session folder "
            "to import it.",
        )

    def _action_validate(self) -> None:
        if not self._store.has_project:
            QMessageBox.warning(self, "Validate pipeline", "No project is open.")
            return
        self._flush_current_page()

        from track2data.api import Engine

        engine = Engine(self._store.manifest)
        issues = engine.validate()
        # Non-blocking by design: pooling 30 fps and 60 fps sessions is a
        # legitimate deliberate choice and a serious accident, and only the
        # user can tell those apart. Reported either way -- a project can be
        # perfectly valid and still not be safe to pool.
        warnings = engine.consistency_warnings()
        if warnings:
            self._store.append_log(
                "### Session consistency\n"
                + "\n".join(f"- {w}" for w in warnings)
                + "\n"
            )

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
            if warnings:
                QMessageBox.warning(
                    self,
                    "Pipeline validation",
                    "Ready to run, but these sessions are not interchangeable:\n\n"
                    + "\n\n".join(warnings)
                    + "\n\nThe run will proceed and record this in the export.",
                )
            else:
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
        self._store.tasks.cancel_all(lane="run")

    def _action_export(self) -> None:
        # Phase 2+: calls exporters
        self._go_to_page(9)  # jump to Export screen

    def _action_open_guide(self) -> None:
        QDesktopServices.openUrl(QUrl(GUIDE_URL))

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
        if not self._save_before_project_change():
            event.ignore()
            return
        self._autosave_timer.stop()
        self._store.tasks.shutdown(5000)
        super().closeEvent(event)
