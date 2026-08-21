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

    candidates = [
        ("h5",       traj_dir / "trajectories.h5"),
        ("parquet",  traj_dir / "trajectories.parquet"),
        ("npy",      traj_dir / "trajectories.npy"),
        ("pickle",   traj_dir / "trajectories.pickle"),
        ("csv_tidy", traj_dir / "trajectories_tidy.csv"),
        ("csv",      traj_dir / "trajectories_csv"),
    ]

    found: list[tuple[str, Path]] = [
        (fmt, path) for fmt, path in candidates if path.exists()
    ]

    if not found:
        return None

    best_fmt, best_path = found[0]
    return ReaderHit(format=best_fmt, path=best_path, all_present=found)
