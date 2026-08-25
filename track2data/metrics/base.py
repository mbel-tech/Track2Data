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
from pydantic import BaseModel, model_validator

from track2data.metrics.references import Reference


class MetricDocumentation(BaseModel):
    """Renderable documentation for a single metric (see METRICS_SPEC.md §5.2).

    A metric cites a specific, findable work in one of two ways:

    - ``primary_reference`` (a ``Reference`` from ``metrics/references.py``)
      when one exists -- ``citation``/``citation_doi`` are then filled in
      automatically from it, so every metric that points at the same
      ``Reference`` object produces byte-identical citation text. This is
      what makes
      ``test_no_doi_is_shared_by_metrics_citing_different_works`` unfailable
      by construction rather than merely checked.
    - ``citation`` set directly, as free text, when no single work applies
      (e.g. "Standard kinematics; no single originating work"). Inventing a
      ``Reference`` for a generic convention would misrepresent it as
      having one paper behind it.

    Exactly one of the two is used per metric; setting both is a
    contributor error the validator below catches at class-definition time
    rather than leaving it to be noticed later in the rendered CSV.

    ``supporting_references`` (works that strengthen but do not solely
    define the metric) are independent of this choice and may be attached
    either way.
    """

    definition: str
    formula_plain: str
    formula_latex: str | None = None
    inputs: list[str]
    assumptions: list[str]
    warnings: list[str]
    citation: str | None = None
    citation_doi: str | None = None
    primary_reference: Reference | None = None
    supporting_references: list[Reference] = []

    @model_validator(mode="after")
    def _resolve_citation_from_primary_reference(self) -> MetricDocumentation:
        if self.primary_reference is not None:
            if self.citation is not None or self.citation_doi is not None:
                raise ValueError(
                    "set either primary_reference or citation/citation_doi, not both "
                    f"(got primary_reference={self.primary_reference.key!r} and "
                    f"citation={self.citation!r})"
                )
            self.citation = self.primary_reference.text
            self.citation_doi = self.primary_reference.doi
        return self


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
    # Most metrics (24 of 44 today) take no configuration at all --
    # an empty default, not a required field, so every existing
    # metric class stays valid without declaring it. The figure is
    # pinned by tests/test_metric_references_consistency.py.
    parameters: ClassVar[list[MetricParameter]] = []
    # Set to another metric's `id` when this metric is kept only for
    # output-compatibility with existing projects and a strictly better
    # statistic now exists (e.g. Z-2's unbounded ratio vs Z-8's bounded
    # Jacobs' D) -- see METRICS_SPEC.md's Z-2 entry. `None` for every
    # other metric. Rendered as a notice in the ⓘ dialog and the
    # metrics-screen row tooltip; never changes what compute() returns.
    superseded_by: ClassVar[str | None] = None

    @abstractmethod
    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        ...
