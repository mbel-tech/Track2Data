"""The vertical span of the water column, read from the zones the user already draws.

On a side view the main-level zones outline the water: the top edge is the surface and the
bottom edge the tank floor. Image rows grow downward, so the surface is the *smaller* row.

Every main-level additive ("+") zone is pooled, not one per animal as IL-3 does: only the
vertical span matters, tanks side by side share it, and a project that nests an inner main zone
(`centre`) inside an outer one (`wall`) must be measured against the outer one. A project with
tanks stacked on top of each other is the documented exception: they pool into one tall column.

There is deliberately no fallback to the video frame. A frame is not a water column, and a
depth computed against it would look plausible and be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from track2data.core.models import ZoneSet


@dataclass(frozen=True)
class WaterColumn:
    """The surface and floor rows, or None for both when no usable extent exists.

    ``source`` always says where the extent came from, or why there is none:
    ``zone:<name>``, ``zones:<a>|<b>``, ``none:no_main_zone`` or ``none:degenerate_zone``.
    """

    top_px: float | None
    bottom_px: float | None
    source: str


def water_column(zone_set: ZoneSet) -> WaterColumn:
    """The pooled vertical span of every main-level "+" zone in *zone_set*."""
    main = [r for r in zone_set.rois if r.level == "main" and r.sign == "+" and r.vertices]
    if not main:
        return WaterColumn(None, None, "none:no_main_zone")

    ys = [v[1] for roi in main for v in roi.vertices]
    top, bottom = float(min(ys)), float(max(ys))
    if not bottom > top:
        return WaterColumn(None, None, "none:degenerate_zone")

    names = sorted({roi.name for roi in main})
    source = f"zone:{names[0]}" if len(names) == 1 else "zones:" + "|".join(names)
    return WaterColumn(top, bottom, source)
