"""SLEAP "analysis" HDF5 files (File > Export Analysis HDF5, or ``sleap-convert --format analysis``)

The file holds a ``tracks`` array of shape ``(n_tracks, 2, n_nodes, n_frames)`` (x and y, then the
skeleton's nodes), a ``track_occupancy`` ``(n_frames, n_tracks)`` flag, and the names of the tracks
and nodes. Missing positions are NaN.

What the file does **not** record is the frame rate and the frame size, so they are options the
user gives (never defaulted). The GUI export carries no attributes at all, so the layout cannot be
read from the file: it is *checked* (the occupancy and the names must agree with ``tracks``) and a
file that does not fit is refused with a clear error rather than guessed at.

Traps handled here, each pinned by a test:

* A project with no tracks writes an **empty float64** ``track_names`` (not bytes) and still has one
  slot in ``tracks``: one animal, no identity question.
* Several slots with no names, or sleap-io's synthetic ``track_0``, ``track_1``: positional, not
  tracked identities. The session is identity-free by construction.
* A skeleton with no edges writes an empty ``(0,)`` ``edge_inds``, not ``(0, 2)``.
* ``tracks`` as a *group* is a different format (stitched DeepLabCut tracklets); not claimed.
* ``.slp`` project files are a different, unsupported format (the scan says what to do instead).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.assemble import (
    PX_PER_UNIT_PARAMETER,
    assemble_session,
    build_keypoints,
    reduce_keypoints,
    skeleton_fits,
    to_nan,
)
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.params import ReaderParameter, resolve_options
from track2data.readers.peek import Hdf5Root, Peeker

_MARKERS = ("track_names", "node_names", "track_occupancy")
_SUFFIXES = (".h5", ".hdf5")
_SYNTHETIC = re.compile(r"^track_\d+$")
_STANDARD_DIMS = ["track", "xy", "node", "frame"]


def _is_analysis(root: Hdf5Root | None) -> bool:
    """Whether a file's top level has the analysis markers (``tracks`` a 4-D *dataset*)."""
    if root is None:
        return False
    tracks = root.nodes.get("tracks")
    if tracks is None or tracks.shape is None or len(tracks.shape) != 4:  # a group has no shape
        return False
    return all(m in root.nodes and root.nodes[m].kind == "dataset" for m in _MARKERS)


def _session_id(path: Path) -> str:
    stem = path.stem
    if stem.lower().endswith(".analysis"):
        stem = stem[: -len(".analysis")]
    return default_session_id(Path(stem), is_file=False) if not stem else _clean(stem)


def _clean(stem: str) -> str:
    from track2data.core.ids import sanitise_session_id

    return sanitise_session_id(stem)


def _files_in(path: Path) -> list[Path]:
    """The analysis files a path stands for: itself, or the ones directly inside a folder."""
    path = Path(path)
    if path.is_file():
        return [path] if _is_analysis(Peeker().hdf5_root(path)) else []
    if not path.is_dir():
        return []
    try:
        candidates = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES
        )
    except OSError:
        return []
    return [p for p in candidates if _is_analysis(Peeker().hdf5_root(p))]


def _error(code: str, message: str, remediation: str, subject: str = "") -> ImportError_:
    return ImportError_(message, code=code, subject=subject, remediation=remediation)


def _warnings_for(root: Hdf5Root) -> tuple[str, ...]:
    tracks = root.nodes["tracks"].shape
    n_tracks = tracks[0] if tracks else 0
    names = root.strings.get("track_names", [])
    if n_tracks > 1 and (not names or all(_SYNTHETIC.match(n) for n in names)):
        return (
            "The tracks have no names (or the synthetic track_0, track_1...): they are positional "
            "slots, not identities that were tracked.",
        )
    return ()


class SleapAnalysisReader(SessionReader):
    """SLEAP analysis HDF5: one session per file."""

    name = "sleap_analysis"
    display_name: ClassVar[str] = "SLEAP (analysis HDF5)"
    verification = "real_sample"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(
            name="fps",
            label="Frame rate (frames per second)",
            kind="float",
            required=True,
            minimum=0.001,
            help="SLEAP analysis files do not record the video's frame rate.",
        ),
        ReaderParameter(
            name="width_px",
            label="Frame width (pixels)",
            kind="int",
            required=True,
            minimum=1,
            help="SLEAP analysis files do not record the video's size.",
        ),
        ReaderParameter(
            name="height_px",
            label="Frame height (pixels)",
            kind="int",
            required=True,
            minimum=1,
        ),
        ReaderParameter(
            name="keypoint",
            label="Animal position from",
            kind="choice",
            help="The skeleton node that stands for the animal. Left unset, the node seen most "
            "often is used.",
        ),
        ReaderParameter(
            name="score_cutoff",
            label="Point score cutoff",
            kind="float",
            default=0.0,
            minimum=0.0,
            help="Positions whose SLEAP point score is below this are treated as missing. "
            "0 (the default) keeps everything SLEAP found.",
        ),
        PX_PER_UNIT_PARAMETER,
        ReaderParameter(
            name="keep_skeleton",
            label="Keep all nodes",
            kind="bool",
            default=True,
            help="Store every node beside the one used (no metric reads them).",
        ),
    )

    # ── detection ──────────────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_files_in(Path(folder)))

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        found: list[tuple[Path, Hdf5Root]] = []
        for entry in index.walk():
            if entry.is_dir or entry.suffix not in _SUFFIXES or entry.cloud_only:
                continue
            root = peek.hdf5_root(entry.path, strings=("node_names", "track_names"))
            if _is_analysis(root):
                found.append((entry.path, root))  # type: ignore[arg-type]
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=_session_id(path),
                source=path,
                files=(path,),
                warnings=_warnings_for(root),
            )
            for path, root in found
        )
        nodes = [r.strings.get("node_names", []) for _, r in found]
        common = [n for n in nodes[0] if all(n in other for other in nodes)]
        parameters = tuple(
            spec.model_copy(update={"choices": tuple(common)}) if spec.name == "keypoint" else spec
            for spec in cls.parameters
        )
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.HIGH,
                evidence=(
                    f"{len(found)} HDF5 file(s) with tracks, track_names, node_names and "
                    "track_occupancy (a SLEAP analysis export)",
                ),
                sessions=sessions,
                parameters=parameters,
                verification=cls.verification,
            )
        ]

    # ── reading ────────────────────────────────────────────────────────────

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        data = _load(path)
        return _build_session(Path(folder), path, data, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            if folder.is_file():
                raise _not_an_analysis_file(folder)
            if folder.is_dir() and any(
                p.suffix.lower() in _SUFFIXES for p in folder.iterdir() if p.is_file()
            ):
                raise _not_an_analysis_file(folder)
            raise _error(
                "SLEAP_NO_FILE",
                f"Nothing to read at {folder}.",
                "Point at a SLEAP analysis .h5 file, or a folder that holds one.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} SLEAP analysis files, one per video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _not_an_analysis_file(path: Path) -> ImportError_:
    return _error(
        "SLEAP_NOT_AN_ANALYSIS_FILE",
        f"{path} is not a SLEAP analysis file.",
        "In SLEAP choose File > Export Analysis HDF5 and add that .h5 file. Project files (.slp) "
        "are not read.",
        str(path),
    )


class _Data:
    def __init__(self) -> None:
        self.tracks: np.ndarray
        self.track_names: list[str] = []
        self.node_names: list[str] = []
        self.edges: list[tuple[int, int]] = []
        self.point_scores: np.ndarray | None = None
        self.occupancy_shape: tuple[int, ...] = ()
        self.dims: Any = None


def _text(v: Any) -> str:
    return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)


def _load(path: Path) -> _Data:
    import h5py

    out = _Data()
    try:
        with h5py.File(path, "r") as f:
            if not _is_analysis(Peeker().hdf5_root(path)):
                raise _not_an_analysis_file(path)
            tracks = f["tracks"]
            out.dims = tracks.attrs.get("dims")
            out.tracks = np.asarray(tracks[...], dtype=np.float64)
            out.node_names = [_text(v) for v in f["node_names"][...]]
            names = f["track_names"]
            # A project with no tracks writes an empty float64 dataset: iterating it gives no names.
            out.track_names = [_text(v) for v in names[...]]
            out.occupancy_shape = tuple(f["track_occupancy"].shape)
            edges = np.asarray(f["edge_inds"][...]) if "edge_inds" in f else np.empty((0,))
            # No edges are written as an empty (0,) dataset, not (0, 2).
            if edges.ndim == 2 and edges.size:
                flat = [int(v) for v in edges.reshape(-1)]
                out.edges = list(zip(flat[0::2], flat[1::2], strict=True))
            if "point_scores" in f:
                out.point_scores = np.asarray(f["point_scores"][...], dtype=np.float64)
    except ImportError_:
        raise
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise _error(
            "SLEAP_UNREADABLE",
            f"{path.name} could not be read as HDF5 ({exc}).",
            "The file may be damaged or incomplete; export it from SLEAP again.",
            str(path),
        ) from None
    return out


def _check_layout(path: Path, d: _Data) -> None:
    """Refuse a layout that is not the one this reader understands, rather than guessing."""
    if d.dims is not None:
        try:
            dims = json.loads(_text(d.dims))
        except (ValueError, TypeError):
            dims = None
        if dims != _STANDARD_DIMS:
            raise _error(
                "SLEAP_LAYOUT_UNSUPPORTED",
                f"{path.name} declares the axis order {_text(d.dims)!r}.",
                "Only the standard order (track, xy, node, frame) is read. Export the file again "
                "from the SLEAP GUI (File > Export Analysis HDF5).",
                str(path),
            )
    n_tracks, n_xy, n_nodes, n_frames = d.tracks.shape
    problems = []
    if n_xy != 2:
        problems.append(f"the second axis of tracks has {n_xy} entries, not 2 (x and y)")
    if d.occupancy_shape != (n_frames, n_tracks):
        problems.append(
            f"track_occupancy is {d.occupancy_shape}, expected {(n_frames, n_tracks)} "
            "(frames, tracks)"
        )
    if n_nodes != len(d.node_names):
        problems.append(f"tracks has {n_nodes} nodes but node_names lists {len(d.node_names)}")
    if d.track_names and len(d.track_names) != n_tracks:
        problems.append(f"tracks has {n_tracks} tracks but track_names lists {len(d.track_names)}")
    if problems:
        raise _error(
            "SLEAP_LAYOUT_AMBIGUOUS",
            f"{path.name} does not match the SLEAP analysis layout: " + "; ".join(problems) + ".",
            "The file may not be a SLEAP analysis export, or may be from an unsupported version. "
            "Export it from the SLEAP GUI (File > Export Analysis HDF5).",
            str(path),
        )


def _build_session(given: Path, path: Path, d: _Data, opts: dict[str, Any]) -> Session:
    _check_layout(path, d)
    n_tracks, _, _, n_frames = d.tracks.shape
    if n_frames == 0:
        raise DataValidationError(
            f"{path.name} holds no frames.",
            code="READER_OUTPUT_INVALID",
            subject="raw_xy",
            remediation="The file has a header but no data; export it from SLEAP again.",
        )
    xy = to_nan(d.tracks.transpose(3, 0, 2, 1))  # (frames, tracks, nodes, xy)
    confidence = None
    if d.point_scores is not None and d.point_scores.shape == (
        n_tracks,
        len(d.node_names),
        n_frames,
    ):
        confidence = d.point_scores.transpose(2, 0, 1)
    cutoff = opts["score_cutoff"]
    reduction = reduce_keypoints(
        xy,
        d.node_names,
        confidence,
        keypoint=opts.get("keypoint") or None,
        cutoff=cutoff if cutoff else None,
    )
    keep = bool(opts.get("keep_skeleton")) and skeleton_fits(xy, confidence)
    edges = [(a, b) for a, b in d.edges if a < len(d.node_names) and b < len(d.node_names)]
    keypoints = build_keypoints(xy, d.node_names, confidence, edges, reduction.selection, keep=keep)
    positional = n_tracks > 1 and (
        not d.track_names or all(_SYNTHETIC.match(n) for n in d.track_names)
    )
    session = assemble_session(
        session_id=_session_id(path),
        folder=given,
        reader=SleapAnalysisReader.name,
        fps=opts["fps"],
        width_px=opts["width_px"],
        height_px=opts["height_px"],
        raw_xy=reduction.raw_xy,
        has_stable_identities=not positional,
        track_wo_identities=True if positional else None,
        identities_labels=(list(d.track_names) if d.track_names and not positional else None),
        keypoints=keypoints,
        trajectory_source=path,
        trajectory_format="sleap_analysis_h5",
        length_unit=opts.get("px_per_unit"),
    )
    if opts.get("keep_skeleton") and keypoints is None:
        session.raw_attrs = {
            "skeleton_not_kept": "the full skeleton is larger than the storage budget; "
            "only the chosen node was kept"
        }
    return session
