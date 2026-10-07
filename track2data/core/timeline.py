"""Trajectory-row to video-time mapping, shared by the per-frame table and binning."""

from __future__ import annotations

from typing import Any


def map_array_index_to_true_frame(
    tracking_intervals: list[tuple[int, int]] | None, n_frames: int
) -> tuple[Any, bool]:
    """
    Map trajectory-array row position (0..n_frames-1) to the true video
    frame number, using ``Session.tracking_intervals``.

    idtracker.ai only tracks (and stores trajectory rows for) frames inside
    the configured ``--tracking_intervals``; array position 0 is the first
    frame of the first interval, not frame 0 of the video
    (idtracker.ai_usage.md:552: "Tracking intervals in frames ... If not
    set, the whole video is tracked"; session_idtrackerai.md:240: interval
    end is exclusive). With a single interval starting elsewhere than 0,
    using the raw array position as "frame" understates every frame number
    by the interval's start; with multiple intervals, it also makes the
    derived time axis non-monotonic in real time across the gap between
    intervals.

    Returns
    -------
    true_frames:
        Array of length n_frames with the true video frame number per row.
    valid:
        Whether the mapping could be trusted, i.e. the intervals'
        combined length matches n_frames exactly. When False, true_frames
        is simply ``arange(n_frames)`` (today's behaviour) because the
        intervals don't reconcile with the data -- e.g. a partial/embargoed
        session.json, or gaps closed by preprocessing on idtracker.ai's
        side that this reader has no way to reconstruct.
    """
    import numpy as np

    if not tracking_intervals:
        return np.arange(n_frames), False

    lengths = [max(0, end - start) for start, end in tracking_intervals]
    if sum(lengths) != n_frames:
        return np.arange(n_frames), False

    true_frames = np.empty(n_frames, dtype=np.int64)
    pos = 0
    for (start, _end), length in zip(tracking_intervals, lengths, strict=True):
        true_frames[pos : pos + length] = np.arange(start, start + length)
        pos += length
    return true_frames, True
