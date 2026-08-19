"""
Canonical metadata field list and built-in alias table.

The canonical field names are the single source of truth for column names
produced by the metadata join and consumed by exporters.
"""

from __future__ import annotations

#: Ordered canonical output column names.
CANONICAL: list[str] = [
    "session_id",
    "trial_id",
    "individual_id",
    "group_id",
    "treatment",
    "trial_date",
    "timepoint",
]

#: Built-in alias map: ``{source_column -> canonical_name}``.
ALIASES: dict[str, str] = {
    "condition":  "treatment",
    "date":       "trial_date",
    "time":       "timepoint",
    "fish_id":    "individual_id",
    "animal_id":  "individual_id",
    "tank":       "group_id",
    "tank_id":    "group_id",
    "exp_date":   "trial_date",
    "experiment": "treatment",
}


def resolve_column(name: str, extra_aliases: dict[str, str] | None = None) -> str:
    """
    Return the canonical name for *name*, applying built-in then extra aliases.
    Returns *name* unchanged if it is already canonical or has no known alias.
    """
    merged = {**ALIASES, **(extra_aliases or {})}
    lowered = name.strip().lower()
    return merged.get(lowered, lowered)


def is_canonical(name: str) -> bool:
    """Return True if *name* is a canonical field name."""
    return name.strip().lower() in CANONICAL
