"""
Session-folder detection for idtracker.ai output.

Priority order: h5 > parquet > npy > pickle > csv_tidy > csv_bundle > legacy.
Rationale: h5 is binary, cross-platform, and secure; parquet next; npy/pickle
last for safety.  csv_bundle is universal in the observed corpus.

Candidate paths are built from fixed literal filenames ("trajectories.h5",
etc.), so macOS resource-fork files (._trajectories.h5, ...) never match
them regardless -- there is nothing to filter at this layer. Real
resource-fork filtering (needed where this reader globs a directory rather
than checking one fixed name) lives in custom_artefacts.py,
preprocessing.py, and blobs.py, each via `not name.startswith("._")`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from track2data.readers.index import ScanIndex
from track2data.readers.peek import Peeker

#: Trajectory artefacts inside ``<session>/trajectories/``, in priority order: (format, name).
TRAJECTORY_ARTEFACTS: tuple[tuple[str, str], ...] = (
    ("h5", "trajectories.h5"),
    ("parquet", "trajectories.parquet"),
    ("npy", "trajectories.npy"),
    ("pickle", "trajectories.pickle"),
    ("csv_tidy", "trajectories_tidy.csv"),
    ("csv", "trajectories_csv"),
)

#: The v5 layout keeps its video metadata in a pickled object next to ``trajectories/``.
VIDEO_OBJECT_NAME = "video_object.npy"


@dataclass
class ReaderHit:
    """Result of a successful detect() call."""

    format: str
    path: Path
    # All detected formats in priority order: [(format_name, path), ...]
    all_present: list[tuple[str, Path]] = field(default_factory=list)


def detect(folder: Path) -> ReaderHit | None:
    """
    Probe *folder* for an idtracker.ai session and return the best ReaderHit.

    Returns None when the folder is not a recognisable session.
    """
    folder = Path(folder)
    traj_dir = folder / "trajectories"

    if not traj_dir.is_dir():
        return None

    found: list[tuple[str, Path]] = [
        (fmt, traj_dir / name)
        for fmt, name in TRAJECTORY_ARTEFACTS
        if (traj_dir / name).exists()
    ]

    if not found:
        return None

    best_fmt, best_path = found[0]
    return ReaderHit(format=best_fmt, path=best_path, all_present=found)


def hit_from_index(index: ScanIndex, folder: Path) -> ReaderHit | None:
    """The same answer as :func:`detect`, read from a scan index instead of the file system."""
    traj = index.child(folder, "trajectories")
    if traj is None or not traj.is_dir:
        return None
    found = [
        (fmt, traj.path / name)
        for fmt, name in TRAJECTORY_ARTEFACTS
        if index.child(traj.path, name) is not None
    ]
    if not found:
        return None
    best_fmt, best_path = found[0]
    return ReaderHit(format=best_fmt, path=best_path, all_present=found)


def is_v5_layout(hit: ReaderHit, *, has_video_object: bool, peek: Peeker) -> bool:
    """True when *hit* is the legacy v5 layout rather than idtracker.ai 6's.

    Both keep ``trajectories/trajectories.npy``. In 6.x it is a pickled dict (an object array);
    in the v5 layout it is a raw float array and ``video_object.npy`` sits next to
    ``trajectories/``. The two are told apart from the ``.npy`` header alone, so nothing is
    unpickled.

    A raw array with no ``video_object.npy`` is deliberately *not* v5: the unified reader keeps
    claiming it so that reading it explains what is wrong, instead of "no reader recognised".
    """
    if [fmt for fmt, _ in hit.all_present] != ["npy"] or not has_video_object:
        return False
    header = peek.npy_header(hit.path)
    return header is not None and not header.is_object
