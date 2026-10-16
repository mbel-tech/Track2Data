"""Anipose ``pose-3d`` tables (CSV): 3-D positions in the calibration board's unit.

A table has one header line and one line per frame. Per keypoint it carries ``<kp>_x``, ``<kp>_y``,
``<kp>_z`` (plus ``_error``, ``_ncams`` and ``_score``), then ``M_xx`` and ``center_*`` columns for
the animal's rigid-body fit, and ``fnum``, the frame number. Keypoint names contain hyphens and
underscores, so a suffix is split from the *right*. A keypoint that could not be triangulated is
NaN in x, y and z together.

What the file does **not** record is the frame rate and the unit of its coordinates (the unit of
the calibration board the user used; mm is the usual one, but it is a fact about the recording
rather than the file). Both are options the user gives, never defaulted. A file holds one animal
unless the user lists the animals' column prefixes in the ``animals`` option (decision D-053):
``fishA,fishB`` reads the columns ``fishA_<keypoint>_x|y|z`` and ``fishB_<keypoint>_x|y|z`` as two
slots of one session, in that order. The prefixes are never guessed from the names, because
``left_ear`` / ``right_ear`` look the same as ``fishA_nose`` / ``fishB_nose``.

Rows missing from ``fnum`` are not filled: the stored rows are the frames the file has, and the
gaps become ``tracking_intervals``, so no step treats the move across a gap as one frame of motion.
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
from track2data.readers.params import ProposedValue, ReaderParameter, resolve_options
from track2data.readers.peek import (
    Peeker,
    header_too_long,
    header_too_long_error,
    read_header_lines,
)

_FRAME_COLUMN = "fnum"


@dataclass(frozen=True)
class _Layout:
    """The columns of a pose-3d table."""

    columns: tuple[str, ...]
    keypoints: tuple[str, ...]  # those with a complete x, y, z triple, in file order
    scored: bool  # every keypoint also has a ``_score`` column
    duplicates: tuple[str, ...] = ()  # x/y/z column names of a keypoint that appear twice


def _parse_header(line: str | None) -> _Layout | None:
    """The layout a header line describes, or None if this is not a pose-3d table."""
    if not line:
        return None
    columns = tuple(c.strip() for c in next(csv.reader([line]), []))
    if _FRAME_COLUMN not in columns:
        return None
    present = set(columns)
    names: list[str] = []
    for column in columns:
        name, _, suffix = column.rpartition("_")
        if (
            suffix == "x"
            and name
            and name not in names
            and f"{name}_y" in present
            and f"{name}_z" in present
        ):
            names.append(name)
    if not names:
        return None
    scored = all(f"{n}_score" in present for n in names)
    wanted = {f"{n}_{axis}" for n in names for axis in "xyz"}
    seen: set[str] = set()
    repeated: list[str] = []
    for column in columns:
        if column in seen and column in wanted and column not in repeated:
            repeated.append(column)
        seen.add(column)
    return _Layout(
        columns=columns, keypoints=tuple(names), scored=scored, duplicates=tuple(repeated)
    )


def _header_of(path: Path) -> _Layout | None:
    lines = read_header_lines(path, 1)  # the whole header line, however many keypoints it names
    return _parse_header(lines[0] if lines else None)


def _files_in(path: Path) -> list[Path]:
    """The pose-3d files a path stands for: itself, or the ones directly inside a folder."""
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


class AniposeReader(SessionReader):
    """Anipose pose-3d tables (CSV): one session per file."""

    name = "anipose"
    display_name: ClassVar[str] = "Anipose (pose-3d CSV)"
    verification = "synthetic_only"
    coordinate_frame = "physical_unaligned"
    provides_native_3d: ClassVar[bool] = True
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        *native_parameters("mm"),
        ReaderParameter(
            name="animals",
            label="Animal column prefixes (several animals in one file)",
            kind="str",
            help="Leave empty for a file with one animal. For several animals in one file, "
            "list the prefixes of their columns in order, separated by commas: 'fishA,fishB' "
            "reads fishA_<keypoint>_x, _y, _z and fishB_<keypoint>_x, _y, _z. Every animal "
            "needs the same keypoints.",
        ),
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
            lines = peek.header_lines(entry.path, 1)
            layout = _parse_header(lines[0] if lines else None)
            if layout is not None:
                found.append((entry.path, layout))
        if not found:
            return []
        sessions = tuple(
            SessionCandidate(
                session_id=default_session_id(path, is_file=True),
                source=path,
                files=(path,),
                warnings=tuple(
                    f"duplicate column {name}: the file will be refused when read"
                    for name in layout.duplicates
                ),
            )
            for path, layout in found
        )
        layouts = [layout for _, layout in found]
        evidence = (
            f"{len(found)} file(s) with an Anipose pose-3d header "
            "(fnum and <keypoint>_x / _y / _z columns)",
        )
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                confidence=Confidence.HIGH,
                evidence=evidence,
                sessions=sessions,
                parameters=_resolved_parameters(layouts),
                # The file does not state its unit; mm is what Anipose users calibrate in, but it
                # is a proposal the user confirms, never a default.
                proposed={"unit": ProposedValue(value="mm", source="tool-default")},
                verification=cls.verification,
            )
        ]

    # ── reading ────────────────────────────────────────────────────────────

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        layout = _header_of(path)
        if layout is None:  # _the_file already checked; the file changed under us
            raise _not_a_pose_3d_file(path)
        return _build_session(Path(folder), path, layout, opts)

    def _the_file(self, folder: Path) -> Path:
        files = _files_in(folder)
        if not files:
            if folder.is_file() or folder.is_dir():
                raise _not_a_pose_3d_file(folder)
            raise _error(
                "ANIPOSE_NO_FILE",
                f"Nothing to read at {folder}.",
                "Point at an Anipose pose-3d .csv file, or a folder that holds one.",
                str(folder),
            )
        if len(files) > 1:
            names = ", ".join(f.name for f in files)
            raise _error(
                "SESSION_AMBIGUOUS",
                f"{folder} holds {len(files)} Anipose files, one per animal or video.",
                f"Add one of them directly, or scan the folder to add them all: {names}.",
                str(folder),
            )
        return files[0]


def _resolved_parameters(layouts: list[_Layout]) -> tuple[ReaderParameter, ...]:
    """The class's options with the keypoints of every scanned file as the choices."""
    return with_keypoint_choices(AniposeReader.parameters, [lay.keypoints for lay in layouts])


def _not_a_pose_3d_file(path: Path) -> DataValidationError:
    if path.is_file() and header_too_long(path, 1):
        return header_too_long_error(path, "an Anipose pose-3d table")
    return _error(
        "ANIPOSE_NOT_A_POSE_3D_FILE",
        f"{path} is not an Anipose pose-3d table.",
        "A pose-3d table has an 'fnum' column and <keypoint>_x, _y and _z columns for each "
        "keypoint.",
        str(path),
    )


def _read_table(path: Path, layout: _Layout) -> pd.DataFrame:
    if layout.duplicates:
        raise _error(
            "ANIPOSE_DUPLICATE_COLUMN",
            f"{path.name}: Anipose columns appear more than once ({', '.join(layout.duplicates)}).",
            "Each keypoint needs exactly one x, one y and one z column; re-export it from Anipose.",
            str(path),
        )
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="strict")
        df = pd.read_csv(io.StringIO(text), dtype=str)
    except UnicodeDecodeError as exc:
        raise _error(
            "ANIPOSE_UNREADABLE",
            f"{path.name} is not valid text ({exc.reason}).",
            "The file may be damaged; re-export it from Anipose.",
            str(path),
        ) from None
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise _error(
            "ANIPOSE_UNREADABLE",
            f"{path.name} could not be parsed: {exc}",
            "The file may be damaged; re-export it from Anipose.",
            str(path),
        ) from None
    df.columns = [str(c).strip() for c in df.columns]
    used = [_FRAME_COLUMN]
    for name in layout.keypoints:
        used += [f"{name}_x", f"{name}_y", f"{name}_z"]
        if layout.scored:
            used.append(f"{name}_score")
    df = df[used]
    numeric = df.apply(pd.to_numeric, errors="coerce")
    if (numeric.isna() & df.notna()).to_numpy().any():
        raise _error(
            "ANIPOSE_BAD_VALUE",
            f"{path.name} has cells that are not numbers.",
            "The file may be damaged or edited; re-export it from Anipose.",
            str(path),
        )
    return numeric


def animal_prefixes(value: Any) -> list[str]:
    """The prefixes in the ``animals`` option, in order; empty when the option is not used."""
    if value is None:
        return []
    names = [part.strip() for part in str(value).split(",") if part.strip()]
    if len(set(names)) != len(names):
        raise ImportError_(
            f"Option 'animals' repeats a name: {value!r}.",
            code="READER_OPTION_INVALID",
            subject="animals",
            remediation="List each animal prefix once, e.g. fishA,fishB.",
        )
    return names


def _split_animals(
    path: Path, layout: _Layout, prefixes: list[str]
) -> tuple[list[str], list[list[str]]]:
    """Per animal, the file's column stem of each shared keypoint, and the shared names.

    A keypoint column belongs to the longest listed prefix it starts with (``fish_`` and
    ``fish_2_`` can both be animals). Every column must belong to one, and every animal must have
    the same keypoints; otherwise the file is not what the user said it is.
    """
    by_animal: list[list[str]] = [[] for _ in prefixes]
    stray: list[str] = []
    for name in layout.keypoints:
        owners = [
            (len(p), i) for i, p in enumerate(prefixes) if name.startswith(f"{p}_") and name != p
        ]
        if not owners:
            stray.append(name)
            continue
        by_animal[max(owners)[1]].append(name)
    problems: list[str] = []
    for prefix, stems in zip(prefixes, by_animal, strict=True):
        if not stems:
            problems.append(f"no columns start with '{prefix}_'")
    if stray:
        problems.append(
            "columns of no listed animal: "
            + ", ".join(stray[:4])
            + (" ..." if len(stray) > 4 else "")
        )
    shared: list[str] = []
    if not problems:
        shortened = [
            [s[len(p) + 1 :] for s in stems]
            for p, stems in zip(prefixes, by_animal, strict=True)
        ]
        shared = shortened[0]
        for p, names in zip(prefixes[1:], shortened[1:], strict=True):
            if names != shared:
                missing = sorted(set(shared) ^ set(names))
                problems.append(
                    f"'{p}' does not have the same keypoints as '{prefixes[0]}' "
                    f"({', '.join(missing[:4])})"
                )
    if problems:
        raise _error(
            "ANIPOSE_ANIMAL_COLUMNS",
            f"{path.name}: the animals option does not match the columns: "
            + "; ".join(problems)
            + ".",
            "List every animal's column prefix in the order you want the animals, and give each "
            "the same keypoints; or leave the option empty for a file with one animal.",
            str(path),
        )
    return shared, by_animal


def _build_session(given: Path, path: Path, layout: _Layout, opts: dict[str, Any]) -> Session:
    """The session for one file. ``raw_xy``/``raw_z`` follow ``vertical_axis`` and ``flip``; the
    stored skeleton keeps the file's axes (converted to the target unit, not permuted or flipped).
    """
    table = _read_table(path, layout)
    if table.empty:
        raise DataValidationError(
            f"{path.name} holds no frames.",
            code="READER_OUTPUT_INVALID",
            subject="raw_xy",
            remediation="The file has a header but no data; re-export it from Anipose.",
        )
    fnum = table[_FRAME_COLUMN].to_numpy(dtype=np.float64)
    if (
        not np.isfinite(fnum).all()
        or (fnum != np.floor(fnum)).any()
        or (fnum < 0).any()
        or len(np.unique(fnum)) != len(fnum)
    ):
        raise _error(
            "ANIPOSE_BAD_FRAME_INDEX",
            f"{path.name}: the fnum column must hold each frame number once.",
            "The file may be damaged or edited; re-export it from Anipose.",
            str(path),
        )
    order = np.argsort(fnum, kind="stable")
    frames = fnum[order].astype(np.int64)
    prefixes = animal_prefixes(opts.get("animals"))
    if prefixes:
        names, stems_by_animal = _split_animals(path, layout, prefixes)
    else:
        names, stems_by_animal = list(layout.keypoints), [list(layout.keypoints)]
    xyz = np.stack(
        [
            np.stack(
                [
                    table[[f"{n}_x", f"{n}_y", f"{n}_z"]].to_numpy(dtype=np.float64)[order]
                    for n in stems
                ],
                axis=1,
            )
            for stems in stems_by_animal
        ],
        axis=1,
    )  # (R, A, K, 3)
    xyz[~np.isfinite(xyz).all(axis=-1)] = np.nan  # a triple is missing as a whole
    xyz = convert_units(xyz, opts["unit"], opts["target_unit"])
    score = None
    if layout.scored:
        score = np.stack(
            [
                np.stack(
                    [table[f"{n}_score"].to_numpy(dtype=np.float64)[order] for n in stems], axis=1
                )
                for stems in stems_by_animal
            ],
            axis=1,
        )  # (R, A, K)
    cutoff = opts.get("likelihood_cutoff")
    if cutoff and score is None:
        raise DataValidationError(
            "A score cutoff was set but not every keypoint has a _score column.",
            code="READER_OPTION_INVALID",
            subject="likelihood_cutoff",
            remediation="Set the score cutoff to 0, or use a file with scores for every keypoint.",
        )
    reduction, z = reduce_native(
        xyz,
        names,
        score,
        keypoint=opts.get("keypoint") or None,
        cutoff=cutoff if cutoff else None,
        vertical_axis=opts["vertical_axis"],
        flip=bool(opts["flip"]),
    )
    keep = bool(opts.get("keep_skeleton")) and skeleton_fits(xyz, score)
    keypoints = build_keypoints(xyz, names, score, [], reduction.selection, keep=keep)
    session = assemble_native_session(
        session_id=default_session_id(path, is_file=True),
        folder=given,
        reader=AniposeReader.name,
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
        trajectory_format="anipose_pose3d_csv",
    )
    if prefixes:
        session.identities_labels = list(prefixes)
    if opts.get("keep_skeleton") and keypoints is None and session.raw_attrs is not None:
        session.raw_attrs["skeleton_not_kept"] = (
            "the full skeleton is larger than the storage budget; only the chosen keypoint was kept"
        )
    return session
