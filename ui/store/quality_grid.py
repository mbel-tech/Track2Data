"""Per-session traffic-light quality verdicts for the Preview diagnostics grid.

Pure (no Qt): ``assess_session`` reads one ``SessionRunResult``'s diagnostic
frames and returns a ``SessionQuality`` -- one ``Cell`` per measure plus a
verdict (the worst cell) and one plain sentence per non-green measure.

Sources: coverage D-1, identity stability D-5, crossing share D-8, implausible
jumps D-10, interpolated frames D-11. The cut-offs below are UI-side defaults,
kept in one table so they can be moved into the engine config later. Crossings
are the share of tracked frames with animals in contact (D-8's
``crossing_unique_frame_fraction``), not the older fragment-duration share, which
depends on the group size. An identity-free session is only left unjudged when it
was tracked that way on purpose: low identification of a session that asked for
identities is flagged (D-5's ``identity_free_reason``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Level = Literal["good", "check", "review", "na"]

_ORDER = {"na": 0, "good": 1, "check": 2, "review": 3}

#: measure -> (good limit, check limit); direction is per measure below.
THRESHOLDS = {
    "coverage": (0.95, 0.85),  # higher is better
    "crossings": (0.02, 0.05),  # share of frames; lower is better
    "jumps": (2, 10),  # count; lower is better
    "interpolated": (0.05, 0.15),  # share of frames; lower is better
}


@dataclass(frozen=True)
class Cell:
    text: str
    level: Level


@dataclass
class SessionQuality:
    session_id: str
    coverage: Cell
    identity: Cell
    crossings: Cell
    jumps: Cell
    interpolated: Cell
    verdict: str  # Good | Check | Review
    reasons: list[str] = field(default_factory=list)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _higher_better(value: float | None, good: float, check: float) -> Level:
    if value is None:
        return "na"
    return "good" if value >= good else "check" if value >= check else "review"


def _lower_better(value: float | None, good: float, check: float) -> Level:
    if value is None:
        return "na"
    return "good" if value <= good else "check" if value <= check else "review"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def _column(diagnostics: dict, metric_id: str, column: str, how: str) -> float | None:
    frame = diagnostics.get(metric_id)
    if frame is None or column not in frame or len(frame) == 0:
        return None
    series = frame[column].dropna()
    if series.empty:
        return None
    return float(getattr(series, how)())


def assess_session(result) -> SessionQuality:
    """Quality cells and verdict for one ``SessionRunResult``."""
    sid = result.session_id
    if getattr(result, "error", None):
        bad = Cell("—", "review")
        return SessionQuality(
            sid, bad, bad, bad, bad, bad, "Review", [f"The run failed for {sid}: {result.error}"]
        )

    diag = result.diagnostics or {}
    reasons: list[str] = []

    cov = _column(diag, "D-1", "coverage_fraction", "min")
    cov_level = _higher_better(cov, *THRESHOLDS["coverage"])
    if cov_level in ("check", "review"):
        reasons.append(
            f"Only {_pct(cov)} of positions were tracked for the worst animal "
            f"(good is {THRESHOLDS['coverage'][0] * 100:.0f} % or more)."
        )

    stability = None
    ident_reason = ""
    ident_fraction: float | None = None
    frame = diag.get("D-5")
    if frame is not None and len(frame):
        stability = str(frame["identity_stability_status"].iloc[0])
        if "identity_free_reason" in frame:
            ident_reason = str(frame["identity_free_reason"].iloc[0])
        if "identified_fraction" in frame:
            ident_fraction = _num(frame["identified_fraction"].iloc[0])
    ident = {
        "stable": Cell("Stable", "good"),
        "weak": Cell("Weak", "check"),
        "identity_free": Cell("n/a", "na"),
        "not_assessed": Cell("n/a", "na"),
    }.get(stability or "", Cell("—", "na"))
    if stability == "weak":
        reasons.append("Identities exist but are unreliable; swaps are likely.")
    elif stability == "identity_free" and ident_reason == "low_identification":
        ident = Cell(f"Low ({_pct(ident_fraction)})", "check")
        reasons.append(
            f"Only {_pct(ident_fraction)} of animals were identified although identities were "
            "requested; per-animal results are unreliable."
        )
    elif stability == "identity_free" and ident_reason == "unknown":
        ident = Cell("Unknown", "check")
        shown = "" if ident_fraction is None else f" ({_pct(ident_fraction)} identified)"
        reasons.append(
            "The tracker does not say whether identities were switched off on purpose"
            f"{shown}; mark the session identity-free if they were, otherwise check them."
        )

    unique = _column(diag, "D-8", "crossing_unique_frame_fraction", "max")
    if unique is not None:
        cross = unique
        cross_text = f"Animals cross paths in {_pct(cross)} of frames."
    else:
        # Older diagnostics carry only the fragment-duration share; say what it is.
        cross = _column(diag, "D-8", "crossing_frame_fraction", "max")
        cross_text = f"Crossing fragments make up {_pct(cross)} of all fragment time."
    cross_level = _lower_better(cross, *THRESHOLDS["crossings"])
    if cross_level in ("check", "review"):
        reasons.append(cross_text)

    jumps = _column(diag, "D-10", "teleport_jump_count", "sum")
    jump_level = _lower_better(jumps, *THRESHOLDS["jumps"])
    if jump_level in ("check", "review"):
        limit = THRESHOLDS["jumps"][0]
        reasons.append(f"{int(jumps)} implausible jumps were found (limit {limit}).")

    interp = _column(diag, "D-11", "frac_interpolated", "max")
    interp_level = _lower_better(interp, *THRESHOLDS["interpolated"])
    if interp_level in ("check", "review"):
        reasons.append(
            f"{_pct(interp)} of positions are interpolated "
            f"(limit {THRESHOLDS['interpolated'][0] * 100:.0f} %)."
        )

    cells = SessionQuality(
        sid,
        Cell(_pct(cov), cov_level),
        ident,
        Cell(_pct(cross), cross_level),
        Cell("—" if jumps is None else str(int(jumps)), jump_level),
        Cell(_pct(interp), interp_level),
        "Good",
        reasons,
    )
    worst = max(
        (c.level for c in (cells.coverage, cells.identity, cells.crossings, cells.jumps,
                           cells.interpolated)),
        key=_ORDER.__getitem__,
    )
    cells.verdict = {"review": "Review", "check": "Check"}.get(worst, "Good")
    return cells


def count_verdicts(qualities: list[SessionQuality], excluded: set[str]) -> dict[str, int]:
    """{'Good': n, 'Check': n, 'Review': n} over the sessions not excluded."""
    counts = {"Good": 0, "Check": 0, "Review": 0}
    for q in qualities:
        if q.session_id not in excluded:
            counts[q.verdict] += 1
    return counts
