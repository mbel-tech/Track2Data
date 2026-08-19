"""Stub reader for legacy idtracker.ai v4 output — not yet implemented."""

from __future__ import annotations

from pathlib import Path

from track2data.core.models import Session
from track2data.readers.base import SessionReader


class IDTrackerAiV4Reader(SessionReader):
    """Legacy reader — placeholder; will be implemented when v4 samples are available."""

    name = "idtrackerai_v4"
    priority = 5

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False  # disabled until implemented

    def read(self, folder: Path) -> Session:
        raise NotImplementedError("idtrackerai_v4 reader not yet implemented")
