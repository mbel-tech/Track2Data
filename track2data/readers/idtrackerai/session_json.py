"""
Parser for idtracker.ai session.json.

session.json is the primary metadata source for a session. Real files
contain non-strict JSON literals (Infinity, -Infinity, NaN) which the
stdlib json module rejects.  This module uses the parse_constant hook to
handle them leniently and emits IDT_JSON_NONSTRICT at info level.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# "+ Polygon [[274.1, 13.2], [144.9, 401.2], ...]" or "- Polygon [...]"
# (idtracker.ai_usage.md:30-31). "+" is the arena outer boundary, "-" is an
# exclusion hole -- 85% of the ~660 roi_list entries across a 70-session
# real corpus are subtractive, so ignoring the sign and treating every
# entry as additive would include every excluded region as trackable area.
_ROI_STRING_RE = re.compile(r"^\s*([+-])\s*Polygon\s*(\[.*\])\s*$")


def parse_roi_string(raw: str) -> dict[str, Any] | None:
    """
    Parse one ``session.json['roi_list']`` entry into ``{sign, vertices, raw}``.

    Returns None (logging a warning, never raising) when *raw* doesn't
    match the documented format -- this is enrichment, and a malformed
    entry must not break session import.
    """
    match = _ROI_STRING_RE.match(raw)
    if not match:
        logger.warning("Could not parse roi_list entry (unrecognised format): %r", raw[:80])
        return None

    sign, literal = match.groups()
    try:
        raw_vertices = ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        logger.warning("Could not parse roi_list polygon vertices: %r", raw[:80])
        return None

    try:
        vertices = [(float(x), float(y)) for x, y in raw_vertices]
    except (TypeError, ValueError):
        logger.warning("roi_list polygon vertices are not (x, y) pairs: %r", raw[:80])
        return None

    if len(vertices) < 3:
        logger.warning("roi_list polygon has fewer than 3 vertices: %r", raw[:80])
        return None

    return {"sign": sign, "vertices": vertices, "raw": raw}

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
