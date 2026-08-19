"""
Reader registry and discovery.

Built-in readers are registered here.  External readers register via the
'track2data.readers' entry point in their own pyproject.toml.
"""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path

from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.idtrackerai.reader import IDTrackerAiReader
from track2data.readers.idtrackerai_v4 import IDTrackerAiV4Reader
from track2data.readers.idtrackerai_v5 import IDTrackerAiV5Reader

log = logging.getLogger(__name__)

_REGISTRY: list[type[SessionReader]] = []


def register(reader_cls: type[SessionReader]) -> None:
    if reader_cls not in _REGISTRY:
        _REGISTRY.append(reader_cls)
        _REGISTRY.sort(key=lambda r: r.priority, reverse=True)


def _load_entry_points() -> None:
    try:
        eps = importlib.metadata.entry_points(group="track2data.readers")
        for ep in eps:
            try:
                cls = ep.load()
                register(cls)
            except Exception as exc:
                log.warning("Failed to load reader entry point %s: %s", ep.name, exc)
    except Exception as exc:
        log.debug("Entry-point discovery failed: %s", exc)


# Register built-ins — unified reader has highest priority (20) so it wins
# over the legacy v5 (10) and v4 (5) readers when the folder is detected.
register(IDTrackerAiReader)
register(IDTrackerAiV5Reader)
register(IDTrackerAiV4Reader)
_load_entry_points()


def detect_reader(folder: Path) -> type[SessionReader] | None:
    """Return the highest-priority reader that detects *folder*, or None."""
    for cls in _REGISTRY:
        try:
            if cls.detect(folder):
                return cls
        except Exception as exc:
            log.debug("Reader %s raised during detect: %s", cls.name, exc)
    return None


def read_session(folder: Path) -> Session:
    """Auto-detect the reader for *folder* and return a Session."""
    from track2data.core.errors import ImportError_
    cls = detect_reader(folder)
    if cls is None:
        raise ImportError_(
            f"No reader recognised the session folder: {folder}",
            code="NO_READER",
            subject=str(folder),
            remediation="Ensure the folder is a valid idtracker.ai output directory.",
        )
    return cls().read(folder)


__all__ = [
    "IDTrackerAiReader",
    "IDTrackerAiV4Reader",
    "IDTrackerAiV5Reader",
    "SessionReader",
    "detect_reader",
    "read_session",
    "register",
]
