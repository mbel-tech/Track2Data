"""
Digest extractor for idtrackerai.log.

Extracts: final run status (Success / Failed / Unknown) and WARNING/ERROR
lines. All parsing is best-effort -- never required, never crashes the
reader.

Real-format notes (verified against the 70-session GOT corpus; the
previous parser matched neither pattern below and reported "Unknown" on
every real session):

- idtracker.ai's own log format is `[HH:MM:SS ]<message>   <source.py:line>`
  -- the timestamp is shown only when it changes from the previous line
  (a common terse-logging convention), so most lines have no leading time
  at all. There is no `[stage] Status: X` marker anywhere in real logs.
- The terminal status on a successful run is the bare word `Success` on
  its own line (source `run.py:81` in every sample), not
  `[done] Status: Success`.
- WARNING/ERROR lines carry the level as a literal token right after the
  (optional) timestamp: `WARNING <message>` / `ERROR <message>`. Plain
  INFO lines carry no level token at all.
- A run that aborted mid-way (idtracker.ai_usage.md:83: "the last lines
  of the log describe what went wrong") has no `Success` line and ends
  in a Python traceback instead -- this occurs in the real corpus
  (session_trial15_Segment1, an OSError from too many open files).
  Reporting "Unknown" for that session is indistinguishable from a
  clean run; this parser now reports "Failed" and captures the crash's
  last line.

Per-stage durations are intentionally NOT extracted here: idtracker.ai's
session.json carries a structured `timers` dict (per-stage start/finish
ISO timestamps) that is a parse-free, more reliable source for that data.
Wiring session.json's timers into Session.tracking_log is a separate,
larger change (see the format-alignment plan, Fase 4); this module stays
scoped to what the log text itself can honestly answer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Optional "HH:MM:SS " timestamp, then WARNING/ERROR, then the message,
# then a right-aligned "some/path/module.py:LINE" source reference.
# Matched in two linear steps (prefix regex, then rsplit of the last token)
# rather than one pattern: the old ``\s+(?P<msg>.*?)\s+source\s*$`` let three
# whitespace quantifiers compete for the same run of spaces, so a WARNING
# line of padding with no source backtracked cubically and hung the import.
_LEVEL_PREFIX_RE = re.compile(r"\s*(?:\d{2}:\d{2}:\d{2}\s+)?(?:WARNING|ERROR)\s")
_SOURCE_RE = re.compile(r"[\w./\-]+\.py:\d+")


def _level_line_source(line: str) -> str | None:
    """The ``module.py:N`` source of a WARNING/ERROR line, None if *line* is not one."""
    m = _LEVEL_PREFIX_RE.match(line)
    if m is None:
        return None
    parts = line[m.end():].rsplit(None, 1)
    if len(parts) != 2 or _SOURCE_RE.fullmatch(parts[1]) is None:
        return None
    return parts[1]


_SUCCESS_LINE_RE = re.compile(r"^\s*Success\s+[\w./\-]+\.py:\d+\s*$")
_TRACEBACK_MARKER = "Traceback (most recent call last):"
# The actual exception line inside a traceback, e.g. "OSError: [Errno 24]
# Too many open files" -- distinct from the boilerplate "please report this"
# footer idtracker.ai appends after every crash, which is the literal last
# line of the file and not informative on its own.
_EXCEPTION_LINE_RE = re.compile(r"^\s*[A-Za-z_][\w.]*(?:Error|Exception|Warning):\s")

# telemetry.py failures (e.g. "Error fetching PyPI data" -- idtracker.ai
# phoning home for a version check) are noise unrelated to tracking
# quality; they would otherwise sit indistinguishably next to genuinely
# important warnings like "There are 75 frames with more blobs than
# animals".
_NOISE_SOURCE_PREFIXES = ("telemetry.py",)


def load_log_digest(folder: Path) -> dict[str, Any] | None:
    """
    Parse idtrackerai.log and return a summary dict, or None if absent.

    Keys in the returned dict:
      status           : "Success" | "Failed" | "Unknown"
      failure_summary   : last traceback line, or "" when status != "Failed"
      durations        : {} (see module docstring -- not sourced from the log)
      warnings         : [line, …]  (WARNING/ERROR lines, telemetry noise excluded)
    """
    path = Path(folder) / "idtrackerai.log"
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = text.splitlines()

    status = "Unknown"
    failure_summary = ""
    warnings: list[str] = []

    for line in lines:
        if _SUCCESS_LINE_RE.match(line):
            status = "Success"

        source = _level_line_source(line)
        if source is not None and not source.startswith(_NOISE_SOURCE_PREFIXES):
            warnings.append(line.strip())

    if status != "Success" and _TRACEBACK_MARKER in text:
        status = "Failed"
        # Prefer the last actual exception line (e.g. "OSError: ...") over
        # the boilerplate "please report this" footer idtracker.ai appends
        # after every crash, which would otherwise win as "the last line".
        exception_lines = [ln.strip() for ln in lines if _EXCEPTION_LINE_RE.match(ln)]
        if exception_lines:
            failure_summary = exception_lines[-1]
        else:
            tail = [ln.strip() for ln in lines if ln.strip()]
            failure_summary = tail[-1] if tail else ""

    return {
        "status": status,
        "failure_summary": failure_summary,
        "durations": {},
        "warnings": warnings,
    }
