"""
Opportunistic loaders for custom post-processing artefacts.

These files are NOT part of idtracker.ai itself — they come from the user's
own post-processing pipeline.  All loaders:
  - Return None (or []) when the file is absent.
  - Never crash the reader.
  - Are loaded silently (A7 decision: default-on, no noise when absent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_inconsistent_frames(folder: Path) -> set[int] | None:
    """
    Load inconsistent_frames.csv → set of integer frame indices.

    The file has no header and a single column of integer frame indices.
    Returns None when the file is absent.
    """
    path = Path(folder) / "inconsistent_frames.csv"
    if not path.exists():
        return None
    try:
        frames: set[int] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                frames.add(int(line))
        return frames
    except Exception:
        return None


def load_bbox_table(folder: Path) -> Any | None:
    """
    Load the per-(frame, identity) bounding-box CSV → pd.DataFrame.

    The file is named <session_name>_bboxes.csv and is located inside
    trajectories/trajectories_csv/.  Pandas is imported lazily so callers
    without pandas still get None rather than an ImportError.

    Returns None when no such file is found.
    """
    csv_dir = Path(folder) / "trajectories" / "trajectories_csv"
    if not csv_dir.is_dir():
        return None

    candidates = [p for p in csv_dir.glob("*_bboxes.csv") if not p.name.startswith("._")]
    if not candidates:
        return None

    path = candidates[0]
    try:
        import pandas as pd  # type: ignore[import]
        return pd.read_csv(path)
    except Exception:
        return None


def load_bbox_summary(folder: Path) -> dict[str, Any] | None:
    """
    Load the per-session bbox QC summary → dict.

    The file is named <session_name>_bboxes_summary.json inside
    trajectories/trajectories_csv/.  Returns None when absent.
    """
    csv_dir = Path(folder) / "trajectories" / "trajectories_csv"
    if not csv_dir.is_dir():
        return None

    candidates = [
        p for p in csv_dir.glob("*_bboxes_summary.json")
        if not p.name.startswith("._")
    ]
    if not candidates:
        return None

    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def load_matching_results(folder: Path) -> list[str]:
    """
    List session names matched by idmatcher.ai in matching_results/.

    Returns an empty list when the directory is absent (v1.0: list-and-ignore).
    """
    mr_dir = Path(folder) / "matching_results"
    if not mr_dir.is_dir():
        return []
    return [
        p.name for p in mr_dir.iterdir()
        if p.is_dir() and not p.name.startswith("._")
    ]
