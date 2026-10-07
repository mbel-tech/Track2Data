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

from track2data.core.models import ProjectManifest

Status = Literal["empty", "valid", "warning", "blocked"]

PAGE_NAMES = [
    "Project", "Sessions", "Calibration", "Zones", "Metadata",
    "Preprocessing", "Metrics", "Processing", "Preview", "Export",
]
_PROJECT, _SESSIONS, _CALIB, _ZONES, _META, _PREP, _METRICS, _PROC, _PREVIEW, _EXPORT = range(10)

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
        return [StageInfo("empty", "Create or open a project.")] + [blocked] * 9

    out: list[StageInfo] = [StageInfo("valid", manifest.project_name)] + [
        StageInfo("empty")
    ] * 9

    # Sessions
    sessions = manifest.sessions
    free = [s.session_id for s in sessions if s.is_identity_free()]
    if not sessions:
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
    return out


def next_blocker(statuses: list[StageInfo], page: int) -> str | None:
    """Why leaving *page* forward is not allowed, or None when it is."""
    if not (0 <= page < len(statuses)):
        return None
    info = statuses[page]
    if info.status == "blocked":
        return info.message or f"Fix the {PAGE_NAMES[page]} settings first."
    if info.status == "empty" and page in REQUIRED_PAGES:
        return info.message or f"Complete the {PAGE_NAMES[page]} step first."
    return None
