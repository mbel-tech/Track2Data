"""Row and fish alignment shared by ``fuse`` and the offset suggestion.

Alignment is on video frame numbers (``PreprocessedSession.timeline()``): side frame = top frame +
offset. Pure numpy; no Qt.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import FusionSettings, PreprocessedSession, ViewPair
from track2data.views.pairing import fish_labels, validate_fish_map


class FusionError(ValueError):
    """The pair cannot be fused; the message says why, in words for the user."""


def fusable_rows(psess: PreprocessedSession) -> tuple[np.ndarray, np.ndarray, bool]:
    """(row numbers, their true video frames, timeline verified) of the observed-video rows."""
    frames, valid = psess.timeline()
    frames = np.asarray(frames)
    ok = psess.counted_rows()
    if psess.tracked_mask is not None:
        ok = ok & np.asarray(psess.tracked_mask, dtype=bool)
    rows = np.flatnonzero(ok)
    return rows, frames[rows], bool(valid)


def match_sorted(
    top_frames: np.ndarray, sorted_side_frames: np.ndarray, offset: int
) -> tuple[np.ndarray, np.ndarray]:
    """(indices into ``top_frames``, into ``sorted_side_frames``) with side = top + offset."""
    if top_frames.size == 0 or sorted_side_frames.size == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    target = top_frames + offset
    pos = np.clip(np.searchsorted(sorted_side_frames, target), 0, sorted_side_frames.size - 1)
    hit = np.flatnonzero(sorted_side_frames[pos] == target)
    return hit, pos[hit]


def match_rows(
    top_rows: np.ndarray,
    top_frames: np.ndarray,
    side_rows: np.ndarray,
    side_frames: np.ndarray,
    offset: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Row pairs (top row, side row) with side frame = top frame + offset, in top order."""
    order = np.argsort(side_frames, kind="stable")
    hit, pos = match_sorted(top_frames, side_frames[order], offset)
    return top_rows[hit], side_rows[order[pos]]


def match_fish(
    top: PreprocessedSession, side: PreprocessedSession, pair: ViewPair
) -> tuple[list[int], list[int], list[str], list[str], list[str]]:
    """(top columns kept, side columns, top labels, side labels, fused labels) from the fish map.

    Raises ``FusionError`` for inconsistent labels, an invalid map or no matched fish.
    """
    top_labels = fish_labels(top.session.identities_labels, top.n_animals)
    side_labels = fish_labels(side.session.identities_labels, side.n_animals)
    for name, psess, labels in (("top", top, top_labels), ("side", side, side_labels)):
        given = psess.session.identities_labels
        if given and len(given) != psess.n_animals:
            raise FusionError(f"fish labels do not match the number of animals in the {name} view")
        if len(set(labels)) != len(labels):
            raise FusionError(f"duplicate fish labels in the {name} view")
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
    return keep, side_cols, top_labels, side_labels, fused_labels


def _settings(pair: ViewPair) -> FusionSettings:
    if pair.fusion is None:
        raise FusionError("no fusion settings for this pair")
    return pair.fusion


def top_axis_cm(
    top: PreprocessedSession, pair: ViewPair, rows: np.ndarray, keep: list[int]
) -> np.ndarray:
    """The top view's chosen axis in cm, (len(rows), len(keep))."""
    fs = _settings(pair)
    axis = 0 if fs.horizontal_axis == "x" else 1
    return top.xy[:, :, axis][rows][:, keep] / top.px_per_cm


def side_horizontal_cm(
    side: PreprocessedSession, pair: ViewPair, rows: np.ndarray, cols: list[int]
) -> np.ndarray:
    """The side view's horizontal position in cm, (len(rows), len(cols)); negated when ``flip``."""
    fs = _settings(pair)
    side_scale = (fs.floor_row - fs.surface_row) / fs.tank_height_cm
    cm = side.xy[:, :, 0][rows][:, cols] / side_scale
    return -cm if fs.flip else cm


def horizontal_cm(
    top: PreprocessedSession,
    side: PreprocessedSession,
    pair: ViewPair,
    rows: np.ndarray,
    srows: np.ndarray,
    keep: list[int],
    side_cols: list[int],
) -> tuple[np.ndarray, np.ndarray]:
    """(top axis, side horizontal) in cm on the matched rows."""
    return top_axis_cm(top, pair, rows, keep), side_horizontal_cm(side, pair, srows, side_cols)
