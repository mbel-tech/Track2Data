"""GUI-03: per-page stage status and Next-gating rules (Qt-free)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from track2data.core.models import (
    CalibrationConfig,
    ExportTarget,
    IdSwitchCfg,
    MappingRule,
    MetadataSource,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)
from ui.store.stage_status import compute_stage_statuses, next_blocker

PROJECT, SESSIONS, CALIB, ZONES, META, PREP, METRICS, PROC, PREVIEW, EXPORT = range(10)


def _manifest(**kw) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(project_name="p", created_at=now, updated_at=now, **kw)


def _ref(sid="s1", **kw) -> SessionRef:
    return SessionRef(session_id=sid, folder=Path("/tmp") / sid, sha256="", **kw)


def _status(manifest, *, has_run=False):
    return [s.status for s in compute_stage_statuses(manifest, has_run_results=has_run)]


def test_no_project_blocks_everything_after_project() -> None:
    st = _status(None)
    assert st[PROJECT] == "empty"
    assert all(s == "blocked" for s in st[1:])


def test_fresh_project_needs_sessions_and_metrics() -> None:
    st = _status(_manifest())
    assert st[PROJECT] == "valid"
    assert st[SESSIONS] == "empty"
    assert st[METRICS] == "empty"
    assert st[PREP] == "valid"          # defaults are usable
    assert st[ZONES] == "empty"         # optional


def test_sessions_valid_and_identity_free_warns() -> None:
    assert _status(_manifest(sessions=[_ref()]))[SESSIONS] == "valid"
    st = _status(_manifest(sessions=[_ref(track_wo_identities=True)]))
    assert st[SESSIONS] == "warning"


def test_calibration_blocked_without_a_scale_or_confirmation() -> None:
    bad = _manifest(calibration=CalibrationConfig(mode="scalar", px_per_cm=None))
    assert _status(bad)[CALIB] == "blocked"
    unconfirmed = _manifest(
        calibration=CalibrationConfig(mode="session", length_unit_confirmed_by_user=False)
    )
    assert _status(unconfirmed)[CALIB] == "blocked"
    ok = _manifest(calibration=CalibrationConfig(mode="scalar", px_per_cm=12.0))
    assert _status(ok)[CALIB] == "valid"
    assert _status(_manifest(calibration=CalibrationConfig(mode="bodylength")))[CALIB] == "valid"


def test_metadata_needs_a_mapping_once_a_source_is_chosen() -> None:
    src = MetadataSource(path=Path("/tmp/m.csv"), sha256="x")
    assert _status(_manifest())[META] == "empty"
    assert _status(_manifest(metadata_source=src))[META] == "warning"
    ok = _manifest(metadata_source=src, mapping=MappingRule(rules={"session_id": "id"}))
    assert _status(ok)[META] == "valid"


def test_identity_switch_on_warns_in_preprocessing() -> None:
    m = _manifest()
    m = m.model_copy(
        update={
            "preprocess": m.preprocess.model_copy(
                update={"identity_switch": IdSwitchCfg(enabled=True)}
            )
        }
    )
    assert _status(m)[PREP] == "warning"


def test_metrics_valid_when_anything_selected() -> None:
    m = _manifest(metrics=MetricSelection(group=["GL-1"]))
    assert _status(m)[METRICS] == "valid"


def test_results_and_export_follow_run_and_targets() -> None:
    m = _manifest(export_targets=[ExportTarget(exporter_name="csv_long")])
    st = _status(m, has_run=True)
    assert st[PROC] == st[PREVIEW] == "valid"
    assert st[EXPORT] == "valid"
    assert _status(_manifest())[PREVIEW] == "empty"


def test_next_blocker_gates_required_pages_only() -> None:
    fresh = compute_stage_statuses(_manifest(), has_run_results=False)
    assert next_blocker(fresh, PROJECT) is None
    assert "session" in next_blocker(fresh, SESSIONS).lower()
    assert next_blocker(fresh, ZONES) is None          # optional
    assert "metric" in next_blocker(fresh, METRICS).lower()

    none = compute_stage_statuses(None, has_run_results=False)
    assert "project" in next_blocker(none, PROJECT).lower()

    bad_cal = compute_stage_statuses(
        _manifest(calibration=CalibrationConfig(mode="scalar", px_per_cm=None)),
        has_run_results=False,
    )
    assert next_blocker(bad_cal, CALIB) is not None


@pytest.mark.parametrize("page", range(10))
def test_every_page_has_a_message_for_non_valid_states(page) -> None:
    for s in compute_stage_statuses(None, has_run_results=False):
        assert isinstance(s.message, str)


# ── camera view: the Zones stage and the sidebar ─────────────────────────────


def _side(**kw) -> ProjectManifest:
    from track2data.core.models import SceneConfig

    return _manifest(scene=SceneConfig(camera_view="side"), **kw)


def _tank():
    from track2data.core.models import ROI

    return ROI(name="tank", level="main", vertices=[(0, 100), (500, 100), (500, 700), (0, 700)])


def test_side_view_with_depth_selected_but_no_water_column_warns_on_zones() -> None:
    m = _side(metrics=MetricSelection(individual=["IL-15"]))
    info = compute_stage_statuses(m, has_run_results=False)[ZONES]
    assert info.status == "warning"
    assert "waterline" in info.message
    assert "IL-15" in info.message


def test_side_view_with_a_main_zone_is_fine() -> None:
    from track2data.core.models import ZoneSet

    m = _side(
        metrics=MetricSelection(individual=["IL-15"]), zones=ZoneSet(rois=[_tank()])
    )
    assert _status(m)[ZONES] == "valid"


def test_side_view_with_only_secondary_zones_still_has_no_water_column() -> None:
    from track2data.core.models import ROI, ZoneSet

    band = ROI(name="band", level="secondary", vertices=[(0, 0), (5, 0), (5, 5)])
    m = _side(metrics=MetricSelection(individual=["IL-15"]), zones=ZoneSet(rois=[band]))
    assert _status(m)[ZONES] == "warning"


def test_side_view_without_a_depth_metric_selected_does_not_nag() -> None:
    m = _side(metrics=MetricSelection(individual=["IL-1"]))
    assert _status(m)[ZONES] == "empty"


@pytest.mark.parametrize("view", ["unknown", "top"])
def test_other_views_never_warn_about_the_water_column(view) -> None:
    from track2data.core.models import SceneConfig

    m = _manifest(
        scene=SceneConfig(camera_view=view), metrics=MetricSelection(individual=["IL-15"])
    )
    assert _status(m)[ZONES] == "empty"


def test_the_sidebar_names_a_declared_camera_view() -> None:
    from track2data.core.models import SceneConfig
    from ui.store.stage_status import stage_summaries

    base = stage_summaries(_manifest(), has_run_results=False)[2]
    side = stage_summaries(
        _manifest(scene=SceneConfig(camera_view="side")), has_run_results=False
    )[2]
    top = stage_summaries(
        _manifest(scene=SceneConfig(camera_view="top")), has_run_results=False
    )[2]
    assert side == f"{base} · Side view"
    assert top == f"{base} · Top-down"


def test_the_sidebar_says_when_the_water_column_is_missing() -> None:
    from ui.store.stage_status import stage_summaries

    m = _side(metrics=MetricSelection(individual=["IL-15"]))
    assert stage_summaries(m, has_run_results=False)[3] == "Draw the water column"
