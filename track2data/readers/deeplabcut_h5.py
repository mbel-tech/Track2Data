"""DeepLabCut prediction tables as HDF5 (``*.h5``), the file DeepLabCut writes beside the CSV.

DeepLabCut saves ``df.to_hdf(path, key="df_with_missing", format="table")``. The numbers are a
``table`` compound dataset (``index`` plus ``values_block_N`` arrays). The column labels
``(scorer, [individual,] bodypart, coord)`` are not stored as text: pandas pickles them into HDF5
attributes. They are decoded here with an unpickler that refuses **every** global (the pickles
pandas writes for labels are protocol 0 and hold only lists, tuples, strings and integers), and
each attribute is size-capped. PyTables is neither imported nor needed (DECISIONS D-050). The scan
itself never unpickles: it only sees the plain-text ``pandas_type`` marker (``Peeker.hdf5_root``).

After decoding, the table goes through the same ``_build_session`` as the CSV reader, so the two
formats of one prediction give the same session. The frame rate and frame size are options the
user gives; the files record neither.

Not read: the multi-animal tracklet files (``*_el.h5`` / ``*_full.pickle`` side files, whose root
group is ``tracks``) and pandas "fixed"-format files. Both are refused with a remediation.
"""

from __future__ import annotations

import io
import pickle
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from track2data.core.errors import ImportError_
from track2data.core.ids import default_session_id
from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.deeplabcut import (
    _NEEDED,
    DeepLabCutReader,
    _build_session,
    _Header,
    _parse_header,
    _Table,
)
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanIndex
from track2data.readers.params import ReaderParameter, resolve_options
from track2data.readers.peek import Peeker

#: The key DeepLabCut writes its prediction table under.
_KEY = "df_with_missing"
_SUFFIXES = (".h5", ".hdf5")
#: The most a pickled attribute may be before it is refused unread (a hostile or damaged file).
_MAX_LABEL_BYTES = 16 * 1024 * 1024
_NOT_DLC_LABELS = "its column labels are not a (scorer, bodyparts, coords) table"


def _error(code: str, message: str, remediation: str, subject: str = "") -> ImportError_:
    return ImportError_(message, code=code, subject=subject, remediation=remediation)


class _LabelUnpickler(pickle.Unpickler):
    """Decodes label pickles and nothing else: no global (class, function) may be looked up."""

    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(f"{module}.{name} is not allowed in a label")


def _labels(raw: Any, attribute: str, path: Path) -> Any:
    """Decode one pickled label attribute, or raise ``DLCH5_LABELS_REFUSED``."""
    data = bytes(raw)
    refuse = _error(
        "DLCH5_LABELS_REFUSED",
        f"{path.name}: the column labels ({attribute}) are not plain labels, so the file was "
        "not read.",
        "Nothing was run. Export the prediction as CSV from DeepLabCut instead "
        "(analyze_videos with save_as_csv=True, or deeplabcut.analyze_videos_converth5_to_csv).",
        str(path),
    )
    if len(data) > _MAX_LABEL_BYTES:
        raise refuse
    try:
        return _LabelUnpickler(io.BytesIO(data), encoding="utf-8").load()
    except Exception:  # a refused global, a truncated or non-pickle attribute
        raise refuse from None


def _the_pandas_group(handle: Any, path: Path) -> Any:
    """The group holding the prediction table; refuses the layouts this reader does not take."""
    import h5py

    candidates = [
        name
        for name, obj in handle.items()
        if isinstance(obj, h5py.Group)
        and _text(obj.attrs.get("pandas_type")) == "frame_table"
        and isinstance(obj.get("table"), h5py.Dataset)
    ]
    if not candidates:
        if "tracks" in handle:
            raise _error(
                "DLCH5_LAYOUT_UNSUPPORTED",
                f"{path.name} looks like a DeepLabCut multi-animal tracklet file (its root "
                "group is 'tracks'), not a prediction table.",
                "Use the prediction table DeepLabCut writes for the video, as CSV or as the "
                "'.h5' that does not end in '_el' or '_full'.",
                str(path),
            )
        raise _error(
            "DLCH5_LAYOUT_UNSUPPORTED",
            f"{path.name} does not hold a DeepLabCut prediction table "
            f"(no pandas 'table' group such as '{_KEY}').",
            "Point at the '.h5' prediction file DeepLabCut writes beside the video, or at its CSV.",
            str(path),
        )
    name = _KEY if _KEY in candidates else candidates[0]
    return handle[name]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _load(path: Path) -> tuple[_Header, _Table]:
    """Decode the table into the header and values the CSV path builds."""
    import h5py

    try:
        handle = h5py.File(path, "r")
    except OSError as exc:
        raise _error(
            "DLCH5_UNREADABLE",
            f"{path.name} could not be opened as HDF5 ({exc}).",
            "The file may be damaged or not finished writing; re-run the analysis in DeepLabCut.",
            str(path),
        ) from None
    with handle:
        group = _the_pandas_group(handle, path)
        table = group["table"]
        axes = _labels(group.attrs.get("non_index_axes", b""), "non_index_axes", path)
        columns = _columns_of(axes, path)
        if _text(table.attrs.get("index_kind")) != "integer":
            raise _error(
                "DLCH5_LAYOUT_UNSUPPORTED",
                f"{path.name}: the row index is not a frame number.",
                "Use the prediction file DeepLabCut writes for a video, not a labelled-data file.",
                str(path),
            )
        try:
            data = table[()]
            frames = np.asarray(data["index"], dtype=np.int64)
            values = np.full((len(frames), len(columns)), np.nan)
            slot = {label: j for j, label in enumerate(columns)}
            for field in data.dtype.names or ():
                if not field.startswith("values_block_"):
                    continue
                kind = _labels(table.attrs.get(f"{field}_kind", b""), f"{field}_kind", path)
                block = np.asarray(data[field], dtype=np.float64).reshape(len(frames), -1)
                if len(kind) != block.shape[1] or any(tuple(k) not in slot for k in kind):
                    raise _layout(path, "the value blocks do not match the column labels")
                for i, label in enumerate(kind):
                    values[:, slot[tuple(label)]] = block[:, i]
        except ImportError_:
            raise
        except Exception as exc:
            raise _error(
                "DLCH5_UNREADABLE",
                f"{path.name}: the table could not be read ({exc}).",
                "The file may be damaged; re-run the analysis in DeepLabCut.",
                str(path),
            ) from None
    if (frames < 0).any() or len(np.unique(frames)) != len(frames):
        raise _error(
            "DLC_BAD_FRAME_INDEX",
            f"{path.name}: the frame numbers must be non-negative and each appear once.",
            "The file may be damaged or edited; re-run the analysis in DeepLabCut.",
            str(path),
        )
    depth = len(columns[0])
    header_columns = tuple(
        (label[1] if depth == 4 else "", label[-2], label[-1].lower()) for label in columns
    )
    if not set(_NEEDED) <= {c[2] for c in header_columns}:
        raise _layout(path, "it has no likelihood columns (an annotation file or a 3-D table)")
    header = _Header(depth=depth, columns=header_columns, scorer=columns[0][0])
    return header, _Table(frames, values)


def _layout(path: Path, why: str) -> ImportError_:
    return _error(
        "DLCH5_LAYOUT_UNSUPPORTED",
        f"{path.name} is not a DeepLabCut prediction table: {why}.",
        "Point at the '.h5' prediction file DeepLabCut writes beside the video, or at its CSV.",
        str(path),
    )


def _columns_of(axes: Any, path: Path) -> list[tuple[str, ...]]:
    """The ``(scorer, [individual,] bodypart, coord)`` labels from ``non_index_axes``."""
    try:
        labels = next(items for axis, items in axes if axis == 1)
        columns = [tuple(str(part) for part in label) for label in labels]
    except (StopIteration, TypeError, ValueError):
        raise _layout(path, _NOT_DLC_LABELS) from None
    if not columns or len({len(c) for c in columns}) != 1 or len(columns[0]) not in (3, 4):
        raise _layout(path, _NOT_DLC_LABELS)
    return columns


def _pandas_group_names(root: Any) -> list[str]:
    return [] if root is None else sorted(root.pandas_tables)


def _files_in(path: Path) -> list[Path]:
    """The prediction files a path stands for: itself, or the ``.h5`` files directly inside."""
    path = Path(path)
    if path.is_file():
        return [path] if _KEY in _pandas_group_names(Peeker().hdf5_root(path)) else []
    if not path.is_dir():
        return []
    try:
        candidates = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES
        )
    except OSError:
        return []
    return [p for p in candidates if _KEY in _pandas_group_names(Peeker().hdf5_root(p))]


class DeepLabCutH5Reader(SessionReader):
    """DeepLabCut prediction tables (HDF5): one session per file."""

    name = "deeplabcut_h5"
    display_name: ClassVar[str] = "DeepLabCut (HDF5)"
    #: Built from the documented pandas layout; flips to "real_sample" once the real EPM file
    #: has been read in a run (DECISIONS D-050).
    verification = "synthetic_only"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = tuple(
        # The keypoint names are pickled, so the scan cannot offer them: the user types one (or
        # leaves it empty for the best-covered), and animals are all but DeepLabCut's catch-all.
        spec.model_copy(update={"kind": "str"}) if spec.name == "keypoint" else spec
        for spec in DeepLabCutReader.parameters
        if spec.name != "individuals"
    )

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return bool(_files_in(Path(folder)))

    @classmethod
    def discover(cls, index: ScanIndex, peek: Peeker) -> list[Detection]:
        sessions: list[SessionCandidate] = []
        for entry in index.walk():
            if entry.is_dir or entry.suffix not in _SUFFIXES or entry.cloud_only:
                continue
            root = peek.hdf5_root(entry.path)
            if _KEY not in _pandas_group_names(root):
                continue
            if _has_csv_twin(entry.path, index, peek):
                continue  # DeepLabCut writes both; the CSV is the one session
            sessions.append(
                SessionCandidate(
                    session_id=default_session_id(entry.path, is_file=True),
                    source=entry.path,
                    files=(entry.path,),
                )
            )
        if not sessions:
            return []
        return [
            Detection(
                reader=cls.name,
                display_name=cls.display_name,
                # The labels are pickled and a scan never unpickles, so the table's shape is all
                # that was checked: sure of the layout, not yet of the labels.
                confidence=Confidence.MEDIUM,
                evidence=(
                    f"{len(sessions)} HDF5 file(s) with a pandas table under '{_KEY}' "
                    "(DeepLabCut's prediction layout; labels are checked when read)",
                ),
                sessions=tuple(sessions),
                parameters=cls.parameters,
                verification=cls.verification,
            )
        ]

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        opts = resolve_options(self.name, self.parameters, options)
        path = self._the_file(Path(folder))
        header, table = _load(path)
        return _build_session(
            Path(folder),
            path,
            header,
            table,
            opts,
            reader_name=self.name,
            trajectory_format="deeplabcut_h5",
        )

    def _the_file(self, folder: Path) -> Path:
        if folder.is_file():
            return folder  # _load says what is wrong with it
        files = _files_in(folder)
        if not files:
            raise _error(
                "DLCH5_NO_FILE",
                f"No DeepLabCut .h5 prediction file at {folder}.",
                "Point at a DeepLabCut .h5 file, or a folder that holds one.",
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


def _has_csv_twin(path: Path, index: ScanIndex, peek: Peeker) -> bool:
    """Whether a DeepLabCut CSV of the same name sits beside *path* (so the pair is one session)."""
    twin = index.entry(path.with_suffix(".csv"))
    if twin is None or twin.is_dir or twin.cloud_only:
        return False
    lines = peek.text_lines(twin.path, 5)
    return lines is not None and _parse_header(lines) is not None
