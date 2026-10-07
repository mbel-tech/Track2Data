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
    """Sessions matched by more than one metadata row (per-animal mode: an
    animal matched by more than one row of its session)."""

    matched_individuals: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    """Per-animal mode only: session_id -> normalised individual key -> that
    animal's fields (key columns excluded). ``matched`` then holds only the
    fields that are constant across the session's rows."""


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
    per_animal = "individual_id" in rule.rules and "individual_id" in df.columns

    for sid in session_ids:
        rows = _find_rows(sid, df, rule)
        if per_animal and len(rows) > 0:
            _match_animals(sid, rows, result, matched_row_indices)
            continue
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


_KEY_FIELDS = ("session_id", "individual_id")


def _norm_key(value: Any) -> str | None:
    """Normalise an individual key: '1', 1 and 1.0 (a CSV column with a missing
    value reads as float) are the same animal. None for a missing key."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _match_animals(
    sid: str, rows: pd.DataFrame, result: JoinResult, matched_row_indices: set[int]
) -> None:
    """Per-animal join for one session: one metadata row per animal.

    Several rows for the session are expected, so they are not a conflict; a
    repeated animal is. Fields constant across the rows become session-level;
    everything else belongs to its animal only.
    """
    by_key: dict[str, dict[str, Any]] = {}
    first_index: dict[str, int] = {}
    for idx, row in rows.iterrows():
        key = _norm_key(row.get("individual_id"))
        if key is None:
            continue
        values = {k: v for k, v in row.to_dict().items() if k not in _KEY_FIELDS}
        if key in by_key:
            result.conflicts.append(
                ConflictRecord(
                    session_id=sid,
                    matching_row_indices=[first_index[key], int(idx)],
                    values=[by_key[key], values],
                )
            )
            continue  # keep the first row, as the session-level join does
        by_key[key] = values
        first_index[key] = int(idx)
        matched_row_indices.add(int(idx))
    if not by_key:
        result.unmatched_sessions.append(sid)
        return
    result.matched_individuals[sid] = by_key
    columns = list(next(iter(by_key.values())))
    constant = {
        c: by_key[next(iter(by_key))][c]
        for c in columns
        if len({_hashable(v[c]) for v in by_key.values()}) == 1
    }
    result.matched[sid] = {"session_id": sid, **constant}


def _hashable(value: Any) -> Any:
    return "<NA>" if value is None or (isinstance(value, float) and pd.isna(value)) else value


def resolve_animal(key: str, labels: list[str], mode: str, n_animals: int) -> int | None:
    """Animal index for a metadata individual key, or None.

    "label": the validator's identity label (case-insensitive); a session with
    no labels falls back to the 0-based position. "index": always the 0-based
    position.
    """
    if mode == "label" and labels:
        try:
            return labels.index(key.strip().lower())
        except ValueError:
            return None
    try:
        idx = int(float(key))
    except ValueError:
        return None
    return idx if 0 <= idx < n_animals else None


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
