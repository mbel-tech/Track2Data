"""
Per-session derived parameter values for metrics whose configuration
cannot be user-typed -- it is a property of the session's own tracked
arena (IL-3's centre/radius, Z-2's zone areas), not a scientific choice
a researcher enters. See ``MetricParameter.derived`` in
``track2data/metrics/base.py``.

Kept separate from ``api.py``'s config-assembly plumbing so each
metric's derivation logic is testable in isolation, and the set of
"which metric derives what" is discoverable in one place rather than
scattered through the pipeline.
"""

from __future__ import annotations

from typing import Any

from track2data.core.models import PreprocessedSession, ZoneSet
from track2data.zones.geometry import roi_area_px2


def derive_metric_params(
    metric_id: str, psess: PreprocessedSession, zone_set: ZoneSet
) -> dict[str, Any]:
    """Return the derived (never user-typed) cfg values for *metric_id*
    given *psess* and the project's *zone_set*, or ``{}`` if it
    declares none. Called from ``api.py`` before every ``compute()``,
    so this must be cheap and side-effect-free.
    """
    if metric_id == "IL-3":
        return _derive_il3(psess, zone_set)
    if metric_id == "Z-2":
        return _derive_z2(zone_set)
    return {}


def _derive_il3(psess: PreprocessedSession, zone_set: ZoneSet) -> dict[str, Any]:
    """IL-3 (centre_distance)'s centre/arena_radius: the centroid and
    half-extent of the project's "main"-level zone, if one is defined
    -- else the video frame's own centre and half-shorter-dimension.
    Only additive ("+") polygons contribute; a subtractive exclusion
    hole doesn't move the arena's overall centre or extent."""
    main_rois = [roi for roi in zone_set.rois if roi.level == "main" and roi.sign == "+"]
    if main_rois:
        vertices = [v for roi in main_rois for v in roi.vertices]
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        centre = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]
        radius = max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0
    else:
        video = psess.session.video
        centre = [video.width_px / 2.0, video.height_px / 2.0]
        radius = min(video.width_px, video.height_px) / 2.0
    return {"centre": centre, "arena_radius": radius}


def _derive_z2(zone_set: ZoneSet) -> dict[str, Any]:
    """Z-2 (area_corrected_occupancy)'s roi_areas/total_arena_area,
    via zones.geometry.roi_area_px2 -- fully tested, previously with
    zero production callers. Signed polygons combine per name exactly
    as zones.geometry.assign_zones does: "+" adds, "-" subtracts (an
    exclusion hole). total_arena_area sums "main"-level zone areas
    (the overall tracked arena); falls back to every zone's area when
    no zone is marked "main"."""
    if not zone_set.rois:
        return {}

    roi_areas: dict[str, float] = {}
    for roi in zone_set.rois:
        signed_area = roi_area_px2(roi) if roi.sign == "+" else -roi_area_px2(roi)
        roi_areas[roi.name] = roi_areas.get(roi.name, 0.0) + signed_area

    main_names = {roi.name for roi in zone_set.rois if roi.level == "main"}
    names_for_total = main_names if main_names else set(roi_areas)
    total_arena_area = sum(roi_areas[name] for name in names_for_total)

    return {"roi_areas": roi_areas, "total_arena_area": total_arena_area}
