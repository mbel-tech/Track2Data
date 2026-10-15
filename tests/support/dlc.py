"""Writes DeepLabCut-layout CSV files from arrays, for tests (no pytest import).

The layouts follow the real files pinned in ``tests/real_samples`` (single-animal: three header
rows; multi-animal: four; Lightning Pose / EKS: extra ``*_ens_*`` coordinate columns). Missing is
an empty cell, as DeepLabCut writes it.
"""

from __future__ import annotations

import csv
import pickle
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


def write_dlc_h5(
    path: Path,
    xy: np.ndarray,
    likelihood: np.ndarray | None = None,
    *,
    bodyparts: list[str],
    individuals: list[str] | None = None,
    scorer: str = "DLC_resnet50_testshuffle1_1000",
    frames: list[int] | None = None,
    key: str = "df_with_missing",
    label_pickle: bytes | None = None,
    split_blocks: bool = False,
) -> Path:
    """Write ``xy`` (F, A, K, 2) in the layout pandas gives ``df.to_hdf(key=..., format="table")``.

    Written with h5py alone (no PyTables), following what PyTables 3 writes: a group with the
    plain-text ``pandas_type`` attribute, a ``table`` compound dataset of ``index`` and
    ``values_block_N``, and the column labels as protocol-0 pickles in ``non_index_axes`` and each
    block's ``values_block_N_kind``. ``label_pickle`` replaces the ``non_index_axes`` pickle (for
    hostile-file tests); ``split_blocks`` stores the likelihood columns as a second block.
    """
    import h5py

    def set_text(node, name: str, value: bytes, *, pickled: bool = False) -> None:
        # PyTables writes plain text attributes as UTF-8 NULLTERM strings and pickled objects as
        # ASCII ones, and tells them apart by that; pandas reads the file back only if both match.
        tid = h5py.h5t.C_S1.copy()
        tid.set_size(len(value))
        tid.set_strpad(h5py.h5t.STR_NULLTERM)
        tid.set_cset(h5py.h5t.CSET_ASCII if pickled else h5py.h5t.CSET_UTF8)
        node.attrs.create(name, np.bytes_(value), dtype=tid)

    n_frames, n_animals, n_kp, _ = xy.shape
    if individuals is None and n_animals != 1:
        raise ValueError("the single-animal layout holds one animal")
    if likelihood is None:
        likelihood = np.ones((n_frames, n_animals, n_kp))
    names = individuals or [""]
    labels: list[tuple[str, ...]] = []
    columns: list[np.ndarray] = []
    for a, animal in enumerate(names):
        for k, bodypart in enumerate(bodyparts):
            for coord in ("x", "y", "likelihood"):
                labels.append(
                    (scorer, animal, bodypart, coord) if individuals else (scorer, bodypart, coord)
                )
                if coord == "likelihood":
                    columns.append(likelihood[:, a, k])
                else:
                    columns.append(xy[:, a, k, 0 if coord == "x" else 1])
    values = np.stack(columns, axis=1).astype(np.float64)
    blocks: list[tuple[str, list[int]]] = [("values_block_0", list(range(len(labels))))]
    if split_blocks:
        is_lik = [i for i, label in enumerate(labels) if label[-1] == "likelihood"]
        rest = [i for i in range(len(labels)) if i not in is_lik]
        blocks = [("values_block_0", rest), ("values_block_1", is_lik)]
    dtype = np.dtype([("index", "<i8")] + [(name, "<f8", (len(cols),)) for name, cols in blocks])
    index = frames if frames is not None else list(range(n_frames))
    data = np.zeros(n_frames, dtype=dtype)
    data["index"] = index
    for name, cols in blocks:
        data[name] = values[:, cols]
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        group = handle.create_group(key)
        set_text(group, "pandas_type", b"frame_table")
        set_text(group, "table_type", b"appendable_frame")
        set_text(group, "pandas_version", b"0.15.2")
        set_text(group, "encoding", b"UTF-8")
        set_text(group, "errors", b"strict")
        set_text(group, "nan_rep", b"nan")
        set_text(group, "data_columns", pickle.dumps([], protocol=0), pickled=True)
        set_text(group, "index_cols", pickle.dumps([(0, "index")], protocol=0), pickled=True)
        set_text(
            group,
            "values_cols",
            pickle.dumps([name for name, _ in blocks], protocol=0),
            pickled=True,
        )
        level_names = (
            ["scorer", "individuals", "bodyparts", "coords"]
            if individuals
            else [
                "scorer",
                "bodyparts",
                "coords",
            ]
        )
        info = {1: {"names": level_names, "type": "MultiIndex"}, "index": {}}
        info.update({name: {} for name, _ in blocks})
        set_text(group, "info", pickle.dumps(info, protocol=0), pickled=True)
        group.attrs["levels"] = np.int64(1)
        set_text(
            group,
            "non_index_axes",
            label_pickle if label_pickle is not None else pickle.dumps([(1, labels)], protocol=0),
            pickled=True,
        )
        table = group.create_dataset("table", data=data)
        set_text(table, "index_kind", b"integer")
        set_text(table, "CLASS", b"TABLE")
        set_text(table, "VERSION", b"2.7")
        table.attrs["NROWS"] = np.int64(n_frames)
        set_text(table, "FIELD_0_NAME", b"index")
        for i, (name, _cols) in enumerate(blocks, start=1):
            set_text(table, f"FIELD_{i}_NAME", name.encode())
            set_text(table, f"{name}_dtype", b"float64")
            set_text(table, f"{name}_meta", b"N.", pickled=True)
        for name, cols in blocks:
            set_text(
                table,
                f"{name}_kind",
                pickle.dumps([labels[i] for i in cols], protocol=0),
                pickled=True,
            )
    return path
