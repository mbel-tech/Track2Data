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

from track2data.core.models import CameraView
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

    ``auto_label`` overrides the text the config dialog shows for a
    numeric parameter left unset (``default=None``). The generic
    "Auto (data-driven)" is right for IL-4's ``threshold_px_s``, which
    really is computed from the data whenever it is blank -- but wrong
    for a threshold whose unset behaviour depends on another parameter
    (IL-7's ``min_bout_frames`` resolves to a fixed 5 unless
    ``derive_bout_criterion`` is switched on), where claiming
    "data-driven" would describe behaviour the user has not enabled.

    ``disabled_by`` names another (boolean) parameter that overrides
    this one: when it is on, this parameter's value is ignored, so the
    config dialog greys the row out. Without it a user could type a
    threshold into a control the metric will not read -- e.g. IL-7's
    ``min_bout_frames`` while ``derive_bout_criterion`` is switched on.
    The stored value is preserved, not cleared, so unticking the
    controlling switch brings it back into effect.
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
    auto_label: str | None = None
    disabled_by: str | None = None


class Metric(ABC):
    """Abstract base for every Track2Data metric (see METRICS_SPEC.md §5).

    Every attribute below is a ``ClassVar``: a metric's identity, level and
    declared schema are properties of the class, not of an instance, and
    every concrete metric sets them with a plain class-body assignment.
    Declaring them as instance variables here made each of those 50
    assignments a type error.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    label: ClassVar[str]
    level: ClassVar[Literal["individual", "group", "zone", "diagnostic"]]
    priority: ClassVar[Literal["primary", "optional", "advanced", "diagnostic"]]
    requires_identity: ClassVar[bool]
    # The camera views this metric is meaningful for; None = any view, which is the safe default
    # (a legacy project declares none). A set rather than one required value so a later
    # "top-down or not set" gate cannot lock out legacy projects. Read it through
    # metrics/availability.py, never directly: test doubles predate the attribute.
    valid_camera_views: ClassVar[frozenset[CameraView] | None] = None
    # True for a metric that reads the fused depth array (PreprocessedSession.depth): it is then
    # available for any session that has depth, whatever its camera view says.
    uses_depth: ClassVar[bool] = False
    # True for a metric that needs the fused session's 3-D positions in cm (depth plus a cm scale
    # for the top view). Availability goes through metrics/availability.py: depth_scale_reason.
    requires_depth_scale: ClassVar[bool] = False
    # True for a metric that differentiates a series itself and so must use the estimator the
    # pipeline used for ``kinematics``: the Engine then puts the manifest's KinematicsCfg
    # (as a dict) under ``cfg["kinematics"]``.
    uses_kinematics_cfg: ClassVar[bool] = False
    # Zone metrics that stay meaningful on an identity-free session when
    # computed on a pooled view of all slots (see metrics/zone.py).
    pools_when_identity_free: ClassVar[bool] = False
    # False for metrics whose value is not meaningful on a time window of the
    # session (whole-track tortuosity; a half-vs-half stability check). With
    # timepoint binning on, such a metric stays one whole-session row per animal.
    window_safe: ClassVar[bool] = True
    output_columns: ClassVar[list[str]]
    documentation: ClassVar[MetricDocumentation]
    # Most metrics (32 of 53 today) take no configuration at all --
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

    @classmethod
    def resolve_for_windows(cls, session: object, cfg: dict | None) -> dict:
        """cfg entries a metric derives *from the data*, resolved on the whole
        session so every time window (timepoint binning) uses the same value.

        Without this, a metric that sets its own threshold from the data it is
        given (mean speed, a fitted bout criterion) would pick a different one
        per window, and per-bin values would stop being comparable. The default
        is ``{}``: nothing is data-derived.
        """
        return {}

    @abstractmethod
    def compute(self, session: Any, cfg: dict | None = None) -> pd.DataFrame:
        """Compute this metric and return one DataFrame.

        ``session`` is deliberately ``Any``: the D-1..D-10 diagnostics
        describe the tracker's own output and take a ``Session``, while every
        other metric -- including D-11 -- takes a ``PreprocessedSession``.
        That split is real rather than accidental (a diagnostic that read the
        preprocessed array could not report on preprocessing), so the base
        class does not pretend to a single parameter type it would then have
        to violate 36 times.

        The returned frame's columns must match :attr:`output_columns`
        exactly -- see tests/test_metrics/test_output_schema_contract.py.
        """
