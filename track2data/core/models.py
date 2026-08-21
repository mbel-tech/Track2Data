"""
Core Pydantic data models.

Design notes
────────────
• Session holds numpy arrays (arbitrary_types_allowed=True).  It is
  never serialised to JSON directly; only ProjectManifest is.
• ProjectManifest is fully JSON-serialisable (no numpy).
• All config models use plain Python types and export cleanly via
  model_dump_json() / model_validate_json().
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

# ── Video / Session ───────────────────────────────────────────────────────────


class VideoInfo(BaseModel):
    path: Path | None = None
    fps: float
    n_frames: int
    width_px: int
    height_px: int


class Session(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    folder: Path
    reader: str
    video: VideoInfo
    n_animals: int
    trajectory_variant: Literal["with_gaps", "wo_gaps"]
    has_stable_identities: bool
    # Shape (n_frames, n_animals, 2), dtype float64, NaN = missing position.
    raw_xy: np.ndarray
    # Shape (n_animals,) in pixels; None when no body-length data is available.
    body_length_px: np.ndarray | None = None
    # Always False until the user explicitly acknowledges the segmentation-dependency caveat.
    body_length_reliable: bool = False

    # ── idtracker.ai reader fields ────────────────────────────────────────────
    # Shape (n_frames, n_animals), squeezed from (N, M, 1) when needed.
    id_probabilities: np.ndarray | None = None
    # Quality metrics: estimated_accuracy, fraction_identified, silhouette_score, etc.
    quality: dict[str, Any] | None = None
    # Px-to-real-unit ratio from the validator's length-calibration tool; None = not calibrated.
    length_unit: float | None = None
    identities_labels: list[str] | None = None
    # idtracker.ai docs disagree on this type: session_idtrackerai.md:21 says dict
    # ("Named groups of identities... if exclusive ROI, saved here"); output_structure
    # says list. Real 6.x sessions ship a dict (verified: 70/70 in the GOT corpus).
    # Kept permissive on purpose -- do not narrow this back to list[str].
    identities_groups: dict[str, Any] | list[str] | None = None
    setup_points: dict[str, Any] | None = None
    # [[start, end], …] frame ranges that are valid; frames outside are not tracked.
    tracking_intervals: list[tuple[int, int]] | None = None
    # Parsed signed polygons from session.json roi_list.
    roi_list: list[dict[str, Any]] | None = None
    # Digest extracted from idtrackerai.log: status, per-stage durations, warnings.
    tracking_log: dict[str, Any] | None = None
    # Frame indices flagged as inconsistent by post-processing.
    inconsistent_frames: set[int] | None = None
    # Per-(frame, identity) bounding-box table (pd.DataFrame when present).
    bbox_table: Any | None = None
    bbox_summary: dict[str, Any] | None = None
    # Names of sessions matched by idmatcher.ai (v1.0: list-and-ignore).
    matching_results: list[str] | None = None
    idtrackerai_version: str | None = None
    trajectory_format: str | None = None
    # Verbatim unknown keys from the source trajectory dict.
    raw_attrs: dict[str, Any] | None = None

    @property
    def n_frames(self) -> int:
        return int(self.raw_xy.shape[0])

    def coverage(self) -> np.ndarray:
        """Fraction of non-NaN frames per animal, shape (n_animals,)."""
        valid = ~np.isnan(self.raw_xy[:, :, 0])  # (n_frames, n_animals)
        return valid.mean(axis=0)


# ── Preprocessing config ──────────────────────────────────────────────────────


class GapFillCfg(BaseModel):
    enabled: bool = True
    max_gap_frames: int = 30


class JumpCfg(BaseModel):
    enabled: bool = True
    method: Literal["sd_multiple", "percentile"] = "sd_multiple"
    sd_mult: float = 10.0
    percentile: float = 99.0
    pct_mult: float = 2.0
    replacement: Literal["nan", "linear_interp"] = "linear_interp"


class IdSwitchCfg(BaseModel):
    # Defaults to OFF. This corrector reasons about identity from raw
    # geometry alone (nearest-neighbour + Hungarian assignment), with no
    # knowledge of idtracker.ai's own fragment boundaries -- the only
    # frames where an identity swap is even possible. Measured on the real
    # idtracker.ai corpus (session_trial10_Segment1), it re-permutes 17.1%
    # of the recording and injects ~640px single-frame teleports (a
    # stationary animal's path length inflated from 218px to 11,639px,
    # +5234%). See docs_from_idtracker.ai/fragment_idtrackerai.md and the
    # format-alignment plan Fase 1.5b/6d: a fragment-boundary-aware
    # replacement is planned; this pass is not safe to run unconditionally
    # until then. Enable only if you understand and accept that risk.
    enabled: bool = False
    tier1_ratio: float = 1.5
    tier2_hungarian: bool = True
    consolidate_window: int = 5


class SmoothCfg(BaseModel):
    enabled: bool = True
    method: Literal["none", "moving_avg", "savgol"] = "savgol"
    window: int = 5
    polyorder: int = 2


class ValidateCfg(BaseModel):
    min_track_frames: int = 0
    max_pct_na_per_individual: float = 0.10


class PreprocessConfig(BaseModel):
    gap_fill: GapFillCfg = GapFillCfg()
    jump: JumpCfg = JumpCfg()
    identity_switch: IdSwitchCfg = IdSwitchCfg()
    smoothing: SmoothCfg = SmoothCfg()
    coverage: ValidateCfg = ValidateCfg()


# ── Calibration & zones ───────────────────────────────────────────────────────


class CalibrationConfig(BaseModel):
    mode: Literal["scalar", "bodylength"] = "bodylength"
    px_per_cm: float | None = None
    bl_min_samples: int = 30


class ROI(BaseModel):
    name: str
    level: str = "main"
    vertices: list[tuple[float, float]]
    area_units: float | None = None
    # "+" (additive) or "-" (subtractive/exclusion). idtracker.ai's roi_list
    # defines an arena as one or more "+ Polygon" outer boundaries minus any
    # number of "- Polygon" exclusion holes (idtracker.ai_usage.md:30-31).
    # Multiple ROIs sharing the same (name, level) with different signs
    # combine: a point belongs to the zone iff it is covered by at least
    # one "+" polygon and not covered by any "-" polygon of that name.
    # Defaults to "+" so hand-drawn zones (which have no notion of holes)
    # are unaffected.
    sign: Literal["+", "-"] = "+"


class ZoneSet(BaseModel):
    rois: list[ROI] = []
    orientation_tag: str | None = None
    zone_levels: dict[str, str] = {}
    # Pixel dimensions of the video these ROIs were defined against. Set
    # when seeding a ZoneSet from Session.roi_list; None for hand-drawn
    # zones (no source video to compare against). Used to detect (not
    # silently ignore) reusing a ZoneSet on a session tracked at a
    # different resolution -- see zones/io.py::zone_set_from_roi_list.
    source_width_px: int | None = None
    source_height_px: int | None = None


# ── Metric selection ──────────────────────────────────────────────────────────


class MetricSelection(BaseModel):
    individual: list[str] = []
    group: list[str] = []
    zone: list[str] = []
    # Diagnostic IDs (D-*) are auto-computed regardless; this list is
    # reserved for future per-user opt-outs.
    diagnostic: list[str] = []
    timepoint_minutes: int | None = None
    # Mask per-frame metrics when id_probabilities[frame, animal] < threshold.
    quality_threshold: float = 0.0


# ── Manifest building blocks ──────────────────────────────────────────────────


class SessionRef(BaseModel):
    session_id: str
    folder: Path
    sha256: str


class MetadataSource(BaseModel):
    path: Path
    sha256: str


class MappingRule(BaseModel):
    rules: dict[str, str] = {}   # canonical_field -> source_column
    join_keys: list[str] = ["session_id"]
    join_regex: str | None = None


class ExportTarget(BaseModel):
    exporter_name: str
    out_dir: Path | None = None


# ── Project manifest ──────────────────────────────────────────────────────────


class ProjectManifest(BaseModel):
    schema_version: int = 1
    app_version: str = "0.1.0"
    project_name: str
    created_at: datetime
    updated_at: datetime
    sessions: list[SessionRef] = []
    calibration: CalibrationConfig = CalibrationConfig()
    zones: ZoneSet = ZoneSet()
    metadata_source: MetadataSource | None = None
    mapping: MappingRule | None = None
    preprocess: PreprocessConfig = PreprocessConfig()
    metrics: MetricSelection = MetricSelection()
    export_targets: list[ExportTarget] = []
    run_log_path: Path | None = None

    def project_hash(self) -> str:
        """16-char hex hash of the manifest content (timestamps excluded)."""
        data: dict[str, Any] = self.model_dump(
            exclude={"created_at", "updated_at", "run_log_path"}
        )
        serialised = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]


# ── Preprocessing runtime types ───────────────────────────────────────────────
# These are dataclasses (not Pydantic) because they hold numpy arrays and are
# never serialised to JSON; they exist only in memory during a pipeline run.


@dataclass
class PPStepResult:
    """Result of a single preprocessing step."""

    step_name: str
    affected_frames: int
    affected_per_individual: list[int]
    notes: str = ""


@dataclass
class PreprocessReport:
    """Ordered log of all preprocessing steps applied to a session."""

    steps: list[PPStepResult] = field(default_factory=list)

    @property
    def total_affected_frames(self) -> int:
        return sum(s.affected_frames for s in self.steps)


@dataclass
class SessionRunResult:
    """
    Outcome of running one session through ``Engine.run()``.

    Deliberately small and picklable (a prerequisite for any future
    parallel execution across processes): metric previews are capped at
    ``head(200)`` and the full ``fish_by_frame`` table is never retained
    at all -- a 70-session real run would need tens of GB if every
    session's per-frame table were kept in memory afterwards.
    """

    session_id: str
    written: list[Path] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metric_previews: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class RunResult:
    """Outcome of running every session in a manifest through ``Engine.run()``."""

    sessions: list[SessionRunResult] = field(default_factory=list)

    @property
    def written(self) -> list[Path]:
        """All written paths across every session, flattened."""
        paths: list[Path] = []
        for s in self.sessions:
            paths.extend(s.written)
        return paths


@dataclass
class KinematicsArrays:
    """Per-frame kinematics derived from a preprocessed xy array."""

    speed_px_s: np.ndarray        # (n_frames, n_animals) — NaN at missing/boundary frames
    accel_px_s2: np.ndarray       # (n_frames, n_animals)
    heading_rad: np.ndarray       # (n_frames, n_animals)


@dataclass
class PreprocessedSession:
    """
    A fully preprocessed session ready for metric computation.

    Produced by ``preprocess.pipeline.run(session, config)``; consumed by
    all metric modules and the exporter layer.
    """

    session: Session                          # original Session (raw_xy untouched)
    xy: np.ndarray                            # (n_frames, n_animals, 2) preprocessed
    kinematics: KinematicsArrays
    px_per_cm: float | None = None            # set by calibration.scalar
    body_length_cm: np.ndarray | None = None  # (n_animals,) — set by calibration.bodylength
    # Zone assignments: object arrays of zone-name strings; None if zones not configured.
    main_zone: np.ndarray | None = None       # (n_frames, n_animals)
    sec_zone: np.ndarray | None = None        # (n_frames, n_animals)
    report: PreprocessReport = field(default_factory=PreprocessReport)

    # ── convenience pass-throughs ─────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def n_frames(self) -> int:
        return int(self.xy.shape[0])

    @property
    def n_animals(self) -> int:
        return int(self.xy.shape[1])

    @property
    def fps(self) -> float:
        return self.session.video.fps
