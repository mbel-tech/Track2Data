"""ZoneSet CSV round-trip I/O and dict-based construction."""

from __future__ import annotations

import csv
from pathlib import Path

from track2data.core.models import ROI, ZoneSet

# ── public API ────────────────────────────────────────────────────────────────

_CSV_HEADER = (
    "roi_name", "level", "vertex_x", "vertex_y",
    "sign", "polygon", "source_width_px", "source_height_px",
)


def load_zones_csv(path: Path) -> ZoneSet:
    """Load zones from a CSV file.

    The CSV must have a header row followed by one row per vertex::

        roi_name, level, vertex_x, vertex_y[, sign, polygon, source_width_px, source_height_px]

    The first four columns are required; the rest are written by
    :func:`save_zones_csv` and optional on input, so older files still load.
    ``sign`` ("+" additive or "-" subtractive hole, default "+") and ``polygon``
    (an id shared by the rows of one polygon) keep same-named ROIs apart: an arena
    outline and an exclusion hole may share the name ``arena`` and must stay two
    polygons. Without ``polygon``, rows are grouped by ``(roi_name, sign)``. Vertex
    order is preserved. ``source_width_px`` / ``source_height_px`` restore the
    resolution the zones were drawn against. An empty CSV (header only) returns an
    empty ``ZoneSet``.

    Parameters
    ----------
    path:
        Path to the CSV file to read.

    Returns
    -------
    ZoneSet
        Parsed zone set.  ``orientation_tag`` and ``zone_levels`` are left at
        their defaults because the CSV format does not store them.

    Raises
    ------
    ValueError
        If a ``sign`` is neither "+" nor "-".

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Zone CSV not found: {path}")

    # Preserve insertion order of the polygons.
    polygons: dict[tuple[str, str], dict] = {}
    source_size: list[int | None] = [None, None]

    def _optional_int(text: str | None) -> int | None:
        text = (text or "").strip()
        return int(float(text)) if text else None

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = row["roi_name"].strip()
            level = row["level"].strip()
            sign = (row.get("sign") or "+").strip() or "+"
            if sign not in ("+", "-"):
                raise ValueError(f"Zone CSV sign must be '+' or '-', got {sign!r} for {name!r}.")
            polygon = (row.get("polygon") or "").strip()
            key = (name, polygon if polygon else sign)
            if key not in polygons:
                polygons[key] = {"name": name, "level": level, "sign": sign, "vertices": []}
            polygons[key]["vertices"].append((float(row["vertex_x"]), float(row["vertex_y"])))
            for i, column in enumerate(("source_width_px", "source_height_px")):
                if source_size[i] is None:
                    source_size[i] = _optional_int(row.get(column))

    rois = [ROI(**fields) for fields in polygons.values()]
    return ZoneSet(
        rois=rois, source_width_px=source_size[0], source_height_px=source_size[1]
    )


def save_zones_csv(zone_set: ZoneSet, path: Path) -> None:
    """Save a ZoneSet to a CSV file (inverse of :func:`load_zones_csv`).

    One row is written per vertex.  The CSV header is::

        roi_name,level,vertex_x,vertex_y,sign,polygon,source_width_px,source_height_px

    ``polygon`` numbers the ROIs in order, so same-named ROIs (an outline and its
    holes) round-trip as separate polygons with their ``sign``.

    Parameters
    ----------
    zone_set:
        The zone set to serialise.
    path:
        Destination path.  Parent directories must already exist.
    """
    path = Path(path)
    width = "" if zone_set.source_width_px is None else zone_set.source_width_px
    height = "" if zone_set.source_height_px is None else zone_set.source_height_px
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for polygon, roi in enumerate(zone_set.rois):
            for x, y in roi.vertices:
                writer.writerow([roi.name, roi.level, x, y, roi.sign, polygon, width, height])


def zone_set_from_dict(data: dict) -> ZoneSet:
    """Parse a ZoneSet from a plain dict (e.g. deserialised from JSON).

    This is a thin convenience wrapper around ``ZoneSet.model_validate``.
    Vertices may be given as lists; Pydantic will coerce them to tuples.

    Parameters
    ----------
    data:
        Dictionary representation of a ZoneSet.  Missing keys use model
        defaults, so an empty dict returns ``ZoneSet()``.

    Returns
    -------
    ZoneSet
        Validated zone set instance.
    """
    return ZoneSet.model_validate(data)


def zone_set_from_roi_list(
    roi_list: list[dict] | None,
    *,
    name: str = "arena",
    level: str = "main",
    width_px: int | None = None,
    height_px: int | None = None,
) -> ZoneSet:
    """
    Seed a ``ZoneSet`` from ``Session.roi_list``.

    idtracker.ai defines the tracked arena as one or more additive
    ("+") outer-boundary polygons minus zero or more subtractive ("-")
    exclusion holes (idtracker.ai_usage.md:30-31) -- all sharing one
    logical zone. Every parsed entry becomes an ``ROI`` with that shared
    *name*/*level* and its own ``sign``; ``zones.geometry.assign_zones``
    combines same-named ROIs by sign (covered by a "+" polygon and not
    covered by any "-" polygon of that name).

    Parameters
    ----------
    roi_list:
        ``Session.roi_list`` -- a list of ``{"sign", "vertices", "raw"}``
        dicts as produced by
        ``readers.idtrackerai.session_json.parse_roi_string``. ``None`` or
        empty returns an empty ``ZoneSet``.
    name, level:
        Zone name/level assigned to every ROI built from *roi_list*. All
        entries share these because idtracker.ai's roi_list has no
        per-polygon naming -- it describes one arena.
    width_px, height_px:
        The session's video dimensions, recorded on the returned
        ``ZoneSet`` so that reusing it against a session tracked at a
        different resolution can be detected rather than silently
        misapplied.

    Returns
    -------
    ZoneSet
        Never raises on a malformed entry -- entries lacking "sign" or
        "vertices" are skipped.
    """
    if not roi_list:
        return ZoneSet()

    rois = [
        ROI(name=name, level=level, vertices=entry["vertices"], sign=entry["sign"])
        for entry in roi_list
        if "sign" in entry and "vertices" in entry
    ]
    return ZoneSet(rois=rois, source_width_px=width_px, source_height_px=height_px)
