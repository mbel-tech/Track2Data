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

import logging
from functools import cached_property
from pathlib import Path
from typing import Any

from track2data.core.models import (
    PreprocessedSession,
    PreprocessReport,
    ProjectManifest,
    RunResult,
    Session,
    SessionRef,
    SessionRunResult,
)
from track2data.core.progress import ProgressCallback, ProgressEvent, emit
from track2data.readers import read_session

logger = logging.getLogger(__name__)


def _map_array_index_to_true_frame(
    tracking_intervals: list[tuple[int, int]] | None, n_frames: int
) -> tuple[Any, bool]:
    """
    Map trajectory-array row position (0..n_frames-1) to the true video
    frame number, using ``Session.tracking_intervals``.

    idtracker.ai only tracks (and stores trajectory rows for) frames inside
    the configured ``--tracking_intervals``; array position 0 is the first
    frame of the first interval, not frame 0 of the video
    (idtracker.ai_usage.md:552: "Tracking intervals in frames ... If not
    set, the whole video is tracked"; session_idtrackerai.md:240: interval
    end is exclusive). With a single interval starting elsewhere than 0,
    using the raw array position as "frame" understates every frame number
    by the interval's start; with multiple intervals, it also makes the
    derived time axis non-monotonic in real time across the gap between
    intervals.

    Returns
    -------
    true_frames:
        Array of length n_frames with the true video frame number per row.
    valid:
        Whether the mapping could be trusted, i.e. the intervals'
        combined length matches n_frames exactly. When False, true_frames
        is simply ``arange(n_frames)`` (today's behaviour) because the
        intervals don't reconcile with the data -- e.g. a partial/embargoed
        session.json, or gaps closed by preprocessing on idtracker.ai's
        side that this reader has no way to reconstruct.
    """
    import numpy as np

    if not tracking_intervals:
        return np.arange(n_frames), False

    lengths = [max(0, end - start) for start, end in tracking_intervals]
    if sum(lengths) != n_frames:
        return np.arange(n_frames), False

    true_frames = np.empty(n_frames, dtype=np.int64)
    pos = 0
    for (start, _end), length in zip(tracking_intervals, lengths, strict=True):
        true_frames[pos : pos + length] = np.arange(start, start + length)
        pos += length
    return true_frames, True


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


class Engine:
    """Stateless facade over all engine subsystems."""

    def __init__(self, manifest: ProjectManifest) -> None:
        self._manifest = manifest

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

    # ── session import ─────────────────────────────────────────────────────

    def import_session(self, folder: Path) -> Session:
        """Auto-detect reader and return a Session for *folder*."""
        return read_session(Path(folder))

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
            sessions.append(self.import_session(ref.folder))
        return sessions

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

        psess = pp_run(session, self._manifest.preprocess)

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

    def _effective_cfg(self, metric_cls: type, psess: PreprocessedSession) -> dict[str, Any]:
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

    def compute_metrics(
        self, psess: PreprocessedSession, *, identity_free: bool | None = None
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
        """

        from track2data.metrics.diagnostic import compute_all_diagnostics

        results: dict[str, Any] = {}

        # Always-on diagnostics. Computed even for an identity-free session:
        # D-5 IdentityStability is precisely the record of that fact, so
        # suppressing the diagnostics would remove the evidence for the
        # skips below.
        results.update(compute_all_diagnostics(psess.session))

        sel = self._manifest.metrics

        is_identity_free = self.identity_free_for(psess.session, identity_free)
        skipped = self.identity_skipped_metrics(is_identity_free)
        if skipped:
            logger.warning(
                "Skipping identity-dependent metrics (%s) for session %s: "
                "the session is identity-free, so per-individual results "
                "would not correspond to individual animals.",
                ", ".join(sorted(skipped)),
                psess.session_id,
            )

        def _run(metric_ids: list[str]) -> None:
            from track2data.metrics import get
            for mid in metric_ids:
                if mid in skipped:
                    continue
                cls = get(mid)
                if cls is None:
                    logger.warning("Metric %s not registered; skipping.", mid)
                    continue
                try:
                    cfg = self._effective_cfg(cls, psess)
                    results[mid] = cls().compute(psess, cfg)
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
        _run(sel.diagnostic)

        meta_fields = self._metadata_fields_for(psess.session_id)
        if meta_fields:
            for df in results.values():
                for col, val in meta_fields.items():
                    df[col] = val

        return results

    def build_fish_by_frame(self, psess: PreprocessedSession) -> Any:
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
        (see ``_map_array_index_to_true_frame``); ``in_tracking_interval``
        records whether that mapping was trusted (True) or the raw array
        position was used as a fallback (NaN -- not False, since "outside
        the interval" is not what an unreconciled mapping means).
        """
        import numpy as np
        import pandas as pd

        n_frames = psess.n_frames
        n_animals = psess.n_animals
        fps = psess.fps

        true_frame_per_row, mapping_valid = _map_array_index_to_true_frame(
            psess.session.tracking_intervals, n_frames
        )
        frames = np.repeat(true_frame_per_row, n_animals)
        individuals = np.tile(np.arange(n_animals), n_frames)
        time_s = frames / fps
        in_interval_fill = True if mapping_valid else np.nan
        in_interval = np.full(n_frames * n_animals, in_interval_fill)

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
        id_prob = psess.session.id_probabilities
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

        for col, val in self._metadata_fields_for(psess.session_id).items():
            df[col] = val

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

        fish_by_frame = self.build_fish_by_frame(psess)

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
        provenance = SessionProvenance(
            reader=session.reader,
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
            skipped_metrics=self.identity_skipped_metrics(is_identity_free),
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

        ``n_workers`` is accepted for forward compatibility with a future
        parallel implementation but only the sequential (n_workers=1)
        path is implemented today; see DECISIONS.md D-013 and D-014.
        """
        if n_workers > 1:
            logger.warning(
                "Engine.run(n_workers=%d) requested, but only sequential "
                "execution is implemented; running with n_workers=1.",
                n_workers,
            )

        refs = self._manifest.sessions
        n_configured = len(refs)
        emit(
            progress,
            ProgressEvent(stage="run", current=0, total=n_configured, message="Run started"),
        )

        results: list[SessionRunResult] = []
        for i, ref in enumerate(refs):
            results.append(
                self._run_one_session(ref, Path(out_dir) / ref.session_id, exporters, progress)
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

        emit(
            progress,
            ProgressEvent(
                stage="run", current=n_configured, total=n_configured, message="Run complete"
            ),
        )
        return RunResult(sessions=results)

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

        start = time.monotonic()
        psess = None
        try:
            session = self.import_session(ref.folder)
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
                    session_id=ref.session_id, message="Import complete",
                ),
            )
            psess = self.preprocess(session)
            emit(
                progress,
                ProgressEvent(
                    stage="preprocess", current=2, total=4,
                    session_id=ref.session_id, message="Preprocessing complete",
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
        Return a list of validation warning strings.
        Empty list means the pipeline is ready to run.
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
        issues.extend(self._identity_selection_issues())
        return issues

    def _identity_selection_issues(self) -> list[str]:
        """Warn when the identity gate would empty the whole run.

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
        if not sessions or not all(ref.is_identity_free() for ref in sessions):
            return []
        selected = [
            *self._manifest.metrics.individual,
            *self._manifest.metrics.group,
            *self._manifest.metrics.zone,
        ]
        if not selected:
            return []
        skipped = self.identity_skipped_metrics(True)
        if len(skipped) < len(set(selected)):
            return []
        return [
            "Every session is identity-free and every selected metric "
            f"({', '.join(sorted(skipped))}) requires identity, so the run "
            "would produce diagnostics only. Select identity-independent "
            "metrics, or untick 'Identity-free' for the sessions that do "
            "preserve identities."
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
                session = read_session(ref.folder)
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
