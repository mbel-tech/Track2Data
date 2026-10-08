"""Exporter abstract base class and ExportPayload dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from track2data.core.models import PreprocessReport


@dataclass
class SessionProvenance:
    """
    idtracker.ai-derived facts about *how* a session was tracked and read,
    carried through to the export so a Methods section can be written from
    the output alone.

    Before this existed, ExportPayload carried no reference to Session at
    all, so none of this could reach the README even in principle --
    readme.py listed only metric *IDs*, never quality values, and a reader
    reproducing the same analysis had no way to know which trajectory
    format was actually read, whether the session's tracking run
    succeeded, or how reliable the calibration is.
    """

    reader: str = ""
    idtrackerai_version: str | None = None
    trajectory_format: str | None = None
    trajectory_variant: str | None = None
    n_frames: int = 0
    n_animals: int = 0
    has_stable_identities: bool = False

    # Identity-free tracking. has_stable_identities alone cannot carry this:
    # it is a 3-way OR (tracked without identification, OR
    # fraction_identified < 0.5, OR the NaN-coverage fallback failed), so a
    # False there does not tell a reader whether per-individual metrics were
    # refused on principle or merely looked poor. These three do.
    #   track_wo_identities     -- what the tracker declared; None = unreported
    #   identity_free_effective -- what Track2Data actually acted on
    #   identity_free_source    -- "tracker" | "user override" | "not reported"
    track_wo_identities: bool | None = None
    identity_free_effective: bool = False
    identity_free_source: str = "not reported"

    # From Session.tracking_log (see readers/idtrackerai/log.py)
    tracking_status: str | None = None
    tracking_failure_summary: str = ""
    tracking_warnings_count: int = 0

    # From Session.quality
    estimated_accuracy: float | None = None
    fraction_identified: float | None = None
    silhouette_score: float | None = None
    fragment_connectivity: float | None = None

    # Calibration caveats -- length_unit is a user-defined-unit ratio
    # (session_idtrackerai.md:242), not necessarily centimetres; and
    # output_structure_idtrackerai.md:104 warns body_length depends on
    # segmentation parameters and video conditions regardless of source.
    length_unit: float | None = None
    length_unit_label: str = "cm"
    length_unit_confirmed_by_user: bool = False
    body_length_reliable: bool = False
    # Set when body_length_px came from the opt-in blob-layer enrichment
    # (readers/idtrackerai/blobs.py) rather than the session-wide scalar
    # broadcast -- records which of a session's blob pickles (base vs
    # _validated) produced the value, since mixing curated and uncurated
    # sessions in one analysis without recording which is which is a
    # reproducibility hazard.
    blob_body_length_source_file: str | None = None
    # Validator/data-retention provenance (Session.last_validated /
    # Session.data_policy): whether a human reviewed this session, and which
    # idtracker.ai output folders could have survived.
    last_validated: str | None = None
    data_policy: str | None = None
    # Spread between the Validator's length-calibration clicks; the only
    # direct uncertainty estimate on *_cm columns. n counts usable clicks.
    length_calibration_n: int = 0
    length_calibration_rel_sd: float | None = None

    # Which software produced the trajectories and how the reader that read them was chosen.
    # Every field above that is about idtracker.ai stays empty for any other tracker; these are
    # what a Methods section needs from a session that did not come from idtracker.ai. A reader
    # written from documentation alone is not a reader tested against real output, and the
    # export has to say which one it was.
    #   source_software     -- the reader's display name ("idtracker.ai", "DeepLabCut")
    #   reader_verification -- "real_sample" | "synthetic_only"; None = reader not registered
    #   reader_chosen_by    -- "detected" | "user"; None = recorded before readers were saved
    source_software: str | None = None
    reader_verification: str | None = None
    reader_options: dict[str, Any] = field(default_factory=dict)
    reader_chosen_by: str | None = None
    detection_confidence: str | None = None
    source_files: tuple[str, ...] = ()
    # Pose trackers: which keypoint stood for the animal (Session.keypoints.selection, plus
    # n_keypoints). None for a tracker with one point per animal.
    keypoint_selection: dict[str, Any] | None = None

    # What the length columns are named in (core/units.py): "px", "tu" (the tool's own units,
    # not yet confirmed to be anything), or a unit someone confirmed ("mm"). A tracker's own
    # label for its units ("mm") is recorded beside it, never believed on its own.
    coordinate_unit: str = "px"
    coordinate_unit_reported: str | None = None
    coordinate_unit_confirmed: bool = False


@dataclass
class ExportPayload:
    """All data produced by a pipeline run, ready for export."""

    # Identifiers
    session_id: str
    project_name: str
    project_hash: str          # 16-char hex
    app_version: str

    # Long-format per-frame data (from kinematics + zone assignment)
    fish_by_frame: pd.DataFrame           # the master per-frame table

    # Metric results (dict of metric_id → DataFrame)
    individual_metrics: dict[str, pd.DataFrame] = field(default_factory=dict)
    group_metrics: dict[str, pd.DataFrame] = field(default_factory=dict)
    zone_metrics: dict[str, pd.DataFrame] = field(default_factory=dict)
    diagnostic_metrics: dict[str, pd.DataFrame] = field(default_factory=dict)

    # Pipeline report
    preprocess_report: PreprocessReport = field(default_factory=PreprocessReport)
    manifest_json: str = "{}"   # JSON string of the project manifest
    provenance: SessionProvenance = field(default_factory=SessionProvenance)
    # metric_id -> human-readable reason, for metrics that were selected but
    # deliberately not computed for this session (see
    # Engine.compute_metrics). An export has to be able to say what was NOT
    # computed, or a Methods section written from it silently overstates
    # what the analysis covered.
    skipped_metrics: dict[str, str] = field(default_factory=dict)


class Exporter(ABC):
    """Abstract base for every Track2Data exporter."""

    name: str
    file_extension: str

    @abstractmethod
    def write(self, payload: object, out_dir: Path) -> list[Path]: ...
