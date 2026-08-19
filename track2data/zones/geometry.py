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
    """
    n_frames, n_animals, _ = xy.shape

    main_zone: np.ndarray = np.empty((n_frames, n_animals), dtype=object)
    sec_zone: np.ndarray = np.empty((n_frames, n_animals), dtype=object)
    main_zone[:] = ""
    sec_zone[:] = ""

    if not zone_set.rois:
        return main_zone, sec_zone

    # Build Polygon objects once — expensive, do not repeat inside the loop.
    polygons: list[tuple[str, str, Polygon]] = []
    for roi in zone_set.rois:
        polygons.append((roi.name, roi.level, Polygon(roi.vertices)))

    # Warn once if overlapping ROIs are detected.
    overlaps = detect_overlaps(zone_set)
    if overlaps:
        warnings.warn(
            f"Overlapping ROI pairs detected (first match wins): {overlaps}",
            UserWarning,
            stacklevel=2,
        )

    main_polys = [(name, poly) for name, level, poly in polygons if level == "main"]
    sec_polys = [(name, poly) for name, level, poly in polygons if level == "secondary"]

    for f in range(n_frames):
        for a in range(n_animals):
            x, y = float(xy[f, a, 0]), float(xy[f, a, 1])
            if np.isnan(x) or np.isnan(y):
                continue  # already initialised to ""
            pt = Point(x, y)
            for name, poly in main_polys:
                if pt.within(poly):
                    main_zone[f, a] = name
                    break
            for name, poly in sec_polys:
                if pt.within(poly):
                    sec_zone[f, a] = name
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

    Parameters
    ----------
    zone_set:
        The set of ROIs to check for pairwise overlaps.

    Returns
    -------
    list of (str, str)
        Each element is a ``(name_a, name_b)`` pair where the two polygons
        share interior area.  Order within each pair follows the order in
        ``zone_set.rois``.
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
            intersection = poly_a.intersection(poly_b)
            if not intersection.is_empty and intersection.area > 0:
                overlapping.append((name_a, name_b))

    return overlapping
