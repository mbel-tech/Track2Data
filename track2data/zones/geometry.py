"""Shapely-based polygon ops: point-in-polygon, area, and overlap detection."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import numpy as np
from shapely.geometry import Point, Polygon

from track2data.core.models import ROI, ZoneSet

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── public API ────────────────────────────────────────────────────────────────


def _make_valid_polygon(vertices: list[tuple[float, float]]) -> Polygon:
    """Build a Polygon, repairing self-intersections with the standard
    buffer(0) idiom. Real idtracker.ai roi_list polygons can be invalid
    (2/10 in a real sample: a self-touching vertex) -- Polygon.covers()
    doesn't raise on an invalid geometry but its result is unreliable, so
    repair rather than risk a silently wrong containment test."""
    poly = Polygon(vertices)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _group_by_name(
    rois: list[ROI],
) -> dict[str, tuple[list[Polygon], list[Polygon]]]:
    """Group ROIs sharing a name into (additive polygons, subtractive polygons)."""
    grouped: dict[str, tuple[list[Polygon], list[Polygon]]] = {}
    for roi in rois:
        add, sub = grouped.setdefault(roi.name, ([], []))
        (add if roi.sign == "+" else sub).append(_make_valid_polygon(roi.vertices))
    return grouped


def _point_in_named_zone(
    pt: Point, additive: list[Polygon], subtractive: list[Polygon]
) -> bool:
    """A point belongs to a zone iff covered by any additive polygon and
    not covered by any subtractive one -- see ROI.sign's docstring."""
    if not any(poly.covers(pt) for poly in additive):
        return False
    return not any(poly.covers(pt) for poly in subtractive)


def assign_zones(
    xy: np.ndarray,
    zone_set: ZoneSet,
) -> tuple[np.ndarray, np.ndarray]:
    """Assign each (frame, animal) position to the first matching ROI.

    For each frame and animal, finds which zone (ROI) contains that point.
    Main zones and secondary zones are tracked independently — a point can
    match one main zone AND one secondary zone in the same frame.

    Parameters
    ----------
    xy:
        Position array of shape ``(n_frames, n_animals, 2)``, dtype float64.
        NaN values indicate missing positions and yield empty zone strings.
    zone_set:
        Collection of ROI polygons with associated levels.

    Returns
    -------
    main_zone:
        ``np.ndarray`` of shape ``(n_frames, n_animals)``, dtype object.
        Zone name string for ROIs with ``level == "main"``, or ``""`` when
        no match is found.
    sec_zone:
        ``np.ndarray`` of shape ``(n_frames, n_animals)``, dtype object.
        Zone name string for ROIs with ``level == "secondary"``, or ``""``
        when no match is found.

    Notes
    -----
    - Shapely ``Polygon`` objects are built once outside the inner loop.
    - NaN positions (any coordinate is NaN) yield ``""`` for both arrays.
    - For overlapping ROIs of the same level, the first ROI in list order wins;
      a ``UserWarning`` is emitted once if overlaps are detected.
    - Containment is boundary-inclusive (``Polygon.covers``, not
      ``within``): a point exactly on a zone's edge counts as inside it.
      A strictly-interior test would systematically undercount
      wall-following/thigmotaxis behaviour along an arena's own boundary.
    - ROIs sharing a ``name`` combine by ``sign``: a point matches that
      name only if covered by at least one ``"+"`` polygon and not
      covered by any ``"-"`` polygon of the same name (idtracker.ai's
      roi_list arena-minus-holes convention -- see ``ROI.sign``).
    """
    n_frames, n_animals, _ = xy.shape

    main_zone: np.ndarray = np.empty((n_frames, n_animals), dtype=object)
    sec_zone: np.ndarray = np.empty((n_frames, n_animals), dtype=object)
    main_zone[:] = ""
    sec_zone[:] = ""

    if not zone_set.rois:
        return main_zone, sec_zone

    # Warn once if overlapping ROIs are detected.
    overlaps = detect_overlaps(zone_set)
    if overlaps:
        warnings.warn(
            f"Overlapping ROI pairs detected (first match wins): {overlaps}",
            UserWarning,
            stacklevel=2,
        )

    main_rois = [roi for roi in zone_set.rois if roi.level == "main"]
    sec_rois = [roi for roi in zone_set.rois if roi.level == "secondary"]
    # Groups preserve first-seen name order (dict insertion order), so
    # "first match wins" for overlaps still holds.
    main_groups = _group_by_name(main_rois)
    sec_groups = _group_by_name(sec_rois)

    for f in range(n_frames):
        for a in range(n_animals):
            x, y = float(xy[f, a, 0]), float(xy[f, a, 1])
            if np.isnan(x) or np.isnan(y):
                continue  # already initialised to ""
            pt = Point(x, y)
            for zname, (add, sub) in main_groups.items():
                if _point_in_named_zone(pt, add, sub):
                    main_zone[f, a] = zname
                    break
            for zname, (add, sub) in sec_groups.items():
                if _point_in_named_zone(pt, add, sub):
                    sec_zone[f, a] = zname
                    break

    return main_zone, sec_zone


def roi_area_px2(roi: ROI) -> float:
    """Compute the area of an ROI polygon in pixels squared.

    Parameters
    ----------
    roi:
        The ROI whose polygon area to compute.

    Returns
    -------
    float
        Area in pixels squared, using the Shapely polygon area formula
        (shoelace/Gauss formula).
    """
    return float(Polygon(roi.vertices).area)


def detect_overlaps(zone_set: ZoneSet) -> list[tuple[str, str]]:
    """Return pairs of ROI names whose polygons overlap (share interior area).

    Touching edges or shared boundary points alone are not counted as overlap.
    ROIs sharing a ``name`` are never reported: an additive polygon and its
    subtractive holes are *expected* to overlap by design (``ROI.sign``) --
    that pair is not the ambiguous "which zone wins" case this function
    exists to catch.

    Parameters
    ----------
    zone_set:
        The set of ROIs to check for pairwise overlaps.

    Returns
    -------
    list of (str, str)
        Each element is a ``(name_a, name_b)`` pair, with ``name_a !=
        name_b``, where the two polygons share interior area. Order within
        each pair follows the order in ``zone_set.rois``.
    """
    rois = zone_set.rois
    if len(rois) < 2:
        return []

    polys = [(roi.name, Polygon(roi.vertices)) for roi in rois]
    overlapping: list[tuple[str, str]] = []

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            name_a, poly_a = polys[i]
            name_b, poly_b = polys[j]
            if name_a == name_b:
                continue
            try:
                intersection = poly_a.intersection(poly_b)
            except Exception:
                # Real-world hand-drawn/tracker-exported polygons can be
                # topologically invalid (self-touching vertices); overlap
                # detection is a warning aid, not a correctness gate, so
                # skip rather than let it crash zone assignment.
                logger.warning(
                    "Could not test '%s'/'%s' for overlap (invalid geometry); skipped.",
                    name_a,
                    name_b,
                )
                continue
            if not intersection.is_empty and intersection.area > 0:
                overlapping.append((name_a, name_b))

    return overlapping
