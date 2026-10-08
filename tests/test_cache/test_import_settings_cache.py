"""The preprocessed-session cache honours every setting that changes the imported session.

Blob diagnostics, pickle permission and the applicable video override all change what an
import returns, but were left out of the cache key, so a rerun after changing one of them
silently reused the stale session. Key equality alone is not enough: each case asserts the
returned session and that import/preprocessing really ran again (or did not).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SecurityConfig,
    Session,
    SessionRef,
)

REF_ID = "manifest-id"  # deliberately not the id the reader derives from the folder


def _manifest(
    folder: Path,
    *,
    allow_pickle: bool = False,
    diagnostics: bool = False,
    blob_calibration: bool = False,
    overrides: dict[str, Path] | None = None,
    extra_sessions: list[SessionRef] | None = None,
) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(session_id=REF_ID, folder=folder, sha256="x"),
            *(extra_sessions or []),
        ],
        security=SecurityConfig(allow_pickle_trajectories=allow_pickle),
        blob_diagnostics=diagnostics,
        calibration=CalibrationConfig(
            mode="bodylength" if blob_calibration else "scalar",
            px_per_cm=None if blob_calibration else 10.0,
            body_length_source="blobs" if blob_calibration else "session",
        ),
        metrics=MetricSelection(individual=["IL-1"]),
        video_overrides=overrides or {},
    )


@pytest.fixture()
def folder(tiny_real_session: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "sess"
    shutil.copytree(tiny_real_session, dst)
    return dst


@pytest.fixture()
def imports(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per real import; the blob helpers leave visible marks instead of reading files."""
    from track2data.readers.idtrackerai import blobs

    calls: list[int] = []

    def body_length(session: Session, *, allow_pickle: bool) -> Session:
        assert allow_pickle is True  # never reached without permission
        n = session.n_animals
        return session.model_copy(
            update={
                "body_length_px": np.full(n, 42.0),
                "blob_body_length_source_file": Path("blobs.pickle"),
            }
        )

    def corrections(session: Session, *, allow_pickle: bool) -> Session:
        assert allow_pickle is True
        return session.model_copy(update={"tracker_corrected_frames": {1, 2}})

    monkeypatch.setattr(blobs, "enrich_session_with_blob_body_length", body_length)
    monkeypatch.setattr(blobs, "enrich_session_with_blob_corrections", corrections)

    real = Engine.import_ref

    def counting(self: Engine, ref: SessionRef) -> Session:
        calls.append(1)
        return real(self, ref)

    monkeypatch.setattr(Engine, "import_ref", counting)
    return calls


def _psess(manifest: ProjectManifest, cache: Path) -> Any:
    engine = Engine(manifest, cache_dir=cache)
    return engine.preprocess_ref(manifest.sessions[0])


def test_unchanged_inputs_reuse_the_entry(folder, tmp_path, imports) -> None:
    cache = tmp_path / "cache"
    a = _psess(_manifest(folder), cache)
    b = _psess(_manifest(folder), cache)
    assert len(imports) == 1
    np.testing.assert_array_equal(a.xy, b.xy)


def test_enabling_blob_diagnostics_adds_the_correction_data(folder, tmp_path, imports) -> None:
    cache = tmp_path / "cache"
    before = _psess(_manifest(folder, allow_pickle=True), cache)
    assert before.session.tracker_corrected_frames is None
    after = _psess(_manifest(folder, allow_pickle=True, diagnostics=True), cache)
    assert len(imports) == 2
    assert after.session.tracker_corrected_frames == {1, 2}


def test_granting_pickle_permission_after_a_fallback_run_uses_blob_body_lengths(
    folder, tmp_path, imports
) -> None:
    cache = tmp_path / "cache"
    fallback = _psess(_manifest(folder, blob_calibration=True), cache)
    assert fallback.session.blob_body_length_source_file is None
    granted = _psess(_manifest(folder, blob_calibration=True, allow_pickle=True), cache)
    assert len(imports) == 2
    assert granted.session.blob_body_length_source_file == Path("blobs.pickle")
    assert granted.body_length_px is not None
    assert np.allclose(granted.body_length_px, 42.0)  # the calibrated value changed too


def test_revoking_pickle_permission_drops_the_blob_data_and_reads_nothing(
    folder, tmp_path, imports
) -> None:
    cache = tmp_path / "cache"
    with_blobs = _psess(_manifest(folder, allow_pickle=True, diagnostics=True), cache)
    assert with_blobs.session.tracker_corrected_frames == {1, 2}
    revoked = _psess(_manifest(folder, allow_pickle=False, diagnostics=True), cache)
    assert len(imports) == 2  # a cache miss, not the permitted entry served back
    assert revoked.session.tracker_corrected_frames is None  # and the helper asserts it never ran


def test_revoked_permission_is_also_a_miss_when_the_cache_already_holds_that_state(
    folder, tmp_path, imports
) -> None:
    cache = tmp_path / "cache"
    _psess(_manifest(folder, allow_pickle=False, diagnostics=True), cache)
    _psess(_manifest(folder, allow_pickle=True, diagnostics=True), cache)
    again = _psess(_manifest(folder, allow_pickle=False, diagnostics=True), cache)
    assert len(imports) == 2  # the first state's entry is reused...
    assert again.session.tracker_corrected_frames is None  # ...and carries no blob data


class TestVideoOverride:
    def _video(self, tmp_path: Path, name: str) -> Path:
        path = tmp_path / name
        path.write_bytes(b"x")
        return path

    def test_adding_changing_and_removing_it_updates_the_returned_path(
        self, folder, tmp_path, imports
    ) -> None:
        cache = tmp_path / "cache"
        one, two = self._video(tmp_path, "one.avi"), self._video(tmp_path, "two.avi")
        none = _psess(_manifest(folder), cache)
        added = _psess(_manifest(folder, overrides={REF_ID: one}), cache)
        changed = _psess(_manifest(folder, overrides={REF_ID: two}), cache)
        removed = _psess(_manifest(folder), cache)
        assert added.session.video.path == one
        assert changed.session.video.path == two
        assert removed.session.video.path == none.session.video.path
        assert len(imports) == 3  # the removal is served from the first entry

    def test_another_sessions_override_does_not_invalidate_this_one(
        self, folder, tmp_path, imports
    ) -> None:
        cache = tmp_path / "cache"
        other = SessionRef(session_id="other", folder=tmp_path / "other", sha256="y")
        elsewhere = self._video(tmp_path, "elsewhere.avi")
        _psess(_manifest(folder, extra_sessions=[other]), cache)
        _psess(
            _manifest(folder, extra_sessions=[other], overrides={"other": elsewhere}), cache
        )
        assert len(imports) == 1


class TestTheKeyItself:
    def _key(self, manifest: ProjectManifest, cache: Path) -> str:
        keyed = Engine(manifest, cache_dir=cache)._cache_key(manifest.sessions[0])
        assert keyed is not None
        return keyed[1]

    def test_each_import_setting_moves_the_key(self, folder, tmp_path) -> None:
        cache = tmp_path / "cache"
        video = tmp_path / "v.avi"
        video.write_bytes(b"x")
        keys = {
            self._key(_manifest(folder), cache),
            self._key(_manifest(folder, allow_pickle=True), cache),
            self._key(_manifest(folder, diagnostics=True), cache),
            self._key(_manifest(folder, overrides={REF_ID: video}), cache),
        }
        assert len(keys) == 4

    def test_a_worker_rebuilding_the_engine_from_the_manifest_json_gets_the_same_key(
        self, folder, tmp_path
    ) -> None:
        cache = tmp_path / "cache"
        video = tmp_path / "v.avi"
        video.write_bytes(b"x")
        manifest = _manifest(folder, allow_pickle=True, diagnostics=True, overrides={REF_ID: video})
        rebuilt = ProjectManifest.model_validate_json(manifest.model_dump_json())
        assert self._key(manifest, cache) == self._key(rebuilt, cache)

    def test_the_schema_moved_past_the_faulty_key(self) -> None:
        assert Engine._CACHE_SCHEMA >= 4


def test_cached_and_uncached_runs_agree(folder, tmp_path, imports) -> None:
    manifest = _manifest(folder, allow_pickle=True, diagnostics=True)
    cache = tmp_path / "cache"
    _psess(manifest, cache)
    cached = _psess(manifest, cache)
    fresh = Engine(manifest).preprocess_ref(manifest.sessions[0])
    np.testing.assert_array_equal(cached.xy, fresh.xy)
    assert cached.session.tracker_corrected_frames == fresh.session.tracker_corrected_frames
