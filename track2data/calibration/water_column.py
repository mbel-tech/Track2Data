"""Depth of a native 3-D session from its water column.

Public API
----------
apply_water_column  -- derive psess.depth from psess.z, the surface and the floor
parse_water_column  -- the two typed values of the Calibration page as a WaterColumn or an error
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from track2data.core.models import PreprocessedSession, WaterColumn


def apply_water_column(psess: PreprocessedSession, wc: WaterColumn) -> PreprocessedSession:
    """Set ``depth`` (0 = surface, 1 = floor) from ``psess.z``; unchanged when there is no z.

    ``depth = (z - surface_z) / (floor_z - surface_z)``, so the floor may lie on either side of
    the surface. A z outside the column gives NaN and is counted (``depth_outside_mask``,
    ``depth_outside``), never clipped. A non-finite z (NaN or +/-inf) is missing: NaN depth,
    not counted. ``depth_height_cm`` is the column height
    ``abs(floor_z - surface_z)`` (the file's z is already in the project's length unit).

    The column is entered on the file's own vertical axis. The reader has already negated ``z``
    for a session read with ``flip``, so for such a session both values are negated here: the
    same physical fish gets the same depth with or without the flip.
    """
    if psess.z is None:
        return psess
    z = np.asarray(psess.z, dtype=np.float64)
    surface, floor = float(wc.surface_z), float(wc.floor_z)
    native = (getattr(psess.session, "raw_attrs", None) or {}).get("native_3d") or {}
    if native.get("flip"):
        surface, floor = -surface, -floor
    span = floor - surface
    with np.errstate(invalid="ignore"):
        frac = (z - surface) / span
        outside = np.isfinite(frac) & ((frac < 0.0) | (frac > 1.0))
    depth = np.where(outside | ~np.isfinite(frac), np.nan, frac)
    return dataclasses.replace(
        psess,
        depth=depth,
        depth_height_cm=abs(span),
        depth_outside_mask=outside,
        depth_outside=outside.sum(axis=0).astype(int),
    )


def parse_water_column(surface: str, floor: str) -> tuple[WaterColumn | None, str | None]:
    """The water column typed as text, as ``(column, error)``.

    Both texts empty, or either one, gives ``(None, None)``: no column (the way to clear it).
    Otherwise a value that is not a finite number, or a floor equal to the surface, gives
    ``(None, message)`` where the message names the field; a valid pair gives the column (the
    floor may lie on either side of the surface).
    """
    texts = {"surface z": surface.strip(), "floor z": floor.strip()}
    if not all(texts.values()):
        return None, None
    values: dict[str, float] = {}
    for name, text in texts.items():
        try:
            value = float(text)
        except ValueError:
            return None, f"{name} is not a number"
        if not math.isfinite(value):
            return None, f"{name} must be a finite number"
        values[name] = value
    if values["surface z"] == values["floor z"]:
        return None, "floor z must differ from surface z"
    return WaterColumn(surface_z=values["surface z"], floor_z=values["floor z"]), None
