"""Tests for the metric abstract base + MetricDocumentation (TDD RED)."""

from __future__ import annotations

import pytest

from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter


class TestMetricDocumentation:
    def test_required_fields(self) -> None:
        doc = MetricDocumentation(
            definition="Mean speed of each tracked individual.",
            formula_plain="v[t,k] = ||xy[t+1] - xy[t]|| * fps",
            inputs=["Session.raw_xy", "Session.video.fps"],
            assumptions=["Constant fps"],
            warnings=["Max speed sensitive to jumps"],
        )
        assert doc.definition.startswith("Mean speed")
        assert "fps" in doc.formula_plain
        assert "Session.raw_xy" in doc.inputs

    def test_optional_fields_default_none(self) -> None:
        doc = MetricDocumentation(
            definition="d",
            formula_plain="f",
            inputs=[],
            assumptions=[],
            warnings=[],
        )
        assert doc.formula_latex is None
        assert doc.citation is None
        assert doc.citation_doi is None

    def test_citation_fields_stored(self) -> None:
        doc = MetricDocumentation(
            definition="d", formula_plain="f", inputs=[],
            assumptions=[], warnings=[],
            citation="Couzin et al. 2002, J. Theor. Biol.",
            citation_doi="10.1006/jtbi.2002.3065",
        )
        assert doc.citation.startswith("Couzin")
        assert doc.citation_doi.startswith("10.")

    def test_round_trip_json(self) -> None:
        doc = MetricDocumentation(
            definition="d", formula_plain="f",
            inputs=["a", "b"],
            assumptions=["x"],
            warnings=["y"],
            citation="c",
            citation_doi="10.0/abc",
        )
        restored = MetricDocumentation.model_validate_json(doc.model_dump_json())
        assert restored == doc


class TestMetricBase:
    def test_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            Metric()  # type: ignore[abstract]

    def test_subclass_must_implement_compute(self) -> None:
        class Incomplete(Metric):
            id = "X-1"
            name = "x"
            label = "X"
            level = "individual"
            priority = "primary"
            requires_identity = False
            output_columns: list[str] = ["v"]
            documentation = MetricDocumentation(
                definition="d", formula_plain="f", inputs=[],
                assumptions=[], warnings=[],
            )

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_with_compute_is_instantiable(self) -> None:
        import pandas as pd

        class Concrete(Metric):
            id = "X-1"
            name = "x"
            label = "X"
            level = "individual"
            priority = "primary"
            requires_identity = False
            output_columns: list[str] = ["v"]
            documentation = MetricDocumentation(
                definition="d", formula_plain="f", inputs=[],
                assumptions=[], warnings=[],
            )

            def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
                return pd.DataFrame({"v": []})

        m = Concrete()
        assert m.id == "X-1"
        assert m.documentation.definition == "d"

    def test_level_includes_diagnostic(self) -> None:
        """Level must accept 'diagnostic' (new) in addition to the original three."""
        import pandas as pd

        class Diag(Metric):
            id = "D-1"
            name = "coverage"
            label = "Tracking coverage"
            level = "diagnostic"
            priority = "diagnostic"
            requires_identity = False
            output_columns: list[str] = ["coverage_fraction"]
            documentation = MetricDocumentation(
                definition="d", formula_plain="f", inputs=[],
                assumptions=[], warnings=[],
            )

            def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
                return pd.DataFrame()

        m = Diag()
        assert m.level == "diagnostic"
        assert m.priority == "diagnostic"

    def test_parameters_defaults_to_empty_list(self) -> None:
        """Most metrics (24/33) take no configuration at all -- the gear
        button must disable itself for these rather than open an empty
        dialog, so an empty default (not a required field) matters."""
        import pandas as pd

        class NoParams(Metric):
            id = "X-1"
            name = "x"
            label = "X"
            level = "individual"
            priority = "primary"
            requires_identity = False
            output_columns: list[str] = ["v"]
            documentation = MetricDocumentation(
                definition="d", formula_plain="f", inputs=[],
                assumptions=[], warnings=[],
            )

            def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
                return pd.DataFrame()

        assert NoParams.parameters == []


class TestMetricParameter:
    def test_minimal_construction(self) -> None:
        p = MetricParameter(name="threshold_px_s", label="Activity threshold", kind="float")
        assert p.name == "threshold_px_s"
        assert p.kind == "float"
        assert p.default is None
        assert p.derived is False

    def test_choice_kind_carries_choices(self) -> None:
        p = MetricParameter(
            name="cohesion_source",
            label="Cohesion source",
            kind="choice",
            default="nnd",
            choices=["nnd", "iid"],
            help="Which pairwise-distance measure group cohesion is derived from.",
        )
        assert p.choices == ["nnd", "iid"]
        assert p.default == "nnd"

    def test_derived_parameter_has_no_user_default_semantics(self) -> None:
        """derived=True marks a parameter as computed per-session (e.g.
        IL-3's arena centre from that session's own zones) -- the GUI
        renders it read-only rather than as an editable default."""
        p = MetricParameter(
            name="centre", label="Arena centre", kind="float", derived=True,
        )
        assert p.derived is True

    def test_bounds_and_unit(self) -> None:
        p = MetricParameter(
            name="min_bout_frames",
            label="Minimum bout length",
            kind="int",
            default=5,
            minimum=1,
            maximum=1000,
            unit="frames",
        )
        assert p.minimum == 1
        assert p.maximum == 1000
        assert p.unit == "frames"

    def test_round_trip_json(self) -> None:
        p = MetricParameter(
            name="threshold_px_s", label="Activity threshold", kind="float",
            default=1.5, minimum=0.0, maximum=None, unit="px/s",
            help="Speed above which an animal counts as active.",
        )
        restored = MetricParameter.model_validate_json(p.model_dump_json())
        assert restored == p

    def test_metric_can_declare_parameters(self) -> None:
        import pandas as pd

        class Configurable(Metric):
            id = "X-2"
            name = "x2"
            label = "X2"
            level = "individual"
            priority = "primary"
            requires_identity = False
            output_columns: list[str] = ["v"]
            documentation = MetricDocumentation(
                definition="d", formula_plain="f", inputs=[],
                assumptions=[], warnings=[],
            )
            parameters = [
                MetricParameter(
                    name="threshold_px_s", label="Threshold", kind="float", default=1.0,
                ),
            ]

            def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
                return pd.DataFrame()

        assert len(Configurable.parameters) == 1
        assert Configurable.parameters[0].name == "threshold_px_s"
