"""
Version-sniffing utilities for idtracker.ai session folders.

Used by readers to determine which format variant to apply before
loading the full trajectory data.
"""

from __future__ import annotations

from pathlib import Path


def sniff_version(folder: Path) -> str | None:
    """
    Return a version hint string or None if the folder is not recognised.

    Current heuristics:
      'v5'  — trajectories/ subdir + video_object.npy present
      'v4'  — trajectories.npy at root level (flat layout, no subdir)
      None  — not a known idtracker.ai output
    """
    if (folder / "trajectories").is_dir() and (folder / "video_object.npy").exists():
        return "v5"
    if (folder / "trajectories.npy").exists():
        return "v4"
    return None
