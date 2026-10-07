"""Independent parsers for the fixture formats.

These are the ground truth for the tests. They use only numpy, pandas, h5py and
scipy, and make no use of Track2Data, so a bug in a reader cannot hide in the
oracle. Every oracle returns image-convention pixel coordinates (origin top-left,
y down) wherever the source records pixels, with NaN for missing values.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.io as sio
from scipy.spatial import cKDTree


@dataclass
class Oracle:
    xy: np.ndarray            # (n_frames, n_animals, n_keypoints, 2), NaN = missing
    names: list[str]          # animal names in column order
    tol: float = 1.0          # pixel tolerance for the "inside the keypoint box" check


# ---------------------------------------------------------------- DeepLabCut / Lightning Pose
def read_dlc(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".h5":
        pytest.importorskip("tables", reason="the DLC .h5 oracle reads pandas HDF5 via PyTables")
        return pd.read_hdf(path, key="df_with_missing")
    with open(path) as f:
        rows = [f.readline().split(",")[0] for _ in range(3)]
    header = [0, 1, 2, 3] if rows[1] == "individuals" else [0, 1, 2]
    return pd.read_csv(path, header=header, index_col=0)


def oracle_dlc(path: Path, tol: float = 1.0) -> Oracle:
    df = read_dlc(path)
    cols = df.columns.droplevel("scorer")
    multi = "individuals" in cols.names
    inds = list(dict.fromkeys(cols.get_level_values("individuals"))) if multi else ["animal"]
    bps = list(dict.fromkeys(cols.get_level_values("bodyparts")))
    n = int(df.index.max()) + 1
    xy = np.full((n, len(inds), len(bps), 2), np.nan)
    d = df.copy()
    d.columns = cols
    for a, ind in enumerate(inds):
        for k, bp in enumerate(bps):
            key = (ind, bp) if multi else (bp,)
            xy[d.index.values, a, k, 0] = d[key + ("x",)].values
            xy[d.index.values, a, k, 1] = d[key + ("y",)].values
    return Oracle(xy, inds, tol)


# ---------------------------------------------------------------- SLEAP analysis HDF5
def read_sleap(path: Path) -> dict:
    with h5py.File(path, "r") as f:
        return dict(
            tracks=f["tracks"][:],
            occupancy=f["track_occupancy"][:],
            node_names=[x.decode() for x in f["node_names"][:]],
            track_names=[x.decode() for x in f["track_names"][:]] if f["track_names"].dtype.kind == "S" else [],
            file_attrs=dict(f.attrs),
            ds_attrs={k: dict(f[k].attrs) for k in f.keys()},
        )


def oracle_sleap(path: Path, tol: float = 1.0) -> Oracle:
    s = read_sleap(path)
    xy = s["tracks"].transpose(3, 0, 2, 1)          # (T,2,N,F) -> (F,T,N,2)
    names = s["track_names"] or [f"track_{i}" for i in range(xy.shape[1])]
    return Oracle(xy.astype(float), names, tol)


# ---------------------------------------------------------------- TRex NPZ
def numeric_key(name: str) -> int:
    return int(re.search(r"(\d+)\.npz$", name).group(1))


def trex_zip_members(zip_path: Path) -> dict[str, dict]:
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for m in sorted(z.namelist(), key=lambda n: numeric_key(n) if n.endswith(".npz") else -1):
            if m.endswith(".npz"):
                d = np.load(io.BytesIO(z.read(m)))
                out[Path(m).name] = {k: d[k] for k in d.files}
    return out


def trex_npz_files(paths: list[Path]) -> dict[str, dict]:
    out = {}
    for p in sorted(paths, key=lambda p: numeric_key(p.name)):
        d = np.load(p)
        out[p.name] = {k: d[k] for k in d.files}
    return out


def oracle_trex_pose(members: dict[str, dict], tol: float = 40.0) -> Oracle:
    """New-style export: pixel pose keypoints poseX0..poseXn / poseY0..poseYn."""
    first = next(iter(members.values()))
    nk = len([k for k in first if re.fullmatch(r"poseX\d+", k)])
    n = int(max(m["frame"].max() for m in members.values())) + 1
    xy = np.full((n, len(members), nk, 2), np.nan)
    for a, m in enumerate(members.values()):
        fr = m["frame"].astype(int)
        for k in range(nk):
            for c, key in enumerate((f"poseX{k}", f"poseY{k}")):
                v = m[key].astype(float)
                v[~np.isfinite(v)] = np.nan
                xy[fr, a, k, c] = v
    return Oracle(xy, list(members), tol)


def oracle_trex_point(members: dict[str, dict], tol: float = 1e-3) -> Oracle:
    """Old-style export: single centroid X, Y per individual (pixel scale, see quirk test)."""
    n = int(max(m["frame"].max() for m in members.values())) + 1
    xy = np.full((n, len(members), 1, 2), np.nan)
    for a, m in enumerate(members.values()):
        fr = m["frame"].astype(int)
        for c, key in enumerate(("X", "Y")):
            v = m[key].astype(float)
            v[~np.isfinite(v)] = np.nan
            xy[fr, a, 0, c] = v
    return Oracle(xy, list(members), tol)


# ---------------------------------------------------------------- AnimalTA
def read_animalta(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def oracle_animalta(path: Path, tol: float = 1e-3) -> Oracle:
    df = read_animalta(path)
    inds = sorted({int(m.group(1)) for c in df.columns if (m := re.fullmatch(r"X_Arena0_Ind(\d+)", c))})
    xy = np.full((len(df), len(inds), 1, 2), np.nan)
    for a, i in enumerate(inds):
        xy[:, a, 0, 0] = df[f"X_Arena0_Ind{i}"].values
        xy[:, a, 0, 1] = df[f"Y_Arena0_Ind{i}"].values
    return Oracle(xy, [f"Ind{i}" for i in inds], tol)


# ---------------------------------------------------------------- Ctrax raw .mat
def read_ctrax(path: Path) -> dict:
    m = sio.loadmat(path)
    return {k: v for k, v in m.items() if not k.startswith("__")}


def ctrax_points(m: dict, frame: int, height: float | None) -> np.ndarray:
    """Detections of one frame as (n,2). Ctrax y is measured from the bottom."""
    nt = m["ntargets"].ravel().astype(int)
    start = int(nt[:frame].sum())
    pts = np.c_[m["x_pos"].ravel()[start:start + nt[frame]], m["y_pos"].ravel()[start:start + nt[frame]]]
    if height is not None:
        pts[:, 1] = height - pts[:, 1]
    return pts


# ---------------------------------------------------------------- ToxTrac
TOX_COLUMNS = ["Time (sec)", "Arena", "Track", "Pos. X (mm)", "Pos. Y (mm)", "Label"]


def read_toxtrac(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t")


def read_toxtrac_stats(path: Path) -> dict[str, str]:
    """Stats files alternate a 'name :' line and a value line."""
    lines = [ln.rstrip("\n") for ln in open(path, encoding="utf8", errors="replace")]
    out = {}
    for a, b in zip(lines[::2], lines[1::2]):
        if a.strip().endswith(":"):
            out[a.strip().rstrip(":").strip()] = b.strip()
    return out


# ---------------------------------------------------------------- geometry
def median_nn(a: np.ndarray, b: np.ndarray) -> float:
    """Median distance from each point of *a* to its nearest neighbour in *b* (identity-free)."""
    a = a[np.isfinite(a).all(axis=1)]
    b = b[np.isfinite(b).all(axis=1)]
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    return float(np.median(cKDTree(b).query(a)[0]))
