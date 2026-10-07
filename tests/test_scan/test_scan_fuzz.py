"""A scan is a total function: whatever the tree looks like, it returns, the same way each time."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from track2data.readers.index import IndexEntry, ScanIndex
from track2data.readers.scan import ScanResult, scan_index

#: A vocabulary biased towards names that readers look for, so generated trees hit real code paths.
NAMES = [
    "trajectories",
    "trajectories.npy",
    "trajectories.h5",
    "trajectories_csv",
    "trajectories_wo_gaps.npy",
    "video_object.npy",
    "session.json",
    "notes.txt",
    "d1",
    "d2",
    "a.csv",
    "x.h5",
]

trees = st.lists(
    st.tuples(st.lists(st.sampled_from(NAMES), min_size=1, max_size=5), st.booleans()),
    max_size=15,
)


def _index_from(tree: list[tuple[list[str], bool]]) -> ScanIndex:
    root = Path("/virtual") / "root"
    entries: dict[Path, IndexEntry] = {root: IndexEntry(root, is_dir=True)}
    for parts, last_is_dir in tree:
        path = root
        for depth, part in enumerate(parts, start=1):
            path = path / part
            is_dir = depth < len(parts) or last_is_dir
            existing = entries.get(path)
            entries[path] = IndexEntry(
                path, is_dir or (existing is not None and existing.is_dir), 0, False, depth
            )
    ordered = sorted(entries.values(), key=lambda e: (e.depth, str(e.path)))
    return ScanIndex([root], ordered)


def _summary(result: ScanResult) -> tuple[object, ...]:
    return tuple(
        (
            d.reader,
            int(d.confidence),
            tuple((s.session_id, str(s.source)) for s in d.sessions),
        )
        for g in result.groups
        for d in g.detections
    )


@settings(max_examples=200, deadline=None)
@given(trees)
def test_a_scan_never_raises_and_is_deterministic(tree: list[tuple[list[str], bool]]) -> None:
    index = _index_from(tree)
    first = scan_index(index)
    second = scan_index(index)
    assert _summary(first) == _summary(second)


@settings(max_examples=200, deadline=None)
@given(trees)
def test_session_ids_are_always_safe_and_unique_within_a_detection(
    tree: list[tuple[list[str], bool]],
) -> None:
    result = scan_index(_index_from(tree))
    for group in result.groups:
        for detection in group.detections:
            ids = [s.session_id for s in detection.sessions]
            assert len(set(ids)) == len(ids)
            assert all(i and "/" not in i and "\\" not in i for i in ids)
