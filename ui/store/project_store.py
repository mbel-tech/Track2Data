"""
Project state store — single source of truth for the in-memory manifest.

Implements the ProjectStore described in UI_DESIGN.md §4.  All wizard
pages bind to its Qt signals; no page mutates state directly.

Moved here from app/state.py per D-004 / issue #27, once the full
TaskRunner (ui/store/task_runner.py) existed for it to own and forward
signals from. app/state.py keeps a deprecated re-export for compatibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from track2data.core.models import (
    CalibrationConfig,
    ExportTarget,
    MappingRule,
    MetadataSource,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    RunResult,
    SessionRef,
    ZoneSet,
)
from ui.store.session_facts import SessionFacts
from ui.store.task_runner import TaskRunner


class ProjectStore(QObject):
    """
    Reactive project state container.

    Emits a fine-grained signal for every top-level field so wizard pages
    can subscribe only to what they need, avoiding unnecessary redraws.
    State is never mutated in place; setters replace fields then emit.

    Owns a TaskRunner (self.tasks) and forwards its signals onto its own
    taskProgress/taskFinished so wizard pages only ever need to listen to
    ProjectStore, never reach into store.tasks directly for routine
    progress/completion handling. taskFinished carries a result on
    success or an Exception on failure (see its own signal comment) --
    a failed task's message and traceback are both attached to that
    exception (.args and a dynamically-added .traceback attribute), since
    TaskRunner.taskFailed only carries the stringified message +
    traceback, not the original exception object, which isn't reliably
    picklable/marshalable across the Qt signal boundary.
    """

    # ── signals ────────────────────────────────────────────────────────────
    projectChanged     = Signal()
    sessionsChanged    = Signal()
    calibrationChanged = Signal()
    zonesChanged       = Signal()
    metadataChanged    = Signal()
    preprocessChanged  = Signal()
    metricsChanged     = Signal()
    exportChanged      = Signal()
    runResultsChanged  = Signal()
    runLogAppended     = Signal(str)           # one Markdown line
    taskProgress       = Signal(str, int)      # task_id, percent 0-100
    taskFinished       = Signal(str, object)   # task_id, result-or-exception
    sessionFactsChanged = Signal()             # a SessionFacts entry was added/removed

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manifest: ProjectManifest | None = None
        self._project_dir: Path | None = None
        self._run_results: RunResult | None = None
        self._identity_probes: dict[str, str] = {}  # task_id -> session_id
        # Derived cache, never persisted -- see ui/store/session_facts.py's
        # module docstring for why this lives here and not on SessionRef.
        self._session_facts: dict[str, SessionFacts] = {}

        self._tasks = TaskRunner(self)
        self._tasks.taskProgress.connect(self.taskProgress)
        self._tasks.taskFinished.connect(self.taskFinished)
        self._tasks.taskFailed.connect(self._on_task_failed)
        self._tasks.taskLog.connect(lambda _task_id, line: self.append_log(line))
        self.taskFinished.connect(self._on_identity_probe_finished)

    # ── accessors ──────────────────────────────────────────────────────────

    @property
    def manifest(self) -> ProjectManifest | None:
        return self._manifest

    @property
    def project_dir(self) -> Path | None:
        return self._project_dir

    @property
    def has_project(self) -> bool:
        return self._manifest is not None

    @property
    def tasks(self) -> TaskRunner:
        """The owned background TaskRunner. Prefer ProjectStore's own
        taskProgress/taskFinished signals for routine listening; use this
        directly for submit()/submit_with_progress()/cancel()/cancel_all()."""
        return self._tasks

    @property
    def run_results(self) -> RunResult | None:
        return self._run_results

    def session_facts(self, session_id: str) -> SessionFacts | None:
        """Derived facts read from *session_id*'s own trajectory files
        (length_unit, setup_points, roi_list, video dims, ...), or None
        before its background probe has completed / if it failed. See
        ui/store/session_facts.py."""
        return self._session_facts.get(session_id)

    def set_run_results(self, results: RunResult) -> None:
        """Record the outcome of the most recent Engine.run() and notify
        listeners (e.g. the preview screen's Diagnostics/Metrics tabs)."""
        self._run_results = results
        self.runResultsChanged.emit()

    def _on_task_failed(self, task_id: str, message: str, tb: str) -> None:
        exc = RuntimeError(message)
        exc.traceback = tb
        self.taskFinished.emit(task_id, exc)

    # ── project lifecycle ──────────────────────────────────────────────────

    def new_project(self, name: str, directory: Path) -> None:
        """Create a blank manifest for a new project."""
        self._identity_probes.clear()
        self._session_facts.clear()
        now = datetime.now(tz=UTC)
        self._manifest = ProjectManifest(
            project_name=name,
            created_at=now,
            updated_at=now,
        )
        self._project_dir = Path(directory)
        self.projectChanged.emit()
        self.runLogAppended.emit(
            f"## New project: {name}\n_Created {now.isoformat()}_\n"
        )

    def open_project(self, t2d_path: Path) -> None:
        """Load an existing project from a .t2d.json file."""
        self._identity_probes.clear()
        self._session_facts.clear()
        from track2data.core.manifest import read as manifest_read

        self._manifest = manifest_read(t2d_path)
        self._project_dir = t2d_path.parent
        self.projectChanged.emit()
        self.runLogAppended.emit(
            f"## Opened project: {self._manifest.project_name}\n"
            f"_Loaded from `{t2d_path}`_\n"
        )

    def save_project(self) -> Path | None:
        """Persist the current manifest.  Returns the written path or None."""
        if self._manifest is None or self._project_dir is None:
            return None
        from track2data.core.manifest import write as manifest_write

        out = self._project_dir / f"{self._manifest.project_name}.t2d.json"
        manifest_write(self._manifest, out)
        return out

    # ── field setters (each replaces the field and emits its signal) ───────

    def update_calibration(self, cfg: CalibrationConfig) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"calibration": cfg})
        self.calibrationChanged.emit()

    def update_zones(self, zone_set: ZoneSet) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"zones": zone_set})
        self.zonesChanged.emit()

    def update_preprocess(self, cfg: PreprocessConfig) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"preprocess": cfg})
        self.preprocessChanged.emit()

    def update_sessions(self, sessions: list[SessionRef]) -> None:
        """Replace the session list and emit sessionsChanged."""
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"sessions": list(sessions)})
        self.sessionsChanged.emit()
        # Prune cached facts for anything no longer in the list, so a
        # removed session's stale entry doesn't linger indefinitely.
        kept_ids = {s.session_id for s in sessions}
        removed = [sid for sid in self._session_facts if sid not in kept_ids]
        if removed:
            for sid in removed:
                del self._session_facts[sid]
            self.sessionFactsChanged.emit()

    def add_session(self, folder: Path) -> None:
        """Append a new SessionRef for *folder*, emit sessionsChanged, and
        submit a background probe (see _on_identity_probe_finished) that
        fills in has_stable_identities once the reader has read it."""
        if self._manifest is None:
            return
        from track2data.readers import read_session

        session_id = folder.name
        ref = SessionRef(session_id=session_id, folder=folder, sha256="")
        sessions = [*list(self._manifest.sessions), ref]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()

        task_id = self._tasks.submit(partial(read_session, folder))
        self._identity_probes[task_id] = session_id

    def _on_identity_probe_finished(self, task_id: str, result: object) -> None:
        session_id = self._identity_probes.pop(task_id, None)
        if session_id is None:
            return  # not an identity-probe task (e.g. a pipeline run/preview)
        if isinstance(result, Exception):
            self.append_log(f"_Identity probe failed for `{session_id}`: {result}_\n")
            return
        self._set_session_identity(session_id, result.has_stable_identities)
        # The probe already read the full Session for that one boolean --
        # cache the rest of it too rather than discard it (see
        # ui/store/session_facts.py).
        self._session_facts[session_id] = SessionFacts.from_session(result)
        self.sessionFactsChanged.emit()

    def _set_session_identity(self, session_id: str, has_stable_identities: bool) -> None:
        if self._manifest is None:
            return
        sessions = [
            s.model_copy(update={"has_stable_identities": has_stable_identities})
            if s.session_id == session_id else s
            for s in self._manifest.sessions
        ]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()

    def update_metrics(self, sel: MetricSelection) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"metrics": sel})
        self.metricsChanged.emit()

    def update_metadata_source(self, source: MetadataSource | None) -> None:
        """Set (or clear, via None) the metadata file reference."""
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"metadata_source": source})
        self.metadataChanged.emit()

    def update_mapping(self, rule: MappingRule | None) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"mapping": rule})
        self.metadataChanged.emit()

    def update_export_targets(self, targets: list[ExportTarget]) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"export_targets": list(targets)})
        self.exportChanged.emit()

    def append_log(self, markdown_line: str) -> None:
        """Append a line to the in-memory run log and emit the signal."""
        self.runLogAppended.emit(markdown_line)

    # ── helpers ────────────────────────────────────────────────────────────

    def status_summary(self) -> dict[str, Any]:
        """Return a dict describing the current project state (for status bar)."""
        if self._manifest is None:
            return {"status": "no_project"}
        return {
            "status": "open",
            "name": self._manifest.project_name,
            "n_sessions": len(self._manifest.sessions),
            "calibration_mode": self._manifest.calibration.mode,
        }
