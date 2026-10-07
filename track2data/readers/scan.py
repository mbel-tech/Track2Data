"""Scanning a folder: one read-only walk, every reader's ``discover``, ranked detections.

``scan`` is what the confirm dialog and ``track2data scan`` both call. It never writes, never
unpickles, and never raises (a reader that misbehaves becomes a warning), with one exception:
cancellation, which propagates so a user's "Cancel" actually stops it.

Detections that claim the same session folders are one *group*: the best reader is offered
first and the others stay available as alternatives, which is how a folder that two readers could
read (an idtracker.ai 6 session with a stray ``video_object.npy``) reaches the user as one
choice instead of two. Detections that claim different folders are separate groups.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from track2data.core.ids import sanitise_session_id, uniquify
from track2data.core.progress import CancellationToken, ProgressCallback
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.index import ScanBudget, ScanIndex, build_index
from track2data.readers.peek import Peeker


@dataclass(frozen=True)
class FormatGroup:
    """Detections over the same session folders, best first; the rest are alternatives."""

    detections: tuple[Detection, ...]

    @property
    def best(self) -> Detection:
        return self.detections[0]


@dataclass(frozen=True)
class ScanResult:
    """Everything a scan found, and what it cost."""

    roots: tuple[Path, ...]
    groups: tuple[FormatGroup, ...]
    #: Files seen by lower-case suffix, for the "nothing recognised" state.
    file_types: Mapping[str, int]
    truncated: bool
    warnings: tuple[str, ...]
    entries: int
    seconds: float


def scan(
    roots: Sequence[Path],
    *,
    budget: ScanBudget | None = None,
    progress: ProgressCallback | None = None,
    token: CancellationToken | None = None,
) -> ScanResult:
    """Walk *roots* once and return the ranked detections.

    Raises only ``OperationCancelled``, from *token* or from *progress*.
    """
    index = build_index(roots, budget, progress, token)
    return scan_index(index, budget=budget, token=token)


def scan_index(
    index: ScanIndex,
    *,
    budget: ScanBudget | None = None,
    token: CancellationToken | None = None,
) -> ScanResult:
    """Run every registered reader over *index*. Pure apart from header peeks."""
    from track2data.readers import _REGISTRY

    peek = Peeker(budget, index)
    warnings = list(index.warnings)
    priority = {cls.name: cls.priority for cls in _REGISTRY}
    found: list[Detection] = []
    for cls in list(_REGISTRY):
        if token is not None:
            token.raise_if_cancelled()
        try:
            found.extend(cls.discover(index, peek))
        except Exception as exc:  # a reader must never break a scan
            warnings.append(f"reader {cls.name} failed during discovery: {exc}")
    found = _prune_nested(found, index)
    found = [_with_unique_ids(d, index.roots) for d in found]
    return ScanResult(
        roots=index.roots,
        groups=tuple(_group(found, priority)),
        file_types=index.file_types,
        truncated=index.truncated,
        warnings=tuple(warnings),
        entries=len(index),
        seconds=index.seconds,
    )


def _prune_nested(detections: list[Detection], index: ScanIndex) -> list[Detection]:
    """Drop weaker claims that sit inside a folder another reader is sure about.

    A session's own files (an idtracker.ai ``trajectories_csv/`` bundle) must not also be
    offered as a table by a generic reader.
    """
    sure = [
        (d.reader, s.source)
        for d in detections
        if d.confidence is Confidence.HIGH
        for s in d.sessions
        if (entry := index.entry(s.source)) is not None and entry.is_dir
    ]
    kept: list[Detection] = []
    for detection in detections:
        if detection.confidence is Confidence.HIGH:
            kept.append(detection)
            continue
        sessions = tuple(
            s
            for s in detection.sessions
            if not any(
                owner != detection.reader and folder in s.source.parents for owner, folder in sure
            )
        )
        if sessions:
            kept.append(dataclasses.replace(detection, sessions=sessions))
    return kept


def _slug(source: Path, roots: Sequence[Path]) -> str:
    """A path-derived id: the folder's place under the root that holds it."""
    for root in roots:
        try:
            parts = source.relative_to(root).parts or (root.name,)
        except ValueError:
            continue
        return sanitise_session_id("__".join(parts))
    return sanitise_session_id("__".join(source.parts[-2:]))


def _with_unique_ids(detection: Detection, roots: Sequence[Path]) -> Detection:
    """Make session ids unique: a name used twice is replaced by its path, then numbered."""
    ids = [s.session_id for s in detection.sessions]
    repeated = {i for i in ids if ids.count(i) > 1}
    if not repeated and len(set(ids)) == len(ids):
        return detection
    named = [
        dataclasses.replace(
            s, session_id=_slug(s.source, roots) if s.session_id in repeated else s.session_id
        )
        for s in detection.sessions
    ]
    final = uniquify([s.session_id for s in named])
    sessions: tuple[SessionCandidate, ...] = tuple(
        dataclasses.replace(s, session_id=new_id) for s, new_id in zip(named, final, strict=True)
    )
    return dataclasses.replace(detection, sessions=sessions)


def _group(detections: list[Detection], priority: Mapping[str, int]) -> list[FormatGroup]:
    """Merge detections that claim any of the same session folders, then rank."""
    parent = list(range(len(detections)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[Path, int] = {}
    for i, detection in enumerate(detections):
        for session in detection.sessions:
            j = owner.setdefault(session.source, i)
            if j != i:
                parent[find(i)] = find(j)

    buckets: dict[int, list[Detection]] = {}
    for i, detection in enumerate(detections):
        buckets.setdefault(find(i), []).append(detection)

    groups = [
        FormatGroup(
            tuple(
                sorted(
                    members,
                    key=lambda d: (-int(d.confidence), -priority.get(d.reader, 0), d.reader),
                )
            )
        )
        for members in buckets.values()
    ]
    groups.sort(key=lambda g: (-int(g.best.confidence), -len(g.best.sessions), g.best.reader))
    return groups
