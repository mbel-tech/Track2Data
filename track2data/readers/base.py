"""Abstract base class for session readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from track2data.core.models import Session


class SessionReader(ABC):
    """
    Contract that every reader plug-in must satisfy.

    Discovery order: candidates sorted by priority (descending); the first
    whose detect() returns True wins.  Readers with higher priority are
    checked before lower-priority ones.
    """

    #: Unique name used in Session.reader and pyproject entry-point keys.
    name: str = ""
    #: Higher priority wins when multiple readers detect the same folder.
    priority: int = 0

    @classmethod
    @abstractmethod
    def detect(cls, folder: Path) -> bool:
        """Return True if this reader can handle *folder*."""

    @abstractmethod
    def read(self, folder: Path) -> Session:
        """
        Parse *folder* and return a Session.

        Must not modify any file inside *folder* (FR-IMP-5).
        Raises DataValidationError on unrecoverable format problems.
        """
