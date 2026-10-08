"""Coordinate units: what a session's positions are expressed in, and what its columns are called.

Most trackers report pixels, and every metric column that holds a length is named for it
(``distance_px``, ``speed_px_s``, ``area_px2``). A few tools report no pixel frame at all (a 3-D
triangulation in board units; a tracker that gives only millimetres). The pipeline's arithmetic is
unit-agnostic, so those sessions run unchanged; what has to change is the *name*, because a distance
in millimetres exported under a ``_px`` header is a mislabelled number that will be believed.

So the rename happens once, at the export boundary (``relabel_frame``), after all computation.
Nothing inside the pipeline is renamed, which keeps pixel projects byte-identical.

A tool's own unit label is not believed on its own: a "mm" a tracker prints may be pixels with an
offset (one real ToxTrac export is exactly that). Until someone confirms the unit, columns are named
in *tool units* (``_tu``) and the codebook says "tool units". Confirming it (the calibration unit
label plus the "I confirmed this" box, which already exists for pixel projects) switches the names
to the confirmed unit and, for a known physical length, enables the centimetre columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

PIXELS = "px"
TOOL_UNITS = "tu"

#: Labels that cannot name a native unit because a column family already ends with them.
RESERVED_LABELS: frozenset[str] = frozenset({"px", "tu", "bl", "s", "rad", "pct", "count", "bits"})

_UNITS_PER_CM: dict[str, float] = {
    "mm": 10.0,
    "cm": 1.0,
    "m": 0.01,
    "um": 10_000.0,
    "µm": 10_000.0,
}

#: Pixel-family suffix -> the tail that follows the unit. No suffix here is the end of another
#: ("a_px_s2" does not end in "_px_s"), so the order does not matter.
_PIXEL_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("_px_s2", "_s2"),
    ("_px_s", "_s"),
    ("_px2", "2"),
    ("_px", ""),
)
#: The tail of a relabelled column -> how its unit reads, with {u} the unit symbol.
_NATIVE_TAILS: tuple[tuple[str, str], ...] = (
    ("_s2", "{u}/s^2"),
    ("_s", "{u}/s"),
    ("2", "{u}^2"),
    ("", "{u}"),
)


def effective_unit(*, has_pixel_frame: bool, confirmed_label: str | None) -> str:
    """The unit a project's length columns are named in.

    Pixels when there is a pixel frame. Otherwise tool units, unless the user confirmed a label
    that does not collide with another column family.
    """
    if has_pixel_frame:
        return PIXELS
    if confirmed_label and confirmed_label not in RESERVED_LABELS:
        return confirmed_label
    return TOOL_UNITS


def unit_symbol(unit: str) -> str:
    """How a unit reads in a codebook or a README."""
    return "tool units" if unit == TOOL_UNITS else unit


def units_per_cm(unit: str) -> float | None:
    """How many of *unit* make a centimetre, or None when that is not known (never guessed)."""
    return _UNITS_PER_CM.get(unit)


def relabel_column(name: str, unit: str) -> str:
    """The column name with its pixel suffix replaced by *unit*; other names are unchanged."""
    if unit == PIXELS:
        return name
    for suffix, tail in _PIXEL_SUFFIXES:
        if name.endswith(suffix):
            return f"{name[: -len(suffix)]}_{unit}{tail}"
    return name


def relabel_frame(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    """*df* with its pixel-family columns renamed for *unit*.

    A pixel project gets the very same object back, so nothing about its export can change.
    """
    if unit == PIXELS or df is None or (df.empty and not len(df.columns)):
        return df
    renamed = {c: relabel_column(c, unit) for c in df.columns}
    if all(old == new for old, new in renamed.items()):
        return df
    return df.rename(columns=renamed)


def native_unit_for_column(column: str, unit: str) -> str | None:
    """The unit of a column that ``relabel_column`` produced for *unit*, else None."""
    if unit == PIXELS:
        return None
    for tail, reading in _NATIVE_TAILS:
        if column.endswith(f"_{unit}{tail}"):
            return reading.format(u=unit_symbol(unit))
    return None
