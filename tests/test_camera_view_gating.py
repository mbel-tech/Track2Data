"""The engine skips metrics the project's camera view rules out, and says why.

Mirrors the identity gate (tests/test_api.py): the metric is absent from the results, present
in the export's skipped-metrics record, and a run that would be empty is blocked up front.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

import track2data.metrics as metrics_module
from tests.test_api import (
    _identity_free_ref,
    _make_manifest,
    _make_psess,
    _make_session,
)
from track2data.api import Engine
from track2data.core.models import MetricSelection, SceneConfig
from track2data.metrics.base import Metric, MetricDocumentation


def _register_side_metric(
    monkeypatch: pytest.MonkeyPatch, metric_id: str = "IL-SIDE", *, requires_identity: bool = False
) -> None:
    class SideOnly(Metric):
        id = metric_id
        name = "side only"
        label = "Side only"
        level = "individual"
        priority = "optional"
        valid_camera_views = frozenset({"side"})
        output_columns = ["session_id"]
        documentation = MetricDocumentation(
            definition="test-only", formula_plain="n/a", inputs=[], assumptions=[], warnings=[],
        )

        def compute(self, session, cfg=None):
            return pd.DataFrame({"session_id": [session.session_id]})

    SideOnly.requires_identity = requires_identity
    monkeypatch.setitem(metrics_module._registry, metric_id, SideOnly)


def _manifest(view: str, individual: list[str], **kw):
    return _make_manifest(
        metrics=MetricSelection(individual=individual), **kw
    ).model_copy(update={"scene": SceneConfig(camera_view=view)})


def test_a_side_only_metric_is_skipped_until_the_view_is_declared(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("unknown", ["IL-SIDE"]))

    results = engine.compute_metrics(psess)
    payload = engine.build_payload(psess, results)

    assert "IL-SIDE" not in results
    assert set(payload.skipped_metrics) == {"IL-SIDE"}
    assert "camera view" in payload.skipped_metrics["IL-SIDE"]


def test_a_top_down_project_skips_it_too(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    results = Engine(_manifest("top", ["IL-SIDE"])).compute_metrics(psess)
    assert "IL-SIDE" not in results


def test_a_side_view_project_runs_it(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("side", ["IL-SIDE"]))

    results = engine.compute_metrics(psess)

    assert "IL-SIDE" in results
    assert engine.build_payload(psess, results).skipped_metrics == {}


def test_an_identity_free_view_gated_metric_records_both_reasons(monkeypatch) -> None:
    _register_side_metric(monkeypatch, requires_identity=True)
    session = _make_session(n_frames=10, n_animals=2).model_copy(
        update={"track_wo_identities": True}
    )
    psess = _make_psess(session)
    ref = _identity_free_ref(track_wo_identities=True)
    engine = Engine(_manifest("unknown", ["IL-1", "IL-SIDE"], sessions=[ref]))

    payload = engine.build_payload(psess, engine.compute_metrics(psess))

    assert set(payload.skipped_metrics) == {"IL-1", "IL-SIDE"}
    assert "identity-free" in payload.skipped_metrics["IL-1"]
    assert "camera view" not in payload.skipped_metrics["IL-1"]
    both = payload.skipped_metrics["IL-SIDE"]
    assert "identity-free" in both
    assert "camera view" in both


def test_the_skip_is_logged_as_a_view_skip_not_an_identity_skip(monkeypatch, caplog) -> None:
    _register_side_metric(monkeypatch)
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    with caplog.at_level(logging.WARNING, logger="track2data.api"):
        Engine(_manifest("unknown", ["IL-SIDE"])).compute_metrics(psess)

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "IL-SIDE" in text
    assert "camera view" in text
    assert "identity" not in text


def test_the_camera_view_comes_from_one_seam(monkeypatch) -> None:
    """Per-session views arrive with the two-camera work; every caller already asks here."""
    engine = Engine(_manifest("side", []))
    assert engine.camera_view_for(_make_session()) == "side"


# ── validate / consistency_warnings ──────────────────────────────────────────


def test_validate_blocks_a_run_where_every_selected_metric_is_view_gated(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    engine = Engine(_manifest("unknown", ["IL-SIDE"], sessions=[_identity_free_ref()]))

    issues = engine.validate()

    assert any("IL-SIDE" in i and "camera view" in i for i in issues)


def test_validate_does_not_block_when_some_selected_metric_still_runs(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    engine = Engine(_manifest("unknown", ["IL-1", "IL-SIDE"], sessions=[_identity_free_ref()]))

    assert not any("IL-SIDE" in i for i in engine.validate())


def test_a_partial_skip_is_reported_as_a_warning(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    engine = Engine(_manifest("unknown", ["IL-1", "IL-SIDE"], sessions=[_identity_free_ref()]))

    warnings = engine.consistency_warnings()

    assert any("IL-SIDE" in w and "camera view" in w for w in warnings)
    assert not any("IL-1" in w for w in warnings)


def test_a_fully_available_selection_adds_no_warning(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    engine = Engine(_manifest("side", ["IL-1", "IL-SIDE"], sessions=[_identity_free_ref()]))

    assert not any("camera view" in w for w in engine.consistency_warnings())
    assert not any("camera view" in i for i in engine.validate())
