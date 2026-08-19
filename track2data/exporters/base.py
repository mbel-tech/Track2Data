"""Exporter abstract base class and ExportPayload dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from track2data.core.models import PreprocessReport


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


class Exporter(ABC):
    """Abstract base for every Track2Data exporter."""

    name: str
    file_extension: str

    @abstractmethod
    def write(self, payload: object, out_dir: Path) -> list[Path]: ...
