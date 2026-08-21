"""Exporter abstract base class and ExportPayload dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

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


class Exporter(ABC):
    """Abstract base for every Track2Data exporter."""

    name: str
    file_extension: str

    @abstractmethod
    def write(self, payload: object, out_dir: Path) -> list[Path]: ...
