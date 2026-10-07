"""A single read-only walk of the tree the user pointed at, kept as an immutable index.

Every reader's ``discover`` is a pure function over this index, so the tree is walked once however
many readers there are, and all file opening is confined to ``readers/peek.py``. The walk uses
``os.scandir`` only (names, sizes and attribute bits come from the directory listing, never from
opening a file), so it never triggers a cloud download and never writes.

What it will not do: follow symlinks or directory reparse points (a junction is how a Windows tree
loops back on itself), list macOS noise, version-control folders or DeepLabCut's training data
(thousands of images that no reader wants), or run past its budget. An unreadable directory becomes
a warning, not an exception.
"""

from __future__ import annotations

import os
import stat
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from track2data.core.progress import CancellationToken, ProgressCallback, ProgressEvent, emit

# Windows file attributes (winnt.h).
_REPARSE_POINT = 0x400
#: RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE: a OneDrive-style placeholder. Opening it
#: downloads it, so it is listed (and flagged) but never opened by a scan.
_CLOUD_ONLY = 0x400000 | 0x40000 | 0x1000

#: Names never listed: macOS and Windows noise, version control, and DeepLabCut training data.
_SKIP_NAMES = frozenset(
    {
        "__MACOSX",
        ".git",
        "$RECYCLE.BIN",
        "System Volume Information",
        "labeled-data",
        "training-datasets",
        "dlc-models",
        "dlc-models-pytorch",
    }
)
_SKIP_PREFIXES = ("._",)

#: Seconds between progress events: a Qt-backed UI queues every one it is sent.
_PROGRESS_INTERVAL = 0.1


def classify_attributes(attrs: int, *, is_dir: bool) -> tuple[bool, bool]:
    """Return ``(skip, cloud_only)`` for a Windows ``st_file_attributes`` value.

    A directory reparse point (junction, directory symlink) is skipped unless it is a cloud
    placeholder, which is how OneDrive marks an unsynced folder. A file reparse point is kept:
    deduplicated and similar files are ordinary to read. A pure function so Linux CI can test the
    Windows rules.
    """
    cloud = bool(attrs & _CLOUD_ONLY)
    skip = bool(attrs & _REPARSE_POINT) and is_dir and not cloud
    return skip, cloud


@dataclass(frozen=True)
class ScanBudget:
    """How much a scan may spend. Exceeding it marks the result truncated, never raises."""

    max_entries: int = 100_000
    #: Directory levels below a root that are expanded. Entries at this depth are listed but not
    #: opened: ``root/video/session/trajectories/trajectories.h5`` is depth 4.
    max_depth: int = 4
    max_seconds: float = 30.0
    max_peeks: int = 2_000
    peek_bytes: int = 65_536


@dataclass(frozen=True)
class IndexEntry:
    """One file or directory seen by the walk."""

    path: Path
    is_dir: bool
    size: int = 0
    cloud_only: bool = False
    depth: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


class ScanIndex:
    """The result of a walk: entries in breadth-first order, with lookups by parent."""

    def __init__(
        self,
        roots: Sequence[Path],
        entries: Sequence[IndexEntry],
        *,
        truncated: bool = False,
        warnings: Sequence[str] = (),
        seconds: float = 0.0,
    ) -> None:
        self.roots = tuple(roots)
        self.truncated = truncated
        self.warnings = tuple(warnings)
        self.seconds = seconds
        self._entries = {e.path: e for e in entries}
        root_set = set(self.roots)
        children: dict[Path, list[IndexEntry]] = {}
        for entry in entries:
            if entry.path not in root_set:
                children.setdefault(entry.path.parent, []).append(entry)
        self._children = {parent: tuple(items) for parent, items in children.items()}

    def __len__(self) -> int:
        return len(self._entries)

    def walk(self) -> Iterator[IndexEntry]:
        """Every entry, breadth-first, roots first."""
        return iter(self._entries.values())

    def dirs(self) -> Iterator[IndexEntry]:
        """Every directory, breadth-first: the candidates for a session folder."""
        return (e for e in self._entries.values() if e.is_dir)

    def entry(self, path: Path) -> IndexEntry | None:
        return self._entries.get(Path(path))

    def children(self, path: Path) -> tuple[IndexEntry, ...]:
        return self._children.get(Path(path), ())

    def child(self, path: Path, name: str) -> IndexEntry | None:
        for entry in self.children(path):
            if entry.name == name:
                return entry
        return None

    @property
    def file_types(self) -> dict[str, int]:
        """Count of files by lower-case suffix ('' for none), for the "nothing recognised" state."""
        counts: dict[str, int] = {}
        for entry in self._entries.values():
            if not entry.is_dir:
                counts[entry.suffix] = counts.get(entry.suffix, 0) + 1
        return counts


def build_index(
    roots: Sequence[Path],
    budget: ScanBudget | None = None,
    progress: ProgressCallback | None = None,
    token: CancellationToken | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ScanIndex:
    """Walk *roots* once and return the index. Never writes, never opens a file, never raises
    except ``OperationCancelled`` (raised by *token* or by the *progress* callback)."""
    budget = budget or ScanBudget()
    start = clock()
    entries: list[IndexEntry] = []
    warnings: list[str] = []
    truncated = False
    last_emit = float("-inf")
    queue: deque[tuple[Path, int]] = deque()
    root_paths = [Path(os.path.abspath(root)) for root in roots]

    for root in root_paths:
        try:
            info = os.stat(root)
        except OSError as exc:
            warnings.append(f"cannot read {root}: {exc}")
            continue
        is_dir = stat.S_ISDIR(info.st_mode)
        _, cloud = classify_attributes(getattr(info, "st_file_attributes", 0), is_dir=is_dir)
        entries.append(IndexEntry(root, is_dir, 0 if is_dir else info.st_size, cloud, 0))
        if is_dir:
            queue.append((root, 0))

    while queue and not truncated:
        if token is not None:
            token.raise_if_cancelled()
        now = clock()
        if now - start > budget.max_seconds:
            truncated = True
            break
        directory, depth = queue.popleft()
        if progress is not None and now - last_emit >= _PROGRESS_INTERVAL:
            last_emit = now
            emit(
                progress,
                ProgressEvent(stage="scan", current=len(entries), total=0, message=str(directory)),
            )
        try:
            with os.scandir(directory) as listing:
                for item in sorted(listing, key=lambda e: e.name.casefold()):
                    if item.name in _SKIP_NAMES or item.name.startswith(_SKIP_PREFIXES):
                        continue
                    try:
                        if item.is_symlink():
                            continue
                        is_dir = item.is_dir(follow_symlinks=False)
                        info = item.stat(follow_symlinks=False)
                    except OSError as exc:
                        warnings.append(f"cannot stat {item.path}: {exc}")
                        continue
                    skip, cloud = classify_attributes(
                        getattr(info, "st_file_attributes", 0), is_dir=is_dir
                    )
                    if skip:
                        continue
                    if len(entries) >= budget.max_entries:
                        truncated = True
                        break
                    entry = IndexEntry(
                        Path(item.path), is_dir, 0 if is_dir else info.st_size, cloud, depth + 1
                    )
                    entries.append(entry)
                    if is_dir and depth + 1 < budget.max_depth:
                        queue.append((entry.path, depth + 1))
        except OSError as exc:
            warnings.append(f"cannot list {directory}: {exc}")

    if truncated:
        warnings.append(
            f"scan stopped early after {len(entries)} entries: raise the budget or pick a "
            "narrower folder"
        )
    return ScanIndex(
        root_paths, entries, truncated=truncated, warnings=warnings, seconds=clock() - start
    )
