"""Metadata loading, mapping, and session-join subsystem."""

from track2data.metadata.join import JoinResult, match
from track2data.metadata.loader import load
from track2data.metadata.mapping import apply_mapping, auto_map
from track2data.metadata.schema import ALIASES, CANONICAL, resolve_column

__all__ = [
    "ALIASES",
    "CANONICAL",
    "JoinResult",
    "apply_mapping",
    "auto_map",
    "load",
    "match",
    "resolve_column",
]
