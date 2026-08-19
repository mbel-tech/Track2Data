"""Orientation pairing (FT/TF and similar paradigms) for zone sets."""

from __future__ import annotations

from track2data.core.models import ROI, ZoneSet

# ── public API ────────────────────────────────────────────────────────────────

# Keywords that indicate a "flow" zone for the FT paradigm.
_FLOW_KEYWORDS = ("flow", "f")


def pair_orientation_zones(
    zone_set: ZoneSet,
    tag: str,
) -> dict[str, str]:
    """Return a ``{zone_name: orientation_label}`` mapping for main-level ROIs.

    For the **FT** (flow/target) paradigm, zones whose names contain the
    substring ``"flow"`` (case-insensitive) or start with ``"F"`` are labelled
    ``"flow"``; all other main-level zones are labelled ``"target"``.

    Only zones with ``level == "main"`` are included in the mapping.  If
    ``zone_set.orientation_tag`` is ``None``, an empty dict is returned
    regardless of *tag*.

    Parameters
    ----------
    zone_set:
        The zone set whose ROIs are to be labelled.
    tag:
        The orientation tag to apply (e.g. ``"FT"``).  Currently ``"FT"`` and
        ``"TF"`` are handled; other tags return an empty mapping.

    Returns
    -------
    dict[str, str]
        Mapping of zone name to orientation label (``"flow"`` or ``"target"``),
        or an empty dict when no orientation is defined.
    """
    if zone_set.orientation_tag is None:
        return {}

    main_rois = [roi for roi in zone_set.rois if roi.level == "main"]
    if not main_rois:
        return {}

    if tag not in ("FT", "TF"):
        return {}

    return {roi.name: _label_roi(roi, tag) for roi in main_rois}


def flip_orientation(zone_set: ZoneSet) -> ZoneSet:
    """Return a new ZoneSet with orientation flipped.

    - ``FT`` ↔ ``TF`` (orientation_tag is reversed).
    - Vertex order for every ROI is reversed.
    - The original ``zone_set`` is not mutated.

    Parameters
    ----------
    zone_set:
        Source zone set.

    Returns
    -------
    ZoneSet
        New zone set with flipped orientation.
    """
    new_tag = _flip_tag(zone_set.orientation_tag)
    new_rois = [
        ROI(
            name=roi.name,
            level=roi.level,
            vertices=list(reversed(roi.vertices)),
            area_units=roi.area_units,
        )
        for roi in zone_set.rois
    ]
    return ZoneSet(
        rois=new_rois,
        orientation_tag=new_tag,
        zone_levels=dict(zone_set.zone_levels),
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_flow_zone(roi: ROI) -> bool:
    """Return True if the ROI name indicates a flow zone."""
    name_lower = roi.name.lower()
    if "flow" in name_lower:
        return True
    # Starts with "f" (case-insensitive), e.g. "F1", "F_side"
    return bool(name_lower.startswith("f"))


def _label_roi(roi: ROI, tag: str) -> str:
    """Return the orientation label for a single main-level ROI."""
    if tag == "FT":
        return "flow" if _is_flow_zone(roi) else "target"
    if tag == "TF":
        # TF is the mirror of FT
        return "target" if _is_flow_zone(roi) else "flow"
    return ""


def _flip_tag(tag: str | None) -> str | None:
    """Flip an orientation tag string (FT ↔ TF)."""
    if tag is None:
        return None
    if tag == "FT":
        return "TF"
    if tag == "TF":
        return "FT"
    # Generic reversal for any two-character tag
    return tag[::-1]
