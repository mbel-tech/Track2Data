"""TEST SCAFFOLDING, not production code.

Minimal SessionReader plug-ins for the fixture formats. They exist for one reason:
to demonstrate that the contract tests in test_reader_contract.py can be satisfied
by a reader that follows the real Track2Data contract (detect/read, Session,
DataValidationError). Register them with T2D_REFERENCE_READERS=1.

They deliberately do not import oracles.py, so the reader parsing and the oracle
parsing stay independent and a shared bug cannot make both agree on a wrong answer.

Policy choices made here are placeholders, marked POLICY:
  * a multi-keypoint animal is reduced to the mean of its finite keypoints
  * fps/width/height not recorded by the format come from video_info.json
  * ToxTrac positions stay in the file's own unit (mm), not converted to pixels
"""
from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import scipy.io as sio

from track2data.core.errors import DataValidationError
from track2data.core.models import Session, VideoInfo
from track2data.readers import register
from track2data.readers.base import SessionReader


# ------------------------------------------------------------------ helpers
def _err(msg: str, code: str, folder: Path, fix: str) -> DataValidationError:
    return DataValidationError(msg, code=code, subject=str(folder), remediation=fix)


def _video(folder: Path, n_frames: int, fps=None, width=None, height=None) -> VideoInfo:
    """POLICY: values the file records win; the rest come from video_info.json; else fail loudly."""
    side = {}
    p = folder / "video_info.json"
    if p.exists():
        side = json.loads(p.read_text())
    fps = fps if fps is not None else side.get("fps")
    width = width if width is not None else side.get("width_px")
    height = height if height is not None else side.get("height_px")
    missing = [k for k, v in (("fps", fps), ("width_px", width), ("height_px", height)) if v is None]
    if missing:
        raise _err(f"the source does not record {missing}", "VIDEO_INFO_MISSING", folder,
                   "supply fps, width_px and height_px (video_info.json)")
    return VideoInfo(path=None, fps=float(fps), n_frames=int(n_frames), width_px=int(width), height_px=int(height))


def _centroid(xy: np.ndarray) -> np.ndarray:
    """(F, A, K, 2) -> (F, A, 2). POLICY: mean of the finite keypoints."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(xy, axis=2)


def _session(folder: Path, name: str, video: VideoInfo, xy: np.ndarray, stable: bool) -> Session:
    return Session(session_id=folder.name, folder=folder, reader=name, video=video,
                   n_animals=int(xy.shape[1]), trajectory_variant="with_gaps",
                   has_stable_identities=stable, raw_xy=np.asarray(xy, dtype=np.float64))


def _numeric(p: Path) -> int:
    return int(re.search(r"(\d+)\.npz$", p.name).group(1))


def _is_h5_with(p: Path, *names: str) -> bool:
    try:
        with h5py.File(p, "r") as f:
            return all(n in f for n in names)
    except OSError:
        return False


# ------------------------------------------------------------------ DeepLabCut / Lightning Pose
class RefDLCReader(SessionReader):
    name = "ref_deeplabcut"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        if any(_is_h5_with(p, "df_with_missing") for p in folder.glob("*.h5")):
            return True
        for p in folder.glob("*.csv"):
            with open(p, encoding="utf8", errors="replace") as f:
                if f.readline().startswith("scorer,"):
                    return True
        return False

    def read(self, folder: Path) -> Session:
        h5s = [p for p in folder.glob("*.h5") if _is_h5_with(p, "df_with_missing")]
        try:
            if h5s:
                df = pd.read_hdf(h5s[0], key="df_with_missing")
            else:
                path = next(p for p in folder.glob("*.csv") if open(p, encoding="utf8").readline().startswith("scorer,"))
                with open(path, encoding="utf8") as f:
                    second = [f.readline().split(",")[0] for _ in range(2)][1]
                df = pd.read_csv(path, header=[0, 1, 2, 3] if second == "individuals" else [0, 1, 2], index_col=0)
        except Exception as exc:
            raise _err(f"cannot parse DeepLabCut table: {exc}", "DLC_UNREADABLE", folder, "check the file is a complete DLC output") from exc
        cols = df.columns
        multi = "individuals" in cols.names
        ind = cols.get_level_values("individuals") if multi else pd.Index(["animal"] * len(cols))
        bp = cols.get_level_values("bodyparts")
        co = cols.get_level_values("coords")
        keep = np.array([i != "single" for i in ind])           # unique body parts are not an animal
        inds = list(dict.fromkeys(ind[keep]))
        bps = list(dict.fromkeys(bp[keep]))
        n = int(df.index.max()) + 1
        xy = np.full((n, len(inds), len(bps), 2), np.nan)
        vals = df.to_numpy(float)
        rows = df.index.to_numpy(int)
        for j in range(len(cols)):
            if keep[j] and co[j] in ("x", "y"):
                xy[rows, inds.index(ind[j]), bps.index(bp[j]), 0 if co[j] == "x" else 1] = vals[:, j]
        return _session(folder, self.name, _video(folder, n), _centroid(xy), True)


# ------------------------------------------------------------------ SLEAP analysis HDF5
class RefSleapReader(SessionReader):
    name = "ref_sleap_analysis"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return any(_is_h5_with(p, "tracks", "track_occupancy", "node_names") for p in folder.glob("*.h5"))

    def read(self, folder: Path) -> Session:
        path = next(p for p in folder.glob("*.h5") if _is_h5_with(p, "tracks", "track_occupancy", "node_names"))
        try:
            with h5py.File(path, "r") as f:
                tracks = f["tracks"][:]
                occ = f["track_occupancy"][:]
                dims = f["tracks"].attrs.get("dims")
                tn = f["track_names"]
                named = tn.dtype.kind == "S" and tn.shape[0] > 0
        except Exception as exc:
            raise _err(f"cannot read SLEAP analysis file: {exc}", "SLEAP_UNREADABLE", folder, "re-export the analysis HDF5") from exc
        # POLICY: attributes are optional; fall back to the layout the GUI writes.
        if dims is not None and json.loads(dims if isinstance(dims, str) else dims.decode())[0] == "frame":
            xy = tracks                                              # (F, T, N, 2)
        else:
            xy = tracks.transpose(3, 0, 2, 1)                        # (T, 2, N, F) -> (F, T, N, 2)
        if xy.shape[0] != occ.shape[0]:
            raise _err("track_occupancy and tracks disagree on the number of frames", "SLEAP_LAYOUT_UNKNOWN", folder,
                       "export the analysis file again")
        stable = bool(named) or xy.shape[1] == 1
        return _session(folder, self.name, _video(folder, xy.shape[0]), _centroid(xy), stable)


# ------------------------------------------------------------------ TRex NPZ
def _trex_files(folder: Path, strict: bool = False) -> list[Path]:
    """npz files that look like TRex output. strict=True: an unreadable npz raises instead of vanishing,
    because silently dropping one individual from a multi-file session is worse than failing."""
    out = []
    for p in folder.glob("*.npz"):
        try:
            with np.load(p) as d:
                if {"frame", "missing", "X", "Y"} <= set(d.files):
                    out.append(p)
        except Exception as exc:
            if strict:
                raise _err(f"cannot read TRex file {p.name}: {exc}", "TREX_UNREADABLE", folder,
                           "re-export it; a session with a missing individual would be silently wrong") from exc
    return sorted(out, key=_numeric)


class RefTRexReader(SessionReader):
    name = "ref_trex_npz"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_trex_files(folder))

    def read(self, folder: Path) -> Session:
        files = _trex_files(folder, strict=True)
        loaded = []
        try:
            for p in files:
                with np.load(p) as d:
                    loaded.append({k: d[k] for k in d.files})
        except Exception as exc:
            raise _err(f"cannot read TRex npz: {exc}", "TREX_UNREADABLE", folder, "re-export from TRex") from exc
        n = int(max(m["frame"].max() for m in loaded)) + 1
        xy = np.full((n, len(loaded), 2), np.nan)
        fps = width = height = None
        for a, m in enumerate(loaded):
            fr = m["frame"].astype(int)
            scale = float(m["cm_per_pixel"][0]) if "cm_per_pixel" in m else 1.0   # POLICY: absent => already pixels
            for c, key in enumerate(("X", "Y")):
                v = m[key].astype(float) / scale
                v[~np.isfinite(v)] = np.nan                                      # +inf is how TRex marks "untracked"
                xy[fr, a, c] = v
            if fps is None:
                if "frame_rate" in m:
                    fps = float(m["frame_rate"][0])
                elif "time" in m:
                    ok = np.isfinite(m["time"]) & np.isfinite(m["frame"])
                    fps = float(1.0 / np.polyfit(m["frame"][ok], m["time"][ok], 1)[0])
            if width is None and "video_size" in m:
                width, height = (int(round(v)) for v in m["video_size"])
        return _session(folder, self.name, _video(folder, n, fps, width, height), xy, True)


# ------------------------------------------------------------------ AnimalTA
class RefAnimalTAReader(SessionReader):
    name = "ref_animalta"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        for p in folder.glob("*.csv"):
            with open(p, encoding="utf8", errors="replace") as f:
                if f.readline().startswith("Frame;Time;X_Arena"):
                    return True
        return False

    def read(self, folder: Path) -> Session:
        path = next(p for p in folder.glob("*.csv") if open(p, encoding="utf8").readline().startswith("Frame;Time;X_Arena"))
        try:
            df = pd.read_csv(path, sep=";", na_values=["NA"])
        except Exception as exc:
            raise _err(f"cannot parse AnimalTA csv: {exc}", "ANIMALTA_UNREADABLE", folder, "check the export") from exc
        pairs = sorted((int(m.group(1)), int(m.group(2))) for c in df.columns
                       if (m := re.fullmatch(r"X_Arena(\d+)_Ind(\d+)", c)))
        if not pairs:
            raise _err("no fixed-layout X_Arena/Y_Arena columns", "ANIMALTA_LAYOUT_UNSUPPORTED", folder,
                       "export the fixed-number-of-targets coordinates file")
        xy = np.stack([np.c_[df[f"X_Arena{a}_Ind{i}"], df[f"Y_Arena{a}_Ind{i}"]] for a, i in pairs], axis=1)
        t = df["Time"].to_numpy(float)
        fps = (len(t) - 1) / (t[-1] - t[0])              # Time is rounded to 0.01 s: use the whole span
        return _session(folder, self.name, _video(folder, len(df), fps=round(fps, 6)), xy, True)


# ------------------------------------------------------------------ Ctrax raw .mat
def _ctrax_mats(folder: Path) -> list[Path]:
    out = []
    for p in folder.glob("*.mat"):
        try:
            if {"ntargets", "x_pos", "y_pos", "identity"} <= {n for n, _, _ in sio.whosmat(p)}:
                out.append(p)
        except Exception:
            continue
    return out


class RefCtraxReader(SessionReader):
    name = "ref_ctrax_raw"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_ctrax_mats(folder))

    def read(self, folder: Path) -> Session:
        path = _ctrax_mats(folder)[0]
        try:
            m = sio.loadmat(path)
        except Exception as exc:
            raise _err(f"cannot read Ctrax mat: {exc}", "CTRAX_UNREADABLE", folder, "check the file is complete") from exc
        side = json.loads((folder / "video_info.json").read_text()) if (folder / "video_info.json").exists() else {}
        height = side.get("height_px")
        if height is None:
            raise _err("Ctrax measures y from the bottom of the frame; the frame height is not in the file",
                       "CTRAX_HEIGHT_REQUIRED", folder, "supply height_px")
        nt = m["ntargets"].ravel().astype(int)
        start = int(m["startframe"].ravel()[0])
        ident = m["identity"].ravel().astype(int)
        ids = np.unique(ident)
        n = start + len(nt)
        xy = np.full((n, len(ids), 2), np.nan)
        frame_of = np.repeat(np.arange(len(nt)) + start, nt)
        col = np.searchsorted(ids, ident)
        xy[frame_of, col, 0] = m["x_pos"].ravel()
        xy[frame_of, col, 1] = height - m["y_pos"].ravel()          # image convention
        ts = m["timestamps"].ravel()
        fps = (len(ts) - 1) / (ts[-1] - ts[0])
        stable = len(ids) <= int(nt.max())                           # more identities than animals => fragments
        return _session(folder, self.name, _video(folder, n, fps=round(float(fps), 6)), xy, stable)


# ------------------------------------------------------------------ ToxTrac
class RefToxTracReader(SessionReader):
    name = "ref_toxtrac"
    priority = 1

    @classmethod
    def detect(cls, folder: Path) -> bool:
        for p in folder.glob("Tracking_RealSpace_*.txt"):
            with open(p, encoding="utf8", errors="replace") as f:
                if f.readline().startswith("Time (sec)\tArena\tTrack"):
                    return True
        return False

    def read(self, folder: Path) -> Session:
        path = next(p for p in sorted(folder.glob("Tracking_RealSpace_*.txt"))
                    if open(p, encoding="utf8").readline().startswith("Time (sec)\tArena\tTrack"))
        try:
            df = pd.read_csv(path, sep="\t")
        except Exception as exc:
            raise _err(f"cannot parse ToxTrac table: {exc}", "TOXTRAC_UNREADABLE", folder, "check the file") from exc
        stats_path = folder / path.name.replace("Tracking_RealSpace", "Stats")
        fps = width = height = None
        if stats_path.exists():
            lines = [ln.strip() for ln in open(stats_path, encoding="utf8", errors="replace")]
            st = {a.rstrip(":").strip(): b for a, b in zip(lines[::2], lines[1::2]) if a.endswith(":")}
            fps = float(st["Video FrameRate"])
            width, height = (int(v) for v in re.findall(r"\d+", st["Video Resolution"]))
        t = df["Time (sec)"].to_numpy(float)
        step = 1.0 / fps if fps else float(np.median(np.diff(t)))
        idx = np.round((t - t[0]) / step).astype(int)                # lost frames are absent rows
        tracks = sorted(df["Track"].unique())
        xy = np.full((int(idx.max()) + 1, len(tracks), 2), np.nan)
        for a, tr in enumerate(tracks):
            sel = (df["Track"] == tr).to_numpy()
            xy[idx[sel], a, 0] = df["Pos. X (mm)"].to_numpy(float)[sel]     # POLICY: unit stays mm
            xy[idx[sel], a, 1] = df["Pos. Y (mm)"].to_numpy(float)[sel]
        return _session(folder, self.name, _video(folder, xy.shape[0], fps if fps else 1 / step, width, height), xy, True)


for _cls in (RefDLCReader, RefSleapReader, RefTRexReader, RefAnimalTAReader, RefCtraxReader, RefToxTracReader):
    register(_cls)
