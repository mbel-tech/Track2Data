"""
Project state store — single source of truth for the in-memory manifest.

Implements the ProjectStore described in UI_DESIGN.md §4.  All wizard
pages bind to its Qt signals; no page mutates state directly.

Moved here from app/state.py per D-004 / issue #27, once the full
TaskRunner (ui/store/task_runner.py) existed for it to own and forward
signals from. app/state.py keeps a deprecated re-export for compatibility.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from track2data.core.ids import default_session_id, uniquify
from track2data.core.models import (
    CalibrationConfig,
    ExportTarget,
    MappingRule,
    MetadataSource,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    RunResult,
    SceneConfig,
    SessionRef,
    ZoneSet,
)
from track2data.core.progress import CancellationToken, OperationCancelled
from track2data.readers import find_reader
from ui.store.session_facts import SessionFacts
from ui.store.task_runner import TaskRunner


def _is_pickle_refusal(exc: object) -> bool:
    """Whether *exc* is the reader declining to execute code from a file.

    Matches on the error code rather than the message: the refusal can
    surface either directly from the loader or wrapped by the reader's
    format-fallback walk once nothing inert remains.
    """
    code = getattr(exc, "code", "") or ""
    return code == "IDT_PICKLE_REFUSED" or "IDT_PICKLE_REFUSED" in str(exc)


class _CallableToken(CancellationToken):
    """A token whose cancellation is whatever *check* says.

    The task runner gives a task a zero-argument ``cancel_check`` that raises
    ``OperationCancelled`` once the user cancels; ``Engine.scan`` takes a
    ``CancellationToken``. This is the bridge, so one cancel stops the walk and the
    discovery that follows it alike.
    """

    def __init__(self, check: Callable[[], None]) -> None:
        super().__init__()
        self._check = check

    @property
    def is_cancelled(self) -> bool:
        try:
            self._check()
        except OperationCancelled:
            return True
        return False

    def raise_if_cancelled(self) -> None:
        self._check()


def _selector(ref: SessionRef) -> tuple[tuple[str, str], ...]:
    """The options that pick *which* session in a file (an arena), not how to read it."""
    reader = find_reader(ref.reader) if ref.reader else None
    names = {p.name for p in reader.parameters if p.scope == "session"} if reader else set()
    return tuple(sorted((k, repr(v)) for k, v in ref.reader_options.items() if k in names))


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _is_duplicate(ref: SessionRef, existing: Sequence[SessionRef]) -> bool:
    """Whether *ref* is a session the project already has: the same place, read by the same
    reader (a legacy entry with no saved reader counts as any), picking the same arena.

    The same folder under another reader is not a duplicate: another reader could read the same
    files into different numbers, so it is a different session.
    """
    place, selector = _resolved(ref.folder), _selector(ref)
    return any(
        _resolved(other.folder) == place
        and (other.reader is None or other.reader == ref.reader)
        and _selector(other) == selector
        for other in existing
    )


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
    sceneChanged       = Signal()
    metadataChanged    = Signal()
    preprocessChanged  = Signal()
    metricsChanged     = Signal()
    exportChanged      = Signal()
    runResultsChanged  = Signal()
    persistenceChanged = Signal()
    runLogAppended     = Signal(str)           # one Markdown line
    taskProgress       = Signal(str, int)      # task_id, percent 0-100
    taskFinished       = Signal(str, object)   # task_id, result-or-exception
    sessionFactsChanged = Signal()             # a SessionFacts entry was added/removed
    # A session folder could only be read by unpickling, which this project
    # has not consented to. Carries (session_id, folder) so the view can name
    # the file it is asking about -- "do you trust this folder?" is not a
    # question anyone can answer in the abstract.
    pickleConsentRequired = Signal(str, str)
    # Looking at a folder before anything is added (the confirm dialog's first step).
    # scanFinished carries a ScanResult, or an Exception for a scan that failed: a failed
    # scan is shown inline by the dialog, never as the generic failure modal.
    scanProgress  = Signal(str, object)   # task_id, ProgressEvent
    scanFinished  = Signal(str, object)   # task_id, ScanResult-or-exception
    scanCancelled = Signal(str)           # task_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manifest: ProjectManifest | None = None
        self._project_dir: Path | None = None
        self._run_results: RunResult | None = None
        self._saved_manifest: str | None = None
        self._manifest_path: Path | None = None
        self._result_analysis_hash: str | None = None
        self._last_results_stale = False
        self._project_revision = 0
        # The window flushes/saves before either Project-screen or menu replacement.
        self.prepare_project_change: Callable[[], bool] | None = None
        self._identity_probes: dict[str, str] = {}  # task_id -> session_id
        self._scans: set[str] = set()  # task ids of scans whose result is still wanted
        # Derived cache, never persisted -- see ui/store/session_facts.py's
        # module docstring for why this lives here and not on SessionRef.
        self._session_facts: dict[str, SessionFacts] = {}

        self._tasks = TaskRunner(self)
        self._tasks.taskProgress.connect(self.taskProgress)
        self._tasks.taskFinished.connect(self.taskFinished)
        self._tasks.taskFailed.connect(self._on_task_failed)
        self._tasks.taskLog.connect(self._on_task_log)
        # Session probes run in their own lane and report on probe* signals, so
        # they never drive the main window's Cancel button or failure dialog.
        self._tasks.probeFinished.connect(self._on_identity_probe_finished)
        self._tasks.probeFailed.connect(self._on_probe_failed)
        # A scan has its own lane and signals for the same reason.
        self._tasks.scanProgress.connect(self._on_scan_progress)
        self._tasks.scanFinished.connect(self._on_scan_finished)
        self._tasks.scanFailed.connect(self._on_scan_failed)
        self._tasks.scanCancelled.connect(self._on_scan_cancelled)
        for signal in (
            self.projectChanged, self.sessionsChanged, self.calibrationChanged,
            self.zonesChanged, self.metadataChanged, self.preprocessChanged,
            self.metricsChanged, self.exportChanged,
        ):
            signal.connect(self._on_manifest_changed)

    # ── accessors ──────────────────────────────────────────────────────────

    @property
    def manifest(self) -> ProjectManifest | None:
        return self._manifest

    @property
    def project_dir(self) -> Path | None:
        return self._project_dir

    @property
    def cache_dir(self) -> Path | None:
        """Where the engine keeps preprocessed sessions for this project."""
        return None if self._project_dir is None else self._project_dir / ".t2d_cache"

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

    @property
    def dirty(self) -> bool:
        return self._manifest is not None and (
            self._manifest.model_dump_json() != self._saved_manifest
        )

    @property
    def project_revision(self) -> int:
        return self._project_revision

    def analysis_hash(self) -> str | None:
        """Settings producing the previews; output formats do not change the numbers."""
        if self._manifest is None:
            return None
        from track2data.core.hashing import dict_sha256

        data = self._manifest.model_dump(mode="json", exclude={
            "created_at", "updated_at", "run_log_path", "export_targets",
        })
        # These are probe-derived facts, not inputs to Engine.import_ref().
        for ref in data["sessions"]:
            for key in ("sha256", "has_stable_identities", "track_wo_identities"):
                ref.pop(key, None)
        return dict_sha256(data)

    @property
    def results_stale(self) -> bool:
        return self._run_results is not None and (
            self._result_analysis_hash != self.analysis_hash()
        )

    def _on_manifest_changed(self) -> None:
        self.persistenceChanged.emit()
        stale = self.results_stale
        if stale != self._last_results_stale:
            self._last_results_stale = stale
            self.runResultsChanged.emit()

    def set_run_results(
        self, results: RunResult | None, *, analysis_hash: str | None = None,
        project_revision: int | None = None,
    ) -> bool:
        """Record the outcome of the most recent Engine.run() and notify
        listeners (e.g. the preview screen's Diagnostics/Metrics tabs)."""
        if project_revision is not None and project_revision != self._project_revision:
            return False
        self._run_results = results
        self._result_analysis_hash = (
            analysis_hash if analysis_hash is not None else self.analysis_hash()
        )
        self._last_results_stale = self.results_stale
        self.runResultsChanged.emit()
        return True

    def _on_probe_failed(self, task_id: str, message: str, tb: str) -> None:
        exc = RuntimeError(message)
        exc.traceback = tb  # type: ignore[attr-defined]
        self._on_identity_probe_finished(task_id, exc)

    def _on_scan_progress(self, task_id: str, event: object) -> None:
        if task_id in self._scans:
            self.scanProgress.emit(task_id, event)

    def _on_scan_finished(self, task_id: str, result: object) -> None:
        if task_id in self._scans:  # a scan dropped by a project switch has no audience
            self._scans.discard(task_id)
            self.scanFinished.emit(task_id, result)

    def _on_scan_failed(self, task_id: str, message: str, tb: str) -> None:
        exc = RuntimeError(message)
        exc.traceback = tb  # type: ignore[attr-defined]
        self._on_scan_finished(task_id, exc)

    def _on_scan_cancelled(self, task_id: str) -> None:
        if task_id in self._scans:
            self._scans.discard(task_id)
            self.scanCancelled.emit(task_id)

    def _cancel_pending_scans(self) -> None:
        """Drop every outstanding scan (project switch): any result that still arrives is
        ignored."""
        for task_id in list(self._scans):
            self._tasks.cancel(task_id)
        self._scans.clear()

    def _cancel_pending_probes(self) -> None:
        """Drop every outstanding probe (project switch): queued ones never
        start, and any result that still arrives is ignored."""
        for task_id in list(self._identity_probes):
            self._tasks.cancel(task_id)
        self._identity_probes.clear()

    def _on_task_log(self, _task_id: str, line: str) -> None:
        self.append_log(line)

    def _on_task_failed(self, task_id: str, message: str, tb: str) -> None:
        exc = RuntimeError(message)
        exc.traceback = tb
        self.taskFinished.emit(task_id, exc)

    # ── project lifecycle ──────────────────────────────────────────────────

    def new_project(self, name: str, directory: Path) -> bool:
        """Create a blank manifest for a new project."""
        target = Path(directory) / f"{name}.t2d.json"
        if target.exists():
            raise FileExistsError(
                f"Project already exists: {target}. Open it or choose another name."
            )
        if self.prepare_project_change is not None and not self.prepare_project_change():
            return False
        self._cancel_pending_probes()
        self._cancel_pending_scans()
        self._session_facts.clear()
        now = datetime.now(tz=UTC)
        self._manifest = ProjectManifest(
            project_name=name,
            created_at=now,
            updated_at=now,
        )
        self._project_dir = Path(directory)
        self._manifest_path = target
        self._saved_manifest = None
        self._project_revision += 1
        self.set_run_results(None)
        self.projectChanged.emit()
        self.runLogAppended.emit(
            f"## New project: {name}\n_Created {now.isoformat()}_\n"
        )
        return True

    def open_project(self, t2d_path: Path) -> bool:
        """Load an existing project from a .t2d.json file."""
        from track2data.core.manifest import read as manifest_read

        manifest = manifest_read(t2d_path)
        if self.prepare_project_change is not None and not self.prepare_project_change():
            return False
        # Saving pending edits may have updated the file being reopened.
        manifest = manifest_read(t2d_path)
        self._cancel_pending_probes()
        self._cancel_pending_scans()
        self._session_facts.clear()
        self._manifest = manifest
        self._project_dir = t2d_path.parent
        self._manifest_path = Path(t2d_path)
        self._saved_manifest = manifest.model_dump_json()
        self._project_revision += 1
        self.set_run_results(None)
        self.projectChanged.emit()
        self.runLogAppended.emit(
            f"## Opened project: {self._manifest.project_name}\n"
            f"_Loaded from `{t2d_path}`_\n"
        )
        # Facts are not persisted in the manifest, so a reopened project would
        # otherwise show blank frame counts / calibration readiness forever.
        for ref in self._manifest.sessions:
            if ref.folder.exists():
                self._submit_probe(ref.session_id, ref.folder)
        return True

    def save_project(self) -> Path | None:
        """Persist the current manifest.  Returns the written path or None."""
        if self._manifest is None or self._project_dir is None:
            return None
        from track2data.core.manifest import write as manifest_write

        out = self._manifest_path or self._project_dir / f"{self._manifest.project_name}.t2d.json"
        manifest_write(self._manifest, out)
        self._manifest_path = out
        self._saved_manifest = self._manifest.model_dump_json()
        self.persistenceChanged.emit()
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

    def update_scene(self, scene: SceneConfig) -> None:
        if self._manifest is None:
            return
        self._manifest = self._manifest.model_copy(update={"scene": scene})
        self.sceneChanged.emit()

    def update_zone_vertices(self, index: int, vertices: list[tuple[float, float]]) -> None:
        """Replace one zone's vertices after checking the new shape.

        Raises ``ZoneValidationError`` and changes nothing if the shape is unusable, so a
        mouse drag can never leave a named zone with no area. Name, level and sign of the
        zone, and every other zone, are kept. ``update_zones`` stays unchecked on purpose:
        it also loads a tracker's own polygons, which the engine repairs.
        """
        if self._manifest is None:
            return
        from track2data.zones.geometry import validate_vertices

        validate_vertices(vertices)
        zones = self._manifest.zones
        rois = list(zones.rois)
        rois[index] = rois[index].model_copy(update={"vertices": [tuple(v) for v in vertices]})
        self.update_zones(zones.model_copy(update={"rois": rois}))

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
        fills in has_stable_identities once the reader has read it.

        A no-op (logged, not raised) if *folder* is already imported --
        multi-select and drag-drop both make it easy to submit the same
        folder twice, and without this guard that used to add two
        SessionRefs sharing one session_id, where removing either one
        removed both (removal filters by id)."""
        if self._manifest is None:
            return
        folder = Path(folder)
        if any(s.folder.resolve() == folder.resolve() for s in self._manifest.sessions):
            self.append_log(f"_Skipped already-imported session folder `{folder}`_\n")
            return
        session_id = default_session_id(folder)
        ref = SessionRef(session_id=session_id, folder=folder, sha256="")
        sessions = [*list(self._manifest.sessions), ref]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()

        self._submit_probe(session_id, folder)

    def _submit_probe(self, session_id: str, folder: Path) -> None:
        from track2data.readers import probe_session

        manifest = self._manifest
        ref = next(
            (r for r in (manifest.sessions if manifest else []) if r.session_id == session_id),
            None,
        )
        # The project's consent travels with the probe: it opens the same
        # trajectory file a read would, so a pickled-only session must be
        # refused (and prompt the user) here exactly as it is when it runs.
        allow_pickle = manifest.security.allow_pickle_trajectories if manifest else False
        # A session whose reader was chosen is probed by that reader with its saved
        # options, never detected again: another reader could read the same files into
        # different numbers, and one that needs the frame rate cannot be probed without it.
        task_id = self._tasks.submit(
            partial(
                probe_session,
                folder,
                allow_pickle=allow_pickle,
                reader=ref.reader if ref else None,
                options=dict(ref.reader_options) if ref else None,
            ),
            lane="probe",
        )
        self._identity_probes[task_id] = session_id

    def scan_folders(self, paths: Sequence[Path]) -> str:
        """Look at *paths* in the background and report which tracking software wrote them.

        Returns the task id. The result arrives on ``scanFinished`` (a ``ScanResult``, or an
        exception if it failed), progress on ``scanProgress``; ``cancel_scan`` stops it. The scan
        is read-only and runs in its own lane, so it neither waits for a pipeline run nor
        delays a probe.
        """
        from track2data.api import Engine

        roots = [Path(p) for p in paths]

        def run(*, progress: Any, cancel_check: Callable[[], None]) -> Any:
            return Engine.scan(roots, progress=progress, token=_CallableToken(cancel_check))

        task_id = self._tasks.submit_with_progress(run, cancel_check=True, lane="scan")
        self._scans.add(task_id)
        return task_id

    def cancel_scan(self, task_id: str) -> None:
        """Stop a scan; ``scanCancelled`` follows."""
        self._tasks.cancel(task_id)

    def add_confirmed(self, refs: Sequence[SessionRef]) -> list[SessionRef]:
        """Add the sessions the user confirmed, and probe each with the reader it saved.

        Returns the entries actually added. One already in the project (same place, same
        reader) is skipped and logged, like ``add_session`` does for a folder added twice; an id
        that clashes is made unique rather than letting one session replace another (the
        confirm step has already refused this, so it only guards a race).
        """
        if self._manifest is None:
            return []
        existing = list(self._manifest.sessions)
        taken = {ref.session_id for ref in existing}
        added: list[SessionRef] = []
        for ref in refs:
            if _is_duplicate(ref, [*existing, *added]):
                self.append_log(f"_Skipped already-imported session folder `{ref.folder}`_\n")
                continue
            if ref.session_id in taken:
                new_id = uniquify([ref.session_id], taken)[0]
                self.append_log(f"_Session id `{ref.session_id}` was taken; using `{new_id}`_\n")
                ref = ref.model_copy(update={"session_id": new_id})
            taken.add(ref.session_id)
            added.append(ref)
        if not added:
            return []
        self._manifest = self._manifest.model_copy(update={"sessions": [*existing, *added]})
        self.sessionsChanged.emit()
        for ref in added:
            self._submit_probe(ref.session_id, ref.folder)
        return added

    def _on_identity_probe_finished(self, task_id: str, result: object) -> None:
        session_id = self._identity_probes.pop(task_id, None)
        if session_id is None:
            return  # not an identity-probe task (e.g. a pipeline run/preview)
        if isinstance(result, Exception):
            self.append_log(f"_Identity probe failed for `{session_id}`: {result}_\n")
            if _is_pickle_refusal(result):
                # Not a broken folder -- a folder whose only trajectory format
                # executes code on load. Ask, naming the file, rather than
                # leaving the user with an import that simply failed.
                folder = next(
                    (
                        str(ref.folder)
                        for ref in (self._manifest.sessions if self._manifest else [])
                        if ref.session_id == session_id
                    ),
                    "",
                )
                self.pickleConsentRequired.emit(session_id, folder)
            return
        self._set_session_identity(
            session_id, result.has_stable_identities, result.track_wo_identities
        )
        self._set_session_input_hash(session_id, result)
        # The probe already read the full Session for that one boolean --
        # cache the rest of it too rather than discard it (see
        # ui/store/session_facts.py).
        self._session_facts[session_id] = SessionFacts.from_session(result)
        self.sessionFactsChanged.emit()

    def set_allow_pickle_trajectories(self, allowed: bool) -> None:
        """Record the project's answer to the unpickling question.

        Persisted in the manifest rather than held in memory so the user is
        asked once per project, not once per launch -- a question repeated
        every session stops being read.
        """
        if self._manifest is None:
            return
        security = self._manifest.security.model_copy(
            update={"allow_pickle_trajectories": allowed}
        )
        self._manifest = self._manifest.model_copy(update={"security": security})
        state = "enabled" if allowed else "disabled"
        self.append_log(f"_Loading pickled trajectories {state} for this project._\n")
        self.projectChanged.emit()

    def _set_session_input_hash(self, session_id: str, session: object) -> None:
        """Record the SHA-256 of the trajectory file this session was read from.

        Persisted (unlike SessionFacts) because it is the project's record of
        *which* input it was configured against: Engine.run() compares against
        it and says so when the source folder has changed underneath. Without
        it, `SessionRef.sha256` stayed "" forever and the manifest's central
        provenance claim was unverifiable.

        Best-effort. A folder that cannot be hashed must not stop it being
        added -- the run reports the missing checksum itself.
        """
        if self._manifest is None:
            return
        source = getattr(session, "trajectory_source", None)
        if source is None:
            return
        from track2data.core.hashing import file_sha256

        try:
            digest = file_sha256(Path(source))
        except OSError as exc:
            self.append_log(f"_Could not hash `{source}` for `{session_id}`: {exc}_\n")
            return

        sessions = [
            s.model_copy(update={"sha256": digest}) if s.session_id == session_id else s
            for s in self._manifest.sessions
        ]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})

    def _set_session_identity(
        self,
        session_id: str,
        has_stable_identities: bool,
        track_wo_identities: bool | None = None,
    ) -> None:
        """Record what the probe read. Deliberately does not touch
        ``identity_free_override`` -- a re-probe (re-opening a project, or
        re-adding a folder) must never quietly undo the user's own answer
        on the Sessions screen."""
        if self._manifest is None:
            return
        sessions = [
            s.model_copy(
                update={
                    "has_stable_identities": has_stable_identities,
                    "track_wo_identities": track_wo_identities,
                }
            )
            if s.session_id == session_id else s
            for s in self._manifest.sessions
        ]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()

    def set_video_path(self, session_id: str, path: Path) -> None:
        """Remember where *session_id*'s video really is ("Locate video...").

        idtracker.ai records the absolute path the video had on the machine it
        was tracked on, which is usually unreachable elsewhere
        (IDT_VIDEO_PATH_UNREACHABLE). Stored in the manifest, so the choice is
        made once per project; Engine.import_session applies it.
        """
        if self._manifest is None:
            return
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Video file not found: {path}")
        if session_id not in {s.session_id for s in self._manifest.sessions}:
            raise KeyError(f"No session {session_id!r} in this project")
        overrides = {**self._manifest.video_overrides, session_id: path}
        self._manifest = self._manifest.model_copy(update={"video_overrides": overrides})
        self.sessionsChanged.emit()

    def set_session_identity_free(self, session_id: str, value: bool | None) -> None:
        """Set (or clear, via None) the user's identity-free override for one
        session.

        ``None`` restores "follow whatever the tracker said". Anything else
        is the user overruling it -- which is the whole point of the
        Sessions-screen checkbox: idtracker.ai only knows whether *it* was
        asked to assign identities, not whether the resulting identities
        are trustworthy enough to build per-individual metrics on.
        """
        if self._manifest is None:
            return
        sessions = [
            s.model_copy(update={"identity_free_override": value})
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
