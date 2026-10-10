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
from track2data.fusion.agreement import agreement
from track2data.fusion.align import (
    FusionError,
    fusable_rows,
    horizontal_cm,
    match_fish,
    match_rows,
)
from track2data.views.panels import keep_animals

#: Overall RMS above this fraction of the top view's range along the axis is a warning.
WARN_FRACTION = 0.10
#: Frame rates that differ by more than this (relative) cannot be aligned frame for frame.
FPS_TOLERANCE = 0.001

__all__ = ["FusedSession", "FusionError", "FusionReport", "fuse"]


@dataclass
class FusionReport:
    """``top_frames`` / ``side_frames`` count the eligible rows of each view (tracked, not
    separators); ``overlap_frames`` the rows both share after the offset."""

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
    #: Not filled by ``fuse`` (the scan is slow); see ``agreement.suggest_offset``.
    suggested_offset: int | None = None


@dataclass
class FusedSession:
    psess: PreprocessedSession
    report: FusionReport
    session_id: str


def _take(arr: np.ndarray | None, rows: np.ndarray, cols: list[int]) -> np.ndarray | None:
    return None if arr is None else arr[rows][:, cols]


def _separate(arr: np.ndarray | None, at: np.ndarray) -> np.ndarray | None:
    """*arr* with one separator row inserted before each row index in *at*: NaN for floats,
    False for flags, "" (no zone) for zone names."""
    if arr is None or at.size == 0:
        return arr
    if arr.dtype == bool:
        fill: object = False
    elif arr.dtype == object:
        fill = ""
    else:
        arr = arr.astype(float, copy=False)
        fill = np.nan
    return np.insert(arr, at, fill, axis=0)


def fuse(
    top: PreprocessedSession,
    side: PreprocessedSession,
    pair: ViewPair,
    *,
    same_video: bool,
) -> FusedSession:
    """Fuse ``side`` into ``top`` as described in the module docstring.

    ``top_frames`` / ``side_frames`` in the report count the eligible rows (tracked, not
    separators). Wherever the kept frames jump (a frame either view lacks), one NaN separator row
    is inserted on every per-row array, as for a 2-D session tracked in separate intervals
    (``preprocess/timeline_expand.py``), so nothing that diffs rows bridges the gap. A fusion
    without jumps has no separator and leaves ``separator_mask`` / ``tracked_mask`` None.
    ``psess.session`` keeps its full-length per-frame data, filtered by animal only.

    Raises ``FusionError`` for missing settings, differing frame rates, an invalid fish map, no
    matched fish, or no frames the two views share. ``same_video`` forces the offset to 0.
    """
    fs = pair.fusion
    if fs is None:
        raise FusionError("no fusion settings for this pair")
    if abs(top.fps - side.fps) > FPS_TOLERANCE * max(top.fps, side.fps):
        raise FusionError(f"frame rates differ: {top.fps:g} vs {side.fps:g} fps")

    keep, side_cols, top_labels, side_labels, fused_labels = match_fish(top, side, pair)
    matched_side = {pair.fish_map[lab] for lab in fused_labels}

    offset = 0 if same_video else fs.frame_offset
    top_rows, top_frames, top_valid = fusable_rows(top)
    side_rows, side_frames, side_valid = fusable_rows(side)
    rows, srows = match_rows(top_rows, top_frames, side_rows, side_frames, offset)
    if rows.size == 0:
        raise FusionError("no shared frames between the two views")

    # Depth: the side view's y between the surface (0) and the floor (1); outside is NaN.
    y = side.xy[srows][:, side_cols, 1]
    x = side.xy[srows][:, side_cols, 0]
    top_ok = np.isfinite(top.xy[rows][:, keep]).all(axis=2)
    valid = np.isfinite(y) & np.isfinite(x) & top_ok
    depth = (y - fs.surface_row) / (fs.floor_row - fs.surface_row)
    with np.errstate(invalid="ignore"):
        # counted on the side y alone; depth is NaN wherever either view lacks a position
        outside = np.isfinite(y) & ~((depth >= 0) & (depth <= 1))
    depth = np.where(valid & ~outside, depth, np.nan)

    kin = top.kinematics
    n = top.n_animals
    fused_id = f"{top.session_id}+{side.session_id}"
    session = keep_animals(top.session, keep).model_copy(update={"session_id": fused_id})

    def per_animal(a: np.ndarray | None) -> np.ndarray | None:
        return a[keep] if a is not None and np.shape(a)[:1] == (n,) else None

    frames = top_frames[np.searchsorted(top_rows, rows)]
    # one separator row before each kept row that does not follow its predecessor's frame
    at = np.flatnonzero(np.diff(frames) > 1) + 1
    separator: np.ndarray | None = None
    if at.size:
        separator = np.insert(np.zeros(frames.size, dtype=bool), at, True)
        # a separator's frame is the one after the frame before it (the 2-D convention)
        frames = np.insert(frames, at, frames[at - 1] + 1)

    def per_row(a: np.ndarray | None) -> np.ndarray | None:
        return _separate(_take(a, rows, keep), at)

    psess = dataclasses.replace(
        top,
        session=session,
        xy=per_row(top.xy),
        kinematics=KinematicsArrays(
            speed_px_s=per_row(kin.speed_px_s),
            accel_px_s2=per_row(kin.accel_px_s2),
            heading_rad=per_row(kin.heading_rad),
        ),
        body_length_cm=per_animal(top.body_length_cm),
        body_length_px=per_animal(top.body_length_px),
        main_zone=per_row(top.main_zone),
        sec_zone=per_row(top.sec_zone),
        jump_replaced=per_row(top.jump_replaced),
        timeline_valid=top_valid and side_valid,
        frame_index=frames,
        tracked_mask=None if separator is None else ~separator,
        separator_mask=separator,
        # the tracker's own positions, laid out on the fused rows
        raw_xy_rows=per_row(top.raw_xy_aligned),
        id_probabilities_rows=per_row(top.id_probabilities_aligned),
        depth=_separate(depth, at),
        depth_height_cm=fs.tank_height_cm,
        depth_outside=outside.sum(axis=0).astype(int),
        depth_outside_mask=_separate(outside, at),
        source_animal_index=np.asarray(keep, dtype=np.int64),
    )
    rms: float | None = None
    per_fish: dict[str, float | None] = {}
    skipped: str | None = None
    warning = False
    if not top.px_per_cm:
        skipped = "top view not calibrated"
    else:
        top_cm, side_cm = horizontal_cm(top, side, pair, rows, srows, keep, side_cols)
        rms, per_list = agreement(top_cm, side_cm)
        per_fish = dict(zip(fused_labels, per_list, strict=True))
        finite = top_cm[np.isfinite(top_cm)]
        span = float(finite.max() - finite.min()) if finite.size else 0.0
        warning = rms is not None and span > 0 and rms > WARN_FRACTION * span
    report = FusionReport(
        overlap_frames=int(rows.size),
        top_frames=int(top_rows.size),
        side_frames=int(side_rows.size),
        fused_labels=fused_labels,
        unmatched_top=[lab for lab in top_labels if lab not in pair.fish_map],
        unmatched_side=[lab for lab in side_labels if lab not in matched_side],
        n_outside_column=int(outside.sum()),
        agreement_rms_cm=rms,
        agreement_per_fish_cm=per_fish,
        agreement_skipped=skipped,
        agreement_warning=warning,
    )
    return FusedSession(psess=psess, report=report, session_id=fused_id)
