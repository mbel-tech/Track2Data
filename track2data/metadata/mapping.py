"""
MappingRule application and canonical-field resolver.

A ``MappingRule`` (defined in ``core/models.py``) stores a dict of
``{canonical_field -> source_column}`` plus join-key policy.

``apply_mapping(df, rule)`` renames and filters columns to the canonical set.
"""

from __future__ import annotations

import pandas as pd

from track2data.core.models import MappingRule
from track2data.metadata.schema import ALIASES, CANONICAL

#: Output columns written by the engine itself. A metadata column with one of
#: these names would overwrite real data, so it is never carried.
RESERVED_COLUMNS = frozenset(
    {
        "metric_id", "frame", "time_s", "in_tracking_interval", "x_px", "y_px", "x_cm", "y_cm",
        "was_interpolated", "speed_px_s", "speed_cm_s", "heading_rad", "main_zone", "sec_zone",
        "individual_label", "individual_color", "bin_index", "bin_start_s", "bin_end_s",
        "zone_name",
    }
)


def apply_mapping(df: pd.DataFrame, rule: MappingRule) -> pd.DataFrame:
    """
    Rename source columns to canonical names using *rule.rules*.

    Columns not referenced in *rule.rules* and not already canonical are
    dropped, except those named in *rule.extra_columns*.  Canonical columns
    already present are kept as-is.

    Parameters
    ----------
    df:
        Raw metadata DataFrame (output of ``loader.load``).
    rule:
        ``MappingRule`` with ``rules = {canonical_name: source_col}``.

    Returns
    -------
    pd.DataFrame
        Subset and renamed to canonical columns (only mapped columns present).
    """
    # Build rename map: source_col -> canonical_name.
    rename: dict[str, str] = {}
    for canonical, source in rule.rules.items():
        src = source.strip().lower()
        if src in df.columns:
            rename[src] = canonical

    # Also apply built-in aliases for columns not explicitly mapped.
    for col in df.columns:
        if col not in rename and col not in rename.values():
            alias = ALIASES.get(col)
            if alias and alias not in rename.values():
                rename[col] = alias

    df2 = df.rename(columns=rename)

    # Keep only columns that are canonical or were explicitly mapped to canonical,
    # plus the extra columns the rule asks for (skipping any whose name would
    # collide with a column the engine writes itself).
    keep = [c for c in df2.columns if c in CANONICAL]
    for extra in rule.extra_columns:
        name = extra.strip().lower()
        if name in df2.columns and name not in keep and name not in RESERVED_COLUMNS:
            keep.append(name)
    return df2[keep].copy()


def auto_map(df: pd.DataFrame) -> MappingRule:
    """
    Heuristically build a ``MappingRule`` from a DataFrame's column names.

    Uses built-in aliases plus exact-match against canonical names.
    Useful as a starting point for the UI mapping screen.
    """
    rules: dict[str, str] = {}
    for col in df.columns:
        lowered = col.strip().lower()
        if lowered in CANONICAL:
            rules[lowered] = col
        elif lowered in ALIASES:
            rules[ALIASES[lowered]] = col
    return MappingRule(rules=rules)
