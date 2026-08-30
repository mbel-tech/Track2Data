"""Abstract base class for session readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

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
    #: Whether ``read()`` accepts an ``allow_pickle`` keyword. Opt-in so that
    #: external readers written against the original one-argument signature
    #: keep working -- ``read_session`` only passes the keyword to readers
    #: that declare they understand it. A reader that loads pickled data
    #: without declaring this is trusting every file it is pointed at.
    accepts_allow_pickle: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def detect(cls, folder: Path) -> bool:
        """Return True if this reader can handle *folder*."""

    @abstractmethod
    def read(self, folder: Path, *, allow_pickle: bool = False) -> Session:
        """
        Parse *folder* and return a Session.

        Must not modify any file inside *folder* (FR-IMP-5).
        Raises DataValidationError on unrecoverable format problems.

        A reader that can load formats which execute code on deserialisation
        (anything unpickled) should accept a keyword-only
        ``allow_pickle: bool = False`` and set
        :attr:`accepts_allow_pickle` to True, refusing those formats with
        ``IDT_PICKLE_REFUSED`` unless the caller opts in.
        """
