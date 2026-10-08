"""Writes Ctrax raw ``.mat`` files from per-frame detections, for tests (no pytest import).

The layout follows the real file pinned in ``tests/real_samples``: nine MATLAB variables, one value
per *detection* concatenated frame by frame (``ntargets`` says how many rows each frame holds),
``identity`` the Ctrax track id of each detection, and ``y`` measured from the **bottom** of the
image. The writer takes coordinates as they are in the image (origin top-left) and flips y itself,
so tests can say what the reader must give back.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import scipy.io as sio

#: One detection: (identity, x, y_in_image).
Detection = tuple[int, float, float]


def write_ctrax_mat(
    path: Path,
    frames: list[list[Detection]],
    *,
    height_px: int = 480,
    fps: float = 25.0,
    startframe: int = 0,
    compress: bool = False,
    drop: tuple[str, ...] = (),
    extra: dict[str, np.ndarray] | None = None,
    timestamps: np.ndarray | None = None,
) -> Path:
    """Write ``frames`` (a list of detections per frame) as a Ctrax raw file."""
    flat = [d for frame in frames for d in frame]
    n_frames = len(frames)
    data: dict[str, np.ndarray] = {
        "ntargets": np.array([[float(len(f))] for f in frames]).reshape(n_frames, 1),
        "x_pos": np.array([[d[1]] for d in flat], dtype=np.float64).reshape(len(flat), 1),
        "y_pos": np.array([[height_px - d[2]] for d in flat], dtype=np.float64).reshape(-1, 1),
        "identity": np.array([[float(d[0])] for d in flat]).reshape(len(flat), 1),
        "maj_ax": np.ones((len(flat), 1)),
        "min_ax": np.ones((len(flat), 1)),
        "angle": np.zeros((len(flat), 1)),
        "startframe": np.array([[startframe]], dtype=np.int64),
        "timestamps": (
            np.arange(n_frames, dtype=np.float64).reshape(n_frames, 1) / fps
            if timestamps is None
            else np.asarray(timestamps, dtype=np.float64).reshape(-1, 1)
        ),
    }
    for name in drop:
        data.pop(name)
    data.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    sio.savemat(path, data, do_compression=compress)
    return path


def walkers(
    n_frames: int = 40, identities: tuple[int, ...] = (0, 1), height_px: int = 480, seed: int = 0
) -> list[list[Detection]]:
    """Each identity present in every frame, a smooth random walk inside the image."""
    rng = np.random.default_rng(seed)
    pos = {i: rng.uniform(100, 300, size=2) for i in identities}
    frames: list[list[Detection]] = []
    for _ in range(n_frames):
        frame = []
        for i in identities:
            pos[i] = np.clip(pos[i] + rng.normal(0, 2, size=2), 5, height_px - 5)
            frame.append((i, float(pos[i][0]), float(pos[i][1])))
        frames.append(frame)
    return frames
