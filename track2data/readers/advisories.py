"""Caveats that follow from which reader produced a project's sessions.

Neither is visible in the numbers, and neither is an error, so they are reported before a run
and recorded in its summary but never block it:

* A reader written from a format's documentation alone (``verification == "synthetic_only"``)
  may disagree with the real files in ways only real output reveals (DECISIONS D-012).
* The default "bodylength" calibration needs a body length, which most trackers do not report.
  Without one it is skipped and the session is exported in pixels only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from track2data.core.session_consistency import SessionSummary
from track2data.readers import find_reader

_LISTED = 4


def reader_advisories(summaries: Sequence[SessionSummary]) -> list[str]:
    """One plain-language warning per caveat, naming the sessions it applies to."""
    return [*_unverified(summaries), *_missing_body_length(summaries)]


def _unverified(summaries: Sequence[SessionSummary]) -> list[str]:
    advisories = []
    for name, ids in _ids_by(summaries, key=lambda s: s.reader).items():
        reader = find_reader(name)
        # A reader that is not registered cannot be described, and the import has failed anyway.
        if reader is None or reader.verification == "real_sample":
            continue
        shown = name if reader.display_name in ("", name) else f"{name} ({reader.display_name})"
        advisories.append(
            f"Reader '{shown}' has not been checked against real tracker output: it was written "
            "from the format's documentation. Compare a few trajectories with the tracker's own "
            f"output before relying on the numbers. Sessions: {_listed(ids)}."
        )
    return advisories


def _missing_body_length(summaries: Sequence[SessionSummary]) -> list[str]:
    lacking = [s for s in summaries if s.calibration_mode == "bodylength" and not s.has_body_length]
    if not lacking:
        return []
    by_reader = _ids_by(lacking, key=lambda s: _label(s.reader))
    detail = "; ".join(f"{label}: {_listed(ids)}" for label, ids in by_reader.items())
    return [
        "Calibration is set to 'bodylength', but some sessions carry no body length, so it is "
        "skipped for them and their columns stay in pixels. Affected sessions, by reader: "
        f"{detail}. To get real-unit columns, choose 'scalar' calibration and give pixels per "
        "cm (or 'session' calibration, for sessions that carry their own length unit)."
    ]


def _ids_by(
    summaries: Sequence[SessionSummary], *, key: Callable[[SessionSummary], str]
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for summary in summaries:
        grouped.setdefault(key(summary), []).append(summary.session_id)
    return grouped


def _label(reader_name: str) -> str:
    reader = find_reader(reader_name)
    return (reader.display_name or reader.name) if reader is not None else reader_name


def _listed(ids: Sequence[str]) -> str:
    shown = ", ".join(ids[:_LISTED])
    return f"{shown}, +{len(ids) - _LISTED} more" if len(ids) > _LISTED else shown
