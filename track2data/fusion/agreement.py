"""Do the two views agree on where the fish are along the shared horizontal axis?

``agreement`` compares the side view's horizontal position with one top-view axis (both in cm,
median difference removed per fish). ``suggest_offset`` scans frame lags for the one that makes
the two traces agree best. Pure numpy; no Qt.
"""

from __future__ import annotations

import numpy as np

from track2data.core.models import PreprocessedSession, ViewPair
from track2data.fusion.align import (
    FusionError,
    fusable_rows,
    match_fish,
    match_sorted,
    side_horizontal_cm,
    top_axis_cm,
)

#: Fewest jointly valid samples for a fish's RMS to mean anything.
MIN_FISH_SAMPLES = 3
#: Fewest jointly valid samples (all fish) for a lag to be scored.
MIN_LAG_SAMPLES = 30
#: A suggested lag must beat the lag-0 RMS by this fraction.
LAG_MARGIN = 0.20
#: The lag scan covers +-this many seconds.
LAG_WINDOW_S = 5.0


def agreement(
    top_axis_cm: np.ndarray, side_h_cm: np.ndarray
) -> tuple[float | None, list[float | None]]:
    """(overall RMS, per-fish RMS) in cm of ``side_h_cm - top_axis_cm`` for (n_rows, n_fish) arrays.

    The median difference is removed per fish (the two views have different origins). A fish with
    fewer than ``MIN_FISH_SAMPLES`` jointly valid samples gets ``None`` and is left out of the
    overall value, which pools the residuals of the other fish (``None`` if there are none).
    """
    top = np.asarray(top_axis_cm, dtype=float)
    side = np.asarray(side_h_cm, dtype=float)
    per_fish: list[float | None] = []
    pooled: list[np.ndarray] = []
    for k in range(top.shape[1]):
        diff = side[:, k] - top[:, k]
        diff = diff[np.isfinite(diff)]
        if diff.size < MIN_FISH_SAMPLES:
            per_fish.append(None)
            continue
        resid = diff - np.median(diff)
        per_fish.append(float(np.sqrt(np.mean(resid**2))))
        pooled.append(resid)
    if not pooled:
        return None, per_fish
    return float(np.sqrt(np.mean(np.concatenate(pooled) ** 2))), per_fish


def suggest_offset(
    top: PreprocessedSession, side: PreprocessedSession, pair: ViewPair
) -> int | None:
    """The frame offset (side = top + offset) that makes the views agree best, or ``None``.

    Lags in ``[-window, +window]`` frames, ``window = round(5 s * fps)``, are scored by overall
    RMS; lags with fewer than 30 jointly valid samples are skipped. The best lag is returned only
    if its RMS is at least 20% lower than the lag-0 RMS (and it is not 0). Also ``None`` when the
    pair has no settings, the top view has no ``px_per_cm``, or the pair cannot be fused at all
    (``FusionError`` from the fish map or labels is swallowed: the caller sees fuse's error).
    """
    fs = pair.fusion
    if fs is None or not top.px_per_cm:
        return None
    try:
        keep, side_cols, _, _, _ = match_fish(top, side, pair)
    except FusionError:
        return None
    top_rows, top_frames, _ = fusable_rows(top)
    side_rows, side_frames, _ = fusable_rows(side)
    if top_rows.size == 0 or side_rows.size == 0:
        return None
    # centimetres once over all eligible rows; each lag then only indexes into these
    top_cm = top_axis_cm(top, pair, top_rows, keep)
    side_cm = side_horizontal_cm(side, pair, side_rows, side_cols)
    order = np.argsort(side_frames, kind="stable")
    sorted_frames = side_frames[order]
    side_cm = side_cm[order]
    window = round(LAG_WINDOW_S * top.fps)

    # Consecutive frame numbers (the usual case) match by slicing, with no index arrays.
    def consecutive(f: np.ndarray) -> bool:
        return bool(np.all(np.diff(f) == 1))

    fast = consecutive(top_frames) and consecutive(sorted_frames)

    def matched(lag: int) -> tuple[np.ndarray, np.ndarray]:
        if not fast:
            hit, pos = match_sorted(top_frames, sorted_frames, lag)
            return top_cm[hit], side_cm[pos]
        shift = int(top_frames[0]) + lag - int(sorted_frames[0])  # side index of top row 0
        lo, hi = max(0, -shift), min(top_cm.shape[0], side_cm.shape[0] - shift)
        return top_cm[lo:hi], side_cm[lo + shift : hi + shift]

    def rms_at(lag: int) -> float | None:
        t_cm, s_cm = matched(lag)
        if t_cm.shape[0] == 0:
            return None
        if int(np.isfinite(t_cm + s_cm).sum()) < MIN_LAG_SAMPLES:
            return None
        return agreement(t_cm, s_cm)[0]

    base = rms_at(0)
    if base is None:
        return None
    best_lag, best = 0, base
    for lag in range(-window, window + 1):
        if lag == 0:
            continue
        r = rms_at(lag)
        if r is not None and r < best:
            best_lag, best = lag, r
    if best_lag != 0 and best <= (1 - LAG_MARGIN) * base:
        return best_lag
    return None
