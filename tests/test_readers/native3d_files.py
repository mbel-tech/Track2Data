"""Writers of synthetic native 3-D tracker files for the reader tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np


def write_anipose_csv(
    path: Path,
    keypoints: Sequence[str],
    frames: Sequence[int] | int,
    *,
    xyz: np.ndarray | None = None,
    score: np.ndarray | None = None,
    extra_columns: bool = True,
    frame_column: bool = True,
) -> Path:
    """Write an Anipose pose-3d CSV and return its path.

    *frames* is the list of ``fnum`` values (or a count for 0..n-1); *xyz* ``(F, K, 3)`` defaults
    to distinct, easy-to-read values (``100 * k + 10 * axis + frame``) and *score* ``(F, K)`` to 1.
    NaN in *xyz* is written as an empty cell, as Anipose does.
    """
    fnum = list(range(frames)) if isinstance(frames, int) else list(frames)
    n, k = len(fnum), len(keypoints)
    if xyz is None:
        base = np.arange(n, dtype=float)[:, None, None]
        xyz = base + 100.0 * np.arange(k)[None, :, None] + 10.0 * np.arange(3)[None, None, :]
    if score is None:
        score = np.ones((n, k))
    header: list[str] = []
    for name in keypoints:
        header += [f"{name}_x", f"{name}_y", f"{name}_z", f"{name}_error", f"{name}_ncams"]
        header += [f"{name}_score"]
    if extra_columns:
        header += [f"M_{i}{j}" for i in range(3) for j in range(3)]
        header += ["center_0", "center_1", "center_2"]
    if frame_column:
        header.append("fnum")

    def cell(value: float) -> str:
        return "" if not np.isfinite(value) else repr(float(value))

    lines = [",".join(header)]
    for row in range(n):
        cells: list[str] = []
        for j in range(k):
            cells += [cell(xyz[row, j, a]) for a in range(3)]
            cells += ["0.1", "4", cell(score[row, j])]
        if extra_columns:
            cells += ["1" if i == j else "0" for i in range(3) for j in range(3)]
            cells += ["0", "0", "0"]
        if frame_column:
            cells.append(str(fnum[row]))
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n")
    return path


def write_dlc3d_csv(
    path: Path,
    bodyparts: Sequence[str],
    frames: Sequence[int] | int,
    *,
    xyz: np.ndarray | None = None,
    scorer: str = "DLC_3D",
    coords: Sequence[str] = ("x", "y", "z"),
) -> Path:
    """Write a DeepLabCut-3D triangulated table and return its path.

    Three header rows (``scorer``, ``bodyparts``, ``coords``), then one line per frame whose first
    cell is the frame number. *frames* is the list of first-column values (or a count for 0..n-1);
    *xyz* ``(F, K, 3)`` defaults to ``frame + 100 * k + 10 * axis``. NaN is written as an empty
    cell. *coords* renames the three columns (to build near-miss headers).
    """
    index = list(range(frames)) if isinstance(frames, int) else list(frames)
    n, k = len(index), len(bodyparts)
    if xyz is None:
        base = np.arange(n, dtype=float)[:, None, None]
        xyz = base + 100.0 * np.arange(k)[None, :, None] + 10.0 * np.arange(3)[None, None, :]
    width = len(coords)
    lines = [
        ",".join(["scorer"] + [scorer] * (k * width)),
        ",".join(["bodyparts"] + [bp for bp in bodyparts for _ in coords]),
        ",".join(["coords"] + list(coords) * k),
    ]
    for row in range(n):
        cells = [str(index[row])]
        for j in range(k):
            for a in range(width):
                value = xyz[row, j, a]
                cells.append("" if not np.isfinite(value) else repr(float(value)))
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n")
    return path
