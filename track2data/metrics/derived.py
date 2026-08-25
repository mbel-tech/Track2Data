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

import logging
from typing import Any

import numpy as np

from track2data.core.models import PreprocessedSession, ZoneSet
from track2data.zones.geometry import roi_area_px2

logger = logging.getLogger(__name__)


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


def _bbox_centre_and_inscribed_radius(
    vertices: list[tuple[float, float]],
) -> tuple[list[float], float]:
    """Bounding-box midpoint, and the largest radius fitting inside it.

    Inscribing -- ``min`` of the two half-extents -- rather than
    circumscribing. Circumscribing would put the default
    ``inner_radius_fraction=0.5`` boundary out at the walls of a
    non-square arena, scoring wall-hugging animals as centre-dwelling
    and inverting the thigmotaxis reading IL-3 exists to produce.
    """
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    centre = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]
    radius = min(max(xs) - min(xs), max(ys) - min(ys)) / 2.0
    return centre, radius


def _arena_geometry_by_name(
    main_rois: list,
) -> dict[str, tuple[list[float], float]]:
    """Centre and radius per *named* main arena. Several ROIs sharing a
    name describe one arena, so their vertices pool into one box."""
    vertices_by_name: dict[str, list[tuple[float, float]]] = {}
    for roi in main_rois:
        vertices_by_name.setdefault(roi.name, []).extend(roi.vertices)
    return {
        name: _bbox_centre_and_inscribed_radius(vertices)
        for name, vertices in vertices_by_name.items()
    }


def _dominant_zone_per_animal(
    main_zone: np.ndarray | None, n_animals: int, known: set[str]
) -> list[str | None]:
    """The arena each animal spent most of its tracked frames in.

    Modal rather than first-seen: a few stray frames across a boundary
    must not decide which arena an animal belongs to. Returns ``None``
    for an animal never seen inside any known main arena.
    """
    result: list[str | None] = [None] * n_animals
    if main_zone is None:
        return result

    for k in range(min(n_animals, main_zone.shape[1])):
        counts: dict[str, int] = {}
        for value in main_zone[:, k]:
            name = str(value)
            if name in known:
                counts[name] = counts.get(name, 0) + 1
        if counts:
            result[k] = max(counts, key=lambda name: (counts[name], name))
    return result


def _derive_il3(psess: PreprocessedSession, zone_set: ZoneSet) -> dict[str, Any]:
    """IL-3 (centre_distance)'s centre/arena_radius, per animal.

    Each animal is measured from the centre of the arena *it* occupies,
    not from one centre shared by the session. Under the
    ``exclusive_rois`` layout -- several separate main arenas, which the
    pipeline explicitly supports -- a single shared centre sits in the
    empty gap between arenas, a point no animal ever visits, so every
    distance is measured from dead space. Which arena an animal is in
    comes from ``psess.main_zone``, the zone assignment ``api.py``
    already computes before metrics run.

    Emits both shapes:

    ``centres`` / ``arena_radii``
        One entry per animal. IL-3 prefers these.
    ``centre`` / ``arena_radius``
        The session-level fallback: the largest main arena, or the video
        frame when no zones are defined. Used for an animal never seen
        inside any arena, and kept as the documented scalar interface.

    Only additive ("+") polygons contribute; a subtractive exclusion
    hole doesn't move an arena's overall centre or extent.
    """
    main_rois = [roi for roi in zone_set.rois if roi.level == "main" and roi.sign == "+"]
    n_animals = psess.session.n_animals

    if main_rois:
        geometry = _arena_geometry_by_name(main_rois)
        largest = max(main_rois, key=roi_area_px2).name
        centre, radius = geometry[largest]
    else:
        video = psess.session.video
        geometry = {}
        centre = [video.width_px / 2.0, video.height_px / 2.0]
        radius = min(video.width_px, video.height_px) / 2.0

    assigned = _dominant_zone_per_animal(psess.main_zone, n_animals, set(geometry))

    centres: list[list[float]] = []
    radii: list[float] = []
    for name in assigned:
        if name is None:
            centres.append(list(centre))
            radii.append(radius)
        else:
            arena_centre, arena_radius = geometry[name]
            centres.append(list(arena_centre))
            radii.append(arena_radius)

    if len(geometry) > 1:
        unplaced = sum(1 for name in assigned if name is None)
        logger.info(
            "IL-3: %d main arenas (%s); each animal is measured from the one it "
            "occupies.%s",
            len(geometry),
            ", ".join(sorted(geometry)),
            (
                f" {unplaced} animal(s) were never inside one and fall back to the "
                f"largest ('{largest}')."
                if unplaced
                else ""
            ),
        )

    return {
        "centre": centre,
        "arena_radius": radius,
        "centres": centres,
        "arena_radii": radii,
    }


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
