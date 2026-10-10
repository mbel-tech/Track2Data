"""Per-page completion status for the wizard, and the rules that gate "Next".

Pure (no Qt): ``compute_stage_statuses`` maps a manifest to one ``StageInfo``
per stacked page, ``next_blocker`` says why Next must stay disabled.

Status meanings: ``valid`` (✓) the page is complete; ``warning`` (⚠) usable
but worth a look; ``empty`` (○) nothing entered yet; ``blocked`` (✗) cannot
proceed until fixed. Only *required* pages block Next when empty -- zones,
metadata, export targets and the result pages are optional or produced by
running the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from track2data.core.models import MODE_3D_BLOCK_REASON, ProjectManifest
from track2data.metrics import get as _get_metric
from track2data.metrics.availability import view_dependent_metrics
from track2data.zones.extent import water_column
from ui.store.screen_flow import VIEWS_PAGE as _VIEWS

Status = Literal["empty", "valid", "warning", "blocked"]

SESSIONS_NEEDS_LAYOUT = "Choose a 3-D layout"


def _missing_water_column(manifest: ProjectManifest) -> list[str]:
    """The selected metrics that need a water column the zones do not give.

    Empty unless the project declared a side view, something selected is only meaningful for
    one, and no main-level zone outlines the water.
    """
    if manifest.mode.dimension == "3d" or manifest.scene.camera_view != "side":
        return []  # a 3-D project takes its depth from the fusion, not from zones
    sel = manifest.metrics
    needing = view_dependent_metrics(
        [*sel.individual, *sel.group, *sel.zone], "side", _get_metric
    )
    if needing and water_column(manifest.zones).top_px is None:
        return needing
    return []


PAGE_NAMES = [
    "Project", "Sessions", "Calibration", "Zones", "Metadata",
    "Preprocessing", "Metrics", "Processing", "Preview", "Export",
]
(
    _PROJECT, _SESSIONS, _CALIB, _ZONES, _META, _PREP, _METRICS, _PROC, _PREVIEW, _EXPORT
) = range(10)

#: Views is a sub-page of the Sessions stage, so it is not a guide chapter (not in PAGE_NAMES).
VIEWS_PAGE_NAME = "Views"

#: Pages whose "empty" state stops Next (the pipeline cannot run without them).
REQUIRED_PAGES = frozenset({_PROJECT, _SESSIONS, _METRICS})


@dataclass(frozen=True)
class StageInfo:
    status: Status
    message: str = ""


def compute_stage_statuses(
    manifest: ProjectManifest | None, *, has_run_results: bool
) -> list[StageInfo]:
    if manifest is None:
        blocked = StageInfo("blocked", "Create or open a project first.")
        first = StageInfo("empty", "Create or open a project.")
        return [first] + [blocked] * 9 + [StageInfo("empty")]

    out: list[StageInfo] = [StageInfo("valid", manifest.project_name)] + [
        StageInfo("empty")
    ] * 10

    # Sessions
    sessions = manifest.sessions
    free = [s.session_id for s in sessions if s.is_identity_free()]
    mode = manifest.mode
    if mode.dimension == "3d" and mode.layout is None:
        out[_SESSIONS] = StageInfo("blocked", SESSIONS_NEEDS_LAYOUT)
    elif not sessions:
        out[_SESSIONS] = StageInfo("empty", "Add at least one session folder.")
    elif free:
        out[_SESSIONS] = StageInfo(
            "warning", f"{len(free)} of {len(sessions)} session(s) tracked without identities."
        )
    else:
        out[_SESSIONS] = StageInfo("valid", f"{len(sessions)} session(s).")

    # Calibration
    cal = manifest.calibration
    if cal.mode == "scalar" and not (cal.px_per_cm and cal.px_per_cm > 0):
        out[_CALIB] = StageInfo("blocked", "Enter a positive pixels-per-cm value.")
    elif cal.mode == "session" and not cal.length_unit_confirmed_by_user:
        out[_CALIB] = StageInfo("blocked", "Confirm the length unit of your sessions.")
    else:
        out[_CALIB] = StageInfo("valid", f"Mode: {cal.mode}.")

    # Zones (optional)
    n_rois = len(manifest.zones.rois)
    out[_ZONES] = (
        StageInfo("valid", f"{n_rois} zone(s).") if n_rois else StageInfo("empty", "Optional.")
    )
    missing = _missing_water_column(manifest)
    if missing:
        out[_ZONES] = StageInfo(
            "warning",
            "Side view: draw the main zone from the waterline to the floor, "
            f"so {', '.join(missing)} can measure depth.",
        )

    # Metadata (optional, but a chosen file needs a mapping)
    if manifest.metadata_source is None:
        out[_META] = StageInfo("empty", "Optional.")
    elif manifest.mapping is None or not manifest.mapping.rules:
        out[_META] = StageInfo("warning", "Map the CSV columns to fields.")
    else:
        out[_META] = StageInfo("valid", f"{len(manifest.mapping.rules)} column(s) mapped.")

    # Preprocessing
    if manifest.preprocess.identity_switch.enabled:
        out[_PREP] = StageInfo("warning", "Identity-switch correction is on (experimental).")
    else:
        out[_PREP] = StageInfo("valid")

    # Metrics
    sel = manifest.metrics
    n_metrics = len(sel.individual) + len(sel.group) + len(sel.zone)
    out[_METRICS] = (
        StageInfo("valid", f"{n_metrics} metric(s).")
        if n_metrics
        else StageInfo("empty", "Select at least one metric.")
    )

    # Results
    ran = StageInfo("valid", "Pipeline has run.") if has_run_results else StageInfo("empty")
    out[_PROC] = out[_PREVIEW] = ran
    out[_EXPORT] = (
        StageInfo("valid", f"{len(manifest.export_targets)} format(s).")
        if manifest.export_targets
        else StageInfo("empty")
    )
    if mode.dimension == "3d" and not has_fusion_settings(manifest):
        # Nothing can run until a pair is set up for fusion. This is the cheap manifest-only
        # check; whether the pairs really fuse is the Processing setup check's job.
        out[_PROC] = out[_PREVIEW] = out[_EXPORT] = StageInfo("blocked", MODE_3D_BLOCK_REASON)
    out[_VIEWS] = _views_status(manifest)
    return out


def has_fusion_settings(manifest: ProjectManifest) -> bool:
    """At least one pair of the 3-D project has fusion settings (it may still fail to fuse)."""
    return any(p.fusion is not None for p in manifest.view_pairs)


def _views_status(manifest: ProjectManifest) -> StageInfo:
    """Status of the Views page (3-D only; manifest data only, never blocking)."""
    if manifest.mode.dimension != "3d":
        return StageInfo("empty")
    sessions = manifest.sessions
    if not sessions:
        return StageInfo("empty", "Add sessions first.")
    if any(s.view_role is None for s in sessions):
        return StageInfo("empty", "Choose a view (top or side) for every session.")
    by_id = {s.session_id: s for s in sessions}
    paired = {sid for p in manifest.view_pairs for sid in (p.top_session_id, p.side_session_id)}
    for s in sessions:
        if s.session_id not in paired:
            return StageInfo("warning", f"Session {s.session_id} is not paired.")
    for p in manifest.view_pairs:
        # Problems first, then matching -- the same order as the page's pair status.
        for sid in (p.top_session_id, p.side_session_id):
            # A dangling pair id is skipped: this status uses manifest data only.
            ref = by_id.get(sid)
            if ref is not None and ref.is_identity_free():
                return StageInfo("warning", f"Session {sid} has no stable identities.")
        # fish_map is the authority: a pair is matched iff its map is non-empty.
        if not p.fish_map:
            name = f"{p.top_session_id} / {p.side_session_id}"
            return StageInfo("warning", f"Match the fish of {name}.")
    # Matched pairs still need their depth set up; a hint only, never blocking.
    for p in manifest.view_pairs:
        if p.fusion is None:
            name = f"{p.top_session_id} / {p.side_session_id}"
            return StageInfo("warning", f"Fusion setup needed for {name}.")
    return StageInfo("valid", f"{len(manifest.view_pairs)} pair(s) matched.")


#: How bad each status is, for combining two (higher is worse).
_SEVERITY: dict[str, int] = {"valid": 0, "empty": 1, "warning": 2, "blocked": 3}


def sessions_row(statuses: list[StageInfo], manifest: ProjectManifest | None) -> StageInfo:
    """What the sidebar's Sessions row shows.

    In a 3-D project the Views page sits under Sessions, so the row shows the worse of
    the two statuses and the Views message is added to its tooltip. Next is unaffected:
    it still follows each page's own status.
    """
    sessions = statuses[_SESSIONS]
    if manifest is None or manifest.mode.dimension != "3d":
        return sessions
    views = statuses[_VIEWS]
    status = max(sessions.status, views.status, key=_SEVERITY.__getitem__)
    parts = [sessions.message, f"{VIEWS_PAGE_NAME}: {views.message}" if views.message else ""]
    return StageInfo(status, "\n".join(p for p in parts if p))


def next_blocker(statuses: list[StageInfo], page: int) -> str | None:
    """Why leaving *page* forward is not allowed, or None when it is."""
    if not (0 <= page < len(statuses)):
        return None
    name = VIEWS_PAGE_NAME if page == _VIEWS else PAGE_NAMES[page]
    info = statuses[page]
    if info.status == "blocked":
        return info.message or f"Fix the {name} settings first."
    if info.status == "empty" and page in REQUIRED_PAGES:
        return info.message or f"Complete the {name} step first."
    return None


def stage_summaries(
    manifest: ProjectManifest | None, *, has_run_results: bool, n_run_units: int | None = None
) -> list[str]:
    """One short live line per sidebar stage (Project … Preview & Export).

    *n_run_units* is how many units the shown results ran (a 3-D run counts its pairs)."""
    if manifest is None:
        return ["Unnamed", "No sessions", "", "", "", "", "", "Not run", "Needs a run"]
    cal = manifest.calibration
    cal_text = {"scalar": "Scalar", "session": "From tracker"}.get(cal.mode, "Body length")
    if cal.mode == "scalar" and cal.px_per_cm:
        cal_text += f" · {cal.px_per_cm:g} px/cm"
    view_text = {"top": "Top-down", "side": "Side view"}.get(manifest.scene.camera_view)
    if view_text:
        cal_text += f" · {view_text}"
    n_zones = len(manifest.zones.rois)
    sel = manifest.metrics
    n_metrics = len(sel.individual) + len(sel.group) + len(sel.zone)
    n_sessions = len(manifest.sessions)
    sessions_text = (
        f"{n_sessions} session{'s' if n_sessions != 1 else ''}" if n_sessions else "No sessions"
    )
    if manifest.mode.dimension == "3d" and n_sessions:
        n_pairs = len(manifest.view_pairs)
        sessions_text += f" · {n_pairs} pair{'s' if n_pairs != 1 else ''}"
    if manifest.metadata_source is None:
        meta = "Not set"
    elif manifest.mapping is None or not manifest.mapping.rules:
        meta = "Map columns"
    else:
        meta = f"{len(manifest.mapping.rules)} columns mapped"
    if manifest.mode.dimension == "3d" and not has_fusion_settings(manifest):
        run_text, preview_text = "Fuse a pair first", "Fuse a pair first"
    elif manifest.mode.dimension == "3d":
        if not has_run_results:
            run_text = "Not run"
        elif n_run_units is None:
            run_text = "Ran"
        else:
            run_text = f"Ran · {n_run_units} pair{'s' if n_run_units != 1 else ''}"
        preview_text = "Results ready" if has_run_results else "Needs a run"
    else:
        run_text = f"Ran · {n_sessions} sessions" if has_run_results else "Not run"
        preview_text = "Results ready" if has_run_results else "Needs a run"
    return [
        manifest.project_name or "Unnamed",
        sessions_text,
        cal_text,
        "Draw the water column"
        if _missing_water_column(manifest)
        else (f"{n_zones} zone{'s' if n_zones != 1 else ''}" if n_zones else "No zones"),
        meta,
        "Identity switch on" if manifest.preprocess.identity_switch.enabled else "Defaults",
        f"{n_metrics} selected" if n_metrics else "None selected",
        run_text,
        preview_text,
    ]
