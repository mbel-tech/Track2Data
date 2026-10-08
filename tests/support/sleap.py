"""Writes SLEAP analysis HDF5 files from arrays, for tests (no pytest import).

The layout follows the real files pinned in ``tests/real_samples`` (GUI "Export Analysis HDF5"):
no file or dataset attributes; ``tracks`` is ``(n_tracks, 2, n_nodes, n_frames)``;
``track_occupancy`` is ``(n_frames, n_tracks)`` uint8; a project with no tracks has an *empty
float64* ``track_names``; a skeleton with no edges has empty ``(0,)`` edge datasets.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


def write_sleap_analysis(
    path: Path,
    tracks: np.ndarray,
    *,
    node_names: list[str],
    track_names: list[str] | None,
    edges: list[tuple[int, int]] | None = None,
    point_scores: np.ndarray | None = None,
    dims: str | None = None,
    occupancy: np.ndarray | None = None,
) -> Path:
    """Write ``tracks`` (T, 2, N, F). ``track_names=None`` writes the empty float64 dataset."""
    n_tracks, _, _, n_frames = tracks.shape
    if occupancy is None:
        occupancy = (~np.isnan(tracks).all(axis=(1, 2))).T.astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        ds = f.create_dataset("tracks", data=tracks.astype(np.float64))
        if dims is not None:
            ds.attrs["dims"] = dims
        f.create_dataset("track_occupancy", data=occupancy)
        f.create_dataset("node_names", data=np.array([n.encode() for n in node_names]))
        if track_names is None:
            f.create_dataset("track_names", data=np.empty((0,), dtype=np.float64))
        else:
            f.create_dataset("track_names", data=np.array([n.encode() for n in track_names]))
        if edges:
            f.create_dataset("edge_inds", data=np.array(edges, dtype=np.int64))
        else:
            f.create_dataset("edge_inds", data=np.empty((0,), dtype=np.float64))
        if point_scores is not None:
            f.create_dataset("point_scores", data=point_scores.astype(np.float64))
        f.create_dataset("tracking_scores", data=np.ones((n_tracks, n_frames)))
        f.create_dataset("instance_scores", data=np.ones((n_tracks, n_frames)))
        text = h5py.string_dtype()
        f.create_dataset("video_path", data="/some/video.mp4", dtype=text)
        f.create_dataset("labels_path", data="/some/labels.slp", dtype=text)
        f.create_dataset("provenance", data="{}", dtype=text)
    return path


def random_tracks(
    n_frames: int = 40, n_tracks: int = 2, n_nodes: int = 3, seed: int = 0
) -> np.ndarray:
    """(T, 2, N, F) smooth random walks; node k is offset by 5 px in x from the track centre."""
    rng = np.random.default_rng(seed)
    centre = rng.uniform(100, 300, size=(n_tracks, 2, 1, 1)) + np.cumsum(
        rng.normal(0, 2, size=(n_tracks, 2, 1, n_frames)), axis=-1
    )
    offsets = np.zeros((1, 2, n_nodes, 1))
    offsets[:, 0, :, 0] = 5.0 * np.arange(n_nodes)
    return centre + offsets
