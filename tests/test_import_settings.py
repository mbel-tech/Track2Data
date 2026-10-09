"""Engine.import_ref / import_session apply the project's import settings on every path.

Blob body-length enrichment, correction enrichment and the video override used to run only
for auto-detected imports. A saved reader skipped all three, and the override was looked up
under the reader-derived id instead of the manifest's.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.test_import_ref import RecordingReader
from track2data import readers
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    ProjectManifest,
    SecurityConfig,
    Session,
    SessionRef,
)


class BlobAwareReader(RecordingReader):
    """An idtracker.ai-family reader (by name) that is also auto-detectable."""

    name = "idtrackerai_test"
    priority = 100
    parameters = ()  # nothing required, so auto-detection can use it

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "auto-marker").exists()

    def read(
        self, folder: Path, *, allow_pickle: bool = False, options: Any = None
    ) -> Session:
        return super().read(folder, allow_pickle=allow_pickle, options={"fps": 25.0})


@pytest.fixture
def blob_enrichment(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace both blob helpers with recorders that leave visible marks on the session."""
    calls: dict[str, list[str]] = {"body_length": [], "corrections": []}
    from track2data.readers.idtrackerai import blobs

    def body_length(session: Session, *, allow_pickle: bool) -> Session:
        calls["body_length"].append(session.session_id)
        assert allow_pickle is True
        return session.model_copy(
            update={"body_length_px": np.array([42.0]), "blob_body_length_source_file": Path("b")}
        )

    def corrections(session: Session, *, allow_pickle: bool) -> Session:
        calls["corrections"].append(session.session_id)
        assert allow_pickle is True
        return session.model_copy(update={"tracker_corrected_frames": {1, 2}})

    monkeypatch.setattr(blobs, "enrich_session_with_blob_body_length", body_length)
    monkeypatch.setattr(blobs, "enrich_session_with_blob_corrections", corrections)
    return calls


@pytest.fixture
def blob_reader() -> Iterator[None]:
    RecordingReader.seen.clear()
    readers.register(BlobAwareReader)
    readers.register(RecordingReader)
    yield
    readers._REGISTRY.remove(BlobAwareReader)
    readers._REGISTRY.remove(RecordingReader)


def _ref(folder: Path, **fields: Any) -> SessionRef:
    return SessionRef(session_id="the-manifest-id", folder=folder, sha256="", **fields)


def _engine(
    ref: SessionRef,
    *,
    allow_pickle: bool = True,
    blobs: bool = True,
    diagnostics: bool = True,
    overrides: dict[str, Path] | None = None,
) -> Engine:
    return Engine(
        ProjectManifest(
            project_name="p",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            sessions=[ref],
            security=SecurityConfig(allow_pickle_trajectories=allow_pickle),
            blob_diagnostics=diagnostics,
            calibration=CalibrationConfig(body_length_source="blobs" if blobs else "session"),
            video_overrides=overrides or {},
        )
    )


def _saved(tmp_path: Path) -> SessionRef:
    return _ref(tmp_path, reader="idtrackerai_test")


def _auto(tmp_path: Path) -> SessionRef:
    (tmp_path / "auto-marker").write_text("x")
    return _ref(tmp_path)


@pytest.mark.parametrize("make_ref", [_saved, _auto], ids=["saved_reader", "auto_detected"])
class TestBothImportPathsApplyTheProjectSettings:
    def test_body_length_enrichment_runs_once(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        ref = make_ref(tmp_path)
        session = _engine(ref).import_ref(ref)
        assert len(blob_enrichment["body_length"]) == 1
        assert session.body_length_px is not None and session.body_length_px[0] == 42.0
        assert session.blob_body_length_source_file == Path("b")

    def test_correction_enrichment_runs_once(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        ref = make_ref(tmp_path)
        session = _engine(ref).import_ref(ref)
        assert len(blob_enrichment["corrections"]) == 1
        assert session.tracker_corrected_frames == {1, 2}

    def test_nothing_is_unpickled_without_permission(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        ref = make_ref(tmp_path)
        session = _engine(ref, allow_pickle=False).import_ref(ref)
        assert blob_enrichment == {"body_length": [], "corrections": []}
        assert session.tracker_corrected_frames is None

    def test_settings_that_are_off_are_not_applied(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        ref = make_ref(tmp_path)
        _engine(ref, blobs=False, diagnostics=False).import_ref(ref)
        assert blob_enrichment == {"body_length": [], "corrections": []}

    def test_the_video_override_is_found_under_the_manifest_id(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        video = tmp_path / "real.avi"
        video.write_bytes(b"x")
        ref = make_ref(tmp_path)
        # The reader derives "derived-by-the-reader"; the override is keyed by the manifest id.
        session = _engine(ref, overrides={"the-manifest-id": video}).import_ref(ref)
        assert session.video.path == video
        assert session.video.fps == 25.0  # only the path is replaced

    def test_a_missing_override_file_keeps_the_recorded_path(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path, make_ref: Any
    ) -> None:
        ref = make_ref(tmp_path)
        engine = _engine(ref, overrides={"the-manifest-id": tmp_path / "gone.avi"})
        assert engine.import_ref(ref).video.path is None


class TestOtherReadersAreLeftAlone:
    def test_a_non_idtrackerai_reader_gets_no_blob_enrichment_but_keeps_its_override(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path
    ) -> None:
        video = tmp_path / "real.avi"
        video.write_bytes(b"x")
        ref = _ref(tmp_path, reader="recording_test", reader_options={"fps": 25.0})
        session = _engine(ref, overrides={"the-manifest-id": video}).import_ref(ref)
        assert blob_enrichment == {"body_length": [], "corrections": []}
        assert session.video.path == video


class TestImportSessionStillWorksOnItsOwn:
    def test_the_reader_derived_id_is_used_for_overrides_without_a_manifest_entry(
        self, blob_reader: None, blob_enrichment: dict, tmp_path: Path
    ) -> None:
        video = tmp_path / "real.avi"
        video.write_bytes(b"x")
        (tmp_path / "auto-marker").write_text("x")
        ref = _ref(tmp_path)
        engine = _engine(ref, overrides={"derived-by-the-reader": video})
        session = engine.import_session(tmp_path)
        assert session.session_id == "derived-by-the-reader"
        assert session.video.path == video
        assert blob_enrichment["corrections"] == ["derived-by-the-reader"]


def test_the_cache_schema_was_bumped_so_faulty_sessions_are_not_reused() -> None:
    assert Engine._CACHE_SCHEMA >= 3
