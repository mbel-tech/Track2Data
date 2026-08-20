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

    # Import all sessions listed in the manifest.
    sessions = engine.import_sessions()

    # Run preprocessing + calibration + zone assignment.
    psessions = [engine.preprocess(s) for s in sessions]

    # Compute metrics and export.
    for ps in psessions:
        payload = engine.compute_metrics(ps)
        engine.export(payload, Path("output/"))
"""

from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path
from typing import Any

from track2data.core.models import (
    PreprocessedSession,
    ProjectManifest,
    Session,
)
from track2data.core.progress import ProgressCallback, ProgressEvent, emit
from track2data.readers import read_session

logger = logging.getLogger(__name__)


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
        """Import all sessions listed in ``manifest.sessions``."""
        sessions: list[Session] = []
        refs = self._manifest.sessions
        for i, ref in enumerate(refs):
            # Emit BEFORE the try opens: if the callback raises
            # OperationCancelled, it must propagate out of this method,
            # not be caught by the except below and treated as just
            # another session that failed to import.
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
            try:
                sess = self.import_session(ref.folder)
                sessions.append(sess)
            except Exception:
                logger.exception("Failed to import session %s", ref.session_id)
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
        """
        from track2data.preprocess.pipeline import run as pp_run

        psess = pp_run(session, self._manifest.preprocess)

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

        # Zone assignment.
        zone_set = self._manifest.zones
        if zone_set.rois:
            from track2data.zones.geometry import assign_zones
            main_zone, sec_zone = assign_zones(psess.xy, zone_set)
            from dataclasses import replace
            psess = replace(psess, main_zone=main_zone, sec_zone=sec_zone)

        return psess

    # ── metrics ────────────────────────────────────────────────────────────

    def compute_metrics(self, psess: PreprocessedSession) -> dict[str, Any]:
        """
        Compute all selected metrics for *psess*.

        Returns a dict mapping metric_id to a ``pd.DataFrame``.
        Diagnostic metrics (D-1..D-5) are always computed.
        """

        from track2data.metrics.diagnostic import compute_all_diagnostics

        results: dict[str, Any] = {}

        # Always-on diagnostics.
        results.update(compute_all_diagnostics(psess.session))

        sel = self._manifest.metrics

        def _run(metric_ids: list[str]) -> None:
            from track2data.metrics import get
            for mid in metric_ids:
                cls = get(mid)
                if cls is None:
                    logger.warning("Metric %s not registered; skipping.", mid)
                    continue
                try:
                    results[mid] = cls().compute(psess)
                except Exception:
                    logger.exception("Metric %s failed; skipping.", mid)

        _run(sel.individual)
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
                 speed_px_s, heading_rad, main_zone, sec_zone.
        Calibrated columns added when psess.px_per_cm is set.
        """
        import numpy as np
        import pandas as pd

        n_frames = psess.n_frames
        n_animals = psess.n_animals
        fps = psess.fps

        frames = np.repeat(np.arange(n_frames), n_animals)
        individuals = np.tile(np.arange(n_animals), n_frames)
        time_s = frames / fps

        xy_flat = psess.xy.reshape(-1, 2)
        speed_flat = psess.kinematics.speed_px_s.reshape(-1)
        heading_flat = psess.kinematics.heading_rad.reshape(-1)

        df = pd.DataFrame({
            "session_id": psess.session_id,
            "individual_id": individuals,
            "frame": frames,
            "time_s": time_s,
            "x_px": xy_flat[:, 0],
            "y_px": xy_flat[:, 1],
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

        for col, val in self._metadata_fields_for(psess.session_id).items():
            df[col] = val

        return df.sort_values(["session_id", "individual_id", "frame"]).reset_index(
            drop=True
        )

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
        from track2data.exporters import get_exporter
        from track2data.exporters.base import ExportPayload

        # Preprocessing + calibration + zones.
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

        # Metrics.
        metric_results = self.compute_metrics(psess)

        # Build master frame table.
        fish_by_frame = self.build_fish_by_frame(psess)
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

        # Separate metric results by level.
        individual_metrics = {k: v for k, v in metric_results.items()
                               if k.startswith("IL-")}
        group_metrics = {k: v for k, v in metric_results.items()
                         if k.startswith("GL-")}
        zone_metrics = {k: v for k, v in metric_results.items()
                        if k.startswith("Z-")}
        diagnostic_metrics = {k: v for k, v in metric_results.items()
                               if k.startswith("D-")}

        payload = ExportPayload(
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
        )

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

    def run_all(
        self,
        out_dir: Path,
        exporters: list[str] | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        """Run the full pipeline for every session in the manifest."""
        n_configured = len(self._manifest.sessions)
        emit(
            progress,
            ProgressEvent(stage="run", current=0, total=n_configured, message="Run started"),
        )

        sessions = self.import_sessions(progress=progress)
        written: list[Path] = []
        for i, sess in enumerate(sessions):
            written.extend(
                self.run_session(sess, out_dir, exporters=exporters, progress=progress)
            )
            emit(
                progress,
                ProgressEvent(
                    stage="session",
                    current=i + 1,
                    total=len(sessions),
                    session_id=sess.session_id,
                    message="Session complete",
                ),
            )

        emit(
            progress,
            ProgressEvent(
                stage="run", current=n_configured, total=n_configured, message="Run complete"
            ),
        )
        return written

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
        sel = self._manifest.metrics
        if not sel.individual and not sel.group and not sel.zone:
            issues.append("No metrics selected.")
        return issues
