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
