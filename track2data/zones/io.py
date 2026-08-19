"""ZoneSet CSV round-trip I/O and dict-based construction."""

from __future__ import annotations

import csv
from pathlib import Path

from track2data.core.models import ROI, ZoneSet

# ── public API ────────────────────────────────────────────────────────────────

_CSV_HEADER = ("roi_name", "level", "vertex_x", "vertex_y")


def load_zones_csv(path: Path) -> ZoneSet:
    """Load zones from a CSV file.

    The CSV must have a header row followed by one row per vertex::

        roi_name, level, vertex_x, vertex_y

    Rows are grouped by ``roi_name``; vertex order is preserved.  An empty
    CSV (header only) returns an empty ``ZoneSet``.

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
    FileNotFoundError
        If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Zone CSV not found: {path}")

    # Preserve insertion order for ROI names.
    roi_vertices: dict[str, list[tuple[float, float]]] = {}
    roi_levels: dict[str, str] = {}

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = row["roi_name"].strip()
            level = row["level"].strip()
            x = float(row["vertex_x"])
            y = float(row["vertex_y"])
            if name not in roi_vertices:
                roi_vertices[name] = []
                roi_levels[name] = level
            roi_vertices[name].append((x, y))

    rois = [
        ROI(name=name, level=roi_levels[name], vertices=verts)
        for name, verts in roi_vertices.items()
    ]
    return ZoneSet(rois=rois)


def save_zones_csv(zone_set: ZoneSet, path: Path) -> None:
    """Save a ZoneSet to a CSV file (inverse of :func:`load_zones_csv`).

    One row is written per vertex.  The CSV header is::

        roi_name,level,vertex_x,vertex_y

    Parameters
    ----------
    zone_set:
        The zone set to serialise.
    path:
        Destination path.  Parent directories must already exist.
    """
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for roi in zone_set.rois:
            for x, y in roi.vertices:
                writer.writerow([roi.name, roi.level, x, y])


def zone_set_from_dict(data: dict) -> ZoneSet:  # type: ignore[type-arg]
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
