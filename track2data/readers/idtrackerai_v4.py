"""Stub reader for legacy idtracker.ai v4 output — not yet implemented.

``looks_like_v4`` is a deliberately conservative heuristic used only to give a
clear "not supported yet" error instead of a generic "no reader" one. The file
names it checks are from memory of the v4 layout, not from a verified sample
(see docs/IDTRACKERAI_V4_SAMPLES.md and DECISIONS.md D-012); the error message
therefore claims nothing about the layout beyond "looks like".
"""

from __future__ import annotations

from pathlib import Path

from track2data.core.models import Session
from track2data.readers.base import SessionReader


def _has_markers(session_dir: Path) -> bool:
    return (session_dir / "video_object.npy").is_file() and any(
        (session_dir / "preprocessing").glob("blobs_collection*.npy")
    )


def looks_like_v4(folder: Path) -> bool:
    """True if *folder* (or a ``session_*`` folder directly inside it) has both
    ``video_object.npy`` and ``preprocessing/blobs_collection*.npy``."""
    if not folder.is_dir():
        return False
    if _has_markers(folder):
        return True
    return any(_has_markers(d) for d in folder.glob("session_*") if d.is_dir())


class IDTrackerAiV4Reader(SessionReader):
    """Legacy reader — placeholder; will be implemented when v4 samples are available."""

    name = "idtrackerai_v4"
    priority = 5

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False  # disabled until implemented

    def read(self, folder: Path) -> Session:
        raise NotImplementedError("idtrackerai_v4 reader not yet implemented")
