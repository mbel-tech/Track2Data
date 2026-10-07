"""Engine.import_ref: a manifest entry's saved reader is replayed, never re-detected."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from track2data import readers
from track2data.api import Engine
from track2data.core.errors import ImportError_
from track2data.core.models import (
    ProjectManifest,
    SecurityConfig,
    Session,
    SessionRef,
    VideoInfo,
)
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter


class RecordingReader(SessionReader):
    """Needs an fps option, records every read, and derives its own session id."""

    name = "recording_test"
    accepts_allow_pickle = True
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
    )
    seen: ClassVar[list[tuple[Path, dict[str, Any], bool]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    def read(
        self, folder: Path, *, allow_pickle: bool = False, options: Any = None
    ) -> Session:
        type(self).seen.append((folder, dict(options), allow_pickle))
        return Session(
            session_id="derived-by-the-reader",
            folder=folder,
            reader=self.name,
            video=VideoInfo(path=None, fps=options["fps"], n_frames=3, width_px=10, height_px=10),
            n_animals=1,
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((3, 1, 2)),
        )


@pytest.fixture
def recording() -> Iterator[None]:
    RecordingReader.seen.clear()
    readers.register(RecordingReader)
    yield
    readers._REGISTRY.remove(RecordingReader)


def _engine(*refs: SessionRef, allow_pickle: bool = False) -> Engine:
    return Engine(
        ProjectManifest(
            project_name="p",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            sessions=list(refs),
            security=SecurityConfig(allow_pickle_trajectories=allow_pickle),
        )
    )


def _ref(folder: Path, **fields: Any) -> SessionRef:
    return SessionRef(session_id="the-manifest-id", folder=folder, sha256="", **fields)


class TestALegacyEntry:
    def test_goes_through_import_session_exactly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _engine(_ref(tmp_path))
        calls: list[Path] = []

        def fake_import_session(folder: Path) -> Session:
            calls.append(folder)
            return RecordingReader().read(folder, options={"fps": 10.0})

        monkeypatch.setattr(engine, "import_session", fake_import_session)
        session = engine.import_ref(engine.manifest.sessions[0])
        assert calls == [tmp_path]
        assert session.session_id == "the-manifest-id"


class TestAnEntryThatRecordsItsReader:
    def test_replays_that_reader_with_its_saved_options(
        self, recording: None, tmp_path: Path
    ) -> None:
        ref = _ref(tmp_path, reader="recording_test", reader_options={"fps": 25.0})
        _engine(ref).import_ref(ref)
        assert RecordingReader.seen == [(tmp_path, {"fps": 25.0}, False)]

    def test_the_project_decides_whether_pickled_data_may_load(
        self, recording: None, tmp_path: Path
    ) -> None:
        ref = _ref(tmp_path, reader="recording_test", reader_options={"fps": 25.0})
        _engine(ref, allow_pickle=True).import_ref(ref)
        assert RecordingReader.seen[0][2] is True

    def test_the_session_takes_the_manifest_id_not_the_one_the_reader_derived(
        self, recording: None, tmp_path: Path
    ) -> None:
        ref = _ref(tmp_path, reader="recording_test", reader_options={"fps": 25.0})
        session = _engine(ref).import_ref(ref)
        assert session.session_id == "the-manifest-id"
        assert session.reader == "recording_test"

    def test_a_missing_required_option_is_named_and_not_defaulted(
        self, recording: None, tmp_path: Path
    ) -> None:
        ref = _ref(tmp_path, reader="recording_test")
        with pytest.raises(ImportError_) as err:
            _engine(ref).import_ref(ref)
        assert err.value.code == "READER_OPTION_MISSING"
        assert err.value.subject == "fps"
        assert RecordingReader.seen == []

    def test_a_reader_that_is_not_installed_is_an_error_not_a_fall_back(
        self, tiny_real_session: Path
    ) -> None:
        # The folder is a perfectly good idtracker.ai session, so detection WOULD succeed.
        # A different reader could read the same files into different numbers, so it must not.
        ref = _ref(tiny_real_session, reader="uninstalled_plugin")
        with pytest.raises(ImportError_) as err:
            _engine(ref, allow_pickle=True).import_ref(ref)
        assert err.value.code == "READER_NOT_AVAILABLE"
        assert err.value.subject == "uninstalled_plugin"
        assert "uninstalled_plugin" in str(err.value)
        assert err.value.remediation


class TestEveryCallerUsesIt:
    def test_import_sessions_replays_each_entrys_reader(
        self, recording: None, tmp_path: Path
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        a = SessionRef(
            session_id="a", folder=tmp_path / "a", sha256="",
            reader="recording_test", reader_options={"fps": 10.0},
        )
        b = SessionRef(
            session_id="b", folder=tmp_path / "b", sha256="",
            reader="recording_test", reader_options={"fps": 20.0},
        )
        sessions = _engine(a, b).import_sessions()
        assert [s.session_id for s in sessions] == ["a", "b"]
        assert [opts["fps"] for _, opts, _ in RecordingReader.seen] == [10.0, 20.0]

    def test_pre_flight_summaries_use_the_saved_reader_too(
        self, recording: None, tmp_path: Path
    ) -> None:
        ref = _ref(tmp_path, reader="recording_test", reader_options={"fps": 25.0})
        engine = _engine(ref)
        engine.consistency_warnings()
        assert RecordingReader.seen  # the summary read went through the named reader
