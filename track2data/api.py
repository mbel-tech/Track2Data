"""
High-level Engine facade.

Orchestrates readers, calibration, zones, metadata, preprocessing,
metrics, and exporters.  The facade is intentionally thin: it wires
subsystems together but delegates all logic to them.

Typical usage::

    from track2data.api import Engine
    from track2data.core.manifest import read

    manifest = read(Path("project.t2d.json"))
    engine = Engine(manifest)

    # Everything below in one call, one output subdirectory per session:
    result = engine.run(Path("output/"))

    # ...or drive it by hand, e.g. to inspect intermediate results:
    for session in engine.import_sessions():
        psess = engine.preprocess(session)
        metric_results = engine.compute_metrics(psess)
        payload = engine.build_payload(psess, metric_results)
        engine.export(payload, Path("output/") / session.session_id)
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import multiprocessing
import queue as queue_mod
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from track2data.core.errors import ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import (
    PreprocessedSession,
    PreprocessReport,
    ProjectManifest,
    RunResult,
    Session,
    SessionRef,
    SessionRunResult,
)
from track2data.core.progress import (
    CancellationToken,
    OperationCancelled,
    ProgressCallback,
    ProgressEvent,
    emit,
)
from track2data.core.timeline import timeline_problem
from track2data.readers import find_reader, read_session

if TYPE_CHECKING:
    from collections.abc import Sequence

    from track2data.core.models import CameraView
    from track2data.core.session_consistency import SessionSummary
    from track2data.metrics.base import Metric
    from track2data.readers.index import ScanBudget
    from track2data.readers.scan import ScanResult

logger = logging.getLogger(__name__)


_BIN_COLUMNS = ("bin_index", "bin_start_s", "bin_end_s")


def _with_bin_columns(df: Any, window: Any | None) -> Any:
    """*df* with bin_index/bin_start_s/bin_end_s placed after its key columns.
    ``window=None`` fills them with NaN (a whole-session result in a binned run)."""
    import numpy as np

    df = df.copy()
    values = (
        (np.nan, np.nan, np.nan)
        if window is None
        else (window.index, window.start_s, window.end_s)
    )
    pos = max(
        (df.columns.get_loc(k) + 1 for k in ("session_id", "individual_id") if k in df.columns),
        default=0,
    )
    for offset, (name, value) in enumerate(zip(_BIN_COLUMNS, values, strict=True)):
        df.insert(pos + offset, name, value)
    return df


def _recover_preprocess_report(
    psess: PreprocessedSession | None, exc: BaseException
) -> PreprocessReport | None:
    """Best available PreprocessReport for a failed session run.

    Two ways the step log can survive a failure, and both matter to a
    user staring at a broken run:

    * the failure came after ``preprocess()`` returned (metrics, payload
      build, export) -- the report is on the PreprocessedSession;
    * the failure came from a stage *inside* ``preprocess()`` that runs
      after the pipeline (calibration, zones) -- ``preprocess()`` raises
      PreprocessStageError, which carries the report.

    Returns None only when preprocessing genuinely never got far enough
    to produce one (e.g. import failed, or the pipeline itself blew up).
    """
    from track2data.core.errors import PreprocessStageError

    if psess is not None:
        return psess.report
    if isinstance(exc, PreprocessStageError):
        return exc.report
    return None


# ── parallel worker plumbing (must be module-level to be picklable) ──────────

_WORKER_EVENTS: Any = None
_WORKER_CANCEL: Any = None


def _parallel_init(events: Any, cancel: Any) -> None:
    global _WORKER_EVENTS, _WORKER_CANCEL
    _WORKER_EVENTS, _WORKER_CANCEL = events, cancel


def _parallel_run_one(
    manifest_json: str,
    index: int,
    out_dir: str,
    exporters: list[str] | None,
    cache_dir: str | None,
) -> SessionRunResult | None:
    """Run session *index* in a worker process.

    Returns None when cancelled (rather than raising: custom exception types
    do not reliably survive the trip back across the process boundary).
    """
    from track2data.core.models import ProjectManifest
    from track2data.core.progress import OperationCancelled

    manifest = ProjectManifest.model_validate_json(manifest_json)
    engine = Engine(manifest, cache_dir=Path(cache_dir) if cache_dir else None)
    ref = manifest.sessions[index]

    def check() -> None:
        if _WORKER_CANCEL.is_set():
            raise OperationCancelled()

    def callback(event: ProgressEvent) -> None:
        check()
        _WORKER_EVENTS.put(event)

    engine._cancel_check = check

    try:
        return engine._run_one_session(ref, Path(out_dir) / ref.session_id, exporters, callback)
    except OperationCancelled:
        return None


class Engine:
    """Stateless facade over all engine subsystems."""

    def __init__(self, manifest: ProjectManifest, *, cache_dir: Path | None = None) -> None:
        """*cache_dir* enables the on-disk preprocessed-session cache used by
        ``run()``; None (the default) never reads or writes it."""
        self._manifest = manifest
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        # Set for the duration of run(); see run()'s cancel_check.
        self._cancel_check: Callable[[], None] | None = None
        # (session_id, identity_free) -> per-animal metadata, so its warnings
        # are logged once per session rather than once per result frame.
        self._individual_metadata: dict[tuple[str, bool], dict[int, dict[str, Any]]] = {}

    @property
    def manifest(self) -> ProjectManifest:
        return self._manifest

    # ── metadata ──────────────────────────────────────────────────────────

    @cached_property
    def _metadata_join(self) -> Any:
        """
        Load, canonically map, and join the manifest's metadata source
        against its session IDs.

        Returns None when no metadata source (or no mapping rule) is
        configured. Computed once and cached: the same join result applies
        to every session processed by this Engine instance.
        """
        src = self._manifest.metadata_source
        rule = self._manifest.mapping
        if src is None or rule is None:
            return None

        from track2data.metadata.join import match
        from track2data.metadata.loader import load
        from track2data.metadata.mapping import apply_mapping

        raw = load(src.path)
        mapped = apply_mapping(raw, rule)
        session_ids = [ref.session_id for ref in self._manifest.sessions]
        return match(session_ids, mapped, rule)

    def _metadata_fields_for(self, session_id: str) -> dict[str, Any]:
        """
        Return the matched canonical metadata fields for *session_id*.

        Empty when metadata isn't configured or this session has no match.
        ``session_id`` and ``individual_id`` are always excluded: the join
        is session-level only, so a metadata-sourced individual_id (e.g.
        from a `fish_id` column alias) would silently overwrite the real
        per-row fish index used throughout the pipeline rather than adding
        useful data.
        """
        join = self._metadata_join
        if join is None:
            return {}
        fields = join.matched.get(session_id, {})
        return {k: v for k, v in fields.items() if k not in ("session_id", "individual_id")}

    def _metadata_individual_fields_for(
        self, psess: PreprocessedSession, identity_free: bool
    ) -> dict[int, dict[str, Any]]:
        """Per-animal metadata for one loaded session: animal index -> fields.

        Only when the mapping gives ``individual_id`` (one metadata row per
        animal). Keys are matched to animals per session, so the validator's
        identity labels are available; see ``MappingRule.individual_match``.
        Empty for identity-free sessions, where the row index is a detection
        slot rather than an animal, so a per-animal value would be attached to
        whichever animal happened to occupy the slot.
        """
        cache_key = (psess.session_id, bool(identity_free))
        if cache_key not in self._individual_metadata:
            self._individual_metadata[cache_key] = self._resolve_individual_metadata(
                psess, identity_free
            )
        return self._individual_metadata[cache_key]

    def _resolve_individual_metadata(
        self, psess: PreprocessedSession, identity_free: bool
    ) -> dict[int, dict[str, Any]]:
        from track2data.metadata.join import resolve_animal

        join = self._metadata_join
        rule = self._manifest.mapping
        keyed = join.matched_individuals.get(psess.session_id) if join is not None else None
        if not keyed or rule is None:
            return {}
        if identity_free:
            logger.warning(
                "Session %s is identity-free: per-animal metadata is ignored for it "
                "(animals cannot be told apart); session-level metadata still applies.",
                psess.session_id,
            )
            return {}
        n_animals = psess.n_animals
        labels = [str(x).strip().lower() for x in (psess.session.identities_labels or [])]
        out: dict[int, dict[str, Any]] = {}
        for key, fields in keyed.items():
            idx = resolve_animal(key, labels, rule.individual_match, n_animals)
            if idx is None:
                logger.warning(
                    "Session %s: metadata individual '%s' matches no animal (%s); ignored.",
                    psess.session_id, key,
                    f"labels {labels}" if labels and rule.individual_match == "label"
                    else f"{n_animals} animals, 0-based",
                )
                continue
            out.setdefault(idx, fields)
        for k in range(n_animals):
            if k not in out:
                logger.warning(
                    "Session %s: no metadata row for animal %d; its metadata is left empty.",
                    psess.session_id, k,
                )
        return out

    def _attach_metadata(self, df: Any, psess: PreprocessedSession, identity_free: bool) -> None:
        """Add this session's metadata columns to *df* in place.

        Session-level fields go on every frame. Per-animal fields go only on
        frames that have an ``individual_id`` column (never on group or pooled
        frames), NaN for an animal with no metadata row. A metadata column
        never overwrites a column the frame already has.
        """
        if df is None or len(df.columns) == 0:
            return
        attached: set[str] = set()
        for col, val in self._metadata_fields_for(psess.session_id).items():
            if col not in df.columns:
                df[col] = val
                attached.add(col)
        if "individual_id" not in df.columns:
            return
        per_animal = self._metadata_individual_fields_for(psess, identity_free)
        if not per_animal:
            return
        columns = list(dict.fromkeys(c for f in per_animal.values() for c in f))
        for col in columns:
            if col in df.columns and col not in attached:
                continue  # an engine column: never overwritten
            df[col] = df["individual_id"].map({k: f.get(col) for k, f in per_animal.items()})

    # ── session import ─────────────────────────────────────────────────────

    @staticmethod
    def scan(
        roots: Sequence[Path],
        *,
        budget: ScanBudget | None = None,
        progress: ProgressCallback | None = None,
        token: CancellationToken | None = None,
    ) -> ScanResult:
        """Look at the folder(s) a user pointed at and report what is in them.

        Which tracking software wrote the output, with what confidence and on what evidence,
        and which sessions it holds -- ranked, so the first group is the best guess. The first
        step of adding sessions: nothing is read into a session and nothing is added to a
        project until the user has confirmed the result.

        Static because it needs no project (it is how a project gets its first sessions).
        Read-only: never writes, and never unpickles. Raises only ``OperationCancelled``.
        """
        from track2data.readers.scan import scan

        return scan(roots, budget=budget, progress=progress, token=token)

    def import_session(self, folder: Path) -> Session:
        """Auto-detect the reader, read *folder* and apply the project's import settings.

        Trajectory formats that execute code on load are refused unless this project has
        opted in via ``security.allow_pickle_trajectories``. A folder that also carries an h5
        or csv trajectory imports normally either way -- the reader falls through to it.
        """
        session = read_session(
            Path(folder), allow_pickle=self._manifest.security.allow_pickle_trajectories
        )
        return self._apply_import_settings(session)

    def _apply_import_settings(self, session: Session) -> Session:
        """Settings that act on a freshly read session: blob-derived body lengths, tracker
        corrections and the video override. The one place they are applied, so a saved reader
        and an auto-detected one behave the same. Blob files are idtracker.ai's, so other
        readers' sessions skip the enrichment (the video override still applies)."""
        allow_pickle = self._manifest.security.allow_pickle_trajectories
        blob_capable = session.reader.startswith("idtrackerai")

        if self._manifest.calibration.body_length_source == "blobs" and blob_capable:
            if allow_pickle:
                from track2data.readers.idtrackerai.blobs import (
                    enrich_session_with_blob_body_length,
                )

                session = enrich_session_with_blob_body_length(
                    session, allow_pickle=True
                )
                if session.blob_body_length_source_file is None:
                    logger.warning(
                        "Session %s: body_length_source='blobs' but no usable "
                        "blob pickle was found; keeping the session-wide "
                        "body length.",
                        session.session_id,
                    )
            else:
                logger.warning(
                    "body_length_source='blobs' needs "
                    "security.allow_pickle_trajectories (the blob file is a "
                    "pickle); keeping the session-wide body length for %s.",
                    session.session_id,
                )

        if self._manifest.blob_diagnostics and blob_capable:
            if allow_pickle:
                from track2data.readers.idtrackerai.blobs import (
                    enrich_session_with_blob_corrections,
                )

                session = enrich_session_with_blob_corrections(
                    session, allow_pickle=True
                )
            else:
                logger.warning(
                    "blob_diagnostics needs security.allow_pickle_trajectories "
                    "(the blob file is a pickle); D-15 will be NaN for %s.",
                    session.session_id,
                )

        return self._apply_video_override(session)

    def _apply_video_override(self, session: Session) -> Session:
        """Point *session* at the replacement video the manifest records under its id, when
        that file exists. Only the path changes; fps, size and frame count stay."""
        override = self._manifest.video_overrides.get(session.session_id)
        if override is not None and Path(override).exists():
            session = session.model_copy(
                update={"video": session.video.model_copy(update={"path": Path(override)})}
            )
        return session

    def set_video_path(self, session_id: str, path: Path) -> None:
        """Point *session_id* at its real video file (the "Locate video..." fix).

        idtracker.ai records the machine-specific absolute path the video had
        when it was tracked, which is usually unreachable elsewhere
        (IDT_VIDEO_PATH_UNREACHABLE). The choice is stored in the manifest so
        it only has to be made once per project.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Video file not found: {path}")
        if session_id not in {r.session_id for r in self._manifest.sessions}:
            raise KeyError(f"No session {session_id!r} in this project")
        overrides = {**self._manifest.video_overrides, session_id: path}
        self._manifest = self._manifest.model_copy(update={"video_overrides": overrides})

    def import_ref(self, ref: SessionRef) -> Session:
        """Import the session a manifest entry describes.

        An entry that records its reader replays that choice, with its saved options, instead of
        detecting again. One that does not (a manifest from before readers could be chosen) is
        auto-detected through :meth:`import_session`, exactly as it always was. A recorded
        reader that is not installed is an error and never a quiet fall back to detection: a
        different reader could read the same files into different numbers.

        Either way the session takes the entry's id, so the output directory, the metadata join
        and the export all key on one name whatever id the reader derived from the files.
        """
        if ref.reader is None:
            # Settings are applied inside import_session, once; only the override is looked
            # up again below, because the manifest keys it by the entry's id and the reader
            # may have derived another.
            session = self.import_session(ref.folder)
            session = session.model_copy(update={"session_id": ref.session_id})
            return self._apply_video_override(session)
        try:
            session = read_session(
                Path(ref.folder),
                reader=ref.reader,
                options=ref.reader_options,
                allow_pickle=self._manifest.security.allow_pickle_trajectories,
            )
        except ImportError_ as exc:
            if exc.code != "READER_UNKNOWN":
                raise
            raise ImportError_(
                f"Session {ref.session_id!r} was added with reader {ref.reader!r}, "
                "which is not available here",
                code="READER_NOT_AVAILABLE",
                subject=ref.reader,
                remediation="Install the plug-in that provides this reader, or remove the "
                "session and add it again so a reader is detected afresh.",
            ) from exc
        session = session.model_copy(update={"session_id": ref.session_id})
        return self._apply_import_settings(session)

    def import_sessions(
        self, *, progress: ProgressCallback | None = None
    ) -> list[Session]:
        """Import all sessions listed in ``manifest.sessions``.

        Raises on the first session that fails to import -- FR-IMP-3
        requires failures be flagged with an actionable message, never
        silently dropped (see issue #7: this used to catch, log, and
        continue, so a bad session in a project was invisible unless
        someone happened to check the log). This is the "import
        everything, or tell me exactly what's wrong" entry point for
        direct/CLI use. ``Engine.run()`` does NOT call this method for
        its own batch resilience -- it imports each session individually
        inside ``_run_one_session`` so one bad session is captured as
        that session's ``SessionRunResult.error`` instead of aborting an
        entire multi-session run.
        """
        sessions: list[Session] = []
        refs = self._manifest.sessions
        for i, ref in enumerate(refs):
            emit(
                progress,
                ProgressEvent(
                    stage="import",
                    current=i + 1,
                    total=len(refs),
                    session_id=ref.session_id,
                    message=f"Importing {ref.session_id}",
                ),
            )
            sessions.append(self.import_ref(ref))
        return sessions

    # ── preprocessed-session cache ─────────────────────────────────────────

    #: Bump when PreprocessedSession's layout or preprocessing semantics change.
    _CACHE_SCHEMA = 6

    def _cache_key(self, ref: SessionRef) -> tuple[Any, str] | None:
        """(store, key) for the session *ref* describes, or None when caching is
        off or impossible.

        The key is the reader that reads it, the options that reader was given, the
        folder's fingerprint and the configs. The reader is the one the entry saved, or
        the one detected for an entry that saved none. The options are in the key because
        they are inputs the files do not record: the same folder read at 25 fps and at
        50 fps is two different sessions.
        """
        if self._cache_dir is None:
            return None
        from track2data import __version__
        from track2data.cache.store import CacheStore
        from track2data.core.hashing import dict_sha256, folder_fingerprint
        from track2data.readers import detect_reader

        reader_name = ref.reader
        if reader_name is None:
            detected = detect_reader(ref.folder)
            if detected is None:
                return None
            reader_name = detected.name
        m = self._manifest
        config_hash = dict_sha256(
            {
                "schema": self._CACHE_SCHEMA,
                "app": __version__,
                "reader_options": ref.reader_options,
                "import_settings": self._import_settings_fingerprint(ref),
                "preprocess": m.preprocess.model_dump(mode="json"),
                "calibration": m.calibration.model_dump(mode="json"),
                "zones": m.zones.model_dump(mode="json"),
            }
        )
        store = CacheStore(self._cache_dir)
        return store, store.key(reader_name, folder_fingerprint(ref.folder), config_hash)

    def _import_settings_fingerprint(self, ref: SessionRef) -> dict[str, Any]:
        """The project settings, besides the configs, that change what importing *ref* returns.

        The cache holds the imported session along with its preprocessed arrays, so any
        setting :meth:`_apply_import_settings` acts on has to be in the key, or a rerun
        after changing it would be served the old session. Pickle permission decides whether
        the blob enrichment can happen at all. The video override is keyed by the manifest's
        id for this entry, so another session's override never invalidates this one; whether
        the file exists is part of it because a missing file is ignored on import.
        """
        m = self._manifest
        override = m.video_overrides.get(ref.session_id)
        return {
            "allow_pickle_trajectories": m.security.allow_pickle_trajectories,
            "blob_diagnostics": m.blob_diagnostics,
            "video_override": (
                None if override is None else [str(override), Path(override).exists()]
            ),
        }

    def preprocess_ref(self, ref: SessionRef) -> PreprocessedSession:
        """Preprocess the session a manifest entry describes, reusing/filling the cache
        when ``cache_dir`` is set. For callers (e.g. the GUI's trajectory viewer) that
        need the arrays but are not running the whole pipeline. A run and the viewer
        share cache entries, because both key on the entry's reader and options."""
        psess = self._cache_get(ref)
        if psess is None:
            psess = self.preprocess(self.import_ref(ref))
            self._cache_put(ref, psess)
        return psess

    def preprocess_folder(self, folder: Path) -> PreprocessedSession:
        """Like :meth:`preprocess_ref` for a folder that is not a manifest entry: its
        reader is detected and no options are saved for it."""
        folder = Path(folder)
        ref = SessionRef(
            session_id=default_session_id(folder.resolve()), folder=folder, sha256=""
        )
        return self.preprocess_ref(ref)

    def _cache_get(self, ref: SessionRef) -> PreprocessedSession | None:
        keyed = self._cache_key(ref)
        if keyed is None:
            return None
        store, key = keyed
        obj = store.get_object(key)
        if not isinstance(obj, PreprocessedSession):
            return None
        # The entry is keyed by what was read, not by what the session is called: the same
        # files may have been cached under another id (a renamed session, the viewer).
        if obj.session.session_id == ref.session_id:
            return obj
        session = obj.session.model_copy(update={"session_id": ref.session_id})
        return dataclasses.replace(obj, session=session)

    def _cache_put(self, ref: SessionRef, psess: PreprocessedSession) -> None:
        try:
            keyed = self._cache_key(ref)
            if keyed is not None:
                keyed[0].put_object(keyed[1], psess)
        except Exception:
            logger.warning("Could not write preprocessed-session cache.", exc_info=True)

    # ── preprocessing ──────────────────────────────────────────────────────

    def preprocess(self, session: Session) -> PreprocessedSession:
        """
        Apply the full preprocessing pipeline then calibration and zones.

        Steps:
          1. ``preprocess.pipeline.run`` → gap fill, jump detect, identity
             switch, smoothing, coverage validation, kinematics.
          2. Calibration (scalar or body-length) if configured.
          3. Zone assignment if zones are configured.

        Steps 2 and 3 run after step 1 has already produced the step
        report. A failure in either still propagates -- silently
        continuing would emit pixel-unit or zone-less results as if they
        were fine -- but it propagates as a ``PreprocessStageError``
        carrying that report, so callers can surface the step log instead
        of losing it to where the exception happened to be raised.
        """
        from track2data.preprocess.pipeline import run as pp_run

        problem = timeline_problem(session.tracking_intervals, int(session.raw_xy.shape[0]))
        if problem is not None:
            logger.warning(
                "Session %s: %s; frame numbers and times fall back to the stored row position "
                "and are not verified video times.",
                session.session_id,
                problem,
            )
        psess = pp_run(
            session,
            self._manifest.preprocess,
            check=self._cancel_check,
            bridge_allowed=not self.identity_free_for(session),
        )
        return self.apply_calibration_and_zones(psess)

    def apply_calibration_and_zones(
        self, psess: PreprocessedSession
    ) -> PreprocessedSession:
        """Steps 2 and 3 of :meth:`preprocess`, on an already-preprocessed session.

        Separated so a caller that ran the pipeline itself -- the
        sensitivity sweep re-runs it once per grid point -- gets the same
        calibration and zone treatment as a normal run rather than a
        re-implementation of it that could drift.
        """
        session = psess.session
        # The tracker's own body length is calibration-independent, so *_bl
        # metrics work whichever mode is chosen. Body-length calibration below
        # then applies its own validation on top of the same values. Done here
        # rather than in preprocess() so a caller that ran the pipeline itself
        # (the sensitivity sweep) gets it too.
        if session.body_length_px is not None:
            psess.body_length_px = np.asarray(session.body_length_px, dtype=np.float64).copy()
        try:
            # Calibration.
            cfg = self._manifest.calibration
            if cfg.mode == "scalar" and cfg.px_per_cm is not None:
                from track2data.calibration.scalar import apply_scalar_calibration
                psess = apply_scalar_calibration(psess, cfg)
            elif cfg.mode == "bodylength":
                try:
                    from track2data.calibration.bodylength import (
                        apply_bodylength_calibration,
                    )
                    psess = apply_bodylength_calibration(psess, cfg)
                except Exception:
                    logger.warning("Body-length calibration failed; skipping.")
            elif cfg.mode == "session":
                # Deliberately not caught-and-skipped like bodylength
                # above: a missing length_unit here means Engine.validate()
                # should already have blocked the run (fail loudly, name
                # the sessions) rather than silently emitting uncalibrated
                # output under a mode the user explicitly chose because
                # they wanted per-session calibration.
                from track2data.calibration.session_unit import apply_session_calibration
                psess = apply_session_calibration(psess, cfg)

            # Zone assignment.
            zone_set = self._manifest.zones
            if zone_set.rois:
                from track2data.zones.geometry import assign_zones
                main_zone, sec_zone = assign_zones(psess.xy, zone_set)
                from dataclasses import replace
                psess = replace(psess, main_zone=main_zone, sec_zone=sec_zone)
        except Exception as exc:
            from track2data.core.errors import PreprocessStageError
            raise PreprocessStageError(
                f"Preprocessing succeeded but a later stage failed: {exc}",
                report=psess.report,
                subject=session.session_id,
                remediation=(
                    "Check the calibration and zone settings for this project; "
                    "the preprocessing step log is attached to this result."
                ),
            ) from exc

        return psess

    # ── metrics ────────────────────────────────────────────────────────────

    def _effective_cfg(
        self, metric_cls: type[Metric], psess: PreprocessedSession
    ) -> dict[str, Any]:
        """Build the cfg dict passed to metric_cls().compute().

        Layered, lowest to highest precedence:
          1. The metric's own MetricParameter defaults.
          2. MetricSelection.config[metric_id] -- the user's ⚙-dialog
             overrides, for non-derived parameters only.
          3. This session's own derived values (metrics/derived.py) --
             never user-settable, so they always win, even against a
             stale/hand-edited manifest that tries to set one.

        Metric.compute(session, cfg) has accepted this dict since it
        was written, but nothing ever called it with one -- every
        cfg-reading branch in every metric was dead code, and Z-2
        (Area-Corrected Occupancy) always returned an empty DataFrame
        as a direct result. This is the plumbing that was missing.
        """
        from track2data.metrics.derived import derive_metric_params

        cfg: dict[str, Any] = {}
        derived_names = {p.name for p in metric_cls.parameters if p.derived}
        for param in metric_cls.parameters:
            if not param.derived and param.default is not None:
                cfg[param.name] = param.default

        overrides = self._manifest.metrics.config.get(metric_cls.id, {})
        for key, value in overrides.items():
            # `is not None` on both layers, not just the defaults one. A
            # metric tests `"key" in cfg` before reading, so a None here
            # passes that check and then fails the conversion -- and
            # compute_metrics() logs and drops the metric, so the export
            # is silently missing it. Absent means "unset", which is what
            # a null in the manifest is trying to say.
            if key not in derived_names and value is not None:
                cfg[key] = value

        cfg.update(derive_metric_params(metric_cls.id, psess, self._manifest.zones))
        return cfg

    def identity_free_for(
        self, session: Session, explicit: bool | None = None
    ) -> bool:
        """Whether *session* must be treated as identity-free.

        Precedence: an explicit answer from the caller, else the user's
        override for that session, else the session file's own
        ``track_wo_identities``.

        The session file -- not ``SessionRef.track_wo_identities`` -- is the
        fallback on purpose. That field is a *cache* of this same value,
        filled by the GUI's background probe, and it stays None on any path
        that has no probe: a hand-edited manifest, ``track2data init``, or
        any CLI run. Resolving from the cache would mean the CLI silently
        ignored a session that idtracker.ai had declared identity-free,
        which is precisely the case this gate exists for. Only the override
        is genuinely manifest-only state, because only a human can author it.

        ``SessionRef.is_identity_free()`` is the matching predicate for
        callers with no Session in hand (the metrics screen, ``validate()``),
        where the cache is all there is.
        """
        if explicit is not None:
            return explicit
        for ref in self._manifest.sessions:
            if (
                ref.session_id == session.session_id
                and ref.identity_free_override is not None
            ):
                return ref.identity_free_override
        return session.track_wo_identities is True

    def _identity_free_override(self, session_id: str) -> bool | None:
        """The user's own identity-free answer for *session_id*, None when they gave none."""
        for ref in self._manifest.sessions:
            if ref.session_id == session_id:
                return ref.identity_free_override
        return None

    def identity_skipped_metrics(self, identity_free: bool) -> dict[str, str]:
        """Selected metric ids that an identity-free session must not run,
        mapped to the reason, for the export record.

        Empty when *identity_free* is False, so the normal path costs
        nothing. Diagnostics are deliberately absent: they are the evidence
        for *why* these were skipped and are always computed.
        """
        if not identity_free:
            return {}
        from track2data.metrics import get

        reason = (
            "session is identity-free (tracked without identification, or "
            "marked identity-free by the user): the row index is a per-frame "
            "detection slot, not a persistent animal"
        )
        selected = [
            *self._manifest.metrics.individual,
            *self._manifest.metrics.group,
            *self._manifest.metrics.zone,
        ]
        skipped: dict[str, str] = {}
        for mid in selected:
            cls = get(mid)
            if cls is not None and cls.requires_identity:
                skipped[mid] = reason
        return skipped

    def camera_view_for(self, session: Session | None = None) -> CameraView:
        """The camera view *session* was recorded from.

        Project-level today. Every caller asks here rather than reading the manifest, so a
        per-session view (a project mixing top and side recordings) is a change to this one
        method.
        """
        return self._manifest.scene.camera_view

    def view_skipped_metrics(self, session: Session | None = None) -> dict[str, str]:
        """Selected metric ids the camera view rules out, mapped to the reason."""
        from track2data.metrics import get
        from track2data.metrics.availability import view_skipped_metrics

        selected = [
            *self._manifest.metrics.individual,
            *self._manifest.metrics.group,
            *self._manifest.metrics.zone,
        ]
        return view_skipped_metrics(selected, self.camera_view_for(session), get)

    def skipped_metrics(
        self, identity_free: bool, session: Session | None = None
    ) -> dict[str, str]:
        """Every selected metric id this session must not run, mapped to the reason, for the
        export record: the identity gate and the camera-view gate together. A metric that both
        gates rule out carries both reasons."""
        skipped = self.identity_skipped_metrics(identity_free)
        for mid, reason in self.view_skipped_metrics(session).items():
            skipped[mid] = f"{skipped[mid]}; also {reason}" if mid in skipped else reason
        return skipped

    def _bin_seconds(self) -> float | None:
        minutes = self._manifest.metrics.timepoint_minutes
        return float(minutes) * 60.0 if minutes and minutes > 0 else None

    @staticmethod
    def _compute_one(
        cls: type[Metric], psess: PreprocessedSession, cfg: dict[str, Any], identity_free: bool
    ) -> Any:
        """One metric on one (whole or sliced) session. Occupancy-style zone
        metrics are pooled over detection slots on identity-free sessions."""
        if identity_free and cls.pools_when_identity_free:
            from track2data.metrics.zone import pooled_view

            df = cls().compute(pooled_view(psess), cfg)
            return df.drop(columns=["individual_id"], errors="ignore")
        return cls().compute(psess, cfg)

    def _compute_windowed(
        self,
        cls: type[Metric],
        psess: PreprocessedSession,
        cfg: dict[str, Any],
        windows: list[Any],
        identity_free: bool,
    ) -> Any:
        """Run *cls* on each time window and stack the results.

        *cfg* (derived on the whole session by the caller) is extended with
        whatever the metric derives from the data itself, resolved once on the
        whole session, so every bin uses the same threshold.
        """
        import pandas as pd

        from track2data.metrics.binning import slice_psess

        window_cfg = {**cfg, **cls.resolve_for_windows(psess, cfg)}
        parts = []
        for w in windows:
            if self._cancel_check is not None:
                self._cancel_check()
            df = self._compute_one(
                cls, slice_psess(psess, w.start_row, w.stop_row), window_cfg, identity_free
            )
            parts.append(_with_bin_columns(df, w))
        non_empty = [p for p in parts if not p.empty]
        if not non_empty:
            return parts[0] if parts else pd.DataFrame()
        return pd.concat(non_empty, ignore_index=True)

    def compute_metrics(
        self,
        psess: PreprocessedSession,
        *,
        identity_free: bool | None = None,
    ) -> dict[str, Any]:
        """
        Compute all selected metrics for *psess*.

        Returns a dict mapping metric_id to a ``pd.DataFrame``.
        Diagnostic metrics (D-1..D-6) are always computed.

        Two guards drop selected metrics for a session:

        * ``Session.exclusive_rois`` is True -> group metrics (see below).
        * the session is identity-free -> every metric whose
          ``requires_identity`` is True. On such a session the row index is
          a per-frame detection slot rather than a persistent animal, so
          any metric that follows an individual across frames returns a
          number that looks publishable and means nothing. The GUI has
          promised this skip in a tooltip since the metrics screen was
          written; this is where it actually happens.

        *identity_free* forces the verdict for callers that already know it
        (``_run_one_session`` passes the user's override, which may itself
        be None); None resolves it via ``identity_free_for()``.

        During ``run()`` the run's *cancel_check* is called before each
        selected metric, so a cancellation request is noticed between
        metrics; ``OperationCancelled`` propagates out of this method.
        """

        from track2data.metrics.diagnostic import compute_all_diagnostics

        results: dict[str, Any] = {}

        # Always-on diagnostics. Computed even for an identity-free session:
        # D-5 IdentityStability is precisely the record of that fact, so
        # suppressing the diagnostics would remove the evidence for the
        # skips below.
        results.update(
            compute_all_diagnostics(
                psess,
                identity_free_declared=self._identity_free_override(psess.session_id),
            )
        )

        sel = self._manifest.metrics

        is_identity_free = self.identity_free_for(psess.session, identity_free)
        identity_skipped = self.identity_skipped_metrics(is_identity_free)
        view_skipped = self.view_skipped_metrics(psess.session)
        skipped = self.skipped_metrics(is_identity_free, psess.session)
        if identity_skipped:
            logger.warning(
                "Skipping identity-dependent metrics (%s) for session %s: "
                "the session is identity-free, so per-individual results "
                "would not correspond to individual animals.",
                ", ".join(sorted(identity_skipped)),
                psess.session_id,
            )
        if view_skipped:
            logger.warning(
                "Skipping metrics (%s) for session %s: the project's camera view is %s, "
                "which they are not meaningful for.",
                ", ".join(sorted(view_skipped)),
                psess.session_id,
                self.camera_view_for(psess.session),
            )

        bin_seconds = self._bin_seconds()
        windows = None
        if bin_seconds is not None:
            from track2data.metrics.binning import bin_windows

            windows = bin_windows(psess, bin_seconds)

        def _run(metric_ids: list[str], *, binned: bool = True) -> None:
            from track2data.metrics import get
            for mid in metric_ids:
                if mid in skipped:
                    continue
                # Outside the try below: OperationCancelled must not be
                # swallowed as "metric failed; skipping".
                if self._cancel_check is not None:
                    self._cancel_check()
                cls = get(mid)
                if cls is None:
                    logger.warning("Metric %s not registered; skipping.", mid)
                    continue
                try:
                    cfg = self._effective_cfg(cls, psess)
                    if windows is not None and binned and cls.window_safe:
                        results[mid] = self._compute_windowed(
                            cls, psess, cfg, windows, is_identity_free
                        )
                        continue
                    results[mid] = self._compute_one(cls, psess, cfg, is_identity_free)
                    if windows is not None and binned:
                        # Not meaningful per window: one whole-session row, with
                        # empty bin columns so it never merges into a bin.
                        results[mid] = _with_bin_columns(results[mid], None)
                except OperationCancelled:
                    raise
                except Exception:
                    logger.exception("Metric %s failed; skipping.", mid)

        _run(sel.individual)

        if psess.session.exclusive_rois is True and sel.group:
            # With exclusive_rois=True, identities are physically
            # partitioned by ROI (idtracker.ai_usage.md: "Treat each
            # separate ROI as a closed group of identities") -- animals in
            # different partitions can never interact, so every group
            # metric (nearest-neighbour distance, polarisation, cohesion,
            # ...) computed across the whole session is meaningless.
            # Skipping rather than silently producing publishable-looking
            # numbers; per-compartment group metrics (using
            # Session.identities_groups to know which identity is in which
            # partition) would be the correct fix but is a larger,
            # separate change than this guard.
            logger.warning(
                "Skipping group metrics (%s) for session %s: "
                "Session.exclusive_rois=True -- identities are physically "
                "partitioned, so cross-session group metrics are meaningless.",
                ", ".join(sel.group),
                psess.session_id,
            )
        else:
            _run(sel.group)

        _run(sel.zone)
        _run(sel.diagnostic, binned=False)

        for df in results.values():
            self._attach_metadata(df, psess, is_identity_free)

        return results

    def build_fish_by_frame(
        self, psess: PreprocessedSession, *, identity_free: bool | None = None
    ) -> Any:
        """
        Build the master per-frame DataFrame for *psess*.

        Columns: session_id, individual_id, frame, time_s, x_px, y_px,
                 was_interpolated, speed_px_s, heading_rad, main_zone, sec_zone.
        Calibrated columns added when psess.px_per_cm is set.
        individual_label/individual_color added when
        Session.identities_labels/identities_colors are present.
        was_interpolated is True where a position was originally missing
        and is now present after preprocessing -- see
        PreprocessedSession.was_interpolated.

        When ``MetricSelection.quality_threshold`` > 0, rows whose
        ``id_probabilities[frame, animal] < threshold`` have their position/
        kinematics columns masked to NaN (position and derived columns only
        -- session_id/individual_id/frame/time_s survive so the row can
        still be located). id_probability itself is always emitted as a
        column, masked or not, so the applied threshold is auditable from
        the export rather than only from the manifest.

        ``frame``/``time_s`` are the true video frame/time when
        ``Session.tracking_intervals`` reconciles with the array length
        (see ``PreprocessedSession.timeline``); ``in_tracking_interval``
        records whether that mapping was trusted (True) or the raw array
        position was used as a fallback (NaN -- not False, since "outside
        the interval" is not what an unreconciled mapping means).
        """
        import numpy as np
        import pandas as pd

        n_frames = psess.n_frames
        n_animals = psess.n_animals
        fps = psess.fps

        true_frame_per_row, mapping_valid = psess.timeline()
        frames = np.repeat(true_frame_per_row, n_animals)
        individuals = np.tile(np.arange(n_animals), n_frames)
        time_s = frames / fps
        in_interval_fill = True if mapping_valid else np.nan
        in_interval = np.full(n_frames * n_animals, in_interval_fill)
        if psess.tracked_mask is not None:
            # rows inserted for unobserved video are estimates, not tracked frames
            in_interval = np.repeat(psess.tracked_mask, n_animals)

        xy_flat = psess.xy.reshape(-1, 2)
        speed_flat = psess.kinematics.speed_px_s.reshape(-1)
        heading_flat = psess.kinematics.heading_rad.reshape(-1)

        df = pd.DataFrame({
            "session_id": psess.session_id,
            "individual_id": individuals,
            "frame": frames,
            "time_s": time_s,
            "in_tracking_interval": in_interval,
            "x_px": xy_flat[:, 0],
            "y_px": xy_flat[:, 1],
            "was_interpolated": psess.was_interpolated.reshape(-1),
            "speed_px_s": speed_flat,
            "heading_rad": heading_flat,
        })
        if psess.separator_mask is not None:
            # a separator row only keeps two tracking intervals apart; it is not a frame
            df["_separator"] = np.repeat(psess.separator_mask, n_animals)

        # Distinct from was_interpolated, which covers only gap-filled frames
        # that started as NaN. A jump-replaced position started as a real
        # measurement that jump_detect judged implausible -- previously
        # visible only as an aggregate count in PreprocessReport, so no
        # reviewer could tell which rows it touched.
        if psess.jump_replaced is not None:
            df["was_jump_replaced"] = psess.jump_replaced.reshape(-1)
        bin_seconds = self._bin_seconds()
        if bin_seconds is not None:
            df.insert(
                df.columns.get_loc("time_s") + 1,
                "bin_index",
                np.floor(time_s / bin_seconds + 1e-9).astype(np.int64),
            )

        if psess.px_per_cm is not None:
            df["x_cm"] = df["x_px"] / psess.px_per_cm
            df["y_cm"] = df["y_px"] / psess.px_per_cm
            df["speed_cm_s"] = df["speed_px_s"] / psess.px_per_cm

        if psess.main_zone is not None:
            df["main_zone"] = psess.main_zone.reshape(-1)
        if psess.sec_zone is not None:
            df["sec_zone"] = psess.sec_zone.reshape(-1)

        # identities_labels/identities_colors are index-aligned with
        # individual_id (0-based) -- surface them so a user who spent time
        # naming/colouring identities in the idtracker.ai Validator gets
        # them back in the export instead of bare 0..N-1 integers.
        labels = psess.session.identities_labels
        if labels:
            df["individual_label"] = [
                labels[i] if i < len(labels) else None for i in individuals
            ]
        colors = psess.session.identities_colors
        if colors:
            df["individual_color"] = [
                colors[i] if i < len(colors) else None for i in individuals
            ]

        threshold = self._manifest.metrics.quality_threshold
        id_prob = psess.id_probabilities_aligned
        if id_prob is not None:
            df["id_probability"] = id_prob.reshape(-1)
        elif threshold > 0:
            # A threshold was configured but there is nothing to evaluate it
            # against -- record that honestly (an all-NaN column) rather
            # than silently skipping the filter, which would make the
            # manifest's quality_threshold value actively misleading (see
            # MetricSelection.quality_threshold).
            logger.warning(
                "quality_threshold=%.3f configured but session %s has no "
                "id_probabilities; no rows were masked.",
                threshold,
                psess.session_id,
            )
            df["id_probability"] = np.nan

        if threshold > 0 and id_prob is not None:
            below = df["id_probability"] < threshold
            masked_cols = [
                c for c in ("x_px", "y_px", "x_cm", "y_cm",
                            "speed_px_s", "speed_cm_s", "heading_rad")
                if c in df.columns
            ]
            df.loc[below, masked_cols] = np.nan

        self._attach_metadata(
            df, psess, self.identity_free_for(psess.session, identity_free)
        )

        if "_separator" in df.columns:
            df = df[~df["_separator"]].drop(columns="_separator")

        return df.sort_values(["session_id", "individual_id", "frame"]).reset_index(
            drop=True
        )

    # ── payload / export ──────────────────────────────────────────────────

    def build_payload(
        self,
        psess: PreprocessedSession,
        metric_results: dict[str, Any],
        *,
        identity_free: bool | None = None,
    ) -> Any:
        """
        Assemble an ``ExportPayload`` from a preprocessed session and its
        computed metric results, bucketing results by level (IL-*/GL-*/
        Z-*/D-*) and building the master per-frame table.

        *identity_free* must match whatever was passed to
        ``compute_metrics`` for this session, so the payload's
        ``skipped_metrics`` record agrees with what was actually skipped;
        None resolves it the same way ``compute_metrics`` does.
        """
        from track2data.exporters.base import ExportPayload, SessionProvenance

        fish_by_frame = self.build_fish_by_frame(psess, identity_free=identity_free)

        individual_metrics = {k: v for k, v in metric_results.items()
                               if k.startswith("IL-")}
        group_metrics = {k: v for k, v in metric_results.items()
                         if k.startswith("GL-")}
        zone_metrics = {k: v for k, v in metric_results.items()
                        if k.startswith("Z-")}
        diagnostic_metrics = {k: v for k, v in metric_results.items()
                               if k.startswith("D-")}

        session = psess.session
        quality = session.quality or {}
        tracking_log = session.tracking_log or {}

        is_identity_free = self.identity_free_for(session, identity_free)
        # Which of the two inputs actually produced the verdict, so a
        # reader of the export can tell "idtracker.ai said so" from "a human
        # overruled idtracker.ai" -- they warrant different scrutiny.
        ref = next(
            (r for r in self._manifest.sessions if r.session_id == session.session_id),
            None,
        )
        if ref is not None and ref.identity_free_override is not None:
            identity_free_source = "user override"
        elif session.track_wo_identities is not None:
            identity_free_source = "tracker"
        else:
            identity_free_source = "not reported"
        from track2data.calibration.session_unit import length_calibration_spread

        cal_n, cal_rel_sd = length_calibration_spread(session.length_calibrations)
        # What the export says about the software behind the numbers. The reader class knows its
        # display name and whether it was ever tested on real output; the manifest entry knows
        # who chose it and with which options. A reader that is no longer registered has neither.
        reader_cls = find_reader(session.reader)
        camera_view = self.camera_view_for(session)
        water_column = None
        from track2data.metrics import get as _get_metric
        from track2data.metrics.availability import view_dependent_metrics

        if view_dependent_metrics(metric_results, "side", _get_metric):
            from track2data.metrics.derived import derive_metric_params

            water_column = derive_metric_params("IL-15", psess, self._manifest.zones)[
                "water_column"
            ]
        provenance = SessionProvenance(
            camera_view=camera_view,
            water_column=water_column,
            reader=session.reader,
            source_software=(reader_cls.display_name or reader_cls.name) if reader_cls else None,
            reader_verification=reader_cls.verification if reader_cls else None,
            reader_options=dict(ref.reader_options) if ref is not None else {},
            reader_chosen_by=ref.reader_chosen_by if ref is not None else None,
            detection_confidence=ref.reader_confidence if ref is not None else None,
            source_files=(
                (str(session.trajectory_source),) if session.trajectory_source else ()
            ),
            keypoint_selection=(
                session.keypoints.provenance() if session.keypoints is not None else None
            ),
            idtrackerai_version=session.idtrackerai_version,
            trajectory_format=session.trajectory_format,
            trajectory_variant=session.trajectory_variant,
            n_frames=session.n_frames,
            n_animals=session.n_animals,
            has_stable_identities=session.has_stable_identities,
            track_wo_identities=session.track_wo_identities,
            identity_free_effective=is_identity_free,
            identity_free_source=identity_free_source,
            tracking_status=tracking_log.get("status"),
            tracking_failure_summary=tracking_log.get("failure_summary", ""),
            tracking_warnings_count=len(tracking_log.get("warnings", [])),
            estimated_accuracy=quality.get("estimated_accuracy"),
            fraction_identified=quality.get("fraction_identified"),
            silhouette_score=quality.get("silhouette_score"),
            fragment_connectivity=quality.get("fragment_connectivity"),
            length_unit=session.length_unit,
            length_unit_label=self._manifest.calibration.length_unit_label,
            length_unit_confirmed_by_user=self._manifest.calibration.length_unit_confirmed_by_user,
            body_length_reliable=session.body_length_reliable,
            blob_body_length_source_file=session.blob_body_length_source_file,
            last_validated=session.last_validated,
            data_policy=session.data_policy,
            length_calibration_n=cal_n,
            length_calibration_rel_sd=cal_rel_sd,
        )

        return ExportPayload(
            session_id=psess.session_id,
            project_name=self._manifest.project_name,
            project_hash=self._manifest.project_hash(),
            app_version=self._manifest.app_version,
            fish_by_frame=fish_by_frame,
            individual_metrics=individual_metrics,
            group_metrics=group_metrics,
            zone_metrics=zone_metrics,
            diagnostic_metrics=diagnostic_metrics,
            preprocess_report=psess.report,
            manifest_json=self._manifest.model_dump_json(indent=2),
            provenance=provenance,
            skipped_metrics=self.skipped_metrics(is_identity_free, psess.session),
        )

    def export(
        self,
        payload: Any,
        out_dir: Path,
        exporters: list[str] | None = None,
    ) -> list[Path]:
        """Write *payload* to *out_dir* via the requested (or configured
        default) exporters. Returns the list of written paths."""
        from track2data.exporters import get_exporter

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exporter_names = exporters or [t.exporter_name for t in self._manifest.export_targets]
        if not exporter_names:
            exporter_names = ["csv_long", "readme"]

        written: list[Path] = []
        for name in exporter_names:
            exp = get_exporter(name)
            if exp is None:
                logger.warning("Exporter %r not registered; skipping.", name)
                continue
            try:
                written.extend(exp.write(payload, out_dir))
            except Exception:
                logger.exception("Exporter %r failed.", name)

        return written

    # ── full run ───────────────────────────────────────────────────────────

    def run_session(
        self,
        session: Session,
        out_dir: Path,
        exporters: list[str] | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        """
        End-to-end pipeline for a single session.

        Returns list of written output paths.
        """
        psess = self.preprocess(session)
        emit(
            progress,
            ProgressEvent(
                stage="preprocess",
                current=1,
                total=3,
                session_id=session.session_id,
                message="Preprocessing complete",
            ),
        )

        metric_results = self.compute_metrics(psess)
        payload = self.build_payload(psess, metric_results)
        emit(
            progress,
            ProgressEvent(
                stage="metrics",
                current=2,
                total=3,
                session_id=session.session_id,
                message="Metrics computed",
            ),
        )

        written = self.export(payload, out_dir, exporters)
        emit(
            progress,
            ProgressEvent(
                stage="export",
                current=3,
                total=3,
                session_id=session.session_id,
                message="Export complete",
            ),
        )

        return written

    def run(
        self,
        out_dir: Path,
        exporters: list[str] | None = None,
        *,
        progress: ProgressCallback | None = None,
        n_workers: int = 1,
        cancel_check: Callable[[], None] | None = None,
    ) -> RunResult:
        """
        Run the full pipeline for every session in the manifest.

        Each session's output is written to ``out_dir/<session_id>/`` so
        multi-session runs never collide. A session that raises during
        import, preprocessing, metrics, or export is captured as that
        session's ``SessionRunResult.error`` without aborting the rest of
        the batch -- ``OperationCancelled`` is the one exception never
        caught here, since it must propagate to actually stop the run.
        (This is deliberately more forgiving than ``import_sessions()``,
        which fails loud on the first bad session -- see issue #7: a
        single unreadable session in a 70-session batch shouldn't lose
        the other 69, but it must never vanish silently either, hence
        surfacing it as this session's own ``.error`` instead.)

        ``cancel_check`` is a zero-argument callable that raises
        ``OperationCancelled`` once the caller wants the run to stop. It is
        called between sessions, preprocessing steps and metrics -- finer
        than the stage-boundary *progress* events, which stay sparse by
        contract -- so a long session can be interrupted. In a parallel run
        it is polled by the calling process and workers stop at their next
        checkpoint.

        ``n_workers > 1`` runs sessions in a pool of spawned worker processes
        (``min(n_workers, n_sessions)``); each worker rebuilds an Engine from
        the serialised manifest and sends progress events back over a queue,
        so the *progress* callback is only ever called in the calling
        process. Results come back in manifest order. Pick a value with
        ``track2data.core.parallel.worker_count()``. A raise from *progress*
        (``OperationCancelled``) stops the run: workers see a shared flag at
        their next checkpoint and stop.
        """
        previous_check, self._cancel_check = self._cancel_check, cancel_check
        try:
            return self._run(out_dir, exporters, progress, n_workers, cancel_check)
        finally:
            self._cancel_check = previous_check

    def _run(
        self,
        out_dir: Path,
        exporters: list[str] | None,
        progress: ProgressCallback | None,
        n_workers: int,
        cancel_check: Callable[[], None] | None,
    ) -> RunResult:
        refs = self._manifest.sessions
        n_configured = len(refs)
        emit(
            progress,
            ProgressEvent(stage="run", current=0, total=n_configured, message="Run started"),
        )

        results: list[SessionRunResult] = []
        n_pool = min(n_workers, n_configured)
        if n_pool > 1:
            results = self._run_parallel(
                refs, Path(out_dir), exporters, progress, n_pool, cancel_check
            )
        else:
            for i, ref in enumerate(refs):
                if cancel_check is not None:
                    cancel_check()
                results.append(
                    self._run_one_session(
                        ref, Path(out_dir) / ref.session_id, exporters, progress
                    )
                )
                emit(
                    progress,
                    ProgressEvent(
                        stage="session",
                        current=i + 1,
                        total=n_configured,
                        session_id=ref.session_id,
                        message="Session complete",
                    ),
                )

        self._write_project_summary(Path(out_dir), results)

        emit(
            progress,
            ProgressEvent(
                stage="run", current=n_configured, total=n_configured, message="Run complete"
            ),
        )
        return RunResult(sessions=results)

    def _hash_and_check_input(self, session: Session, ref: SessionRef) -> str:
        """SHA-256 of the trajectory file that produced this session's numbers.

        The export's central provenance claim is "these bytes produced these
        numbers", and it is not checkable without this. Recorded in
        ``sessions.csv`` and in each session's export README.

        Also the staleness check: when the manifest already carries a hash
        for this session and the folder now hashes differently, the source
        data changed after the project was configured. That is worth saying
        loudly -- it is exactly the case where a cached or re-exported
        session folder silently changes what a "reproduced" run means.

        Never fatal: a hash that cannot be computed costs provenance, not
        results.
        """
        from track2data.core.hashing import file_sha256

        source = session.trajectory_source
        if source is None:
            return ""
        try:
            digest = file_sha256(Path(source))
        except OSError:
            logger.warning(
                "Could not hash %s for session %s; the export will record no "
                "input checksum for it.",
                source,
                ref.session_id,
            )
            return ""

        if ref.sha256 and ref.sha256 != digest:
            logger.warning(
                "Session %s: the trajectory file %s has changed since this "
                "project recorded it (manifest %s, now %s). The numbers in "
                "this run come from the current file, not the one the project "
                "was configured against.",
                ref.session_id,
                source.name,
                ref.sha256[:12],
                digest[:12],
            )
        return digest

    def _write_project_summary(
        self, out_dir: Path, results: list[SessionRunResult]
    ) -> list[Path]:
        """Write the run-root ``sessions.csv`` and ``PROJECT_SUMMARY.md``.

        At the run root rather than inside a session folder, because both
        describe the *project*: which sessions took part, and the ways they
        disagree with each other. A per-session README saying "this project
        mixes frame rates" would be in the wrong place, and repeated once per
        session.

        Built from the summaries the sessions already carried back, so this
        costs no additional session reads.

        Never fatal. A run whose numbers are all computed must not be
        reported as failed because a bookkeeping file could not be written.
        """
        from track2data.core.session_consistency import (
            calibration_spread_warnings,
            heterogeneity_warnings,
            sessions_table,
        )
        from track2data.readers.advisories import reader_advisories

        if not results:
            return []

        summaries = [r.summary for r in results if r.summary is not None]
        errors = {r.session_id: r.error for r in results if r.error}
        warnings = [
            *heterogeneity_warnings(summaries),
            *calibration_spread_warnings(summaries),
        ]
        advisories = reader_advisories(summaries)

        for warning in warnings:
            logger.warning("Session consistency: %s", warning)
        for advisory in advisories:
            logger.warning("Reader: %s", advisory)

        written: list[Path] = []
        try:
            out_dir.mkdir(parents=True, exist_ok=True)

            table_path = out_dir / "sessions.csv"
            sessions_table(summaries, errors=errors).to_csv(
                table_path, index=False, encoding="utf-8", lineterminator="\n"
            )
            written.append(table_path)

            readme_path = out_dir / "PROJECT_SUMMARY.md"
            readme_path.write_text(
                self._project_readme_text(results, warnings, advisories), encoding="utf-8"
            )
            written.append(readme_path)

            # At the run root, not per session: it describes the schema every
            # session folder shares. Covers the whole registry rather than
            # only this run's selection, so a reader can look up any column
            # they encounter in any table.
            from track2data.exporters.schema import build_codebook

            codebook_path = out_dir / "codebook.csv"
            build_codebook().to_csv(
                codebook_path, index=False, encoding="utf-8", lineterminator="\n"
            )
            written.append(codebook_path)
        except Exception:
            logger.exception("Could not write the run summary to %s", out_dir)
        return written

    def _camera_view_summary(self) -> list[str]:
        """One summary bullet naming the declared camera view; nothing when none was declared,
        so a project that never set one keeps its summary exactly as it was."""
        from track2data.metrics.availability import view_label

        view = self._manifest.scene.camera_view
        return [] if view == "unknown" else [f"- Camera view: {view_label(view)}"]

    def _project_readme_text(
        self,
        results: list[SessionRunResult],
        warnings: list[str],
        advisories: Sequence[str] = (),
    ) -> str:
        """Run-root project summary: what ran, what failed, what not to pool.

        Named PROJECT_SUMMARY.md rather than README.md so it cannot be
        confused with the per-session README the readme exporter writes into
        each session folder -- an export that exists to be a provenance
        record must not have two differently-scoped files with one name.

        The consistency section leads when there is one. Someone reading this
        before writing a Methods section needs to know they have a
        mixed-frame-rate project before they need the session count.
        """
        ok = [r for r in results if not r.error]
        failed = [r for r in results if r.error]

        lines = [
            f"# Track2Data Run — {self._manifest.project_name}",
            "",
            f"- Project hash: `{self._manifest.project_hash()}`",
            f"- Sessions processed: {len(ok)} of {len(results)}",
            *self._camera_view_summary(),
            "",
            "Per-session outputs are in the subdirectory named after each "
            "session. `sessions.csv` lists every session's frame rate, group "
            "size, duration and calibration state.",
            "",
        ]

        if warnings:
            lines += [
                "## Read before pooling these sessions",
                "",
                "The sessions in this project are not interchangeable. Each "
                "point below changes what a cross-session comparison means:",
                "",
            ]
            lines += [f"{i}. {w}" for i, w in enumerate(warnings, start=1)]
            lines += [
                "",
                "None of these stopped the run -- they are design facts, not "
                "errors -- but a result pooled across them without accounting "
                "for them will be wrong. Use `sessions.csv` to filter, or to "
                "build the covariate.",
                "",
            ]
        else:
            lines += [
                "## Session consistency",
                "",
                "All sessions agree on frame rate, group size, video "
                "resolution and calibration state, so nothing about the "
                "recording setup implies a cross-session correction.",
                "",
            ]

        # Kept apart from the pooling warnings above: these say how the sessions were read, not
        # that they disagree, and filing them under "not interchangeable" would mislead.
        if advisories:
            lines += [
                "## Notes on the readers",
                "",
                "What the numbers rest on, which is not visible in them:",
                "",
            ]
            lines += [f"{i}. {a}" for i, a in enumerate(advisories, start=1)]
            lines.append("")

        if failed:
            lines += ["## Sessions that failed", ""]
            lines += [f"- `{r.session_id}` — {r.error}" for r in failed]
            lines += [
                "",
                "These produced no metrics. They appear in `sessions.csv` with "
                "their error, so an analysis that expected them can tell they "
                "are missing rather than silently covering fewer animals.",
                "",
            ]

        return "\n".join(lines)

    def _run_parallel(
        self,
        refs: list[SessionRef],
        out_dir: Path,
        exporters: list[str] | None,
        progress: ProgressCallback | None,
        n_pool: int,
        cancel_check: Callable[[], None] | None = None,
    ) -> list[SessionRunResult]:
        """Run *refs* across *n_pool* spawned processes; see ``run()``."""
        # "spawn" on every OS: it is the only start method on Windows and the
        # default on macOS, so Linux behaves the same instead of masking
        # pickling problems only the other two would hit.
        ctx = multiprocessing.get_context("spawn")
        events = ctx.Queue()
        cancel = ctx.Event()
        manifest_json = self._manifest.model_dump_json()
        total = len(refs)
        results: dict[int, SessionRunResult] = {}

        def drain() -> None:
            while True:
                try:
                    event = events.get_nowait()
                except queue_mod.Empty:
                    return
                emit(progress, event)

        with ProcessPoolExecutor(
            max_workers=n_pool,
            mp_context=ctx,
            initializer=_parallel_init,
            initargs=(events, cancel),
        ) as pool:
            futures = {
                pool.submit(
                    _parallel_run_one,
                    manifest_json,
                    i,
                    str(out_dir),
                    exporters,
                    str(self._cache_dir) if self._cache_dir is not None else None,
                ): i
                for i in range(total)
            }
            pending = set(futures)
            try:
                while pending:
                    if cancel_check is not None:
                        cancel_check()
                    drain()
                    finished = [f for f in pending if f.done()]
                    for fut in finished:
                        pending.discard(fut)
                        i = futures[fut]
                        results[i] = self._collect_parallel_result(refs[i], fut)
                        emit(
                            progress,
                            ProgressEvent(
                                stage="session", current=len(results), total=total,
                                session_id=refs[i].session_id, message="Session complete",
                            ),
                        )
                    if not finished:
                        time.sleep(0.05)
                drain()
            except BaseException:
                # Includes OperationCancelled raised by the progress callback.
                cancel.set()
                for fut in pending:
                    fut.cancel()
                # Keep reading so a worker blocked on a full pipe can exit.
                while any(not f.done() for f in pending):
                    with contextlib.suppress(queue_mod.Empty):
                        events.get(timeout=0.1)
                raise
        return [results[i] for i in range(total)]

    @staticmethod
    def _collect_parallel_result(ref: SessionRef, fut: Any) -> SessionRunResult:
        from track2data.core.progress import OperationCancelled

        try:
            result = fut.result()
        except Exception as exc:  # worker crash / unpicklable result
            logger.exception("Worker for session %s failed.", ref.session_id)
            return SessionRunResult(session_id=ref.session_id, error=f"Worker failed: {exc}")
        if result is None:
            raise OperationCancelled()
        return result

    def _run_one_session(
        self,
        ref: SessionRef,
        session_out_dir: Path,
        exporters: list[str] | None,
        progress: ProgressCallback | None,
    ) -> SessionRunResult:
        """Run one session for ``run()``, capturing its outcome (including
        any failure -- import, preprocess, metrics, or export) as a
        SessionRunResult rather than raising -- except OperationCancelled,
        which must propagate to stop the whole run. Keyed throughout by
        ``ref.session_id`` (the manifest's own identity), not a
        reader-derived one, since it must be available even when import
        itself fails."""
        import time

        from track2data.core.progress import OperationCancelled
        from track2data.core.session_consistency import SessionSummary

        start = time.monotonic()
        psess = None
        try:
            psess = self._cache_get(ref)
            cached = psess is not None
            # A cached result carries the Session it was built from, which is all
            # the summary and the input hash below need.
            session = self.import_ref(ref) if psess is None else psess.session
            # The override only, not ref.is_identity_free(): this method is
            # keyed by ref.session_id (see the docstring) because a
            # reader-derived id may differ, so the lookup inside
            # identity_free_for() cannot be trusted here -- but None must
            # still fall through to the session file's own declaration
            # rather than being resolved to False.
            identity_free = ref.identity_free_override
            emit(
                progress,
                ProgressEvent(
                    stage="import", current=1, total=4,
                    session_id=ref.session_id,
                    message="Import complete (cached)" if cached else "Import complete",
                ),
            )
            if psess is None:
                psess = self.preprocess(session)
                self._cache_put(ref, psess)
            emit(
                progress,
                ProgressEvent(
                    stage="preprocess", current=2, total=4,
                    session_id=ref.session_id,
                    message="Preprocessing complete (cached)" if cached
                    else "Preprocessing complete",
                ),
            )
            metric_results = self.compute_metrics(psess, identity_free=identity_free)
            payload = self.build_payload(
                psess, metric_results, identity_free=identity_free
            )
            emit(
                progress,
                ProgressEvent(
                    stage="metrics", current=3, total=4,
                    session_id=ref.session_id, message="Metrics computed",
                ),
            )
            written = self.export(payload, session_out_dir, exporters)
            emit(
                progress,
                ProgressEvent(
                    stage="export", current=4, total=4,
                    session_id=ref.session_id, message="Export complete",
                ),
            )
            diagnostics = {k: v for k, v in metric_results.items() if k.startswith("D-")}
            metric_previews = {
                k: v.head(200) for k, v in metric_results.items() if not k.startswith("D-")
            }
            return SessionRunResult(
                session_id=ref.session_id,
                written=written,
                diagnostics=diagnostics,
                metric_previews=metric_previews,
                preprocess_report=psess.report,
                duration_s=time.monotonic() - start,
                # Built from the session we already read and the calibration
                # the run actually resolved, so sessions.csv reports what
                # happened rather than what the manifest asked for.
                summary=SessionSummary.from_session(
                    session,
                    calibration_mode=self._manifest.calibration.mode,
                    is_identity_free=ref.is_identity_free(),
                    px_per_cm=psess.px_per_cm,
                    trajectory_sha256=self._hash_and_check_input(session, ref),
                ),
            )
        except OperationCancelled:
            raise
        except Exception as exc:
            logger.exception("Session %s failed.", ref.session_id)
            return SessionRunResult(
                session_id=ref.session_id,
                preprocess_report=_recover_preprocess_report(psess, exc),
                duration_s=time.monotonic() - start,
                error=str(exc),
            )

    def run_all(
        self,
        out_dir: Path,
        exporters: list[str] | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        """Run the full pipeline for every session in the manifest.

        Thin wrapper over ``run()`` for callers that only need the
        written paths, not the full ``RunResult`` (diagnostics, metric
        previews, per-session timing/errors).
        """
        return self.run(out_dir, exporters, progress=progress).written

    # ── preview ────────────────────────────────────────────────────────────

    def preview_frame(self, session: Session, frame_index: int = 0) -> bytes | None:
        """Return raw RGB bytes for one video frame, or None if unavailable."""
        from track2data.readers.video_meta import extract_frame

        if session.video.path is None:
            return None
        return extract_frame(session.video.path, frame_index)

    # ── validation ────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Return a list of blocking validation issues.
        Empty list means the pipeline is ready to run.

        Cross-session heterogeneity (mixed frame rates, mixed calibration)
        is deliberately NOT reported here: those are legitimate designs as
        long as the analyst knows, so blocking the run would be wrong. See
        :meth:`consistency_warnings`, which the GUI and CLI surface
        alongside this and which ``run()`` records in the export.
        """
        issues: list[str] = []
        if not self._manifest.sessions:
            issues.append("No sessions imported.")
        cfg = self._manifest.calibration
        if cfg.mode == "scalar" and (cfg.px_per_cm is None or cfg.px_per_cm <= 0):
            issues.append("Scalar calibration selected but px_per_cm is not set.")
        elif cfg.mode == "session":
            issues.extend(self._session_calibration_issues())
        sel = self._manifest.metrics
        if not sel.individual and not sel.group and not sel.zone:
            issues.append("No metrics selected.")
        issues.extend(self._gate_selection_issues())
        return issues

    def consistency_warnings(self) -> list[str]:
        """Report the ways this project's sessions disagree with each other.

        Non-blocking by design (see :meth:`validate`): pooling 30 fps and 60
        fps sessions is a defensible thing to do deliberately and a serious
        mistake to do by accident, and only the analyst can tell those apart.

        Reads every session folder, like ``_session_calibration_issues()``
        and for the same reason -- this is an explicit pre-flight action, not
        something called on every keystroke, so a complete report is worth
        the I/O. Unreadable sessions are skipped silently here; ``validate()``
        and the run itself both report them.

        Also carries the reader advisories (a reader that was never checked
        against real output; body-length calibration for a tracker that
        reports no body length). They are not disagreements between
        sessions, but they are the same kind of fact: true of the project,
        invisible in the numbers, and worth knowing before pooling them.
        """
        from track2data.core.session_consistency import (
            calibration_spread_warnings,
            heterogeneity_warnings,
        )
        from track2data.readers.advisories import reader_advisories

        summaries = self._session_summaries()
        return [
            *heterogeneity_warnings(summaries),
            *calibration_spread_warnings(summaries),
            *reader_advisories(summaries),
            *self._view_selection_notes(),
        ]

    def _session_summaries(self) -> list[SessionSummary]:
        """Read every session in the manifest and summarise it.

        Best-effort: a session that cannot be read contributes nothing rather
        than aborting the report, because the whole point is to describe the
        sessions that *will* take part in the run.
        """
        from track2data.core.session_consistency import SessionSummary

        mode = self._manifest.calibration.mode
        summaries: list[SessionSummary] = []
        for ref in self._manifest.sessions:
            try:
                session = self.import_ref(ref)
            except Exception:
                continue
            summaries.append(
                SessionSummary.from_session(
                    session,
                    calibration_mode=mode,
                    is_identity_free=ref.is_identity_free(),
                    px_per_cm=self._resolve_px_per_cm(session),
                )
            )
        return summaries

    def _resolve_px_per_cm(self, session: Session) -> float | None:
        """The px-to-cm ratio this session would be calibrated with, if any.

        Mirrors the branch structure of ``preprocess()``'s calibration step
        without running it: enough to answer "will this session get real
        *_cm columns?", which is what the consistency report turns on.
        """
        cfg = self._manifest.calibration
        if cfg.mode == "scalar":
            return cfg.px_per_cm if cfg.px_per_cm and cfg.px_per_cm > 0 else None
        if cfg.mode == "session":
            return session.length_unit
        # "bodylength" derives a per-animal scale from body_length_px rather
        # than a single session-wide ratio; it produces *_bl columns whether
        # or not a length_unit exists, so treat the session's own unit as the
        # thing that decides whether *_cm columns are real.
        return session.length_unit

    def _gate_selection_issues(self) -> list[str]:
        """Warn when the identity gate and the camera-view gate would, together, empty the
        whole run.

        The identity half, in full:

        Selecting only identity-dependent metrics on a project where every
        session is identity-free is not an error -- compute_metrics skips
        them and the diagnostics still export -- but the run produces no
        metric output at all, which is worth saying before it starts
        rather than leaving the user to notice the empty CSVs.

        Reads the manifest's cached flags rather than opening every session
        the way _session_calibration_issues() does, so on a CLI project
        (where nothing populates that cache) this stays silent and the run
        proceeds. That is the intended trade: the gate itself resolves from
        the session file and still fires, and the export's "Metrics skipped"
        section records it -- this is only the early warning, not the
        safeguard, and it isn't worth reading 70 session folders for.
        """
        sessions = self._manifest.sessions
        selected = {
            *self._manifest.metrics.individual,
            *self._manifest.metrics.group,
            *self._manifest.metrics.zone,
        }
        if not sessions or not selected:
            return []
        identity = (
            self.identity_skipped_metrics(True)
            if all(ref.is_identity_free() for ref in sessions)
            else {}
        )
        view = self.view_skipped_metrics()
        if len(set(identity) | set(view)) < len(selected):
            return []
        if not view:
            return [
                "Every session is identity-free and every selected metric "
                f"({', '.join(sorted(identity))}) requires identity, so the run "
                "would produce diagnostics only. Select identity-independent "
                "metrics, or untick 'Identity-free' for the sessions that do "
                "preserve identities."
            ]
        if not identity:
            fix = (
                "Set the camera view on the Calibration screen, or select metrics "
                "that apply to this recording."
            )
            return [
                f"Every selected metric ({', '.join(sorted(view))}) needs a different "
                "camera view than the project's, so the run would produce diagnostics "
                f"only. {fix}"
            ]
        return [
            f"Every selected metric ({', '.join(sorted(selected))}) is ruled out, by the "
            "identity-free sessions or by the project's camera view, so the run would "
            "produce diagnostics only. Untick 'Identity-free' where identities were "
            "preserved, set the camera view on the Calibration screen, or select other "
            "metrics."
        ]

    def _view_selection_notes(self) -> list[str]:
        """Say which selected metrics the camera view will skip, when others still run.

        When *every* selected metric is ruled out, validate() already blocks the run with its
        own message, so this stays silent rather than repeat it.
        """
        selected = {
            *self._manifest.metrics.individual,
            *self._manifest.metrics.group,
            *self._manifest.metrics.zone,
        }
        view = self.view_skipped_metrics()
        if not view or len(view) >= len(selected):
            return []
        return [
            f"{mid} will be skipped: {reason}." for mid, reason in sorted(view.items())
        ]

    def _session_calibration_issues(self) -> list[str]:
        """Fail loudly, name the sessions: for 'session' calibration
        mode, every imported session must carry its own length_unit, or
        the run should be blocked here rather than each affected
        session silently failing calibration one at a time inside
        Engine.run() (see apply_session_calibration's CAL-SESSION-MISSING).
        Reads every session up front (same I/O cost as import_sessions())
        -- validate() is an explicit pre-flight action, not something
        called on every keystroke, so this is worth the cost for a
        complete report instead of a partial one."""
        missing: list[str] = []
        unreadable: list[str] = []
        for ref in self._manifest.sessions:
            try:
                session = self.import_ref(ref)
            except Exception:
                unreadable.append(ref.session_id)
                continue
            if session.length_unit is None:
                missing.append(ref.session_id)

        issues: list[str] = []
        if missing:
            issues.append(
                "Session calibration selected but these sessions have no length_unit: "
                + ", ".join(missing)
                + ". Calibrate them in the idtracker.ai validator, or switch calibration mode."
            )
        if unreadable:
            issues.append(
                "Session calibration selected but these sessions could not be read to "
                "check length_unit: " + ", ".join(unreadable)
            )
        return issues
