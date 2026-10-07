"""Abstract base class for session readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Literal

from track2data.core.models import Session
from track2data.readers.params import ReaderParameter


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
    #: Name shown in the confirm dialog ("DeepLabCut (CSV/H5)"). Empty falls back to ``name``.
    display_name: ClassVar[str] = ""
    #: Options the reader must be told because its files do not say (readers/params.py).
    #: Empty means it takes none, and ``read`` is called without ``options``. A reader that
    #: declares parameters also accepts a keyword-only ``options`` mapping on ``read``.
    parameters: ClassVar[tuple[ReaderParameter, ...]] = ()
    #: "real_sample": tested against real tracker output. "synthetic_only": built from the
    #: documented layout alone (DECISIONS D-012). Shown as a badge, recorded in provenance.
    verification: ClassVar[Literal["real_sample", "synthetic_only"]] = "synthetic_only"
    #: Whether coordinates are in the image's pixel frame (zones and the background image only
    #: make sense then), or in physical units that are / are not aligned with that frame.
    coordinate_frame: ClassVar[Literal["image_px", "physical_aligned", "physical_unaligned"]] = (
        "image_px"
    )
    #: Whether the reader supplies per-animal body length (the default calibration needs it).
    provides_body_length: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def detect(cls, folder: Path) -> bool:
        """Return True if this reader can handle *folder*."""

    @abstractmethod
    def read(self, folder: Path, *, allow_pickle: bool = False) -> Session:
        """
        Parse *folder* and return a Session.

        *folder* is the session folder, or its primary file for single-file formats. A folder
        that holds several sessions raises ``SESSION_AMBIGUOUS`` listing the candidates.

        Must not modify any file inside *folder* (FR-IMP-5).
        Raises DataValidationError on unrecoverable format problems.

        A reader that can load formats which execute code on deserialisation
        (anything unpickled) should accept a keyword-only
        ``allow_pickle: bool = False`` and set
        :attr:`accepts_allow_pickle` to True, refusing those formats with
        ``IDT_PICKLE_REFUSED`` unless the caller opts in.
        """
