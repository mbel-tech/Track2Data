"""The read-only directory walk: one pass, bounded, never following links, never writing."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from track2data.core.progress import CancellationToken, OperationCancelled, ProgressEvent
from track2data.readers.index import (
    ScanBudget,
    ScanIndex,
    build_index,
    classify_attributes,
)

REPARSE = 0x400
RECALL_ON_DATA_ACCESS = 0x400000
RECALL_ON_OPEN = 0x40000
OFFLINE = 0x1000


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _names(index: ScanIndex, root: Path) -> set[str]:
    return {str(e.path.relative_to(root)).replace(os.sep, "/") for e in index.walk()}


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        digest.update(str(path.relative_to(folder)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class TestClassifyAttributes:
    """Windows file attributes, as a pure function so CI on Linux can test them."""

    def test_an_ordinary_entry_is_kept(self) -> None:
        assert classify_attributes(0, is_dir=False) == (False, False)
        assert classify_attributes(0x20, is_dir=True) == (False, False)

    def test_a_directory_reparse_point_is_skipped(self) -> None:
        # Junctions and directory symlinks are how a tree loops back on itself.
        assert classify_attributes(REPARSE | 0x10, is_dir=True) == (True, False)

    def test_a_file_reparse_point_is_kept(self) -> None:
        assert classify_attributes(REPARSE, is_dir=False) == (False, False)

    @pytest.mark.parametrize("flag", [RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN, OFFLINE])
    def test_cloud_only_placeholders_are_flagged_not_skipped(self, flag: int) -> None:
        assert classify_attributes(flag | 0x20, is_dir=False) == (False, True)

    def test_a_cloud_only_directory_is_listed_even_with_the_reparse_bit(self) -> None:
        assert classify_attributes(REPARSE | RECALL_ON_DATA_ACCESS, is_dir=True) == (False, True)


class TestWalk:
    def test_lists_files_and_directories_breadth_first(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a" / "b" / "deep.txt")
        _touch(tmp_path / "top.csv")
        index = build_index([tmp_path])
        assert _names(index, tmp_path) == {".", "a", "a/b", "a/b/deep.txt", "top.csv"}
        depths = [e.depth for e in index.walk()]
        assert depths == sorted(depths)

    def test_order_is_deterministic(self, tmp_path: Path) -> None:
        for name in ["b", "A", "c", "a"]:
            _touch(tmp_path / name / "f.txt")
        first = [e.path for e in build_index([tmp_path]).walk()]
        second = [e.path for e in build_index([tmp_path]).walk()]
        assert first == second

    def test_children_and_lookup(self, tmp_path: Path) -> None:
        _touch(tmp_path / "s" / "trajectories" / "trajectories.npy", b"12345")
        index = build_index([tmp_path])
        folder = tmp_path / "s" / "trajectories"
        assert [c.name for c in index.children(folder)] == ["trajectories.npy"]
        entry = index.child(folder, "trajectories.npy")
        assert entry is not None and not entry.is_dir and entry.size == 5
        assert index.child(folder, "missing") is None
        assert index.entry(tmp_path / "s").is_dir  # type: ignore[union-attr]

    def test_depth_limit_lists_entries_at_the_limit_but_does_not_expand_them(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path / "d1" / "d2" / "d3" / "d4" / "d5" / "file.txt")
        index = build_index([tmp_path], ScanBudget(max_depth=4))
        names = _names(index, tmp_path)
        assert "d1/d2/d3/d4" in names  # depth 4: listed
        assert "d1/d2/d3/d4/d5" not in names  # would need expanding d4
        assert not index.truncated  # a depth limit is not a truncation

    @pytest.mark.parametrize(
        "skipped",
        ["._hidden.csv", "__MACOSX", ".git", "$RECYCLE.BIN", "System Volume Information",
         "labeled-data", "dlc-models", "training-datasets"],
    )
    def test_noise_and_training_data_are_never_listed(self, tmp_path: Path, skipped: str) -> None:
        _touch(tmp_path / skipped / "inside.txt")
        _touch(tmp_path / "keep.txt")
        assert _names(build_index([tmp_path]), tmp_path) == {".", "keep.txt"}

    def test_symlinks_are_not_followed(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        _touch(real / "f.txt")
        try:
            os.symlink(real, tmp_path / "loop", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this account cannot create symlinks")
        names = _names(build_index([tmp_path]), tmp_path)
        assert "real/f.txt" in names
        assert not any(n.startswith("loop") for n in names)

    def test_a_file_root_is_a_single_entry(self, tmp_path: Path) -> None:
        file = _touch(tmp_path / "one.h5")
        index = build_index([file])
        assert [e.path for e in index.walk()] == [file]

    def test_several_roots_are_walked_in_order(self, tmp_path: Path) -> None:
        _touch(tmp_path / "x" / "a.txt")
        _touch(tmp_path / "y" / "b.txt")
        index = build_index([tmp_path / "x", tmp_path / "y"])
        assert [e.name for e in index.walk() if not e.is_dir] == ["a.txt", "b.txt"]
        assert index.roots == (tmp_path / "x", tmp_path / "y")

    def test_file_types_are_counted_for_the_empty_state(self, tmp_path: Path) -> None:
        for name in ["a.mp4", "b.mp4", "c.h5", "no_extension"]:
            _touch(tmp_path / name)
        assert build_index([tmp_path]).file_types == {".mp4": 2, ".h5": 1, "": 1}


class TestNeverRaises:
    def test_an_unreadable_directory_becomes_a_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _touch(tmp_path / "ok" / "f.txt")
        _touch(tmp_path / "locked" / "g.txt")
        real_scandir = os.scandir

        def scandir(path: object) -> object:
            if Path(str(path)).name == "locked":
                raise PermissionError(13, "denied")
            return real_scandir(path)

        monkeypatch.setattr(os, "scandir", scandir)
        index = build_index([tmp_path])
        assert "ok/f.txt" in _names(index, tmp_path)
        assert any("locked" in w for w in index.warnings)

    def test_a_missing_root_becomes_a_warning(self, tmp_path: Path) -> None:
        index = build_index([tmp_path / "does-not-exist"])
        assert list(index.walk()) == []
        assert index.warnings


class TestBudgets:
    def test_the_entry_cap_truncates(self, tmp_path: Path) -> None:
        for i in range(20):
            _touch(tmp_path / f"f{i:02d}.txt")
        index = build_index([tmp_path], ScanBudget(max_entries=5))
        assert index.truncated
        assert len(list(index.walk())) == 5

    def test_the_time_cap_truncates(self, tmp_path: Path) -> None:
        for i in range(5):
            _touch(tmp_path / f"d{i}" / "f.txt")
        ticks = iter(range(0, 1000, 10))  # every clock read advances 10 s
        budget = ScanBudget(max_seconds=15)
        index = build_index([tmp_path], budget, clock=lambda: float(next(ticks)))
        assert index.truncated


class TestProgressAndCancellation:
    def test_progress_is_throttled(self, tmp_path: Path) -> None:
        for i in range(30):
            _touch(tmp_path / f"d{i:02d}" / "f.txt")
        events: list[ProgressEvent] = []
        now = [0.0]

        def clock() -> float:
            now[0] += 0.02  # 20 ms per read
            return now[0]

        build_index([tmp_path], progress=events.append, clock=clock)
        assert events
        assert all(e.stage == "scan" for e in events)
        # 31 directories were listed but at most one event per 100 ms was emitted.
        assert len(events) < 31

    def test_a_cancelled_token_stops_the_walk(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a" / "f.txt")
        token = CancellationToken()
        token.cancel()
        with pytest.raises(OperationCancelled):
            build_index([tmp_path], token=token)

    def test_cancellation_raised_from_the_progress_callback_propagates(
        self, tmp_path: Path
    ) -> None:
        for i in range(10):
            _touch(tmp_path / f"d{i}" / "f.txt")

        def cancel(event: ProgressEvent) -> None:
            raise OperationCancelled()

        with pytest.raises(OperationCancelled):
            build_index([tmp_path], progress=cancel, clock=lambda: 1e9)


def test_building_an_index_never_writes(tmp_path: Path) -> None:
    _touch(tmp_path / "a" / "f.txt", b"payload")
    _touch(tmp_path / "b.npy", b"\x93NUMPY")
    before = _tree_hash(tmp_path)
    build_index([tmp_path])
    assert _tree_hash(tmp_path) == before
