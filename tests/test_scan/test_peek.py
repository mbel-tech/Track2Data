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


class TestHdf5Root:
    """What an HDF5 file's top level says about itself: names, kinds, shapes and a few strings.

    Opened with h5py read-only. Only metadata and small string datasets are read; no numeric
    data, and no object that could execute anything.
    """

    @pytest.fixture
    def h5(self, tmp_path: Path) -> Path:
        import h5py

        path = tmp_path / "a.h5"
        with h5py.File(path, "w") as f:
            f.create_dataset("tracks", data=np.zeros((2, 2, 3, 10)))
            f.create_dataset("node_names", data=np.array([b"nose", b"tail", b"ear"]))
            f.create_dataset("empty_names", data=np.empty((0,), dtype=np.float64))
            f.create_group("group")
            f.create_dataset("big_names", data=np.array([b"x"] * 5000))
        return path

    def test_it_lists_top_level_names_with_kind_and_shape(self, h5: Path) -> None:
        root = Peeker().hdf5_root(h5)
        assert root is not None
        tracks = root.nodes["tracks"]
        assert tracks.kind == "dataset" and tracks.shape == (2, 2, 3, 10)
        assert root.nodes["group"].kind == "group" and root.nodes["group"].shape is None

    def test_the_dtype_kind_tells_text_from_numbers(self, h5: Path) -> None:
        root = Peeker().hdf5_root(h5)
        assert root.nodes["node_names"].dtype_kind == "S"
        assert root.nodes["tracks"].dtype_kind == "f"

    def test_small_string_datasets_can_be_read_by_name(self, h5: Path) -> None:
        root = Peeker().hdf5_root(h5, strings=("node_names", "empty_names", "tracks", "nope"))
        assert root.strings["node_names"] == ["nose", "tail", "ear"]
        assert root.strings["empty_names"] == []  # an empty dataset of any type is no names
        assert "tracks" not in root.strings  # numbers are never read
        assert "nope" not in root.strings

    def test_a_long_string_dataset_is_not_read(self, h5: Path) -> None:
        assert "big_names" not in Peeker().hdf5_root(h5, strings=("big_names",)).strings

    def test_attributes_of_a_dataset_are_available(self, tmp_path: Path) -> None:
        import h5py

        path = tmp_path / "b.h5"
        with h5py.File(path, "w") as f:
            f.create_dataset("tracks", data=np.zeros((1, 2, 1, 3))).attrs["dims"] = "x"
        assert Peeker().hdf5_root(path).nodes["tracks"].attrs == {"dims": "x"}

    @pytest.mark.parametrize(
        "content", [b"", b"not hdf5 at all", b"\x89HDF\r\n\x1a\n" + b"\0" * 20]
    )
    def test_anything_that_is_not_a_readable_hdf5_file_is_none(
        self, tmp_path: Path, content: bytes
    ) -> None:
        assert Peeker().hdf5_root(_write(tmp_path / "x.h5", content)) is None

    def test_a_truncated_file_is_none_not_an_error(self, h5: Path) -> None:
        data = h5.read_bytes()
        h5.write_bytes(data[: len(data) // 3])
        assert Peeker().hdf5_root(h5) is None

    def test_a_missing_file_is_none(self, tmp_path: Path) -> None:
        assert Peeker().hdf5_root(tmp_path / "missing.h5") is None

    def test_a_cloud_only_placeholder_is_never_opened(self, h5: Path) -> None:
        index = ScanIndex([h5.parent], [IndexEntry(h5, False, 10, cloud_only=True)])
        assert Peeker(index=index).hdf5_root(h5) is None

    def test_it_counts_against_the_peek_budget(self, h5: Path) -> None:
        peek = Peeker(ScanBudget(max_peeks=1))
        assert peek.hdf5_root(h5) is not None
        assert peek.hdf5_root(h5) is None

    def test_the_file_is_not_modified(self, h5: Path) -> None:
        before = h5.read_bytes()
        Peeker().hdf5_root(h5, strings=("node_names",))
        assert h5.read_bytes() == before
