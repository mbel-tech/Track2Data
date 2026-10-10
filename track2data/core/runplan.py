"""What a run will process: one unit per session (2-D) or per fusable top/side pair (3-D)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from track2data.core.models import SessionRef, ViewPair
    from track2data.fusion.fuse import FusedSession


@dataclass
class RunUnit:
    """One thing the pipeline runs and exports under ``out_dir / unit_id``.

    A 2-D unit is a session (``ref``); a 3-D unit is a fusable pair (``pair``) whose id is
    ``"{top}+{side}"``. ``fused`` is the plan's own fusion result, kept so a serial run does not
    fuse twice; it is never sent to worker processes (they rebuild it from the manifest).
    """

    unit_id: str
    kind: Literal["session", "pair"]
    ref: SessionRef | None = None
    pair: ViewPair | None = None
    fused: FusedSession | None = None


@dataclass
class SkippedSession:
    """A session a 3-D run leaves out, with the reason shown to the user."""

    session_id: str
    reason: str


@dataclass
class RunPlan:
    units: list[RunUnit] = field(default_factory=list)
    skipped: list[SkippedSession] = field(default_factory=list)
