"""
Digest extractor for idtrackerai.log.

Extracts: last Status line (Success / Error), per-stage durations,
and any WARN/ERROR lines.  All parsing is best-effort — never required,
never crashes the reader.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

_STATUS_RE = re.compile(r"\[done\]\s+Status:\s+(\w+)", re.IGNORECASE)
_TIMER_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+INFO\s+\[(\w+)\].*?(\d+\.\d+)s",
    re.IGNORECASE,
)


def load_log_digest(folder: Path) -> dict[str, Any] | None:
    """
    Parse idtrackerai.log and return a summary dict, or None if absent.

    Keys in the returned dict:
      status       : "Success" | "Error" | "Unknown"
      durations    : {stage_name: seconds, …}
      warnings     : [line, …]
    """
    path = Path(folder) / "idtrackerai.log"
    if not path.exists():
        return None

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    status = "Unknown"
    durations: dict[str, float] = {}
    warnings: list[str] = []

    for line in lines:
        m = _STATUS_RE.search(line)
        if m:
            status = m.group(1).capitalize()

        tm = _TIMER_RE.search(line)
        if tm:
            stage = tm.group(2)
            with contextlib.suppress(ValueError):
                durations[stage] = float(tm.group(3))

        upper = line.upper()
        if " WARN" in upper or " ERROR" in upper:
            warnings.append(line)

    return {"status": status, "durations": durations, "warnings": warnings}
