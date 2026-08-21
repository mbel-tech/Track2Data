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
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.idtrackerai.custom_artefacts import (
    load_bbox_summary,
    load_bbox_table,
    load_inconsistent_frames,
    load_matching_results,
)
from track2data.readers.idtrackerai.detect import ReaderHit, detect
from track2data.readers.idtrackerai.formats.csv_bundle import load_csv_bundle
from track2data.readers.idtrackerai.formats.h5 import load_h5
from track2data.readers.idtrackerai.formats.npy import load_npy
from track2data.readers.idtrackerai.fragments import load_fragments
from track2data.readers.idtrackerai.log import load_log_digest
from track2data.readers.idtrackerai.normaliser import Normaliser
from track2data.readers.idtrackerai.preprocessing import find_preprocessing_images
from track2data.readers.idtrackerai.session_json import (
    load_session_json,
    parse_roi_string,
    parse_timers_to_durations,
)

logger = logging.getLogger(__name__)


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

        # Load trajectory payload from the best available format, falling back
        # through hit.all_present when the highest-priority format (often h5,
        # idtracker.ai's own default) has no loader yet.
        fmt_used, payload = self._load_payload(hit)

        # Load session.json once, up front: it is both a fallback source for
        # fps/width/height/version (some formats' payloads omit them -- see
        # Normaliser._require_positive_number) and the enrichment source for
        # tracking_intervals/roi_list below.
        session_meta = load_session_json(folder)

        # Build the normalised Session (core trajectory data + quality + labels).
        normaliser = Normaliser(folder)
        session = normaliser.normalise(
            payload, trajectory_format=fmt_used, session_meta=session_meta
        )

        # Enrich from session.json (tracking_intervals, roi_list, etc.).
        session = self._enrich_from_session_json(session, session_meta)

        # Attach log digest, with durations merged in from session.json's
        # structured `timers` dict -- the log's own duration text ("It took
        # H:MM:SS") has no reliable regex; timers has real ISO timestamps.
        log_digest = load_log_digest(folder)
        if log_digest is not None and session_meta:
            durations = parse_timers_to_durations(session_meta.get("timers"))
            if durations:
                log_digest = {**log_digest, "durations": durations}
        session = session.model_copy(update={"tracking_log": log_digest})

        # Attach custom artefacts (all opportunistic — never required).
        session = session.model_copy(update={
            "inconsistent_frames": load_inconsistent_frames(folder),
            "bbox_table": load_bbox_table(folder),
            "bbox_summary": load_bbox_summary(folder),
            "matching_results": load_matching_results(folder),
        })

        # Attach preprocessing/ image paths (opportunistic — data_policy
        # can delete this folder entirely).
        images = find_preprocessing_images(folder)
        if images:
            session = session.model_copy(update={
                "roi_mask_path": images.get("roi_mask"),
                "background_image_path": images.get("background"),
            })

        # Attach parsed list_of_fragments.json (opportunistic, same caveat).
        fragments_data = load_fragments(folder)
        if fragments_data is not None:
            session = session.model_copy(update={"fragments": fragments_data})

        return session

    # ── private helpers ────────────────────────────────────────────────────────

    # Formats with a working loader. parquet/pickle/csv_tidy are detected by
    # detect.py but have no loader yet -- see _LOADERS below.
    _LOADERS: ClassVar[dict[str, Callable[[Path], dict]]] = {
        "h5": load_h5,
        "npy": load_npy,
        "csv": load_csv_bundle,
    }

    @classmethod
    def _load_payload(cls, hit: ReaderHit) -> tuple[str, dict[str, Any]]:
        """
        Load the trajectory payload from the best *readable* format in *hit*.

        detect() ranks formats by priority (h5 first, per idtracker.ai's own
        default `trajectories_formats`), but not every format has a loader
        implemented yet. Walk hit.all_present in priority order and use the
        first one this reader can actually read, rather than failing outright
        because the single best-ranked format lacks a loader while a readable
        one sits right next to it. Only raise once nothing in the folder is
        readable.
        """
        from track2data.core.errors import ImportError_

        skipped: list[str] = []
        for fmt, path in hit.all_present:
            loader = cls._LOADERS.get(fmt)
            if loader is None:
                skipped.append(fmt)
                continue
            try:
                result = loader(path)
            except ImportError:
                # Optional dependency for this format (e.g. h5py) isn't
                # installed -- treat exactly like "no loader" and keep
                # falling back, rather than crashing the whole import.
                skipped.append(f"{fmt} (missing optional dependency)")
                continue
            if skipped:
                logger.info(
                    "IDT_FORMAT_AMBIGUOUS: %s not readable yet (skipped: %s); "
                    "using '%s' trajectories from %s",
                    hit.format,
                    ", ".join(skipped),
                    fmt,
                    path,
                )
            return fmt, result

        available = ", ".join(fmt for fmt, _ in hit.all_present) or "none"
        raise ImportError_(
            f"No readable trajectory format among: {available}.",
            code="IDT_FORMAT_AMBIGUOUS",
            severity="error",
            subject=str(hit.path),
            remediation=(
                "Convert to a readable format, e.g. "
                f"`idtrackerai_format {hit.path.parent.parent} --formats npy`."
            ),
        )

    @staticmethod
    def _enrich_from_session_json(session: Session, meta: dict | None) -> Session:
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

        # identities_colors: only in session.json, never the trajectory
        # dict (verified: absent from all 70 real trajectories.h5/.npy
        # payloads). Index-aligned with identities_labels/individual_id.
        raw_colors = meta.get("identities_colors")
        if raw_colors:
            with contextlib.suppress(TypeError, ValueError):
                updates["identities_colors"] = [str(c) for c in raw_colors]

        # roi_list: list of "± Polygon [[x,y], …]" strings -> parsed
        # {sign, vertices, raw} dicts. Unparseable entries are dropped
        # (parse_roi_string logs why) rather than failing the whole import.
        raw_roi = meta.get("roi_list")
        if raw_roi:
            parsed_roi = [
                p for r in raw_roi if (p := parse_roi_string(r)) is not None
            ]
            if parsed_roi:
                updates["roi_list"] = parsed_roi

        # Straightforward scalar/list passthroughs -- see the Session field
        # docstrings (core/models.py) for why each of these matters.
        if (v := meta.get("number_of_error_frames")) is not None:
            with contextlib.suppress(TypeError, ValueError):
                updates["number_of_error_frames"] = int(v)

        if (v := meta.get("exclusive_rois")) is not None:
            updates["exclusive_rois"] = bool(v)

        if (v := meta.get("last_validated")):
            updates["last_validated"] = str(v)

        if (v := meta.get("data_policy")):
            updates["data_policy"] = str(v)

        if (v := meta.get("length_calibrations")):
            updates["length_calibrations"] = list(v)

        if (v := meta.get("velocity_threshold")) is not None:
            with contextlib.suppress(TypeError, ValueError):
                updates["velocity_threshold_px_frame"] = float(v)

        if (v := meta.get("resolution_reduction")) is not None:
            with contextlib.suppress(TypeError, ValueError):
                updates["resolution_reduction"] = float(v)

        if (v := meta.get("id_image_size")):
            updates["id_image_size"] = list(v)

        segmentation_keys = (
            "intensity_ths", "area_ths", "use_bkg",
            "background_subtraction_stat", "erosion_kernel_size",
        )
        segmentation_params = {k: meta[k] for k in segmentation_keys if k in meta}
        if segmentation_params:
            updates["segmentation_params"] = segmentation_params

        return session.model_copy(update=updates) if updates else session
