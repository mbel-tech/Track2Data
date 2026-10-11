"""Depth of a native 3-D session from its water column.

Public API
----------
apply_water_column  -- derive psess.depth from psess.z, the surface and the floor
"""

from __future__ import annotations

import dataclasses

import numpy as np

from track2data.core.models import PreprocessedSession, WaterColumn


def apply_water_column(psess: PreprocessedSession, wc: WaterColumn) -> PreprocessedSession:
    """Set ``depth`` (0 = surface, 1 = floor) from ``psess.z``; unchanged when there is no z.

    ``depth = (z - surface_z) / (floor_z - surface_z)``, so the floor may lie on either side of
    the surface. A z outside the column gives NaN and is counted (``depth_outside_mask``,
    ``depth_outside``), never clipped. ``depth_height_cm`` is the column height
    ``abs(floor_z - surface_z)`` (the file's z is already in the project's length unit).
    """
    if psess.z is None:
        return psess
    z = np.asarray(psess.z, dtype=np.float64)
    span = float(wc.floor_z) - float(wc.surface_z)
    with np.errstate(invalid="ignore"):
        frac = (z - float(wc.surface_z)) / span
        outside = np.isfinite(frac) & ((frac < 0.0) | (frac > 1.0))
    depth = np.where(outside, np.nan, frac)
    return dataclasses.replace(
        psess,
        depth=depth,
        depth_height_cm=abs(span),
        depth_outside_mask=outside,
        depth_outside=outside.sum(axis=0).astype(int),
    )
