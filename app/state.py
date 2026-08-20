"""
Project state store — single source of truth for the in-memory manifest.

Implements the ProjectStore described in UI_DESIGN.md §4.  All wizard
pages bind to its Qt signals; no page mutates state directly.

Phase 1 note (D-004): Lives in app/state.py for simplicity.  Will be
split into ui/store/project_store.py + ui/store/task_runner.py in Phase 3
(M3) when the full TaskRunner is wired to engine calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    SessionRef,
    ZoneSet,
)


class ProjectStore(QObject):
    """
    Reactive project state container.

    Emits a fine-grained signal for every top-level field so wizard pages
    can subscribe only to what they need, avoiding unnecessary redraws.
    State is never mutated in place; setters replace fields then emit.
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
    runLogAppended     = Signal(str)           # one Markdown line
    taskProgress       = Signal(str, int)      # task_id, percent 0-100
    taskFinished       = Signal(str, object)   # task_id, result-or-exception

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manifest: ProjectManifest | None = None
        self._project_dir: Path | None = None

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

    # ── project lifecycle ──────────────────────────────────────────────────

    def new_project(self, name: str, directory: Path) -> None:
        """Create a blank manifest for a new project."""
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

    def add_session(self, folder: Path) -> None:
        """Append a new SessionRef for *folder* and emit sessionsChanged."""
        if self._manifest is None:
            return
        session_id = folder.name
        ref = SessionRef(session_id=session_id, folder=folder, sha256="")
        sessions = [*list(self._manifest.sessions), ref]
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
