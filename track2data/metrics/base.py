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
from typing import Any, ClassVar, Literal

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


class MetricParameter(BaseModel):
    """Declarative description of one configurable knob on a metric's
    ``compute(session, cfg)`` dict -- drives the GUI's per-metric ⚙
    config dialog (widget kind, default, bounds) rather than each
    screen having to know each metric's config shape by hand. See
    METRICS_SPEC.md §7/§8 open question 3.

    ``derived=True`` marks a value that cannot be user-typed because
    it is a property of the session's own tracked arena -- e.g. IL-3's
    arena centre, computed per session from that session's own zones
    (track2data/metrics/derived.py) -- so the config dialog renders it
    read-only instead of an editable default.
    """

    name: str
    label: str
    kind: Literal["float", "int", "choice", "bool"]
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    help: str | None = None
    choices: list[str] | None = None
    derived: bool = False


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
    # Most metrics take no configuration at all -- an
    # empty default, not a required field, so every existing metric
    # class stays valid without declaring it.
    parameters: ClassVar[list[MetricParameter]] = []

    @abstractmethod
    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        ...
