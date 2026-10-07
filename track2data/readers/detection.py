"""What a scan reports: ranked detections with the evidence behind them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from track2data.readers.params import ProposedValue, ReaderParameter


class Confidence(IntEnum):
    """How sure a reader is. HIGH needs a structural marker, no negative marker, no rival."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True)
class SessionCandidate:
    """One session a reader found: where it is and which files belong to it."""

    session_id: str
    #: The session folder, or its primary file for single-file formats.
    source: Path
    files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Detection:
    """A reader's claim over part of a scanned tree."""

    reader: str
    display_name: str
    confidence: Confidence
    evidence: tuple[str, ...] = ()
    sessions: tuple[SessionCandidate, ...] = ()
    parameters: tuple[ReaderParameter, ...] = ()
    proposed: Mapping[str, ProposedValue] = field(default_factory=dict)
    verification: str = "synthetic_only"
