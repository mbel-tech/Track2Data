"""DeepLabCut prediction tables as CSV (also Lightning Pose and EKS tables, which share the layout).

A table has a ``scorer`` row, an optional ``individuals`` row, a ``bodyparts`` row and a ``coords``
row, then one line per frame whose first cell is the frame number. Multi-animal files have the
four-row header; single-animal files the three-row one, and the two cannot be told apart by
extension or first cell, only by the second row.

What the file does **not** record is the frame rate and the frame size, so they are options the
user gives (never defaulted). Which keypoint stands for the animal is also a choice; without one
the best-covered keypoint is used (``readers/assemble.py``). The whole skeleton is kept beside it.

Traps handled here, each pinned by a test:

* Only the coordinates named ``x``, ``y`` and ``likelihood`` are read. Lightning Pose / EKS tables
  carry six more per keypoint (``x_ens_median`` ...) that must not shift anything.
* ``single`` is DeepLabCut's catch-all for unique body parts, not an animal: left out unless asked.
* Individuals called ``ind1``, ``ind2`` ... are positional placeholders, not tracked identities.
* A human-filled gap has a likelihood of 0.01, so the default cutoff of 0.6 drops it.
* An annotation file (``CollectedData_*``) or a 3-D table has no likelihood and is not a
  prediction file; this reader does not claim it.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from track2data.core.errors import DataValidationError, ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.assemble import (
    assemble_session,
    build_keypoints,
    reduce_keypoints,
    skeleton_fits,
    to_nan,
)
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.params import ProposedValue, ReaderParameter, resolve_options
from track2data.readers.peek import Peeker

#: DeepLabCut's name for the unique body parts in a multi-animal project: not an animal.
_CATCH_ALL = "single"
_PLACEHOLDER = re.compile(r"^ind\d+$")
_NEEDED = ("x", "y", "likelihood")
_HEAD_BYTES = 65_536


@dataclass(frozen=True)
class _Header:
    """The header rows of a prediction table."""

    depth: int  # 3 (single animal) or 4 (multi-animal)
    columns: tuple[tuple[str, str, str], ...]  # (individual or "", bodypart, coord) per data column
    scorer: str

    @property
    def multi(self) -> bool:
        return self.depth == 4

    @property
    def individuals(self) -> list[str]:
        return list(dict.fromkeys(c[0] for c in self.columns)) if self.multi else []

    @property
    def bodyparts(self) -> list[str]:
        return list(dict.fromkeys(c[1] for c in self.columns))

    @property
    def has_extra_coords(self) -> bool:
        return any(c[2] not in _NEEDED for c in self.columns)


def _parse_header(lines: list[str]) -> _Header | None:
    """The header the first lines describe, or None if this is not a prediction table."""
    if len(lines) < 3:
        return None
    rows = [next(csv.reader([line]), []) for line in lines[:4]]
    if not rows[0] or rows[0][0].strip().lower() != "scorer":
        return None
    second = rows[1][0].strip().lower() if rows[1] else ""
    if second == "individuals":
        depth = 4
    elif second == "bodyparts":
        depth = 3
    else:
        return None
    if len(rows) < depth or len(lines) < depth:
        return None
    bp_row, coord_row = rows[depth - 2], rows[depth - 1]
    if not bp_row or not coord_row:
        return None
    if bp_row[0].strip().lower() != "bodyparts" or coord_row[0].strip().lower() != "coords":
        return None
    width = len(coord_row)
    scorer_row = rows[0] + [""] * (width - len(rows[0]))
    ind_row = (rows[1] + [""] * width)[:width] if depth == 4 else [""] * width
    bp_row = (bp_row + [""] * width)[:width]
    columns = tuple(
        (ind_row[j].strip(), bp_row[j].strip(), coord_row[j].strip().lower())
        for j in range(1, width)
    )
    if not columns or not set(_NEEDED) <= {c[2] for c in columns}:
        return None  # an annotation file or a 3-D table: no likelihood
    return _Header(depth=depth, columns=columns, scorer=scorer_row[1].strip() if width > 1 else "")


def _header_of(path: Path) -> _Header | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read(_HEAD_BYTES)
    except OSError:
        return None
    text = data.decode("utf-8-sig", errors="replace")
    return _parse_header(text.splitlines()[:5])


def _files_in(path: Path) -> list[Path]:
    """The prediction files a path stands for: itself, or the ones directly inside a folder."""
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


class DeepLabCutReader(SessionReader):
    """DeepLabCut prediction tables (CSV): one session per file."""

    name = "deeplabcut"
    display_name: ClassVar[str] = "DeepLabCut (CSV; also Lightning Pose)"
    verification = "real_sample"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(
            name="fps",
            label="Frame rate (frames per second)",
            kind="float",
            required=True,
            minimum=0.001,
            help="DeepLabCut files do not record the video's frame rate.",
        ),
        ReaderParameter(
            name="width_px",
            label="Frame width (pixels)",
            kind="int",
            required=True,
            minimum=1,
            help="DeepLabCut files do not record the video's size.",
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
            help="The keypoint that stands for the animal. Left unset, the keypoint seen "
            "most often after the likelihood cutoff is used.",
        ),
        ReaderParameter(
            name="likelihood_cutoff",
            label="Likelihood cutoff",
            kind="float",
            default=0.6,
            minimum=0.0,
            maximum=1.0,
            help="Positions less certain than this are treated as missing. 0 keeps everything.",
        ),
        ReaderParameter(
            name="individuals",
            label="Animals",
            kind="multichoice",
            help="Which animals to read. Left unset, all but DeepLabCut's catch-all 'single'.",
        ),
        ReaderParameter(
            name="keep_skeleton",
            label="Keep all keypoints",
            kind="bool",
            default=True,
            help="Store every keypoint beside the one used (no metric reads them).",
        ),
    )

    # ── detection ──────────────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_files_in(Path(folder)))

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        found: list[tuple[Path, _Header]] = []
        for entry in index.walk():
            if entry.is_dir or entry.suffix != ".csv" or entry.cloud_only:
                continue
            lines = peek.text_lines(entry.path, 5)
            header = _parse_header(lines) if lines else None
            if header is not None:
                found.append((entry.path, header))
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=default_session_id(path, is_file=True),
                source=path,
                files=(path,),
                warnings=_warnings_for(header),
            )
            for path, header in found
        )
        headers = [h for _, h in found]
        layout = (
            "individuals / bodyparts / coords"
            if any(h.multi for h in headers)
            else ("bodyparts / coords")
        )
        evidence = (
            f"{len(found)} file(s) with a DeepLabCut header (scorer / {layout}, "
            "with x, y and likelihood)",
        )
        proposed: dict[str, ProposedValue] = {}
        if all(h.has_extra_coords for h in headers):
            # Lightning Pose and EKS already filter by their own confidence; a second cutoff on
            # top of it would be a decision nobody made.
            proposed["likelihood_cutoff"] = ProposedValue(value=0.0, source="tool-default")
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.HIGH,
                evidence=evidence,
                sessions=sessions,
                parameters=_resolved_parameters(headers),
                proposed=proposed,
                verification=cls.verification,
            )
        ]

    # ── reading ────────────────────────────────────────────────────────────

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        header = _header_of(path)
        if header is None:  # _the_file already checked; the file changed under us
            raise _not_a_prediction_file(path)
        table = _read_table(path, header)
        return _build_session(Path(folder), path, header, table, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            if folder.is_file() or folder.is_dir():
                raise _not_a_prediction_file(folder)
            raise _error(
                "DLC_NO_FILE",
                f"Nothing to read at {folder}.",
                "Point at a DeepLabCut .csv file, or a folder that holds one.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} DeepLabCut files, one per video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _warnings_for(header: _Header) -> tuple[str, ...]:
    placeholders = [i for i in header.individuals if _PLACEHOLDER.match(i)]
    if len(header.individuals) > 1 and len(placeholders) == len(header.individuals):
        return (
            f"Animals are named {', '.join(placeholders[:3])}...: positional placeholders "
            "(the order detections came in), not identities that were tracked.",
        )
    return ()


def _resolved_parameters(headers: list[_Header]) -> tuple[ReaderParameter, ...]:
    """The class's options with the choices the scanned files make possible."""
    keypoints = [k for k in headers[0].bodyparts if all(k in h.bodyparts for h in headers)]
    individuals = headers[0].individuals
    out: list[ReaderParameter] = []
    for spec in DeepLabCutReader.parameters:
        if spec.name == "keypoint":
            out.append(spec.model_copy(update={"choices": tuple(keypoints)}))
        elif spec.name == "individuals":
            if individuals:
                out.append(spec.model_copy(update={"choices": tuple(individuals)}))
        else:
            out.append(spec)
    return tuple(out)


def _not_a_prediction_file(path: Path) -> ImportError_:
    return _error(
        "DLC_NOT_A_PREDICTION_FILE",
        f"{path} is not a DeepLabCut prediction table.",
        "A prediction table starts with a 'scorer' row and has x, y and likelihood columns. "
        "Annotation files (CollectedData_*) and 3-D tables are not read.",
        str(path),
    )


@dataclass
class _Table:
    frames: np.ndarray  # (R,) int frame number per data row
    values: np.ndarray  # (R, C) float, NaN = empty cell


def _read_table(path: Path, header: _Header) -> _Table:
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(
            "DLC_UNREADABLE",
            f"{path.name} is not valid text ({exc.reason}).",
            "The file may be damaged; re-export it from DeepLabCut.",
            str(path),
        ) from None
    body = text.splitlines()[header.depth :]
    if not body:
        return _Table(np.empty(0, dtype=np.int64), np.empty((0, len(header.columns))))
    try:
        df = pd.read_csv(io.StringIO("\n".join(body)), header=None, index_col=0, dtype=str)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise _error(
            "DLC_UNREADABLE",
            f"{path.name} could not be parsed: {exc}",
            "The file may be damaged; re-export it from DeepLabCut.",
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
            "DLC_BAD_FRAME_INDEX",
            f"{path.name}: the first column must hold each frame number once.",
            "The file may be damaged or edited; re-export it from DeepLabCut.",
            str(path),
        )
    numeric = df.apply(pd.to_numeric, errors="coerce")
    if (numeric.isna() & df.notna()).to_numpy().any():
        raise _error(
            "DLC_BAD_VALUE",
            f"{path.name} has cells that are not numbers.",
            "The file may be damaged or edited; re-export it from DeepLabCut.",
            str(path),
        )
    values = numeric.to_numpy(dtype=np.float64)
    width = len(header.columns)
    if values.shape[1] < width:  # a short table: pad the missing columns as empty
        values = np.pad(values, ((0, 0), (0, width - values.shape[1])), constant_values=np.nan)
    return _Table(frames.astype(np.int64), values[:, :width])


def _build_session(
    given: Path, path: Path, header: _Header, table: _Table, opts: dict[str, Any]
) -> Session:
    wanted = _chosen_individuals(header, opts.get("individuals"))
    animals = wanted if header.multi else [""]
    names = list(dict.fromkeys(c[1] for c in header.columns if c[0] in animals or not header.multi))
    position = {c: j for j, c in enumerate(header.columns)}
    n_frames = int(table.frames.max()) + 1 if len(table.frames) else 0
    xy = np.full((n_frames, len(animals), len(names), 2), np.nan)
    likelihood = np.full((n_frames, len(animals), len(names)), np.nan)
    for a, animal in enumerate(animals):
        for k, bodypart in enumerate(names):
            for axis, coord in enumerate(("x", "y")):
                j = position.get((animal, bodypart, coord))
                if j is not None and len(table.frames):
                    xy[table.frames, a, k, axis] = table.values[:, j]
            j = position.get((animal, bodypart, "likelihood"))
            if j is not None and len(table.frames):
                likelihood[table.frames, a, k] = table.values[:, j]
    xy = to_nan(xy)
    if not len(table.frames):
        raise DataValidationError(
            f"{path.name} holds no frames.",
            code="READER_OUTPUT_INVALID",
            subject="raw_xy",
            remediation="The file has a header but no data; re-export it from DeepLabCut.",
        )
    cutoff = opts["likelihood_cutoff"]
    likelihood_ignored = False
    finite_likelihood = likelihood[np.isfinite(likelihood)]
    if finite_likelihood.size and not finite_likelihood.any():
        # EKS (ensemble Kalman) tables write a likelihood of exactly 0 for every frame, a
        # placeholder: a cutoff on it would erase the whole recording.
        likelihood_ignored = True
        likelihood = None  # type: ignore[assignment]
    reduction = reduce_keypoints(
        xy,
        names,
        likelihood,
        keypoint=opts.get("keypoint") or None,
        cutoff=cutoff if cutoff else None,
    )
    keep = bool(opts.get("keep_skeleton")) and skeleton_fits(xy, likelihood)
    notes: dict[str, str] = {}
    if likelihood_ignored:
        notes["likelihood_ignored"] = (
            "every likelihood in the file is 0, a placeholder rather than a measurement, so "
            "no likelihood cutoff was applied"
        )
    keypoints = build_keypoints(xy, names, likelihood, [], reduction.selection, keep=keep)
    placeholders = len(animals) > 1 and all(_PLACEHOLDER.match(a) for a in animals)
    session = assemble_session(
        session_id=default_session_id(path, is_file=True),
        folder=given,
        reader=DeepLabCutReader.name,
        fps=opts["fps"],
        width_px=opts["width_px"],
        height_px=opts["height_px"],
        raw_xy=reduction.raw_xy,
        has_stable_identities=not placeholders,
        identities_labels=list(animals) if header.multi else None,
        keypoints=keypoints,
        trajectory_source=path,
        trajectory_format="deeplabcut_csv",
    )
    if opts.get("keep_skeleton") and keypoints is None:
        notes["skeleton_not_kept"] = (
            "the full skeleton is larger than the storage budget; only the chosen keypoint was kept"
        )
    if notes:
        session.raw_attrs = notes
    return session


def _chosen_individuals(header: _Header, requested: Any) -> list[str]:
    """The animals to read: those asked for, else all but DeepLabCut's catch-all."""
    available = header.individuals
    if requested:
        if not header.multi:
            raise DataValidationError(
                "This file has no individuals row, so there is no choice of animals.",
                code="READER_OPTION_INVALID",
                subject="individuals",
                remediation="Leave the animals option empty for a single-animal file.",
            )
        unknown = [i for i in requested if i not in available]
        if unknown:
            raise DataValidationError(
                f"Animal(s) {', '.join(unknown)} are not in this file.",
                code="READER_OPTION_INVALID",
                subject="individuals",
                remediation="Choose from: " + ", ".join(available) + ".",
            )
        return [i for i in available if i in set(requested)]
    chosen = [i for i in available if i != _CATCH_ALL]
    return chosen or available
