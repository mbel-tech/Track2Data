"""Header peeks: the only place a scan opens a file, so the only place it can go wrong."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.readers.index import IndexEntry, ScanBudget, ScanIndex
from track2data.readers.peek import NpyHeader, Peeker


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


class TestHeadBytes:
    def test_returns_at_most_the_peek_size(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.bin", b"x" * 1000)
        assert Peeker(ScanBudget(peek_bytes=64)).head_bytes(file) == b"x" * 64

    def test_a_shorter_file_is_returned_whole(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.bin", b"abc")
        assert Peeker().head_bytes(file) == b"abc"

    @pytest.mark.parametrize("name", ["missing.bin", ""])
    def test_a_missing_path_is_none_not_an_error(self, tmp_path: Path, name: str) -> None:
        assert Peeker().head_bytes(tmp_path / name) is None

    def test_a_directory_is_none(self, tmp_path: Path) -> None:
        assert Peeker().head_bytes(tmp_path) is None


class TestTextLines:
    def test_first_lines_with_any_line_ending(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.csv", b"a,b\r\nc,d\re,f\ng,h\n")
        assert Peeker().text_lines(file, 3) == ["a,b", "c,d", "e,f"]

    def test_a_byte_order_mark_is_stripped(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.csv", b"\xef\xbb\xbfscorer,x\n")
        assert Peeker().text_lines(file, 1) == ["scorer,x"]

    def test_undecodable_bytes_do_not_raise(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.csv", b"caf\xe9,x\n")
        lines = Peeker().text_lines(file, 1)
        assert lines is not None and lines[0].endswith(",x")

    def test_an_empty_file_has_no_lines(self, tmp_path: Path) -> None:
        assert Peeker().text_lines(_write(tmp_path / "e.csv", b""), 3) == []


class TestBudget:
    def test_peeks_stop_when_the_budget_is_spent(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "f.bin", b"abc")
        peek = Peeker(ScanBudget(max_peeks=2))
        assert peek.head_bytes(file) == b"abc"
        assert not peek.exhausted
        assert peek.head_bytes(file) == b"abc"
        assert peek.exhausted
        assert peek.head_bytes(file) is None


class TestCloudOnlyFiles:
    def test_a_cloud_only_entry_is_never_opened(self, tmp_path: Path) -> None:
        file = _write(tmp_path / "placeholder.h5", b"real bytes")
        index = ScanIndex(
            [tmp_path],
            [
                IndexEntry(tmp_path, is_dir=True),
                IndexEntry(file, is_dir=False, size=10, cloud_only=True, depth=1),
            ],
        )
        assert Peeker(index=index).head_bytes(file) is None
        # The same bytes are read once the entry is not flagged: it is the flag that stops it.
        normal = ScanIndex(
            [tmp_path],
            [IndexEntry(tmp_path, is_dir=True), IndexEntry(file, is_dir=False, depth=1)],
        )
        assert Peeker(index=normal).head_bytes(file) == b"real bytes"


class TestNpyHeader:
    def test_a_raw_float_array(self, tmp_path: Path) -> None:
        file = tmp_path / "raw.npy"
        np.save(file, np.zeros((5, 2, 2)))
        header = Peeker().npy_header(file)
        assert header == NpyHeader(shape=(5, 2, 2), dtype=np.dtype("float64"), fortran_order=False)
        assert not header.is_object

    def test_a_pickled_dict_is_an_object_array(self, tmp_path: Path) -> None:
        file = tmp_path / "dict.npy"
        np.save(file, {"trajectories": np.zeros((3, 1, 2))}, allow_pickle=True)
        header = Peeker().npy_header(file)
        assert header is not None
        assert header.is_object
        assert header.shape == ()

    def test_fortran_order_is_reported(self, tmp_path: Path) -> None:
        file = tmp_path / "f.npy"
        np.save(file, np.asfortranarray(np.zeros((3, 4))))
        header = Peeker().npy_header(file)
        assert header is not None and header.fortran_order

    def test_a_pickle_is_never_executed(self, tmp_path: Path) -> None:
        marker = tmp_path / "executed.txt"
        file = tmp_path / "evil.npy"
        np.save(file, np.array([_Evil(str(marker))], dtype=object), allow_pickle=True)
        assert not marker.exists()  # saving only pickles it
        header = Peeker().npy_header(file)
        assert header is not None and header.is_object
        assert not marker.exists(), "reading the header must not unpickle the data"

    @pytest.mark.parametrize("content", [b"", b"not a numpy file", b"\x93NUMPY\x01\x00"])
    def test_a_corrupt_file_is_none(self, tmp_path: Path, content: bytes) -> None:
        assert Peeker().npy_header(_write(tmp_path / "bad.npy", content)) is None

    def test_a_missing_file_is_none(self, tmp_path: Path) -> None:
        assert Peeker().npy_header(tmp_path / "nope.npy") is None


class _Evil:
    """Unpickling this writes a marker file, so the test can tell whether anything unpickled."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        return (Path(self.marker).write_text, ("executed",))
