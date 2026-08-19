"""
Unified IDTrackerAiReader.

Wires the full pipeline:
  detect → format-specific loader → session_json → log → custom_artefacts
  → Normaliser → Session

Supports: npy (pickled dict), csv bundle.
The session.json is always loaded when present to enrich the Session with
tracking_intervals, roi_list, quality metrics, etc.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.idtrackerai.custom_artefacts import (
    load_bbox_summary,
    load_bbox_table,
    load_inconsistent_frames,
    load_matching_results,
)
from track2data.readers.idtrackerai.detect import detect
from track2data.readers.idtrackerai.formats.csv_bundle import load_csv_bundle
from track2data.readers.idtrackerai.formats.npy import load_npy
from track2data.readers.idtrackerai.log import load_log_digest
from track2data.readers.idtrackerai.normaliser import Normaliser
from track2data.readers.idtrackerai.session_json import load_session_json


class IDTrackerAiReader(SessionReader):
    """
    Unified reader for idtracker.ai sessions (all formats, all supported versions).

    Detection is file-tree based, not presence of video_object.npy.
    Priority order for trajectory formats: h5 → parquet → npy → pickle → csv.
    """

    name = "idtrackerai"
    priority = 20  # Higher than the legacy v5 reader (priority=10).

    # ── SessionReader protocol ─────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return detect(folder) is not None

    def read(self, folder: Path) -> Session:
        folder = Path(folder)
        hit = detect(folder)
        if hit is None:
            from track2data.core.errors import ImportError_
            raise ImportError_(
                f"No recognisable idtracker.ai trajectory found in {folder}",
                code="IDT_NO_TRAJ",
                severity="error",
                subject=str(folder),
                remediation="Ensure the folder contains a trajectories/ subdirectory.",
            )

        # Load trajectory payload from the best available format.
        payload = self._load_payload(hit.format, hit.path)

        # Build the normalised Session (core trajectory data + quality + labels).
        normaliser = Normaliser(folder)
        session = normaliser.normalise(payload, trajectory_format=hit.format)

        # Enrich from session.json (tracking_intervals, roi_list, etc.).
        session = self._enrich_from_session_json(session, folder)

        # Attach log digest.
        session = session.model_copy(
            update={"tracking_log": load_log_digest(folder)}
        )

        # Attach custom artefacts (all opportunistic — never required).
        session = session.model_copy(update={
            "inconsistent_frames": load_inconsistent_frames(folder),
            "bbox_table": load_bbox_table(folder),
            "bbox_summary": load_bbox_summary(folder),
            "matching_results": load_matching_results(folder),
        })

        return session

    # ── private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _load_payload(fmt: str, path: Path) -> dict:
        if fmt == "npy":
            return load_npy(path)
        if fmt == "csv":
            return load_csv_bundle(path)
        # Placeholder for h5, parquet, pickle, csv_tidy — deferred to later steps.
        from track2data.core.errors import ImportError_
        raise ImportError_(
            f"Format '{fmt}' is not yet implemented.",
            code="IDT_FORMAT_AMBIGUOUS",
            severity="error",
            subject=str(path),
            remediation="Use npy or csv format trajectories.",
        )

    @staticmethod
    def _enrich_from_session_json(session: Session, folder: Path) -> Session:
        meta = load_session_json(folder)
        if not meta:
            return session

        updates: dict = {}

        # tracking_intervals: [[start, end], …] → list[tuple[int, int]]
        raw_ti = meta.get("tracking_intervals")
        if raw_ti:
            with contextlib.suppress(TypeError, ValueError):
                updates["tracking_intervals"] = [
                    (int(s), int(e)) for s, e in raw_ti
                ]

        # roi_list: list of strings like "+ Polygon [...]"
        raw_roi = meta.get("roi_list")
        if raw_roi:
            updates["roi_list"] = [{"raw": r} for r in raw_roi]

        return session.model_copy(update=updates) if updates else session
