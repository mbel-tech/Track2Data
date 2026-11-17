"""Shared constants and helpers for metric edge-case notes (decision D-054).

A metric that hits an edge case does not stay silent. It returns a ``note``
column (an empty string when there is nothing to say; the same channel the
D-* diagnostics already use) and an ``n_frames_used`` column, and gives NaN
rather than a number it cannot stand behind.
"""

from __future__ import annotations

# A mean/median over fewer frames than this is not reported (GL-4, GL-13).
MIN_USABLE_FRAMES = 5

# A share of collinear (GL-4) or coincident-position (GL-13) cases at or above
# this is worth a note.
NOTE_FRACTION = 0.05

# GL-15 drops a frame whose minor-axis SD is below this fraction of the major-axis SD
# (an elongation ratio above 100): the group is a line, and the ratio is noise.
LINE_LIKE_SD_RATIO = 0.01

# GL-15 reports no orientation when the axes of the individual frames agree less than this.
MIN_AXIS_CONSISTENCY = 0.1

# GL-15 is unreliable for groups smaller than this.
RELIABLE_GROUP_SIZE = 6

# IL-11
MIN_HEADINGS = 10
MEAN_HEADING_ALPHA = 0.05
MIN_RESULTANT_LENGTH = 0.1
TURN_WINDOW_S = 0.5


def join_notes(*parts: str) -> str:
    """Join the non-empty notes into one cell."""
    return " ".join(p.strip() for p in parts if p and p.strip())


def usable_frames_note(n_used: int, what: str = "") -> str:
    """The note that accompanies a NaN result: how many frames were usable."""
    suffix = f" ({what})" if what else ""
    return f"NaN: only {n_used} usable frames{suffix}."
