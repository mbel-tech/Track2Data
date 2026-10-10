"""GUI-03: per-page stage status and Next-gating rules (Qt-free)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from track2data.core.models import (
    MODE_3D_BLOCK_REASON,
    CalibrationConfig,
    ExportTarget,
    FusionSettings,
    IdSwitchCfg,
    MappingRule,
    MetadataSource,
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    SessionRef,
    ViewPair,
)
from ui.store.stage_status import SESSIONS_NEEDS_LAYOUT, compute_stage_statuses, next_blocker

(
    PROJECT, SESSIONS, CALIB, ZONES, META, PREP, METRICS, PROC, PREVIEW, EXPORT, VIEWS
) = range(11)


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
    assert all(s == "blocked" for s in st[1:VIEWS])
    assert st[VIEWS] == "empty"
    assert len(st) == 11


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


@pytest.mark.parametrize("page", range(11))
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


def _manifest_3d(layout="two_videos", **kw) -> ProjectManifest:
    return _manifest(mode=ProjectMode(dimension="3d", layout=layout), **kw)


def test_3d_processing_preview_export_blocked() -> None:
    infos = compute_stage_statuses(_manifest_3d(), has_run_results=True)
    for page in (PROC, PREVIEW, EXPORT):
        assert infos[page].status == "blocked"
        assert infos[page].message == MODE_3D_BLOCK_REASON
        assert MODE_3D_BLOCK_REASON == "Pair and fuse a top and a side session first"


def _paired_3d(fusion=None) -> ProjectManifest:
    return _manifest_3d(
        sessions=[_ref("t1", view_role="top"), _ref("s1", view_role="side")],
        view_pairs=[ViewPair(top_session_id="t1", side_session_id="s1", fusion=fusion)],
    )


def test_3d_pair_without_fusion_settings_still_blocks() -> None:
    infos = compute_stage_statuses(_paired_3d(), has_run_results=True)
    for page in (PROC, PREVIEW, EXPORT):
        assert (infos[page].status, infos[page].message) == ("blocked", MODE_3D_BLOCK_REASON)


def test_3d_pair_with_fusion_settings_unblocks_the_result_pages() -> None:
    fusion = FusionSettings(surface_row=10, floor_row=110, tank_height_cm=20)
    st = _status(_paired_3d(fusion))
    assert st[PROC] == st[PREVIEW] == st[EXPORT] == "empty"
    st = _status(_paired_3d(fusion), has_run=True)
    assert st[PROC] == st[PREVIEW] == "valid"


def test_3d_summaries_follow_the_cheap_check() -> None:
    from ui.store.stage_status import stage_summaries

    fusion = FusionSettings(surface_row=10, floor_row=110, tank_height_cm=20)
    blocked = stage_summaries(_paired_3d(), has_run_results=False)
    assert blocked[7] == blocked[8] == "Fuse a pair first"
    ready = stage_summaries(_paired_3d(fusion), has_run_results=False)
    assert (ready[7], ready[8]) == ("Not run", "Needs a run")
    ran = stage_summaries(_paired_3d(fusion), has_run_results=True)
    assert (ran[7], ran[8]) == ("Ran · 1 pair", "Results ready")


def test_2d_stage_statuses_unchanged() -> None:
    st = _status(_manifest())
    assert st[PROC] == st[PREVIEW] == st[EXPORT] == "empty"
    assert _status(_manifest(), has_run=True)[PROC] == "valid"


def test_3d_sessions_status_with_layout_is_normal() -> None:
    assert _status(_manifest_3d())[SESSIONS] == "empty"


def test_blocked_sessions_message_constant() -> None:
    assert SESSIONS_NEEDS_LAYOUT == "Choose a 3-D layout"
    mode = ProjectMode.model_construct(dimension="3d", layout=None)
    m = _manifest().model_copy(update={"mode": mode})
    info = compute_stage_statuses(m, has_run_results=False)[SESSIONS]
    assert (info.status, info.message) == ("blocked", SESSIONS_NEEDS_LAYOUT)


def test_3d_stage_summaries_ask_for_a_fused_pair() -> None:
    from ui.store.stage_status import stage_summaries

    out = stage_summaries(_manifest_3d(), has_run_results=False)
    assert out[-2:] == ["Fuse a pair first", "Fuse a pair first"]


# ── Views page ───────────────────────────────────────────────────────────────


_FUSION = FusionSettings(surface_row=10.0, floor_row=110.0, tank_height_cm=20.0)


def _views(manifest) -> object:
    return compute_stage_statuses(manifest, has_run_results=False)[VIEWS]


def _vref(sid, role, **kw) -> SessionRef:
    return _ref(sid, view_role=role, **kw)


def test_eleven_entries_and_views_name() -> None:
    from ui.store.stage_status import PAGE_NAMES, stage_summaries

    assert len(compute_stage_statuses(_manifest(), has_run_results=False)) == 11
    assert len(compute_stage_statuses(None, has_run_results=False)) == 11
    assert len(PAGE_NAMES) == 10
    assert len(stage_summaries(_manifest(), has_run_results=False)) == 9


def test_views_empty_for_2d_and_no_project() -> None:
    assert _views(_manifest(sessions=[_ref()])).status == "empty"
    assert compute_stage_statuses(None, has_run_results=False)[VIEWS].status == "empty"


def test_views_3d_without_sessions() -> None:
    info = _views(_manifest_3d())
    assert (info.status, info.message) == ("empty", "Add sessions first.")


def test_views_3d_session_without_role() -> None:
    info = _views(_manifest_3d(sessions=[_vref("t", "top"), _ref("x")]))
    assert (info.status, info.message) == (
        "empty",
        "Choose a view (top or side) for every session.",
    )


def test_views_unpaired_session_warns() -> None:
    info = _views(_manifest_3d(sessions=[_vref("t", "top"), _vref("s", "side")]))
    assert info.status == "warning"
    assert "Session t " in info.message


def test_views_pair_without_matching_warns() -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s")],
    )
    assert _views(m).status == "warning"


def test_views_identity_free_pair_warns() -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top", track_wo_identities=True), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s", same_ids=True)],
    )
    info = _views(m)
    assert info.status == "warning"
    assert "identit" in info.message


@pytest.mark.parametrize(
    "kw", [{"same_ids": True, "fish_map": {"0": "0"}}, {"fish_map": {"0": "1"}}]
)
def test_views_matched_pair_is_valid(kw) -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s", fusion=_FUSION, **kw)],
    )
    assert _views(m).status == "valid"


@pytest.mark.parametrize(
    "kw", [{"same_ids": True, "fish_map": {"0": "0"}}, {"fish_map": {"0": "1"}}]
)
def test_views_matched_pair_without_fusion_settings_warns(kw) -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s", **kw)],
    )
    info = _views(m)
    assert info.status == "warning"
    assert "fusion setup needed" in info.message.lower()
    assert "t / s" in info.message


def test_views_unmatched_pair_is_reported_before_fusion_setup() -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s")],
    )
    assert _views(m).message == "Match the fish of t / s."


def test_views_ticked_pair_with_empty_map_needs_matching() -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s", same_ids=True)],
    )
    info = _views(m)
    assert (info.status, info.message) == ("warning", "Match the fish of t / s.")


def test_views_identity_free_reported_before_missing_map() -> None:
    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side", track_wo_identities=True)],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s")],
    )
    assert _views(m).message == "Session s has no stable identities."


def test_views_never_blocks_next() -> None:
    cases = [
        _manifest(),
        _manifest_3d(),
        _manifest_3d(sessions=[_ref("x")]),
        _manifest_3d(sessions=[_vref("t", "top"), _vref("s", "side")]),
        _manifest_3d(
            sessions=[_vref("t", "top"), _vref("s", "side")],
            view_pairs=[ViewPair(top_session_id="t", side_session_id="s", same_ids=True)],
        ),
    ]
    for m in cases:
        assert next_blocker(compute_stage_statuses(m, has_run_results=False), VIEWS) is None


def test_next_blocker_for_a_forced_views_status_does_not_raise() -> None:
    from ui.store.stage_status import StageInfo

    base = compute_stage_statuses(_manifest(), has_run_results=False)
    for status in ("empty", "valid", "warning", "blocked"):
        statuses = [*base[:VIEWS], StageInfo(status)]
        result = next_blocker(statuses, VIEWS)
        assert result is None or status == "blocked"


# ── the sidebar Sessions row ────────────────────────────────────────────────


def _row(manifest):
    from ui.store.stage_status import sessions_row

    return sessions_row(compute_stage_statuses(manifest, has_run_results=False), manifest)


def test_sessions_row_2d_is_the_sessions_status() -> None:
    m = _manifest(sessions=[_ref()])
    assert _row(m) == compute_stage_statuses(m, has_run_results=False)[SESSIONS]
    assert _row(None) == compute_stage_statuses(None, has_run_results=False)[SESSIONS]


@pytest.mark.parametrize(
    ("sessions", "pairs", "expected"),
    [
        ([_vref("t", "top"), _vref("s", "side")], [], "warning"),  # valid + warning
        ([_vref("t", "top"), _ref("x")], [], "empty"),  # valid + empty
        (
            [_vref("t", "top"), _vref("s", "side")],
            [ViewPair(top_session_id="t", side_session_id="s", fish_map={"0": "0"})],
            "warning",  # fusion setup needed
        ),
        (
            [_vref("t", "top"), _vref("s", "side")],
            [
                ViewPair(
                    top_session_id="t", side_session_id="s", fish_map={"0": "0"}, fusion=_FUSION
                )
            ],
            "valid",
        ),
        (
            [_vref("t", "top", track_wo_identities=True), _ref("x")],
            [],
            "warning",  # warning + empty
        ),
    ],
)
def test_sessions_row_3d_is_the_worse_status(sessions, pairs, expected) -> None:
    m = _manifest_3d(sessions=sessions, view_pairs=pairs)
    row = _row(m)
    assert row.status == expected
    views = compute_stage_statuses(m, has_run_results=False)[VIEWS]
    assert f"Views: {views.message}" in row.message


def test_sessions_row_3d_blocked_layout_stays_blocked() -> None:
    mode = ProjectMode.model_construct(dimension="3d", layout=None)
    m = _manifest().model_copy(update={"mode": mode})
    assert _row(m).status == "blocked"


def test_3d_sessions_summary_counts_pairs() -> None:
    from ui.store.stage_status import stage_summaries

    m = _manifest_3d(
        sessions=[_vref("t", "top"), _vref("s", "side")],
        view_pairs=[ViewPair(top_session_id="t", side_session_id="s")],
    )
    assert stage_summaries(m, has_run_results=False)[1] == "2 sessions · 1 pair"
    assert stage_summaries(_manifest(sessions=[_ref()]), has_run_results=False)[1] == "1 session"


def test_a_3d_project_never_needs_a_zone_water_column() -> None:
    from track2data.core.models import SceneConfig

    m = _manifest_3d(
        scene=SceneConfig(camera_view="side"), metrics=MetricSelection(individual=["IL-15"])
    )
    info = compute_stage_statuses(m, has_run_results=False)[ZONES]
    assert "waterline" not in info.message and "IL-15" not in info.message
