"""Header peeks: the only place a scan opens a file.

Detection must be cheap, safe and bounded, so a peek reads a few kilobytes and parses a *header*,
never data. The one exception is a text table's header lines (``header_lines``), which are read
whole, up to a fixed cap (8 MB), because a table with thousands of keypoints has a very long first
line:

* ``.npy`` headers are parsed with ``numpy.lib.format`` (a literal-eval of the header dict), so an
  object array is reported as one without being unpickled. A pickle inside a file a user merely
  pointed the scan at must never run.
* A cloud-only placeholder (OneDrive "online only") is never opened, because opening it downloads
  it. Detection reports it with low confidence and a warning instead.
* There is a budget of peeks per scan, and every method returns ``None`` on any failure: a
  half-written file, a permission error and a corrupt header all mean "cannot tell", not a crash.

HDF5 files get a read-only look at their top level (``hdf5_root``). Peeks for other containers
are added with the first reader that needs them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError
from track2data.readers.index import _CLOUD_ONLY, ScanBudget, ScanIndex

_log = logging.getLogger(__name__)

#: The most a header read takes to get its whole lines. A table with thousands of keypoints has a
#: header line of hundreds of kilobytes; past this the file is treated as not recognised.
MAX_HEADER_BYTES = 8 * 1024 * 1024
_FIRST_CHUNK = 65_536


def _scan_header(path: Path, n: int, limit: int) -> tuple[list[str] | None, bool]:
    """``(lines, too_long)``: the first *n* complete lines, or ``(None, True)`` when they do not
    fit in *limit* bytes, or ``(None, False)`` when the file cannot be opened."""
    chunk = _FIRST_CHUNK
    data = b""
    try:
        with open(path, "rb") as handle:
            while True:
                more = handle.read(min(chunk, max(limit - len(data), 0)))
                data += more
                text = data.decode("utf-8-sig", errors="replace")
                parts = text.splitlines(keepends=True)
                ended = [len(part.splitlines()[0]) != len(part) for part in parts if part]
                if sum(ended) >= n or (not more and len(data) < limit):
                    return text.splitlines()[:n], False
                if len(data) >= limit:
                    return None, True
                chunk = min(chunk * 2, limit)
    except OSError:
        return None, False


def read_header_lines(path: Path, n: int, limit: int = MAX_HEADER_BYTES) -> list[str] | None:
    """The first *n* **complete** text lines of a file (BOM stripped, any line ending, bad bytes
    replaced), never a partial one; fewer if the file has fewer lines.

    Reads in growing chunks until *n* lines are ended or the file is. If *n* lines do not fit in
    *limit* bytes, logs one line and returns None (undetected). None as well when the file cannot
    be opened.
    """
    lines, too_long = _scan_header(path, n, limit)
    if too_long:
        _log.info("%s: header is longer than %d bytes; not recognised", path.name, limit)
    return lines


def header_too_long(path: Path, n: int, limit: int = MAX_HEADER_BYTES) -> bool:
    """True when the first *n* lines of the file do not fit in *limit* bytes (the case
    :func:`read_header_lines` reports as None), so a reader can say so instead of "not a table"."""
    return _scan_header(path, n, limit)[1]


def header_too_long_error(path: Path, what: str) -> DataValidationError:
    """The error for a file whose header exceeds the cap, named after the format *what*."""
    megabytes = MAX_HEADER_BYTES // (1024 * 1024)
    return DataValidationError(
        f"{path.name}: the header is longer than the {megabytes} MB allowed for a header, so "
        f"the file was not recognised as {what}.",
        code="HEADER_TOO_LONG",
        subject=str(path),
        remediation="Check that this is a real tracker export; a header this long is usually a "
        "wrong file or a table written without line breaks.",
    )


@dataclass(frozen=True)
class NpyHeader:
    """What a ``.npy`` file says about itself, without reading its data."""

    shape: tuple[int, ...]
    dtype: np.dtype[Any]
    fortran_order: bool

    @property
    def is_object(self) -> bool:
        """True for a pickled object (such as idtracker.ai's trajectory dict)."""
        return bool(self.dtype.hasobject)


@dataclass(frozen=True)
class Hdf5Node:
    """One top-level object of an HDF5 file."""

    kind: str  # "dataset" or "group"
    shape: tuple[int, ...] | None = None  # datasets only
    dtype_kind: str | None = None  # numpy kind letter: "f" float, "i" int, "S" bytes, "O" object
    attrs: dict[str, Any] = field(default_factory=dict)  # a dataset's attributes, as text/numbers


@dataclass(frozen=True)
class Hdf5Root:
    """The top level of an HDF5 file: what is there, and a few small string datasets."""

    nodes: dict[str, Hdf5Node]
    strings: dict[str, list[str]] = field(default_factory=dict)
    #: Top-level groups that pandas wrote with ``format="table"`` (their ``pandas_type`` attribute,
    #: plain text, is ``frame_table``), as ``{group: (rows, value_columns)}``. Only that marker is
    #: read: the column labels are pickled and a peek never unpickles anything.
    pandas_tables: dict[str, tuple[int, int]] = field(default_factory=dict)


#: A string dataset longer than this is not read by a peek.
_MAX_PEEK_STRINGS = 1000


class Peeker:
    """Budgeted, failure-tolerant reads of file headers."""

    def __init__(self, budget: ScanBudget | None = None, index: ScanIndex | None = None) -> None:
        self._budget = budget or ScanBudget()
        self._index = index
        self._peeks = 0

    @property
    def exhausted(self) -> bool:
        return self._peeks >= self._budget.max_peeks

    def _cloud_only(self, path: Path) -> bool:
        entry = self._index.entry(path) if self._index is not None else None
        if entry is not None:
            return entry.cloud_only
        try:  # stat reads metadata only, so it does not download a placeholder
            attrs = getattr(os.stat(path), "st_file_attributes", 0)
        except OSError:
            return False
        return bool(attrs & _CLOUD_ONLY)

    def _allowed(self, path: Path) -> bool:
        """Count the peek and say whether it may go ahead."""
        if self.exhausted:
            return False
        self._peeks += 1
        return not self._cloud_only(path)

    def head_bytes(self, path: Path, n: int | None = None) -> bytes | None:
        """The first *n* bytes (at most the budget's peek size), or None if unreadable."""
        path = Path(path)
        if not self._allowed(path):
            return None
        limit = self._budget.peek_bytes if n is None else min(n, self._budget.peek_bytes)
        try:
            with open(path, "rb") as handle:
                return handle.read(limit)
        except OSError:
            return None

    def text_lines(self, path: Path, n: int = 5) -> list[str] | None:
        """The first *n* lines as text: BOM stripped, any line ending, bad bytes replaced."""
        data = self.head_bytes(path)
        if data is None:
            return None
        return data.decode("utf-8-sig", errors="replace").splitlines()[:n]

    def header_lines(self, path: Path, n: int) -> list[str] | None:
        """The first *n* complete lines (see :func:`read_header_lines`), however long they are
        up to the header cap, rather than the peek size. One peek."""
        path = Path(path)
        if not self._allowed(path):
            return None
        return read_header_lines(path, n)

    def hdf5_root(self, path: Path, strings: tuple[str, ...] = ()) -> Hdf5Root | None:
        """The top level of an HDF5 file, read-only; None if it cannot be read.

        Lists each top-level object's kind, shape, dtype kind and (for datasets) attributes, and
        reads the datasets named in *strings* when they are small text datasets (or empty). Numeric
        data is never read, and nothing is deserialised beyond text.
        """
        path = Path(path)
        if not self._allowed(path):
            return None
        try:
            import h5py

            with h5py.File(path, "r") as handle:
                nodes: dict[str, Hdf5Node] = {}
                tables: dict[str, tuple[int, int]] = {}
                for name, obj in handle.items():
                    if isinstance(obj, h5py.Dataset):
                        nodes[name] = Hdf5Node(
                            "dataset",
                            tuple(int(n) for n in obj.shape),
                            obj.dtype.kind,
                            {k: _attr_value(v) for k, v in obj.attrs.items()},
                        )
                    else:
                        nodes[name] = Hdf5Node("group")
                        marker = _pandas_table(obj)
                        if marker is not None:
                            tables[name] = marker
                found: dict[str, list[str]] = {}
                for name in strings:
                    node = handle.get(name)
                    if not isinstance(node, h5py.Dataset) or node.ndim != 1:
                        continue
                    if node.shape[0] == 0:
                        found[name] = []
                    elif node.dtype.kind in ("S", "O", "U") and node.shape[0] <= _MAX_PEEK_STRINGS:
                        found[name] = [_text(v) for v in node[:]]
        except Exception:  # not HDF5, truncated, permissions: cannot tell
            return None
        return Hdf5Root(nodes, found, tables)

    def mat_variables(self, path: Path) -> dict[str, tuple[tuple[int, ...], str]] | None:
        """The variables of a classic (v5) MATLAB file as ``{name: (shape, class)}``; else None.

        Reads the variable headers only (scipy's ``whosmat``), never the arrays. A v7.3 file is
        HDF5 underneath and is not listed here. Nothing is executed or deserialised.
        """
        path = Path(path)
        if not self._allowed(path):
            return None
        try:
            import scipy.io as sio

            listing = sio.whosmat(str(path))
        except Exception:  # not MATLAB, truncated, permissions: cannot tell
            return None
        return {name: (tuple(int(n) for n in shape), str(kind)) for name, shape, kind in listing}

    def npy_header(self, path: Path) -> NpyHeader | None:
        """Parse a ``.npy`` header without loading (or unpickling) any data."""
        path = Path(path)
        if not self._allowed(path):
            return None
        try:
            with open(path, "rb") as handle:
                version = np.lib.format.read_magic(handle)
                if version == (1, 0):
                    shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(handle)
                elif version == (2, 0):
                    shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(handle)
                else:
                    return None
        except Exception:  # corrupt, truncated or not numpy at all: cannot tell
            return None
        return NpyHeader(tuple(shape), dtype, bool(fortran_order))


def _pandas_table(group: Any) -> tuple[int, int] | None:
    """``(rows, value columns)`` of a pandas ``format="table"`` group, else None. Reads the
    plain-text ``pandas_type`` attribute and the table's dtype only."""
    try:
        if _attr_value(group.attrs.get("pandas_type")) != "frame_table":
            return None
        table = group.get("table")
        names = table.dtype.names if table is not None else None
        if not names or table.ndim != 1:
            return None
        columns = sum(
            int(np.prod(table.dtype[n].shape)) or 1 for n in names if n.startswith("values_block_")
        )
        return int(table.shape[0]), columns
    except Exception:  # an odd group is just not a pandas table
        return None


def _text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _attr_value(value: Any) -> Any:
    """An HDF5 attribute as something comparable: text for bytes, plain numbers for numpy."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return [_attr_value(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value
