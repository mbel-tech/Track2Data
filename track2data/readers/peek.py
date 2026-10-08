"""Header peeks: the only place a scan opens a file.

Detection must be cheap, safe and bounded, so a peek reads a few kilobytes at most and parses a
*header*, never data:

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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from track2data.readers.index import _CLOUD_ONLY, ScanBudget, ScanIndex


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
        return Hdf5Root(nodes, found)

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
