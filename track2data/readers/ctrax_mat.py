"""Ctrax raw ``.mat`` output (the file Ctrax's "Save Tracks as Matlab File" writes).

Nine variables, one value per *detection*, concatenated frame by frame: ``ntargets[t]`` says how
many rows frame ``t`` owns, so frame ``t`` starts at ``sum(ntargets[:t])``. ``x_pos``, ``y_pos``,
``identity``, ``maj_ax``, ``min_ax`` and ``angle`` are per detection; ``timestamps`` is per frame.

This is **not** ``trx.mat`` (a struct ``trx`` with one element per animal), which is a different
format: a file that has a ``trx`` variable is not claimed.

Facts the files make a reader get right, each pinned by a test:

* **y is measured from the bottom** of the image, not the top. The image height is not in the file,
  so it is an option (required): ``y_image = height - y_pos``. Without the flip positions are
  mirrored (the real sample is 330 px off a tracker that uses image coordinates).
* **Identities are track fragments, not animals.** Ctrax breaks a track whenever it loses it and
  starts a new id; the real 12,033-frame file has 193 ids for at most 17 animals at once. Every id
  becomes a slot, the session is identity-free by construction, and ``top_n`` keeps only the longest
  few for those who prefer a manageable number of slots.
* **The frame rate is in the file** (``timestamps``), as an average over the whole span; frame size
  is not.
* ``startframe`` is the first frame of the tracking run; when it is not 0 the true frame numbers are
  recorded (``tracking_intervals``).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.assemble import PX_PER_UNIT_PARAMETER, assemble_session
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.params import ReaderParameter, resolve_options
from track2data.readers.peek import Peeker

_REQUIRED = ("ntargets", "x_pos", "y_pos", "identity", "timestamps", "startframe")
#: Slots above this many bytes of positions are refused until the user keeps the longest tracks.
_MAX_BYTES = 1 << 30
#: Timestamps further than this many frames from a straight line are called irregular.
_IRREGULAR_FRAMES = 0.5


def _is_raw(names: dict[str, Any] | None) -> bool:
    """Whether a MATLAB file's variables are Ctrax's raw ones (and not a ``trx``)."""
    return names is not None and "trx" not in names and all(n in names for n in _REQUIRED)


def _files_in(path: Path) -> list[Path]:
    """The raw files a path stands for: itself, or the ``.mat`` files directly inside a folder."""
    path = Path(path)
    if path.is_file():
        return [path] if _is_raw(Peeker().mat_variables(path)) else []
    if not path.is_dir():
        return []
    try:
        candidates = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".mat")
    except OSError:
        return []
    return [p for p in candidates if _is_raw(Peeker().mat_variables(p))]


def _error(code: str, message: str, remediation: str, subject: str = "") -> ImportError_:
    return ImportError_(message, code=code, subject=subject, remediation=remediation)


class CtraxMatReader(SessionReader):
    """Ctrax raw ``.mat`` files: one session per file."""

    name = "ctrax_mat"
    display_name: ClassVar[str] = "Ctrax (raw .mat)"
    verification = "real_sample"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(
            name="width_px",
            label="Frame width (pixels)",
            kind="int",
            required=True,
            minimum=1,
            help="Ctrax files do not record the video's size.",
        ),
        ReaderParameter(
            name="height_px",
            label="Frame height (pixels)",
            kind="int",
            required=True,
            minimum=1,
            help="Needed to put y back in image coordinates: Ctrax measures it from the bottom.",
        ),
        ReaderParameter(
            name="top_n",
            label="Keep the longest tracks",
            kind="int",
            minimum=1,
            help="Ctrax starts a new track id every time it loses one, so a file has many more "
            "ids than animals. Left empty, every id becomes a slot; give a number to keep only "
            "that many of the longest tracks (the animals you care about, usually).",
        ),
        PX_PER_UNIT_PARAMETER,
    )

    # ── detection ──────────────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_files_in(Path(folder)))

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        found = [
            entry.path
            for entry in index.walk()
            if not entry.is_dir
            and entry.suffix == ".mat"
            and not entry.cloud_only
            and _is_raw(peek.mat_variables(entry.path))
        ]
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=default_session_id(path, is_file=True),
                source=path,
                files=(path,),
                warnings=(
                    "Ctrax track ids are fragments, not animals: the session gets one slot per "
                    "id (there are usually far more than animals). Use 'Keep the longest tracks' "
                    "to keep only the ones you want.",
                ),
            )
            for path in found
        )
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.HIGH,
                evidence=(
                    f"{len(found)} MATLAB file(s) with ntargets, x_pos, y_pos, identity and "
                    "timestamps and no 'trx' (raw Ctrax output)",
                ),
                sessions=sessions,
                parameters=cls.parameters,
                verification=cls.verification,
            )
        ]

    # ── reading ────────────────────────────────────────────────────────────

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        return _build_session(Path(folder), path, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            if folder.is_file() or (
                folder.is_dir() and any(p.suffix.lower() == ".mat" for p in folder.iterdir())
            ):
                raise _not_a_raw_file(folder)
            raise _error(
                "CTRAX_NO_FILE",
                f"Nothing to read at {folder}.",
                "Point at a Ctrax .mat file, or a folder that holds one.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} Ctrax files, one per video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _not_a_raw_file(path: Path) -> ImportError_:
    return _error(
        "CTRAX_NOT_A_RAW_FILE",
        f"{path} is not a raw Ctrax .mat file.",
        "This reader reads Ctrax's own file (variables ntargets, x_pos, y_pos, identity, "
        "timestamps). A trx.mat file (a 'trx' struct, from Ctrax, FlyTracker or JAABA) is a "
        "different format that is not read yet.",
        str(path),
    )


def _load(path: Path) -> dict[str, np.ndarray]:
    import scipy.io as sio

    wanted = [*_REQUIRED]
    try:
        raw = sio.loadmat(str(path), variable_names=wanted)
    except Exception as exc:
        raise _error(
            "CTRAX_UNREADABLE",
            f"{path.name} could not be read as a MATLAB file ({exc}).",
            "The file may be damaged or incomplete; save the tracks from Ctrax again.",
            str(path),
        ) from None
    missing = [n for n in wanted if n not in raw]
    if missing:
        raise _not_a_raw_file(path)
    return {n: np.asarray(raw[n]) for n in wanted}


def _build_session(given: Path, path: Path, opts: dict[str, Any]) -> Session:
    data = _load(path)
    ntargets = data["ntargets"].astype(np.float64).ravel()
    x = data["x_pos"].astype(np.float64).ravel()
    y = data["y_pos"].astype(np.float64).ravel()
    ident = data["identity"].astype(np.float64).ravel()
    ts = data["timestamps"].astype(np.float64).ravel()
    n_frames = len(ntargets)
    counts_ok = (
        len(x) == len(y) == len(ident)
        and len(ts) == n_frames
        and np.all(np.isfinite(ntargets))
        and np.all(ntargets >= 0)
        and np.all(ntargets == np.floor(ntargets))
        and int(ntargets.sum()) == len(x)
    )
    if not counts_ok:
        raise _error(
            "CTRAX_INCONSISTENT",
            f"{path.name}: ntargets, the per-detection arrays and the timestamps disagree.",
            "The file may be damaged or from a different tool; save the tracks from Ctrax again.",
            str(path),
        )
    if n_frames == 0:
        raise DataValidationError(
            f"{path.name} holds no frames.",
            code="READER_OUTPUT_INVALID",
            subject="raw_xy",
            remediation="Track the video in Ctrax and save the tracks again.",
        )
    fps = _frame_rate(path, ts)

    height = opts["height_px"]
    if np.any(y > height):
        raise _error(
            "CTRAX_FRAME_TOO_SHORT",
            f"{path.name} has positions up to {np.nanmax(y):.0f} px from the bottom, which is "
            f"more than the frame height you gave ({height} px).",
            "Give the video's real height in pixels; Ctrax measures y from the bottom, so it is "
            "needed to put y back in image coordinates.",
            "height_px",
        )

    frame_of = np.repeat(np.arange(n_frames), ntargets.astype(np.int64))
    ids, slot_of = np.unique(ident, return_inverse=True)
    keep = np.arange(len(ids))
    top_n = opts.get("top_n")
    if top_n is not None and top_n < len(ids):
        lengths = np.bincount(slot_of, minlength=len(ids))
        # longest first, lower id first among equals; then back into id order
        order = np.lexsort((np.arange(len(ids)), -lengths))
        keep = np.sort(order[:top_n])
    remap = np.full(len(ids), -1, dtype=np.int64)
    remap[keep] = np.arange(len(keep))
    slots = remap[slot_of]
    selected = slots >= 0

    if n_frames * len(keep) * 16 > _MAX_BYTES:
        raise _error(
            "CTRAX_TOO_LARGE",
            f"{path.name} has {len(ids)} track ids over {n_frames} frames: one slot per id would "
            "not fit in memory.",
            "Set 'top_n' to keep only the longest tracks (the animals you care about).",
            "top_n",
        )
    pairs = frame_of[selected] * len(keep) + slots[selected]
    if len(np.unique(pairs)) != len(pairs):
        raise _error(
            "CTRAX_DUPLICATE_TRACK",
            f"{path.name}: a track id appears twice in the same frame.",
            "A raw Ctrax file never does this; it may be damaged or from a different tool.",
            str(path),
        )
    xy = np.full((n_frames, len(keep), 2), np.nan)
    xy[frame_of[selected], slots[selected], 0] = x[selected]
    xy[frame_of[selected], slots[selected], 1] = height - y[selected]

    start = int(np.asarray(data["startframe"]).ravel()[0])
    session = assemble_session(
        session_id=default_session_id(path, is_file=True),
        folder=given,
        reader=CtraxMatReader.name,
        fps=fps,
        width_px=opts["width_px"],
        height_px=height,
        raw_xy=xy,
        has_stable_identities=False,
        track_wo_identities=True,
        identities_labels=[_label(v) for v in ids[keep]],
        tracking_intervals=[(start, start + n_frames)] if start > 0 else None,
        trajectory_source=path,
        trajectory_format="ctrax_raw_mat",
        length_unit=opts.get("px_per_unit"),
    )
    note = _irregular(ts, fps)
    if note:
        session.raw_attrs = {"timestamps": note}
    return session


def _label(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _frame_rate(path: Path, ts: np.ndarray) -> float:
    """Frames per second from the whole span of the timestamps, never from one step."""
    span = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    if not np.all(np.isfinite(ts)) or span <= 0:
        raise _error(
            "CTRAX_BAD_TIMESTAMPS",
            f"{path.name}: the timestamps give no frame rate "
            "(fewer than two frames, or they do not increase).",
            "Check that the file is complete; the frame rate cannot be guessed.",
            str(path),
        )
    return (len(ts) - 1) / span


def _irregular(ts: np.ndarray, fps: float) -> str | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        line = ts[0] + np.arange(len(ts)) / fps
        worst = float(np.max(np.abs(ts - line))) * fps
    if worst > _IRREGULAR_FRAMES:
        return (
            f"the timestamps are irregular (up to {worst:.1f} frames from a steady rate): a "
            f"single frame rate of {fps:.3f} fps was used"
        )
    return None
