"""
Metric abstract base class + metric documentation model.

`MetricDocumentation` carries the human-readable definition / formula /
inputs / assumptions / warnings / citation that the UI
`MetricInfoDialog` renders. Each concrete metric class declares one as
a class attribute; the content comes verbatim from
`docs/METRICS_SPEC.md` §4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd
from pydantic import BaseModel


class MetricDocumentation(BaseModel):
    """Renderable documentation for a single metric (see METRICS_SPEC.md §5.2)."""

    definition: str
    formula_plain: str
    formula_latex: str | None = None
    inputs: list[str]
    assumptions: list[str]
    warnings: list[str]
    citation: str | None = None
    citation_doi: str | None = None


class Metric(ABC):
    """Abstract base for every Track2Data metric (see METRICS_SPEC.md §5)."""

    id: str
    name: str
    label: str
    level: Literal["individual", "group", "zone", "diagnostic"]
    priority: Literal["primary", "optional", "advanced", "diagnostic"]
    requires_identity: bool
    output_columns: list[str]
    documentation: MetricDocumentation

    @abstractmethod
    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        ...
