"""Abstract base class for session readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal

from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.discovery import claim_sessions
from track2data.readers.index import ScanIndex
from track2data.readers.params import ReaderParameter
from track2data.readers.peek import Peeker


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
    #: Whether the tracker reports how well it kept identities (idtracker.ai's
    #: ``fraction_identified``). The D-5 identity-stability diagnostic is built on it, so for a
    #: tracker without one the diagnostic reports "not assessed" instead of "weak".
    provides_identification_quality: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def detect(cls, folder: Path) -> bool:
        """Return True if this reader can handle *folder*."""

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        """Report the sessions this reader finds in a scanned tree.

        The default wraps :meth:`detect` for readers written before scanning existed: it asks
        ``detect(folder)`` about each directory in the index, breadth-first, and does not look
        inside a folder it has already claimed. A boolean says nothing about how sure the reader
        is, so it can only report MEDIUM confidence, and it probes the file system once per
        directory. A reader should override this with a pure function of *index* and *peek*.

        Must not raise for any tree; a reader that does is reported as a warning and skipped.
        """

        def accept(folder: Path) -> SessionCandidate | None:
            try:
                if not cls.detect(folder):
                    return None
            except Exception:  # a reader's detect() must never break a scan
                return None
            return SessionCandidate(session_id=default_session_id(folder), source=folder)

        sessions = claim_sessions(index, accept)
        if not sessions:
            return []
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name or cls.name,
                confidence=Confidence.MEDIUM,
                evidence=(f"{cls.name}.detect() accepted {len(sessions)} folder(s)",),
                sessions=tuple(sessions),
                parameters=cls.parameters,
                verification=cls.verification,
            )
        ]

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

    def probe(
        self,
        folder: Path,
        *,
        allow_pickle: bool = False,
        options: Mapping[str, Any] | None = None,
    ) -> Session:
        """
        Read only what the GUI needs to describe *folder* (frame count, fps,
        animals, identity flags, calibration/ROI hints, background image).

        Readers override this to skip expensive optional artefacts; the
        default falls back to a full ``read()`` so every reader stays valid.

        ``allow_pickle`` and ``options`` are what ``read`` takes: a probe opens
        the same trajectory file, so it must be refused pickled data exactly as
        a read is, and a reader whose files do not record its frame rate needs
        the same answer. The default hands each on to ``read`` only if the reader
        declares it (:attr:`accepts_allow_pickle`, :attr:`parameters`); a reader
        that overrides ``probe`` must accept the keywords it declares.
        """
        kwargs: dict[str, Any] = {}
        if self.accepts_allow_pickle:
            kwargs["allow_pickle"] = allow_pickle
        if self.parameters:
            kwargs["options"] = options
        return self.read(folder, **kwargs)
