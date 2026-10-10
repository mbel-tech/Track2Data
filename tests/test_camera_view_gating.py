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


# ── provenance ───────────────────────────────────────────────────────────────


def _tank_zones():
    from track2data.core.models import ROI, ZoneSet

    return ZoneSet(
        rois=[ROI(name="tank", level="main", vertices=[(0, 100), (400, 100), (400, 400), (0, 400)])]
    )


def test_the_payload_records_the_declared_view() -> None:
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("side", ["IL-1"]))

    payload = engine.build_payload(psess, engine.compute_metrics(psess))

    assert payload.provenance.camera_view == "side"


def test_the_payload_defaults_to_an_unset_view() -> None:
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("unknown", ["IL-1"]))

    payload = engine.build_payload(psess, engine.compute_metrics(psess))

    assert payload.provenance.camera_view == "unknown"
    assert payload.provenance.water_column is None


def test_the_water_column_is_recorded_when_depth_was_computed() -> None:
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("side", ["IL-15"], zones=_tank_zones()))

    results = engine.compute_metrics(psess)
    payload = engine.build_payload(psess, results)

    assert "IL-15" in results
    assert payload.provenance.water_column == {
        "top_px": 100.0,
        "bottom_px": 400.0,
        "source": "zone:tank",
    }


def test_no_water_column_is_recorded_when_depth_was_not_computed() -> None:
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("side", ["IL-1"], zones=_tank_zones()))

    payload = engine.build_payload(psess, engine.compute_metrics(psess))

    assert payload.provenance.water_column is None


def test_the_project_summary_names_the_view_only_when_declared() -> None:
    engine_side = Engine(_manifest("side", ["IL-1"]))
    engine_default = Engine(_manifest("unknown", ["IL-1"]))

    assert "Camera view: side view" in engine_side._project_readme_text([], [])
    assert "Camera view" not in engine_default._project_readme_text([], [])


# ── fused sessions ───────────────────────────────────────────────────────────


def _with_depth(psess):
    import numpy as np

    psess.depth = np.full((psess.xy.shape[0], psess.xy.shape[1]), 0.5)
    psess.depth_height_cm = 20.0
    psess.depth_outside_mask = np.zeros(psess.depth.shape, dtype=bool)
    psess.depth_outside = np.zeros(psess.xy.shape[1], dtype=int)
    return psess


def test_a_fused_session_is_top_view_whatever_the_project_says() -> None:
    engine = Engine(_manifest("side", []))
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    assert engine.camera_view_for_psess(psess) == "side"
    assert engine.camera_view_for_psess(_with_depth(psess)) == "top"


@pytest.mark.parametrize("view", ["unknown", "top"])
def test_il15_runs_on_a_fused_session_but_not_on_a_plain_one(view) -> None:
    plain = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest(view, ["IL-15"]))
    assert "IL-15" not in engine.compute_metrics(plain)
    assert "IL-15" in engine.skipped_metrics(False, plain.session, psess=plain)

    fused = _with_depth(_make_psess(_make_session(n_frames=10, n_animals=2)))
    results = engine.compute_metrics(fused)
    assert "IL-15" in results
    assert results["IL-15"]["depth_extent_source"].iloc[0] == "fusion"
    assert engine.skipped_metrics(False, fused.session, psess=fused) == {}


def test_a_fused_session_still_skips_other_side_only_metrics(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    fused = _with_depth(_make_psess(_make_session(n_frames=10, n_animals=2)))
    engine = Engine(_manifest("side", ["IL-SIDE"]))
    assert "IL-SIDE" not in engine.compute_metrics(fused)


# ── manifest-level availability in a 3-D project ─────────────────────────────


def _manifest_3d(view: str, individual: list[str]):
    from track2data.core.models import ProjectMode

    return _manifest(view, individual).model_copy(
        update={"mode": ProjectMode(dimension="3d", layout="two_videos")}
    )


@pytest.mark.parametrize("view", ["unknown", "top", "side"])
def test_a_3d_manifest_passes_the_view_gate_for_il15(view) -> None:
    engine = Engine(_manifest_3d(view, ["IL-15"]))
    assert engine.view_skipped_metrics() == {}
    assert not any("view" in i for i in engine.validate())
    assert engine._view_selection_notes() == []


def test_a_3d_manifest_still_gates_other_side_only_metrics(monkeypatch) -> None:
    _register_side_metric(monkeypatch)
    engine = Engine(_manifest_3d("side", ["IL-15", "IL-SIDE"]))
    assert set(engine.view_skipped_metrics()) == {"IL-SIDE"}


def test_a_2d_manifest_still_gates_il15() -> None:
    assert set(Engine(_manifest("top", ["IL-15"])).view_skipped_metrics()) == {"IL-15"}


def test_manifest_view_helper() -> None:
    from track2data.metrics.availability import manifest_view

    assert manifest_view(_manifest_3d("side", [])) == ("top", True)
    assert manifest_view(_manifest("side", [])) == ("side", False)


@pytest.mark.parametrize("view", ["unknown", "side", "top"])
def test_the_payload_of_a_fused_session_records_top_and_no_water_column(view) -> None:
    fused = _with_depth(_make_psess(_make_session(n_frames=10, n_animals=2)))
    engine = Engine(_manifest(view, ["IL-15"]))
    payload = engine.build_payload(fused, engine.compute_metrics(fused))
    assert payload.provenance.camera_view == "top"
    assert payload.provenance.water_column is None


# ── depth-scale metrics (requires_depth_scale) ───────────────────────────────


def _register_depth_scale_metric(monkeypatch, metric_id: str = "IL-DS") -> None:
    class NeedsScale(Metric):
        id = metric_id
        name = "needs scale"
        label = "Needs scale"
        level = "individual"
        priority = "optional"
        requires_identity = False
        requires_depth_scale = True
        output_columns = ["session_id"]
        documentation = MetricDocumentation(
            definition="test-only", formula_plain="n/a", inputs=[], assumptions=[], warnings=[],
        )

        def compute(self, session, cfg=None):
            return pd.DataFrame({"session_id": [session.session_id]})

    monkeypatch.setitem(metrics_module._registry, metric_id, NeedsScale)


def _manifest_3d_cal(mode: str, individual: list[str]):
    from track2data.core.models import CalibrationConfig

    cal = (
        CalibrationConfig(mode="bodylength")
        if mode == "bodylength"
        else CalibrationConfig(mode=mode, px_per_cm=10.0)
    )
    return _manifest_3d("top", individual).model_copy(update={"calibration": cal})


def test_a_2d_project_skips_a_depth_scale_metric_with_the_fused_reason(monkeypatch) -> None:
    _register_depth_scale_metric(monkeypatch)
    psess = _make_psess(_make_session(n_frames=10, n_animals=2))
    engine = Engine(_manifest("top", ["IL-DS"]))
    results = engine.compute_metrics(psess)
    assert "IL-DS" not in results
    assert engine.build_payload(psess, results).skipped_metrics == {
        "IL-DS": "needs a fused 3-D session"
    }
    assert engine.view_skipped_metrics() == {"IL-DS": "needs a fused 3-D session"}


def test_a_3d_bodylength_project_skips_it_at_manifest_level_and_run_time(monkeypatch) -> None:
    _register_depth_scale_metric(monkeypatch)
    engine = Engine(_manifest_3d_cal("bodylength", ["IL-DS"]))
    expected = "needs a cm scale for the top view (use scalar or session calibration)"
    assert engine.view_skipped_metrics() == {"IL-DS": expected}
    assert engine._view_selection_notes() == []  # all selected skipped: validate() blocks
    engine = Engine(
        engine.manifest.model_copy(update={"sessions": [_identity_free_ref()]})
    )
    issues = " ".join(engine._gate_selection_issues())
    assert "IL-DS" in issues
    assert expected in issues
    assert "camera view" not in issues.lower()
    fused = _with_depth(_make_psess(_make_session(n_frames=10, n_animals=2)))
    fused.px_per_cm = 8.0
    assert engine.view_skipped_metrics(psess=fused) == {"IL-DS": expected}
    assert "IL-DS" not in engine.compute_metrics(fused)


def test_a_3d_scalar_project_is_available_at_manifest_level(monkeypatch) -> None:
    _register_depth_scale_metric(monkeypatch)
    engine = Engine(_manifest_3d_cal("scalar", ["IL-DS"]))
    assert engine.view_skipped_metrics() == {}
    assert engine._gate_selection_issues() == []


def test_a_fused_unit_without_px_per_cm_skips_it_with_the_run_time_reason(
    monkeypatch, caplog
) -> None:
    _register_depth_scale_metric(monkeypatch)
    engine = Engine(_manifest_3d_cal("scalar", ["IL-DS", "IL-1"]))
    fused = _with_depth(_make_psess(_make_session(n_frames=10, n_animals=2)))
    fused.px_per_cm = None
    with caplog.at_level(logging.WARNING, logger="track2data.api"):
        results = engine.compute_metrics(fused)
    assert "IL-DS" not in results
    assert "IL-1" in results
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "IL-DS" in text
    assert "needs a cm scale for the top view" in text
    assert "camera view" not in text
    payload = engine.build_payload(fused, results)
    assert payload.skipped_metrics == {"IL-DS": "needs a cm scale for the top view"}

    fused.px_per_cm = 8.0
    assert "IL-DS" in engine.compute_metrics(fused)
    fused.depth_height_cm = None
    assert "IL-DS" not in engine.compute_metrics(fused)


def test_validate_names_the_real_cause_for_depth_scale_metrics_in_a_2d_project(monkeypatch) -> None:
    _register_depth_scale_metric(monkeypatch)
    manifest = _manifest("top", ["IL-DS"], sessions=[_identity_free_ref()])
    issues = " ".join(Engine(manifest).validate())
    assert "needs a fused 3-D session" in issues
    assert "camera view" not in issues.lower()


def test_validate_mixed_ruled_out_branch_has_no_camera_view_cause_for_depth_scale(
    monkeypatch,
) -> None:
    _register_depth_scale_metric(monkeypatch)
    ref = _identity_free_ref(track_wo_identities=True)
    manifest = _manifest_3d_cal("bodylength", ["IL-1", "IL-DS"]).model_copy(
        update={"sessions": [ref]}
    )
    issues = " ".join(Engine(manifest).validate())
    assert "diagnostics only" in issues
    assert "IL-DS" in issues
    assert "camera view" not in issues.lower()
