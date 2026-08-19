"""Tests for the metric abstract base + MetricDocumentation (TDD RED)."""

from __future__ import annotations

import pytest

from track2data.metrics.base import Metric, MetricDocumentation


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
