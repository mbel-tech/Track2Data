"""DeepLabCut-3D triangulated tables (CSV): 3-D positions in the calibration board's unit.

A table has three header rows (``scorer``, ``bodyparts``, ``coords``), with ``x``, ``y`` and ``z``
per body part, then one line per frame whose first cell is the frame number. It has no likelihood,
which is also what keeps :class:`~track2data.readers.deeplabcut.DeepLabCutReader` from claiming it.

What the file does **not** record is the frame rate and the unit of its coordinates (the unit of
the calibration board), so both are options the user gives, never defaulted, and this reader
proposes no unit. A point that could not be triangulated is written as ``0, 0, 0`` (or left empty):
a row whose x, y *and* z are all exactly 0 is missing, while a single 0 is a real coordinate.

Frames missing from the first column are not filled: the stored rows are the frames the file has,
and the gaps become ``tracking_intervals``. The table body has its own parser and its own error
codes (``DLC3D_*``), so a problem in a 3-D file is never reported as a DeepLabCut (2-D) one.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from track2data.core.errors import DataValidationError, ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.assemble import assemble_native_session, build_keypoints, skeleton_fits
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.native3d import (
    convert_units,
    frame_intervals,
    native_parameters,
    reduce_native,
    with_keypoint_choices,
)
from track2data.readers.params import ReaderParameter, resolve_options
from track2data.readers.peek import Peeker, read_header_lines

_AXES = ("x", "y", "z")


@dataclass(frozen=True)
class _Layout:
    """The header of a DLC-3D table."""

    width: int  # number of data columns (every column after the frame number)
    keypoints: tuple[str, ...]  # body parts with an x, y and z column, in file order
    columns: dict[str, tuple[int, int, int]]  # body part -> data-column index of x, y, z
    duplicates: tuple[tuple[str, str], ...] = ()  # (body part, axis) given by several columns


def _parse_header(lines: list[str]) -> _Layout | None:
    """The layout the first lines describe, or None if this is not a DLC-3D table."""
    if len(lines) < 3:
        return None
    rows = [next(csv.reader([line]), []) for line in lines[:3]]
    for row, label in zip(rows, ("scorer", "bodyparts", "coords"), strict=True):
        if not row or row[0].strip().lower() != label:
            return None
    width = len(rows[2])
    bodyparts = (rows[1] + [""] * width)[:width]
    coords = [c.strip().lower() for c in rows[2]]
    position: dict[tuple[str, str], int] = {}
    repeated: list[tuple[str, str]] = []
    for j in range(1, width):
        key = (bodyparts[j].strip(), coords[j])
        if key in position:
            if key[0] and key[1] in _AXES and key not in repeated:
                repeated.append(key)
        else:
            position[key] = j - 1
    names = list(dict.fromkeys(bodyparts[j].strip() for j in range(1, width)))
    keypoints = tuple(n for n in names if n and all((n, a) in position for a in _AXES))
    if not keypoints or "likelihood" in coords:
        return None  # no complete x, y, z triple; or a 2-D table that happens to carry a z
    columns = {n: (position[(n, "x")], position[(n, "y")], position[(n, "z")]) for n in keypoints}
    duplicates = tuple(key for key in repeated if key[0] in keypoints)
    return _Layout(
        width=width - 1, keypoints=keypoints, columns=columns, duplicates=duplicates
    )


def _header_of(path: Path) -> _Layout | None:
    lines = read_header_lines(path, 3)  # whole lines, however many body parts the header names
    return _parse_header(lines) if lines else None


def _files_in(path: Path) -> list[Path]:
    """The DLC-3D files a path stands for: itself, or the ones directly inside a folder."""
    path = Path(path)
    if path.is_file():
        return [path] if _header_of(path) is not None else []
    if not path.is_dir():
        return []
    try:
        candidates = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
    except OSError:
        return []
    return [p for p in candidates if _header_of(p) is not None]


def _error(code: str, message: str, remediation: str, subject: str = "") -> ImportError_:
    return ImportError_(message, code=code, subject=subject, remediation=remediation)


class DeepLabCut3DReader(SessionReader):
    """DeepLabCut-3D triangulated tables (CSV): one session per file."""

    name = "deeplabcut_3d"
    display_name: ClassVar[str] = "DeepLabCut 3-D (triangulated CSV)"
    verification = "synthetic_only"
    coordinate_frame = "physical_unaligned"
    provides_native_3d: ClassVar[bool] = True
    # DLC-3D tables carry no likelihood, so there is no cutoff to offer.
    parameters: ClassVar[tuple[ReaderParameter, ...]] = tuple(
        p for p in native_parameters(None) if p.name != "likelihood_cutoff"
    )

    # ── detection ──────────────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_files_in(Path(folder)))

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        found: list[tuple[Path, _Layout]] = []
        for entry in index.walk():
            if entry.is_dir or entry.suffix != ".csv" or entry.cloud_only:
                continue
            lines = peek.header_lines(entry.path, 3)
            layout = _parse_header(lines) if lines else None
            if layout is not None:
                found.append((entry.path, layout))
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=default_session_id(path, is_file=True), source=path, files=(path,)
            )
            for path, _ in found
        )
        evidence = (
            f"{len(found)} file(s) with a DeepLabCut 3-D header "
            "(scorer / bodyparts / coords, with x, y and z and no likelihood)",
        )
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.HIGH,
                evidence=evidence,
                sessions=sessions,
                parameters=_resolved_parameters([layout for _, layout in found]),
                # No proposed unit: the file does not say, and no unit is usual for DLC-3D.
                proposed={},
                verification=cls.verification,
            )
        ]

    # ── reading ────────────────────────────────────────────────────────────

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        layout = _header_of(path)
        if layout is None:  # _the_file already checked; the file changed under us
            raise _not_a_dlc3d_file(path)
        return _build_session(Path(folder), path, layout, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            if folder.is_file() or folder.is_dir():
                raise _not_a_dlc3d_file(folder)
            raise _error(
                "DLC3D_NO_FILE",
                f"Nothing to read at {folder}.",
                "Point at a DeepLabCut 3-D .csv file, or a folder that holds one.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} DeepLabCut 3-D files, one per animal or video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _resolved_parameters(layouts: list[_Layout]) -> tuple[ReaderParameter, ...]:
    """The class's options with the keypoints of every scanned file as the choices."""
    return with_keypoint_choices(DeepLabCut3DReader.parameters, [lay.keypoints for lay in layouts])


def _not_a_dlc3d_file(path: Path) -> ImportError_:
    return _error(
        "DLC3D_NOT_A_3D_FILE",
        f"{path} is not a DeepLabCut 3-D table.",
        "A DeepLabCut 3-D table starts with 'scorer', 'bodyparts' and 'coords' rows and has x, y "
        "and z columns for each body part (and no likelihood).",
        str(path),
    )


@dataclass
class _Table:
    frames: np.ndarray  # (R,) int frame number per data row
    values: np.ndarray  # (R, C) float, NaN = empty cell


def _read_table(path: Path, layout: _Layout) -> _Table:
    """The frame numbers and data cells of a DLC-3D file (what follows its 3 header rows)."""
    reexport = "The file may be damaged or edited; re-export it from DeepLabCut 3-D."
    if layout.duplicates:
        shown = ", ".join(f"{bp} {axis}" for bp, axis in layout.duplicates)
        raise _error(
            "DLC3D_DUPLICATE_COLUMN",
            f"{path.name}: DeepLabCut 3-D columns appear more than once ({shown}).",
            "Each body part needs exactly one x, one y and one z column; " + reexport,
            str(path),
        )
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(
            "DLC3D_UNREADABLE",
            f"{path.name} is not valid text ({exc.reason}); it is not a readable "
            "DeepLabCut 3-D table.",
            "The file may be damaged; re-export it from DeepLabCut 3-D.",
            str(path),
        ) from None
    body = text.splitlines()[3:]
    if not body:
        return _Table(np.empty(0, dtype=np.int64), np.empty((0, layout.width)))
    try:
        df = pd.read_csv(io.StringIO("\n".join(body)), header=None, index_col=0, dtype=str)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise _error(
            "DLC3D_UNREADABLE",
            f"{path.name} could not be parsed as a DeepLabCut 3-D table: {exc}",
            "The file may be damaged; re-export it from DeepLabCut 3-D.",
            str(path),
        ) from None
    frames = pd.to_numeric(pd.Series(df.index, dtype=str), errors="coerce").to_numpy()
    if (
        not np.isfinite(frames).all()
        or (frames != np.floor(frames)).any()
        or (frames < 0).any()
        or len(np.unique(frames)) != len(frames)
    ):
        raise _error(
            "DLC3D_BAD_FRAME_INDEX",
            f"{path.name}: in a DeepLabCut 3-D table the first column must hold each frame "
            "number once, as a whole number of 0 or more.",
            reexport,
            str(path),
        )
    numeric = df.apply(pd.to_numeric, errors="coerce")
    if (numeric.isna() & df.notna()).to_numpy().any():
        raise _error(
            "DLC3D_BAD_VALUE",
            f"{path.name} has cells that are not numbers (DeepLabCut 3-D table).",
            reexport,
            str(path),
        )
    values = numeric.to_numpy(dtype=np.float64)
    if values.shape[1] < layout.width:  # a short table: pad the missing columns as empty
        pad = ((0, 0), (0, layout.width - values.shape[1]))
        values = np.pad(values, pad, constant_values=np.nan)
    return _Table(frames.astype(np.int64), values[:, : layout.width])


def _build_session(given: Path, path: Path, layout: _Layout, opts: dict[str, Any]) -> Session:
    """The session for one file. ``raw_xy``/``raw_z`` follow ``vertical_axis`` and ``flip``; the
    stored skeleton keeps the file's axes (converted to the target unit, not permuted or flipped).
    """
    table = _read_table(path, layout)
    if len(table.frames) == 0:
        raise DataValidationError(
            f"{path.name} holds no frames.",
            code="READER_OUTPUT_INVALID",
            subject="raw_xy",
            remediation="The file has a header but no data; re-export it from DeepLabCut 3-D.",
        )
    order = np.argsort(table.frames, kind="stable")
    frames = table.frames[order]
    names = list(layout.keypoints)
    xyz = np.stack(
        [table.values[order][:, list(layout.columns[n])] for n in names], axis=1
    )  # (R, K, 3)
    # Not triangulated is 0, 0, 0 (a single 0 is a real coordinate) or an empty cell; a partial
    # triple is missing as a whole.
    missing = ~np.isfinite(xyz).all(axis=-1) | (xyz == 0).all(axis=-1)
    xyz[missing] = np.nan
    xyz = convert_units(xyz, opts["unit"], opts["target_unit"])[:, None, :, :]  # (R, 1, K, 3)
    reduction, z = reduce_native(
        xyz,
        names,
        None,
        keypoint=opts.get("keypoint") or None,
        cutoff=None,
        vertical_axis=opts["vertical_axis"],
        flip=bool(opts["flip"]),
    )
    keep = bool(opts.get("keep_skeleton")) and skeleton_fits(xyz, None)
    keypoints = build_keypoints(xyz, names, None, [], reduction.selection, keep=keep)
    session = assemble_native_session(
        session_id=default_session_id(path, is_file=True),
        folder=given,
        reader=DeepLabCut3DReader.name,
        fps=opts["fps"],
        raw_xy=reduction.raw_xy,
        raw_z=z,
        source_unit=opts["unit"],
        target_unit=opts["target_unit"],
        vertical_axis=opts["vertical_axis"],
        flip=bool(opts["flip"]),
        keypoints=keypoints,
        tracking_intervals=frame_intervals(frames),
        trajectory_source=path,
        trajectory_format="deeplabcut_3d_csv",
    )
    if opts.get("keep_skeleton") and keypoints is None and session.raw_attrs is not None:
        session.raw_attrs["skeleton_not_kept"] = (
            "the full skeleton is larger than the storage budget; only the chosen keypoint was kept"
        )
    return session
