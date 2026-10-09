"""Fuse a matched top/side pair of preprocessed sessions into one session with a depth.

The result is the top view restricted to the video frames both views have and to the fish in the
pair's ``fish_map``, plus ``PreprocessedSession.depth``: the side view's y between the water
surface (0) and the tank floor (1), never clipped (out-of-column samples become NaN).

Alignment is on video frame numbers (``PreprocessedSession.timeline()``): side frame = top frame +
``frame_offset``. Rows that stand for unobserved video (``separator_mask``, and rows not marked in
``tracked_mask``) are never fused. Pure numpy; no Qt.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from track2data.core.models import KinematicsArrays, PreprocessedSession, ViewPair
from track2data.views.pairing import fish_labels, validate_fish_map
from track2data.views.panels import keep_animals

#: Frame rates that differ by more than this (relative) cannot be aligned frame for frame.
FPS_TOLERANCE = 0.001


class FusionError(ValueError):
    """The pair cannot be fused; the message says why, in words for the user."""


@dataclass
class FusionReport:
    overlap_frames: int
    top_frames: int
    side_frames: int
    fused_labels: list[str]
    unmatched_top: list[str]
    unmatched_side: list[str]
    n_outside_column: int
    agreement_rms_cm: float | None = None
    agreement_per_fish_cm: dict[str, float | None] = field(default_factory=dict)
    agreement_skipped: str | None = None
    agreement_warning: bool = False
    suggested_offset: int | None = None


@dataclass
class FusedSession:
    psess: PreprocessedSession
    report: FusionReport
    session_id: str


def _fusable_rows(psess: PreprocessedSession) -> tuple[np.ndarray, np.ndarray]:
    """(row numbers, their true video frames) of the rows that stand for observed video."""
    frames, _ = psess.timeline()
    frames = np.asarray(frames)
    ok = psess.counted_rows()
    if psess.tracked_mask is not None:
        ok = ok & np.asarray(psess.tracked_mask, dtype=bool)
    rows = np.flatnonzero(ok)
    return rows, frames[rows]


def _match_rows(
    top_rows: np.ndarray,
    top_frames: np.ndarray,
    side_rows: np.ndarray,
    side_frames: np.ndarray,
    offset: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Row pairs (top row, side row) with side frame = top frame + offset, in top order."""
    if top_rows.size == 0 or side_rows.size == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    order = np.argsort(side_frames, kind="stable")
    sorted_frames = side_frames[order]
    target = top_frames + offset
    pos = np.clip(np.searchsorted(sorted_frames, target), 0, sorted_frames.size - 1)
    hit = sorted_frames[pos] == target
    return top_rows[hit], side_rows[order[pos[hit]]]


def _take(arr: np.ndarray | None, rows: np.ndarray, cols: list[int]) -> np.ndarray | None:
    return None if arr is None else arr[rows][:, cols]


def fuse(
    top: PreprocessedSession,
    side: PreprocessedSession,
    pair: ViewPair,
    *,
    same_video: bool,
) -> FusedSession:
    """Fuse ``side`` into ``top`` as described in the module docstring.

    Raises ``FusionError`` for missing settings, differing frame rates, an invalid fish map, no
    matched fish, or no frames the two views share. ``same_video`` forces the offset to 0.
    """
    fs = pair.fusion
    if fs is None:
        raise FusionError("no fusion settings for this pair")
    if abs(top.fps - side.fps) > FPS_TOLERANCE * max(top.fps, side.fps):
        raise FusionError(f"frame rates differ: {top.fps:g} vs {side.fps:g} fps")

    top_labels = fish_labels(top.session.identities_labels, top.n_animals)
    side_labels = fish_labels(side.session.identities_labels, side.n_animals)
    msgs = validate_fish_map(
        pair.fish_map,
        top_labels,
        side_labels,
        top_identity_free=not top.session.has_stable_identities,
        side_identity_free=not side.session.has_stable_identities,
    )
    if msgs:
        raise FusionError("; ".join(msgs))
    if not pair.fish_map:
        raise FusionError("no fish are matched")

    keep = [i for i, lab in enumerate(top_labels) if lab in pair.fish_map]
    side_cols = [side_labels.index(pair.fish_map[top_labels[i]]) for i in keep]
    fused_labels = [top_labels[i] for i in keep]
    matched_side = {pair.fish_map[lab] for lab in fused_labels}

    offset = 0 if same_video else fs.frame_offset
    top_rows, top_frames = _fusable_rows(top)
    side_rows, side_frames = _fusable_rows(side)
    rows, srows = _match_rows(top_rows, top_frames, side_rows, side_frames, offset)
    if rows.size == 0:
        raise FusionError("no shared frames between the two views")

    # Depth: the side view's y between the surface (0) and the floor (1); outside is NaN.
    y = side.xy[srows][:, side_cols, 1]
    x = side.xy[srows][:, side_cols, 0]
    top_ok = np.isfinite(top.xy[rows][:, keep]).all(axis=2)
    valid = np.isfinite(y) & np.isfinite(x) & top_ok
    depth = (y - fs.surface_row) / (fs.floor_row - fs.surface_row)
    with np.errstate(invalid="ignore"):
        outside = valid & ~((depth >= 0) & (depth <= 1))
    depth = np.where(valid & ~outside, depth, np.nan)

    kin = top.kinematics
    n = top.n_animals
    fused_id = f"{top.session_id}+{side.session_id}"
    session = keep_animals(top.session, keep).model_copy(update={"session_id": fused_id})

    def per_animal(a: np.ndarray | None) -> np.ndarray | None:
        return a[keep] if a is not None and np.shape(a)[:1] == (n,) else None

    psess = dataclasses.replace(
        top,
        session=session,
        xy=top.xy[rows][:, keep],
        kinematics=KinematicsArrays(
            speed_px_s=kin.speed_px_s[rows][:, keep],
            accel_px_s2=kin.accel_px_s2[rows][:, keep],
            heading_rad=kin.heading_rad[rows][:, keep],
        ),
        body_length_cm=per_animal(top.body_length_cm),
        body_length_px=per_animal(top.body_length_px),
        main_zone=_take(top.main_zone, rows, keep),
        sec_zone=_take(top.sec_zone, rows, keep),
        jump_replaced=_take(top.jump_replaced, rows, keep),
        frame_index=top_frames[np.searchsorted(top_rows, rows)],
        tracked_mask=None,
        separator_mask=None,
        # the tracker's own positions, laid out on the fused rows
        raw_xy_rows=_take(top.raw_xy_aligned, rows, keep),
        id_probabilities_rows=_take(top.id_probabilities_aligned, rows, keep),
        depth=depth,
    )
    report = FusionReport(
        overlap_frames=int(rows.size),
        top_frames=int(top_rows.size),
        side_frames=int(side_rows.size),
        fused_labels=fused_labels,
        unmatched_top=[lab for lab in top_labels if lab not in pair.fish_map],
        unmatched_side=[lab for lab in side_labels if lab not in matched_side],
        n_outside_column=int(outside.sum()),
    )
    return FusedSession(psess=psess, report=report, session_id=fused_id)
