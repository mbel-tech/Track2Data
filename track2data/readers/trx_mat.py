"""Ctrax / FlyTracker / JAABA ``trx.mat``: a MATLAB struct ``trx`` with one element per animal.

Per element (documented layout, docs/tracker-formats/animal_tracking_output_formats.md 2.5):
``x`` and ``y`` in pixels, one value per frame from ``firstframe`` to ``endframe`` (1-based,
inclusive), so an element covers frames ``firstframe-1 .. endframe-1`` in 0-based terms. ``fps`` and
``pxpermm`` (pixels per millimetre) are set by Ctrax's ``convert_units`` and by FlyTracker/JAABA.

* **The scale is in the file.** ``pxpermm`` becomes ``Session.length_unit`` (pixels per cm, so it
  is ten times ``pxpermm``). It stays an unconfirmed suggestion: Session calibration still asks the
  user to confirm the unit. A value of exactly 1 is the "never calibrated" default of those tools
  and is not used.
* **Elements are tracks, not animals.** Ctrax breaks a track whenever it loses it, so the session
  is identity-free by construction, one slot per element (``top_n`` keeps the longest).
* The frame size is not in the file and is an option; the frame rate is read from ``fps`` when the
  file has one and is an option otherwise.
* Only classic (v5/v7) MATLAB files are read; a v7.3 (HDF5) file is not claimed.

Built from the documented layout and labelled ``synthetic_only`` until a real sample is pinned
(DECISIONS D-012, gate G-JAABA).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from track2data.core.errors import ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.assemble import assemble_session
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.params import ReaderParameter, resolve_options
from track2data.readers.peek import Peeker

#: Slots above this many bytes of positions are refused until the user keeps the longest tracks.
_MAX_BYTES = 1 << 30
_REQUIRED_FIELDS = ("x", "y", "firstframe", "endframe")


def _is_trx(names: dict[str, Any] | None) -> bool:
    """Whether a MATLAB file's variables are a ``trx`` struct (and not Ctrax's raw ones)."""
    if names is None or "trx" not in names:
        return False
    _shape, kind = names["trx"]
    return kind == "struct" and "ntargets" not in names


def _files_in(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_file():
        return [path] if _is_trx(Peeker().mat_variables(path)) else []
    if not path.is_dir():
        return []
    try:
        candidates = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".mat")
    except OSError:
        return []
    return [p for p in candidates if _is_trx(Peeker().mat_variables(p))]


def _error(code: str, message: str, remediation: str, subject: str = "") -> ImportError_:
    return ImportError_(message, code=code, subject=subject, remediation=remediation)


class TrxMatReader(SessionReader):
    """``trx.mat`` files: one session per file."""

    name = "trx_mat"
    display_name: ClassVar[str] = "Ctrax / JAABA (trx.mat)"
    verification = "synthetic_only"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(
            name="width_px",
            label="Frame width (pixels)",
            kind="int",
            required=True,
            minimum=1,
            help="trx.mat files do not record the video's size.",
        ),
        ReaderParameter(
            name="height_px",
            label="Frame height (pixels)",
            kind="int",
            required=True,
            minimum=1,
        ),
        ReaderParameter(
            name="fps",
            label="Frame rate (frames per second)",
            kind="float",
            minimum=0.001,
            help="Read from the file's 'fps' when it has one; give it only when it does not.",
        ),
        ReaderParameter(
            name="top_n",
            label="Keep the longest tracks",
            kind="int",
            minimum=1,
            help="Ctrax starts a new track every time it loses one, so a file can hold many "
            "more tracks than animals. Left empty, every track becomes a slot.",
        ),
    )

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
            and _is_trx(peek.mat_variables(entry.path))
        ]
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=default_session_id(path, is_file=True),
                source=path,
                files=(path,),
                warnings=(
                    "Each trx element is a track, not necessarily an animal: the session gets "
                    "one identity-free slot per track. Use 'Keep the longest tracks' to keep "
                    "only some.",
                ),
            )
            for path in found
        )
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.MEDIUM,
                evidence=(f"{len(found)} MATLAB file(s) holding a 'trx' struct",),
                sessions=sessions,
                parameters=cls.parameters,
                verification=cls.verification,
            )
        ]

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        return _build_session(Path(folder), path, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            raise _error(
                "TRX_NO_FILE",
                f"No readable trx.mat at {folder}.",
                "Point at a trx.mat file, or a folder that holds one. A file saved with "
                "MATLAB's -v7.3 option is not read: save it again with '-v7'.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} trx files, one per video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _scalar(element: Any, field: str) -> float | None:
    """A finite number from a struct field that MATLAB stored as a 1x1 array, else None."""
    value = getattr(element, field, None)
    try:
        arr = np.asarray(value, dtype=np.float64).ravel()
    except (TypeError, ValueError):
        return None
    if arr.size == 0 or not math.isfinite(float(arr[0])):
        return None
    return float(arr[0])


def _vector(element: Any, field: str) -> np.ndarray:
    return np.atleast_1d(np.asarray(getattr(element, field), dtype=np.float64)).ravel()


def _load(path: Path) -> list[Any]:
    import scipy.io as sio

    try:
        raw = sio.loadmat(
            str(path), variable_names=["trx"], squeeze_me=True, struct_as_record=False
        )
    except Exception as exc:
        raise _error(
            "TRX_UNREADABLE",
            f"{path.name} could not be read as a MATLAB file ({exc}).",
            "The file may be damaged; export it again.",
            str(path),
        ) from None
    elements = [e for e in np.atleast_1d(raw.get("trx", np.empty(0))).ravel()]
    bad = [f for f in _REQUIRED_FIELDS if not elements or not all(hasattr(e, f) for e in elements)]
    if bad:
        raise _error(
            "TRX_MISSING_FIELDS",
            f"{path.name}: the trx struct has no field(s) {', '.join(bad)}.",
            "This reader needs x, y, firstframe and endframe on every element.",
            str(path),
        )
    return elements


def _build_session(given: Path, path: Path, opts: dict[str, Any]) -> Session:
    elements = _load(path)
    tracks: list[tuple[int, np.ndarray, np.ndarray]] = []
    for i, e in enumerate(elements):
        x, y = _vector(e, "x"), _vector(e, "y")
        first, last = _scalar(e, "firstframe"), _scalar(e, "endframe")
        if first is None or last is None or first < 1 or last < first or len(x) != len(y):
            raise _error(
                "TRX_INCONSISTENT",
                f"{path.name}: track {i + 1} has frame numbers or positions that disagree.",
                "The file may be damaged or from a different tool; export it again.",
                str(path),
            )
        if len(x) != int(last - first) + 1:
            raise _error(
                "TRX_INCONSISTENT",
                f"{path.name}: track {i + 1} spans frames {first:.0f} to {last:.0f} but holds "
                f"{len(x)} positions.",
                "The file may be damaged or from a different tool; export it again.",
                str(path),
            )
        tracks.append((int(first) - 1, x, y))

    n_frames = max(start + len(x) for start, x, _y in tracks)
    keep = list(range(len(tracks)))
    top_n = opts.get("top_n")
    if top_n is not None and top_n < len(tracks):
        order = sorted(keep, key=lambda i: (-len(tracks[i][1]), i))
        keep = sorted(order[:top_n])
    if n_frames * len(keep) * 16 > _MAX_BYTES:
        raise _error(
            "TRX_TOO_LARGE",
            f"{path.name} has {len(tracks)} tracks over {n_frames} frames: one slot per track "
            "would not fit in memory.",
            "Set 'top_n' to keep only the longest tracks (the animals you care about).",
            "top_n",
        )
    xy = np.full((n_frames, len(keep), 2), np.nan)
    for slot, i in enumerate(keep):
        start, x, y = tracks[i]
        xy[start : start + len(x), slot, 0] = x
        xy[start : start + len(x), slot, 1] = y

    width, height = opts["width_px"], opts["height_px"]
    if np.nanmax(xy[..., 1]) > height or np.nanmax(xy[..., 0]) > width:
        raise _error(
            "TRX_FRAME_TOO_SMALL",
            f"{path.name} has positions beyond the frame size you gave ({width} x {height} px).",
            "Give the video's real size in pixels.",
            "height_px",
        )

    fps = opts.get("fps")
    if fps is None:
        fps = next((v for e in elements if (v := _scalar(e, "fps")) and v > 0), None)
    if fps is None:
        raise _error(
            "TRX_NO_FRAME_RATE",
            f"{path.name} does not record a frame rate.",
            "Give the frame rate of the video (option 'fps').",
            "fps",
        )

    # pxpermm is pixels per millimetre; length_unit is pixels per cm. Exactly 1 is the tools'
    # "never calibrated" default, not a measurement.
    scales = {v for e in elements if (v := _scalar(e, "pxpermm")) and v > 0 and v != 1.0}
    length_unit: float | None = None
    if len(scales) == 1:
        length_unit = 10.0 * scales.pop()

    session = assemble_session(
        session_id=default_session_id(path, is_file=True),
        folder=given,
        reader=TrxMatReader.name,
        fps=float(fps),
        width_px=width,
        height_px=height,
        raw_xy=xy,
        has_stable_identities=False,
        track_wo_identities=True,
        identities_labels=[
            str(_scalar(elements[i], "id") or i + 1).removesuffix(".0") for i in keep
        ],
        trajectory_source=path,
        trajectory_format="trx_mat",
        length_unit=length_unit,
    )
    if len(scales) > 1:
        session.raw_attrs = {"pxpermm": "tracks disagree on pxpermm; no scale was taken"}
    return session
