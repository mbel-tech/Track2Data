"""What a run will process: one unit per session (2-D) or per fusable top/side pair (3-D)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from track2data.core.models import FusionSettings, SessionRef, ViewPair
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


@dataclass(frozen=True)
class FusionRunInfo:
    """Provenance of one pair unit, as ``sessions.csv`` and the session README report it.

    Small and plain (no arrays) so it rides back from a worker process on ``SessionRunResult``.
    Fish lists are joined with ``";"`` ("" when none).
    """

    unit_kind: Literal["pair"]
    top_session_id: str
    side_session_id: str
    fusion_frame_offset: int
    fusion_axis: str
    fusion_flip: bool
    fusion_surface_row: float
    fusion_floor_row: float
    fusion_tank_height_cm: float
    fusion_overlap_frames: int
    fusion_fused_fish: int
    fusion_unmatched_top: str
    fusion_unmatched_side: str
    fusion_outside_column: int
    fusion_agreement_rms_cm: float | None
    fusion_agreement_warning: bool
    fusion_agreement_skipped: str | None

    @classmethod
    def from_fused(
        cls, pair: ViewPair, settings: FusionSettings, fused: FusedSession
    ) -> FusionRunInfo:
        """Built from the pair, the settings it was fused with (pass the offset actually applied:
        a single-video layout fuses with offset 0) and the fusion's report."""
        rep = fused.report
        return cls(
            unit_kind="pair",
            top_session_id=pair.top_session_id,
            side_session_id=pair.side_session_id,
            fusion_frame_offset=settings.frame_offset,
            fusion_axis=settings.horizontal_axis,
            fusion_flip=settings.flip,
            fusion_surface_row=settings.surface_row,
            fusion_floor_row=settings.floor_row,
            fusion_tank_height_cm=settings.tank_height_cm,
            fusion_overlap_frames=rep.overlap_frames,
            fusion_fused_fish=len(rep.fused_labels),
            fusion_unmatched_top=";".join(rep.unmatched_top),
            fusion_unmatched_side=";".join(rep.unmatched_side),
            fusion_outside_column=rep.n_outside_column,
            fusion_agreement_rms_cm=rep.agreement_rms_cm,
            fusion_agreement_warning=rep.agreement_warning,
            fusion_agreement_skipped=rep.agreement_skipped,
        )

    def as_row(self) -> dict[str, Any]:
        """The fields in column order, for a provenance row."""
        return asdict(self)
