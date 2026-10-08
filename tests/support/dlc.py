"""Writes DeepLabCut-layout CSV files from arrays, for tests (no pytest import).

The layouts follow the real files pinned in ``tests/real_samples`` (single-animal: three header
rows; multi-animal: four; Lightning Pose / EKS: extra ``*_ens_*`` coordinate columns). Missing is
an empty cell, as DeepLabCut writes it.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

EXTRA_COORDS = (
    "x_ens_median",
    "y_ens_median",
    "x_ens_var",
    "y_ens_var",
    "x_posterior_var",
    "y_posterior_var",
)


def _cell(value: float) -> str:
    return "" if not np.isfinite(value) else repr(float(value))


def write_dlc_csv(
    path: Path,
    xy: np.ndarray,
    likelihood: np.ndarray | None = None,
    *,
    bodyparts: list[str],
    individuals: list[str] | None = None,
    scorer: str = "DLC_resnet50_testshuffle1_1000",
    extra_coords: bool = False,
    frames: list[int] | None = None,
    coords: tuple[str, ...] = ("x", "y", "likelihood"),
) -> Path:
    """Write ``xy`` (F, A, K, 2) as a DeepLabCut table.

    ``individuals=None`` writes the single-animal layout (three header rows) and needs A == 1.
    ``frames`` gives the first-column values (default 0..F-1). ``coords`` can drop ``likelihood``
    (an annotation or 3-D-like file) or rename columns.
    """
    n_frames, n_animals, n_kp, _ = xy.shape
    if individuals is None and n_animals != 1:
        raise ValueError("the single-animal layout holds one animal")
    if likelihood is None:
        likelihood = np.ones((n_frames, n_animals, n_kp))
    all_coords = list(coords) + (list(EXTRA_COORDS) if extra_coords else [])
    names = individuals or [""]
    rows: list[list[str]] = []
    rows.append(["scorer"] + [scorer] * (len(names) * n_kp * len(all_coords)))
    if individuals is not None:
        rows.append(["individuals"] + [n for n in names for _ in range(n_kp * len(all_coords))])
    rows.append(["bodyparts"] + [bp for _ in names for bp in bodyparts for _ in all_coords])
    rows.append(["coords"] + [c for _ in names for _ in bodyparts for c in all_coords])
    index = frames if frames is not None else list(range(n_frames))
    for row, frame in enumerate(index):
        line = [str(frame)]
        for a in range(len(names)):
            for k in range(n_kp):
                for coord in all_coords:
                    if coord == "x":
                        line.append(_cell(xy[row, a, k, 0]))
                    elif coord == "y":
                        line.append(_cell(xy[row, a, k, 1]))
                    elif coord == "likelihood":
                        line.append(_cell(likelihood[row, a, k]))
                    elif coord == "z":
                        line.append(_cell(0.0))
                    else:
                        line.append(_cell(0.5))
        rows.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path


def random_pose(n_frames: int = 50, n_animals: int = 1, n_kp: int = 3, seed: int = 0) -> np.ndarray:
    """Smooth random walks: keypoint k of animal a is offset by (5k, 0) from the animal centre."""
    rng = np.random.default_rng(seed)
    centre = rng.uniform(100, 300, size=(1, n_animals, 1, 2)) + np.cumsum(
        rng.normal(0, 2, size=(n_frames, n_animals, 1, 2)), axis=0
    )
    offsets = np.zeros((1, 1, n_kp, 2))
    offsets[..., 0] = 5.0 * np.arange(n_kp)
    return centre + offsets
