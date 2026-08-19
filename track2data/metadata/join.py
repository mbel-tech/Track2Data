"""
Session <-> metadata-row matcher.

``match(session_ids, df, rule)`` pairs each session with exactly one
metadata row (or flags it as unmatched / conflicted).

Matching strategies (controlled by ``MappingRule.join_keys``):
  1. **Exact** — ``session_id`` column in df equals the session_id.
  2. **Composite** — match on a combination of columns (e.g. tank + trial_date).
  3. **Regex** — ``MappingRule.join_regex`` applied to the folder basename;
     named groups become values for ``trial_id``, ``timepoint``, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from track2data.core.models import MappingRule


@dataclass
class ConflictRecord:
    """Two or more metadata rows matched the same session."""

    session_id: str
    matching_row_indices: list[int]
    values: list[dict[str, Any]]


@dataclass
class JoinResult:
    """Output of ``match()``."""

    matched: dict[str, dict[str, Any]] = field(default_factory=dict)
    """session_id -> canonical field dict for matched sessions."""

    unmatched_sessions: list[str] = field(default_factory=list)
    """Session IDs with no matching metadata row."""

    unmatched_metadata_rows: list[int] = field(default_factory=list)
    """Row indices in the metadata DataFrame with no matching session."""

    conflicts: list[ConflictRecord] = field(default_factory=list)
    """Sessions matched by more than one metadata row."""


def match(
    session_ids: list[str],
    df: pd.DataFrame,
    rule: MappingRule,
) -> JoinResult:
    """
    Match *session_ids* to rows in *df* using the strategy in *rule*.

    Parameters
    ----------
    session_ids:
        List of session IDs to match (folder basenames by default).
    df:
        Canonical-mapped metadata DataFrame (output of ``apply_mapping``).
        Must have lowercased column names.
    rule:
        ``MappingRule`` specifying join keys and optional regex.

    Returns
    -------
    JoinResult
    """
    result = JoinResult()
    matched_row_indices: set[int] = set()

    for sid in session_ids:
        rows = _find_rows(sid, df, rule)
        if len(rows) == 0:
            result.unmatched_sessions.append(sid)
        elif len(rows) == 1:
            idx = rows.index[0]
            result.matched[sid] = rows.iloc[0].to_dict()
            matched_row_indices.add(int(idx))
        else:
            # Conflict: multiple matches.
            indices = list(rows.index)
            result.conflicts.append(
                ConflictRecord(
                    session_id=sid,
                    matching_row_indices=[int(i) for i in indices],
                    values=[rows.loc[i].to_dict() for i in indices],
                )
            )
            # Still use first match so downstream code isn't blocked.
            result.matched[sid] = rows.iloc[0].to_dict()
            matched_row_indices.add(int(indices[0]))

    # Collect unmatched metadata rows.
    result.unmatched_metadata_rows = [
        int(i) for i in df.index if int(i) not in matched_row_indices
    ]

    return result


def _find_rows(
    session_id: str, df: pd.DataFrame, rule: MappingRule
) -> pd.DataFrame:
    """Return subset of *df* rows that match *session_id* per *rule*."""
    # Strategy 1: regex on session_id → match named groups.
    if rule.join_regex:
        pattern = re.compile(rule.join_regex)
        m = pattern.search(session_id)
        if m:
            groups = m.groupdict()
            mask = pd.Series([True] * len(df), index=df.index)
            for col, val in groups.items():
                if col in df.columns:
                    mask &= df[col].astype(str) == str(val)
            return df[mask]
        return df.iloc[0:0]  # empty

    # Strategy 2: composite / exact key join.
    keys = rule.join_keys if rule.join_keys else ["session_id"]
    if "session_id" in keys and "session_id" in df.columns:
        return df[df["session_id"] == session_id]

    # Composite: match session_id against concatenated key columns.
    if len(keys) > 1:
        sep = "_"
        composite = df[keys].astype(str).agg(sep.join, axis=1)
        return df[composite == session_id]

    # Single non-session_id key: fallback to exact value match.
    key = keys[0]
    if key in df.columns:
        return df[df[key] == session_id]

    return df.iloc[0:0]
