"""Helpers shared by the readers' ``discover``: claiming session folders in an index."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from track2data.readers.detection import SessionCandidate
from track2data.readers.index import ScanIndex


def claim_sessions(
    index: ScanIndex,
    accept: Callable[[Path], SessionCandidate | None],
) -> list[SessionCandidate]:
    """Walk the index's directories breadth-first, asking *accept* about each.

    A claimed folder is a leaf: nothing inside it is offered again, so a session's own
    subfolders (``preprocessing/``, ``trajectories_csv/``) are never mistaken for sessions.
    """
    claimed: list[Path] = []
    found: list[SessionCandidate] = []
    for entry in index.dirs():
        if any(folder in entry.path.parents for folder in claimed):
            continue
        candidate = accept(entry.path)
        if candidate is not None:
            claimed.append(entry.path)
            found.append(candidate)
    return found
