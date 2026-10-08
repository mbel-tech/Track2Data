"""The water column a side-view recording is measured against: the vertical span of the main
zones, in image rows (y grows downward, so the surface is the smaller row)."""

from __future__ import annotations

from track2data.core.models import ROI, ZoneSet
from track2data.zones.extent import water_column


def _rect(name: str, top: float, bottom: float, *, level: str = "main", sign: str = "+") -> ROI:
    return ROI(
        name=name,
        level=level,
        sign=sign,
        vertices=[(0.0, top), (100.0, top), (100.0, bottom), (0.0, bottom)],
    )


def test_one_main_zone_gives_its_rows_and_names_itself() -> None:
    wc = water_column(ZoneSet(rois=[_rect("tank", 100, 700)]))
    assert (wc.top_px, wc.bottom_px) == (100.0, 700.0)
    assert wc.source == "zone:tank"


def test_nested_main_zones_pool_to_the_outermost_rows() -> None:
    """The example project nests `centre` (275-725) inside `wall` (50-950), both 'main':
    measuring inside the inner band would squash every depth."""
    wc = water_column(ZoneSet(rois=[_rect("centre", 275, 725), _rect("wall", 50, 950)]))
    assert (wc.top_px, wc.bottom_px) == (50.0, 950.0)
    assert wc.source == "zones:centre|wall"


def test_side_by_side_tanks_share_one_vertical_span() -> None:
    wc = water_column(ZoneSet(rois=[_rect("a", 100, 600), _rect("b", 120, 640)]))
    assert (wc.top_px, wc.bottom_px) == (100.0, 640.0)


def test_secondary_level_zones_do_not_count() -> None:
    zones = ZoneSet(rois=[_rect("tank", 100, 700), _rect("deep", 0, 9999, level="secondary")])
    wc = water_column(zones)
    assert (wc.top_px, wc.bottom_px) == (100.0, 700.0)


def test_a_subtractive_hole_does_not_move_the_extent() -> None:
    zones = ZoneSet(rois=[_rect("tank", 100, 700), _rect("tank", 0, 9999, sign="-")])
    wc = water_column(zones)
    assert (wc.top_px, wc.bottom_px) == (100.0, 700.0)


def test_no_zones_means_no_extent_never_the_frame() -> None:
    wc = water_column(ZoneSet())
    assert wc.top_px is None and wc.bottom_px is None
    assert wc.source == "none:no_main_zone"


def test_only_secondary_zones_means_no_main_zone() -> None:
    wc = water_column(ZoneSet(rois=[_rect("band", 0, 50, level="secondary")]))
    assert wc.source == "none:no_main_zone"


def test_a_flat_zone_has_no_height() -> None:
    flat = ROI(name="line", level="main", vertices=[(0.0, 300.0), (100.0, 300.0)])
    wc = water_column(ZoneSet(rois=[flat]))
    assert wc.top_px is None and wc.bottom_px is None
    assert wc.source == "none:degenerate_zone"
