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

    Two layouts are recognised: a compact array holding only the tracked
    frames (the intervals' combined length equals ``n_frames``), and an array
    that already spans the whole stretch from the first to the last tracked
    frame (that span equals ``n_frames``), which is never expanded twice.

    Returns
    -------
    true_frames:
        Array of length n_frames with the true video frame number per row.
    valid:
        Whether the mapping could be trusted: the intervals are well formed
        (ordered, non-overlapping, half-open, non-negative) and reconcile with
        ``n_frames``. When False, true_frames is simply ``arange(n_frames)``
        because the intervals don't match the data -- e.g. a partial/embargoed
        session.json, or gaps closed by preprocessing on idtracker.ai's side
        that this reader has no way to reconstruct. ``timeline_problem`` says
        which of these it was.
    """
    import numpy as np

    if not tracking_intervals or timeline_problem(tracking_intervals, n_frames) is not None:
        return np.arange(n_frames), False

    lengths = [end - start for start, end in tracking_intervals]
    if sum(lengths) != n_frames:
        # already the whole timeline: first tracked frame .. last tracked frame
        first = tracking_intervals[0][0]
        return first + np.arange(n_frames, dtype=np.int64), True

    true_frames = np.empty(n_frames, dtype=np.int64)
    pos = 0
    for (start, _end), length in zip(tracking_intervals, lengths, strict=True):
        true_frames[pos : pos + length] = np.arange(start, start + length)
        pos += length
    return true_frames, True


def timeline_problem(
    tracking_intervals: list[tuple[int, int]] | None, n_frames: int
) -> str | None:
    """Why *tracking_intervals* cannot be trusted as the timeline of *n_frames* rows.

    None when they can, and also when there are no intervals at all: that is missing metadata,
    not malformed metadata, and keeps the documented row-position fallback.
    """
    if not tracking_intervals:
        return None
    previous_end = -1
    for start, end in tracking_intervals:
        if start < 0:
            return f"tracking interval ({start}, {end}) starts before frame 0"
        if end <= start:
            return f"tracking interval ({start}, {end}) is empty or ends before it starts"
        if start < previous_end:
            return f"tracking interval ({start}, {end}) overlaps or precedes the one before it"
        previous_end = end
    covered = sum(end - start for start, end in tracking_intervals)
    span = tracking_intervals[-1][1] - tracking_intervals[0][0]
    if n_frames not in (covered, span):
        return (
            f"the tracking intervals cover {covered} frames but the trajectory has "
            f"{n_frames} rows"
        )
    return None


def segment_starts(true_frames: Any) -> list[int]:
    """Rows that begin a new unbroken stretch: row i where the video frame does not follow
    row i-1. Empty for a contiguous session, so nothing downstream changes for one."""
    import numpy as np

    frames = np.asarray(true_frames)
    if len(frames) < 2:
        return []
    return [int(i) + 1 for i in np.flatnonzero(np.diff(frames) != 1)]
