"""
Parser for idtracker.ai session.json.

session.json is the primary metadata source for a session. Real files
contain non-strict JSON literals (Infinity, -Infinity, NaN) which the
stdlib json module rejects.  This module uses the parse_constant hook to
handle them leniently and emits IDT_JSON_NONSTRICT at info level.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONSTANT_MAP = {
    "Infinity": float("inf"),
    "-Infinity": float("-inf"),
    "NaN": float("nan"),
}


def _safe_constant(c: str) -> float:
    if c in _CONSTANT_MAP:
        logger.info(
            "IDT_JSON_NONSTRICT: session.json contains non-strict JSON literal %r; "
            "parsed leniently.",
            c,
        )
        return _CONSTANT_MAP[c]
    return float(c)


def load_session_json(folder: Path) -> dict[str, Any] | None:
    """
    Load and return the parsed session.json from *folder*.

    Returns None when the file does not exist or cannot be parsed.
    Non-strict JSON literals (Infinity, NaN) are handled via the
    parse_constant hook rather than crashing.
    """
    path = Path(folder) / "session.json"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text, parse_constant=_safe_constant)
    except Exception as exc:
        logger.warning(
            "IDT_JSON_PARSE_ERROR: Could not parse session.json at %s: %s",
            path,
            exc,
        )
        return None
