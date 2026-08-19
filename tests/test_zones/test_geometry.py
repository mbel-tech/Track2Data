"""Tests for track2data.zones.geometry."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import ROI, ZoneSet
from track2data.zones.geometry import assign_zones, detect_overlaps, roi_area_px2

# ── helpers ────────────────────────────────────────────────────────────────────


def make_square_roi(
    name: str, x0: float, y0: float, x1: float, y1: float, level: str = "main"
) -> ROI:
    return ROI(name=name, level=level, vertices=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


# ── assign_zones: basic point-in-polygon ──────────────────────────────────────


def test_point_inside_zone() -> None:
    roi = make_square_roi("zone_A", 0, 0, 100, 100)
    zone_set = ZoneSet(rois=[roi])
    xy = np.array([[[50.0, 50.0]]])  # (1, 1, 2)
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == "zone_A"
    assert sec[0, 0] == ""


def test_point_outside_all_zones() -> None:
    roi = make_square_roi("zone_A", 0, 0, 100, 100)
    zone_set = ZoneSet(rois=[roi])
    xy = np.array([[[200.0, 200.0]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == ""
    assert sec[0, 0] == ""


def test_nan_position_gives_empty_zone() -> None:
    roi = make_square_roi("zone_A", 0, 0, 100, 100)
    zone_set = ZoneSet(rois=[roi])
    xy = np.array([[[np.nan, np.nan]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == ""
    assert sec[0, 0] == ""


def test_secondary_zone() -> None:
    roi = make_square_roi("zone_B", 0, 0, 50, 50, level="secondary")
    zone_set = ZoneSet(rois=[roi])
    xy = np.array([[[25.0, 25.0]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == ""
    assert sec[0, 0] == "zone_B"


# ── assign_zones: multiple animals / frames ───────────────────────────────────


def test_multiple_animals_different_zones() -> None:
    roi_a = make_square_roi("zone_A", 0, 0, 100, 100, level="main")
    roi_b = make_square_roi("zone_B", 200, 200, 300, 300, level="main")
    zone_set = ZoneSet(rois=[roi_a, roi_b])
    # frame 0: animal 0 in A, animal 1 in B
    xy = np.array([[[50.0, 50.0], [250.0, 250.0]]])  # (1, 2, 2)
    main, _sec = assign_zones(xy, zone_set)
    assert main[0, 0] == "zone_A"
    assert main[0, 1] == "zone_B"


def test_multiple_frames() -> None:
    roi = make_square_roi("zone_A", 0, 0, 100, 100, level="main")
    zone_set = ZoneSet(rois=[roi])
    # 3 frames, 1 animal: inside, outside, inside
    xy = np.array([[[50.0, 50.0]], [[200.0, 200.0]], [[10.0, 10.0]]])  # (3, 1, 2)
    main, _sec = assign_zones(xy, zone_set)
    assert main[0, 0] == "zone_A"
    assert main[1, 0] == ""
    assert main[2, 0] == "zone_A"


def test_nan_x_only_gives_empty_zone() -> None:
    """Partial NaN (only x coord is NaN) should also yield empty zones."""
    roi = make_square_roi("zone_A", 0, 0, 100, 100)
    zone_set = ZoneSet(rois=[roi])
    xy = np.array([[[np.nan, 50.0]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == ""
    assert sec[0, 0] == ""


def test_first_match_wins_for_overlapping_rois() -> None:
    """When ROIs overlap, the first one in order wins."""
    roi_first = make_square_roi("first", 0, 0, 100, 100, level="main")
    roi_second = make_square_roi("second", 50, 50, 150, 150, level="main")
    zone_set = ZoneSet(rois=[roi_first, roi_second])
    # Point at (75, 75) is inside both
    xy = np.array([[[75.0, 75.0]]])
    main, _sec = assign_zones(xy, zone_set)
    assert main[0, 0] == "first"


def test_main_and_secondary_zones_independent() -> None:
    """A point can match one main zone and one secondary zone simultaneously."""
    roi_main = make_square_roi("M", 0, 0, 200, 200, level="main")
    roi_sec = make_square_roi("S", 0, 0, 200, 200, level="secondary")
    zone_set = ZoneSet(rois=[roi_main, roi_sec])
    xy = np.array([[[100.0, 100.0]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == "M"
    assert sec[0, 0] == "S"


def test_return_shapes() -> None:
    roi = make_square_roi("zone_A", 0, 0, 100, 100)
    zone_set = ZoneSet(rois=[roi])
    n_frames, n_animals = 5, 3
    xy = np.ones((n_frames, n_animals, 2)) * 50.0
    main, sec = assign_zones(xy, zone_set)
    assert main.shape == (n_frames, n_animals)
    assert sec.shape == (n_frames, n_animals)
    assert main.dtype == object
    assert sec.dtype == object


def test_empty_zone_set() -> None:
    zone_set = ZoneSet(rois=[])
    xy = np.array([[[50.0, 50.0]]])
    main, sec = assign_zones(xy, zone_set)
    assert main[0, 0] == ""
    assert sec[0, 0] == ""


# ── roi_area_px2 ──────────────────────────────────────────────────────────────


def test_roi_area_px2() -> None:
    roi = make_square_roi("sq", 0, 0, 10, 10)
    assert roi_area_px2(roi) == pytest.approx(100.0)


def test_roi_area_px2_rectangle() -> None:
    roi = make_square_roi("rect", 0, 0, 20, 5)
    assert roi_area_px2(roi) == pytest.approx(100.0)


def test_roi_area_px2_triangle() -> None:
    roi = ROI(name="tri", level="main", vertices=[(0, 0), (10, 0), (5, 10)])
    assert roi_area_px2(roi) == pytest.approx(50.0)


# ── detect_overlaps ───────────────────────────────────────────────────────────


def test_detect_overlaps_finds_overlap() -> None:
    roi_a = make_square_roi("A", 0, 0, 100, 100)
    roi_b = make_square_roi("B", 50, 50, 150, 150)
    zone_set = ZoneSet(rois=[roi_a, roi_b])
    overlaps = detect_overlaps(zone_set)
    assert ("A", "B") in overlaps or ("B", "A") in overlaps


def test_detect_overlaps_no_overlap() -> None:
    roi_a = make_square_roi("A", 0, 0, 100, 100)
    roi_b = make_square_roi("B", 200, 200, 300, 300)
    zone_set = ZoneSet(rois=[roi_a, roi_b])
    overlaps = detect_overlaps(zone_set)
    assert len(overlaps) == 0


def test_detect_overlaps_touching_edges_no_overlap() -> None:
    """Touching edges (shared boundary) should not be counted as overlap."""
    roi_a = make_square_roi("A", 0, 0, 100, 100)
    roi_b = make_square_roi("B", 100, 0, 200, 100)
    zone_set = ZoneSet(rois=[roi_a, roi_b])
    overlaps = detect_overlaps(zone_set)
    assert len(overlaps) == 0
