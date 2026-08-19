"""
Session-folder detection for idtracker.ai output.

Priority order: h5 > parquet > npy > pickle > csv_tidy > csv_bundle > legacy.
Rationale: h5 is binary, cross-platform, and secure; parquet next; npy/pickle
last for safety.  csv_bundle is universal in the observed corpus.

macOS resource-fork files (._*) are filtered at this layer and never returned
as candidate trajectory files.
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


def _is_resource_fork(p: Path) -> bool:
    return p.name.startswith("._")


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

    found: list[tuple[str, Path]] = []
    for fmt, path in candidates:
        if _is_resource_fork(path):
            continue
        if path.exists() and not _is_resource_fork(path):
            found.append((fmt, path))

    if not found:
        return None

    best_fmt, best_path = found[0]
    return ReaderHit(format=best_fmt, path=best_path, all_present=found)
