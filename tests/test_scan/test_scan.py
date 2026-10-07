"""Scanning a folder: ranked detections from one read-only walk, idtracker.ai and legacy."""

from __future__ import annotations

import hashlib
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from track2data import readers
from track2data.core.models import Session
from track2data.core.progress import CancellationToken, OperationCancelled
from track2data.readers.base import SessionReader
from track2data.readers.detection import Confidence, Detection
from track2data.readers.index import ScanBudget
from track2data.readers.scan import ScanResult, scan


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        digest.update(str(path.relative_to(folder)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _readers_in(result: ScanResult) -> list[str]:
    return [d.reader for g in result.groups for d in g.detections]


class TestFolderOfFolders:
    def test_seventy_sessions_are_one_high_group(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        for i in range(70):
            shutil.copytree(tiny_real_session, tmp_path / f"session_{i:02d}")
        started = time.monotonic()
        result = scan([tmp_path])
        elapsed = time.monotonic() - started

        assert len(result.groups) == 1
        best = result.groups[0].best
        assert best.reader == "idtrackerai"
        assert best.confidence is Confidence.HIGH
        assert len(best.sessions) == 70
        ids = [s.session_id for s in best.sessions]
        assert ids == [f"session_{i:02d}" for i in range(70)]
        assert all(s.source.parent == tmp_path for s in best.sessions)
        assert elapsed < 5.0
        assert not result.truncated

    def test_the_root_can_be_a_session_itself(self, tiny_real_session: Path) -> None:
        result = scan([tiny_real_session])
        assert len(result.groups) == 1
        sessions = result.groups[0].best.sessions
        assert [s.source for s in sessions] == [tiny_real_session]
        assert sessions[0].session_id == tiny_real_session.name

    def test_nested_sessions_are_found_up_to_the_depth_limit(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "video" / "session_x")
        result = scan([tmp_path])
        assert [s.session_id for s in result.groups[0].best.sessions] == ["session_x"]

    def test_a_session_inside_a_claimed_session_is_not_a_second_session(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "outer")
        shutil.copytree(tiny_real_session, tmp_path / "outer" / "preprocessing" / "inner")
        result = scan([tmp_path])
        assert [s.session_id for s in result.groups[0].best.sessions] == ["outer"]


class TestV5VersusUnified:
    def test_a_v5_session_goes_to_the_v5_reader_only(self, tiny_v5_session: Path) -> None:
        result = scan([tiny_v5_session])
        assert _readers_in(result) == ["idtrackerai_v5"]
        assert result.groups[0].best.confidence is Confidence.HIGH

    def test_a_unified_session_is_not_claimed_by_the_v5_reader(
        self, tiny_real_session: Path
    ) -> None:
        assert _readers_in(scan([tiny_real_session])) == ["idtrackerai"]

    def test_a_folder_both_readers_could_read_is_one_group_with_an_alternative(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        both = tmp_path / "both"
        shutil.copytree(tiny_real_session, both)
        (both / "video_object.npy").write_bytes(b"placeholder")
        result = scan([tmp_path])
        assert len(result.groups) == 1
        group = result.groups[0]
        assert [d.reader for d in group.detections] == ["idtrackerai", "idtrackerai_v5"]
        assert group.best.confidence > group.detections[1].confidence


class TestHintsAndJunk:
    def test_picking_the_trajectories_subfolder_points_at_the_parent(
        self, tiny_real_session: Path
    ) -> None:
        result = scan([tiny_real_session / "trajectories"])
        assert len(result.groups) == 1
        best = result.groups[0].best
        assert best.confidence is Confidence.LOW
        assert [s.source for s in best.sessions] == [tiny_real_session]
        assert any("trajectories" in line and "parent" in line for line in best.evidence)

    def test_an_empty_folder_matches_nothing_and_says_what_it_saw(self, tmp_path: Path) -> None:
        result = scan([tmp_path])
        assert result.groups == ()
        assert result.file_types == {}

    def test_videos_and_zero_byte_files_match_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").write_bytes(b"")
        (tmp_path / "b.mp4").write_bytes(b"\x00" * 10)
        (tmp_path / "._a.mp4").write_bytes(b"resource fork")
        result = scan([tmp_path])
        assert result.groups == ()
        assert result.file_types == {".mp4": 2}

    def test_a_trajectories_folder_without_a_known_file_matches_nothing(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "s" / "trajectories").mkdir(parents=True)
        (tmp_path / "s" / "trajectories" / "notes.txt").write_text("x")
        assert scan([tmp_path]).groups == ()

    def test_a_raw_array_without_video_object_is_still_claimed_so_the_user_is_told_why(
        self, tmp_path: Path
    ) -> None:
        session = tmp_path / "s"
        (session / "trajectories").mkdir(parents=True)
        np.save(session / "trajectories" / "trajectories.npy", np.zeros((3, 1, 2)))
        result = scan([tmp_path])
        assert _readers_in(result) == ["idtrackerai"]


class TestIds:
    def test_two_sessions_with_one_name_get_distinct_ids_from_their_paths(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "a" / "session")
        shutil.copytree(tiny_real_session, tmp_path / "b" / "session")
        ids = [s.session_id for s in scan([tmp_path]).groups[0].best.sessions]
        assert ids == ["a__session", "b__session"]


class TestResultShape:
    def test_a_scan_reports_what_it_cost(self, tiny_real_session: Path) -> None:
        result = scan([tiny_real_session])
        assert result.entries > 0
        assert result.seconds >= 0
        assert result.roots == (tiny_real_session,)
        assert not result.truncated

    def test_truncation_is_reported_with_a_warning(self, tiny_real_session: Path) -> None:
        result = scan([tiny_real_session], budget=ScanBudget(max_entries=3))
        assert result.truncated
        assert any("stopped early" in w for w in result.warnings)

    def test_groups_are_ranked_by_confidence_then_size(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "good" / "s1")
        # only a trajectories/ subfolder: LOW confidence, pointing at its parent
        lonely = tmp_path / "other" / "trajectories"
        lonely.mkdir(parents=True)
        shutil.copy(tiny_real_session / "trajectories" / "trajectories.npy", lonely)
        result = scan([tmp_path])
        confidences = [g.best.confidence for g in result.groups]
        assert confidences == sorted(confidences, reverse=True)
        assert result.groups[0].best.confidence is Confidence.HIGH


class TestInvariants:
    def test_a_scan_never_writes(self, tiny_real_session: Path, tmp_path: Path) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "s")
        before = _tree_hash(tmp_path)
        scan([tmp_path])
        assert _tree_hash(tmp_path) == before

    def test_a_scan_never_unpickles(
        self, tiny_real_session: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The session's trajectories.npy is a pickled dict. NumPy unpickles through these
        # module-level entry points, so poison them and scan anyway.
        shutil.copytree(tiny_real_session, tmp_path / "s")
        import pickle

        def forbid(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a scan must not unpickle")

        for name in ("load", "loads", "Unpickler"):
            monkeypatch.setattr(pickle, name, forbid)
        assert scan([tmp_path]).groups

    def test_cancellation_propagates(self, tiny_real_session: Path) -> None:
        token = CancellationToken()
        token.cancel()
        with pytest.raises(OperationCancelled):
            scan([tiny_real_session], token=token)

    def test_a_missing_root_is_a_warning_not_an_error(self, tmp_path: Path) -> None:
        result = scan([tmp_path / "nope"])
        assert result.groups == ()
        assert result.warnings


# ── readers written against the original contract, and readers that misbehave ─────────────────


class MarkerReader(SessionReader):
    """A legacy reader: only detect(folder) and read(folder), no discover."""

    name = "marker_test"
    priority = 0

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "marker.txt").exists()

    def read(self, folder: Path) -> Session:  # pragma: no cover - never read in these tests
        raise NotImplementedError


class ExplodingDiscoverReader(SessionReader):
    name = "exploding_discover"
    priority = 0

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    @classmethod
    def discover(cls, index: Any, peek: Any) -> list[Detection]:
        raise RuntimeError("boom in discover")

    def read(self, folder: Path) -> Session:  # pragma: no cover
        raise NotImplementedError


class ExplodingDetectReader(SessionReader):
    name = "exploding_detect"
    priority = 0
    calls: ClassVar[int] = 0

    @classmethod
    def detect(cls, folder: Path) -> bool:
        raise OSError("boom in detect")

    def read(self, folder: Path) -> Session:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def toy_readers() -> Iterator[None]:
    toys = (MarkerReader, ExplodingDiscoverReader, ExplodingDetectReader)
    for cls in toys:
        readers.register(cls)
    yield
    for cls in toys:
        readers._REGISTRY.remove(cls)


class TestLegacyAndMisbehavingReaders:
    def test_a_detect_only_reader_is_wrapped_as_a_medium_detection(
        self, toy_readers: None, tmp_path: Path
    ) -> None:
        for rel in ["a", "b/c", "a/inner"]:
            (tmp_path / rel).mkdir(parents=True)
            (tmp_path / rel / "marker.txt").write_text("x")
        result = scan([tmp_path])
        detection = next(
            d for g in result.groups for d in g.detections if d.reader == "marker_test"
        )
        assert detection.confidence is Confidence.MEDIUM
        # "a/inner" sits inside the already-claimed "a", so it is not a second session.
        assert [s.source.relative_to(tmp_path).as_posix() for s in detection.sessions] == [
            "a",
            "b/c",
        ]

    def test_a_reader_whose_discover_raises_becomes_a_warning(
        self, toy_readers: None, tiny_real_session: Path
    ) -> None:
        result = scan([tiny_real_session])
        assert any("exploding_discover" in w and "boom" in w for w in result.warnings)
        assert _readers_in(result) == ["idtrackerai"]  # the others are unaffected

    def test_a_reader_whose_detect_raises_is_simply_not_a_match(
        self, toy_readers: None, tiny_real_session: Path
    ) -> None:
        assert "exploding_detect" not in _readers_in(scan([tiny_real_session]))
