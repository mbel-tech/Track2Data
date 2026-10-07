"""A folder that looks like idtracker.ai v4 output gets a specific, honest error."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.core.errors import ImportError_
from track2data.readers import detect_reader, probe_session, read_session
from track2data.readers.idtrackerai_v4 import IDTrackerAiV4Reader, looks_like_v4


def _make_v4(root: Path, *, nested: bool) -> Path:
    session = root / "session_demo" if nested else root
    (session / "preprocessing").mkdir(parents=True)
    (session / "video_object.npy").write_bytes(b"x")
    (session / "preprocessing" / "blobs_collection.npy").write_bytes(b"x")
    return root


@pytest.mark.parametrize("nested", [False, True])
def test_v4_markers_are_recognised_directly_or_one_level_down(tmp_path, nested) -> None:
    assert looks_like_v4(_make_v4(tmp_path, nested=nested))


def test_either_marker_alone_is_not_enough(tmp_path) -> None:
    (tmp_path / "video_object.npy").write_bytes(b"x")
    assert not looks_like_v4(tmp_path)


def test_empty_and_missing_folders_are_not_v4(tmp_path) -> None:
    assert not looks_like_v4(tmp_path)
    assert not looks_like_v4(tmp_path / "does-not-exist")


def test_reader_stays_disabled(tmp_path) -> None:
    _make_v4(tmp_path, nested=False)
    assert IDTrackerAiV4Reader.detect(tmp_path) is False
    assert detect_reader(tmp_path) is None


@pytest.mark.parametrize("fn", [read_session, probe_session])
def test_v4_folder_raises_specific_error_not_no_reader(tmp_path, fn) -> None:
    _make_v4(tmp_path, nested=True)
    with pytest.raises(ImportError_) as exc:
        fn(tmp_path)
    assert exc.value.code == "V4_NOT_SUPPORTED"
    assert "v4" in str(exc.value)
    assert "IDTRACKERAI_V4_SAMPLES" in exc.value.remediation


@pytest.mark.parametrize("fn", [read_session, probe_session])
def test_unrelated_folder_still_reports_no_reader(tmp_path, fn) -> None:
    with pytest.raises(ImportError_) as exc:
        fn(tmp_path)
    assert exc.value.code == "NO_READER"
