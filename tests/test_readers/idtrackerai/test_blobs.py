"""
Tests for readers.idtrackerai.blobs.

Uses a class-spoofing fixture (a locally-defined class with __module__ set
to "idtrackerai.blob"/"idtrackerai.list_of_blobs") to produce real pickle
bytes that reference idtrackerai without the package being installed --
exactly the real-world condition this module is designed for. idtrackerai
is never actually imported anywhere in this test file.
"""

from __future__ import annotations

import pickle
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from track2data.readers.idtrackerai.blobs import (
    _AllowlistUnpickler,
    _bbox_diagonal_px,
    _resolve_blob_pickle_path,
    compute_body_length_px_per_identity,
    enrich_session_with_blob_body_length,
    load_body_length_px_per_identity,
)

# ── fake idtrackerai module machinery ───────────────────────────────────────


@pytest.fixture()
def fake_idtrackerai_classes():
    """Temporarily register fake idtrackerai.blob.Blob and
    idtrackerai.list_of_blobs.ListOfBlobs classes in sys.modules so they can
    be pickled, then remove them -- simulating "idtrackerai not installed"
    for anything that unpickles the bytes afterward."""
    blob_mod = types.ModuleType("idtrackerai.blob")

    class Blob:
        pass

    Blob.__module__ = "idtrackerai.blob"
    Blob.__qualname__ = "Blob"
    blob_mod.Blob = Blob

    lob_mod = types.ModuleType("idtrackerai.list_of_blobs")

    class ListOfBlobs:
        pass

    ListOfBlobs.__module__ = "idtrackerai.list_of_blobs"
    ListOfBlobs.__qualname__ = "ListOfBlobs"
    lob_mod.ListOfBlobs = ListOfBlobs

    pkg = types.ModuleType("idtrackerai")

    sys.modules["idtrackerai"] = pkg
    sys.modules["idtrackerai.blob"] = blob_mod
    sys.modules["idtrackerai.list_of_blobs"] = lob_mod
    try:
        yield Blob, ListOfBlobs
    finally:
        del sys.modules["idtrackerai"]
        del sys.modules["idtrackerai.blob"]
        del sys.modules["idtrackerai.list_of_blobs"]


def _make_blob(blob_cls, **attrs) -> object:
    b = blob_cls()
    b.__dict__.update(attrs)
    return b


def _write_blob_pickle(
    path: Path, lob_cls, blob_cls, blobs_in_video: list[list[object]]
) -> None:
    lob = lob_cls()
    lob.__dict__["blobs_in_video"] = blobs_in_video
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(lob, f)


_SQUARE = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]


# ── _AllowlistUnpickler ──────────────────────────────────────────────────────


class TestAllowlistUnpickler:
    def test_loads_idtrackerai_classes_as_stub(self, fake_idtrackerai_classes) -> None:
        blob_cls, _ = fake_idtrackerai_classes
        blob = _make_blob(blob_cls, identity=1, contour=_SQUARE)
        data = pickle.dumps(blob)

        import io

        obj = _AllowlistUnpickler(io.BytesIO(data)).load()
        assert type(obj).__name__ == "_BlobStub"
        assert obj.__dict__["identity"] == 1
        assert obj.__dict__["contour"] == _SQUARE

    def test_refuses_non_idtrackerai_non_numpy_classes(self) -> None:
        """More restrictive than a bare pickle.load(): only idtrackerai.*
        (stubbed) and numpy internals are permitted."""
        import io

        evil_mod = types.ModuleType("totally_not_idtrackerai")

        class Evil:
            pass

        Evil.__module__ = "totally_not_idtrackerai"
        Evil.__qualname__ = "Evil"
        evil_mod.Evil = Evil
        sys.modules["totally_not_idtrackerai"] = evil_mod
        try:
            data = pickle.dumps(Evil())
        finally:
            del sys.modules["totally_not_idtrackerai"]

        with pytest.raises(pickle.UnpicklingError, match="not in the allowlist"):
            _AllowlistUnpickler(io.BytesIO(data)).load()

    def test_loads_real_pickle_without_idtrackerai_installed(
        self, tmp_path: Path, fake_idtrackerai_classes
    ) -> None:
        """The core claim this module is built on: a file produced by real
        idtracker.ai loads without idtracker.ai importable at load time."""
        blob_cls, lob_cls = fake_idtrackerai_classes
        path = tmp_path / "list_of_blobs.pickle"
        _write_blob_pickle(path, lob_cls, blob_cls, [[_make_blob(blob_cls, identity=1)]])

        # The fixture already removed idtrackerai from sys.modules at this
        # point (its teardown runs after the test, but nothing here
        # re-imports it) -- this call is the real assertion under test.
        with path.open("rb") as f:
            lob = _AllowlistUnpickler(f).load()
        assert lob.blobs_in_video[0][0].identity == 1


# ── _resolve_blob_pickle_path ────────────────────────────────────────────────


class TestResolveBlobPicklePath:
    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert _resolve_blob_pickle_path(tmp_path) is None

    def test_prefers_validated_over_base(self, tmp_path: Path) -> None:
        preproc = tmp_path / "preprocessing"
        preproc.mkdir()
        (preproc / "list_of_blobs.pickle").write_bytes(b"base")
        (preproc / "list_of_blobs_validated.pickle").write_bytes(b"validated")
        result = _resolve_blob_pickle_path(tmp_path)
        assert result is not None
        assert result.name == "list_of_blobs_validated.pickle"

    def test_falls_back_to_base_when_no_validated(self, tmp_path: Path) -> None:
        preproc = tmp_path / "preprocessing"
        preproc.mkdir()
        (preproc / "list_of_blobs.pickle").write_bytes(b"base")
        result = _resolve_blob_pickle_path(tmp_path)
        assert result is not None
        assert result.name == "list_of_blobs.pickle"

    def test_ignores_macos_resource_fork(self, tmp_path: Path) -> None:
        preproc = tmp_path / "preprocessing"
        preproc.mkdir()
        (preproc / "._list_of_blobs.pickle").write_bytes(b"\x00\x05")
        assert _resolve_blob_pickle_path(tmp_path) is None


# ── _bbox_diagonal_px ─────────────────────────────────────────────────────────


class TestBboxDiagonalPx:
    def test_square_contour(self) -> None:
        # 10x10 square -> diagonal hypot(10, 10)
        diag = _bbox_diagonal_px(_SQUARE)
        assert diag == pytest.approx(np.hypot(10.0, 10.0))

    def test_uses_ptp_not_boundingrect_convention(self) -> None:
        """Matches idtracker.ai's own `extension`: (max-min) on the
        contour's own coordinates, not cv2.boundingRect's w/h -- verified
        on a real blob to differ by ~0.3% (see docs/EXTRACT_BBOXES_FIX.md)."""
        contour = [[1001, 554], [1095, 554], [1095, 901], [1001, 901]]
        diag = _bbox_diagonal_px(contour)
        assert diag == pytest.approx(np.hypot(94, 347))

    def test_invalid_contour_returns_none(self) -> None:
        assert _bbox_diagonal_px([[1, 2]]) is None  # too few points
        assert _bbox_diagonal_px(None) is None


# ── compute_body_length_px_per_identity ──────────────────────────────────────


class TestComputeBodyLengthPxPerIdentity:
    def test_filters_on_seems_like_individual_and_certainty(
        self, fake_idtrackerai_classes
    ) -> None:
        blob_cls, _ = fake_idtrackerai_classes
        frame = [
            _make_blob(
                blob_cls, seems_like_individual=True, identity=1,
                identity_certainty=0.9, contour=_SQUARE,
            ),
            _make_blob(
                blob_cls, seems_like_individual=False, identity=2,  # crossing, excluded
                identity_certainty=0.9, contour=_SQUARE,
            ),
            _make_blob(
                blob_cls, seems_like_individual=True, identity=3,
                identity_certainty=0.1, contour=_SQUARE,  # below threshold, excluded
            ),
        ]
        # n_animals=3 matches the 3-blob frame -> a unicity frame.
        result = compute_body_length_px_per_identity([frame], n_animals=3, min_certainty=0.5)
        assert result is not None
        assert not np.isnan(result[0])  # identity 1
        assert np.isnan(result[1])      # identity 2 -- crossing, never sampled
        assert np.isnan(result[2])      # identity 3 -- low certainty, never sampled

    def test_requires_unicity_frame(self, fake_idtrackerai_classes) -> None:
        """A frame with fewer/more blobs than n_animals is not a unicity
        frame and must be excluded, even if a blob otherwise qualifies."""
        blob_cls, _ = fake_idtrackerai_classes
        frame = [_make_blob(
            blob_cls, seems_like_individual=True, identity=1,
            identity_certainty=0.9, contour=_SQUARE,
        )]
        result = compute_body_length_px_per_identity(
            [frame], n_animals=4, min_certainty=0.5,  # only 1 blob, needs 4
        )
        assert result is None

    def test_identity_is_1_based_result_is_0_based(self, fake_idtrackerai_classes) -> None:
        blob_cls, _ = fake_idtrackerai_classes
        frame = [_make_blob(
            blob_cls, seems_like_individual=True, identity=1,
            identity_certainty=0.9, contour=_SQUARE,
        )]
        result = compute_body_length_px_per_identity([frame], n_animals=1, min_certainty=0.5)
        assert result is not None
        assert not np.isnan(result[0])  # identity 1 -> index 0

    def test_no_samples_returns_none(self) -> None:
        assert compute_body_length_px_per_identity([], n_animals=4) is None

    def test_median_over_multiple_frames(self, fake_idtrackerai_classes) -> None:
        blob_cls, _ = fake_idtrackerai_classes
        small = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        big = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        frames = [
            [_make_blob(blob_cls, seems_like_individual=True, identity=1,
                        identity_certainty=0.9, contour=small)],
            [_make_blob(blob_cls, seems_like_individual=True, identity=1,
                        identity_certainty=0.9, contour=big)],
        ]
        result = compute_body_length_px_per_identity(frames, n_animals=1, min_certainty=0.5)
        assert result is not None
        expected = np.median([np.hypot(1, 1), np.hypot(100, 100)])
        assert result[0] == pytest.approx(expected)


# ── load_body_length_px_per_identity / enrich_session_with_blob_body_length ──


class TestLoadBodyLengthPxPerIdentity:
    def test_gated_off_by_default_returns_none(
        self, tmp_path: Path, fake_idtrackerai_classes
    ) -> None:
        blob_cls, lob_cls = fake_idtrackerai_classes
        path = tmp_path / "preprocessing" / "list_of_blobs.pickle"
        _write_blob_pickle(path, lob_cls, blob_cls, [[_make_blob(
            blob_cls, seems_like_individual=True, identity=1,
            identity_certainty=0.9, contour=_SQUARE,
        )]])
        result = load_body_length_px_per_identity(tmp_path, 1, allow_pickle=False)
        assert result is None

    def test_allow_pickle_true_returns_result(
        self, tmp_path: Path, fake_idtrackerai_classes
    ) -> None:
        blob_cls, lob_cls = fake_idtrackerai_classes
        path = tmp_path / "preprocessing" / "list_of_blobs.pickle"
        _write_blob_pickle(path, lob_cls, blob_cls, [[_make_blob(
            blob_cls, seems_like_individual=True, identity=1,
            identity_certainty=0.9, contour=_SQUARE,
        )]])
        result = load_body_length_px_per_identity(tmp_path, 1, allow_pickle=True)
        assert result is not None
        assert result["source_file"] == "list_of_blobs.pickle"
        assert not np.isnan(result["body_length_px"][0])

    def test_missing_pickle_returns_none(self, tmp_path: Path) -> None:
        assert load_body_length_px_per_identity(tmp_path, 4, allow_pickle=True) is None


class TestEnrichSessionWithBlobBodyLength:
    def _make_session(self, folder: Path, n_animals: int = 1):
        from track2data.core.models import Session, VideoInfo

        return Session(
            session_id="s1",
            folder=folder,
            reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=5, width_px=100, height_px=100),
            n_animals=n_animals,
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((5, n_animals, 2)),
            body_length_px=np.array([999.0]),  # session-wide broadcast placeholder
        )

    def test_gated_off_returns_same_session_unchanged(self, tmp_path: Path) -> None:
        session = self._make_session(tmp_path)
        result = enrich_session_with_blob_body_length(session, allow_pickle=False)
        assert result is session
        assert result.body_length_px[0] == 999.0

    def test_no_blob_pickle_returns_same_session(self, tmp_path: Path) -> None:
        session = self._make_session(tmp_path)
        result = enrich_session_with_blob_body_length(session, allow_pickle=True)
        assert result is session

    def test_upgrades_body_length_and_records_source(
        self, tmp_path: Path, fake_idtrackerai_classes
    ) -> None:
        blob_cls, lob_cls = fake_idtrackerai_classes
        path = tmp_path / "preprocessing" / "list_of_blobs.pickle"
        _write_blob_pickle(path, lob_cls, blob_cls, [[_make_blob(
            blob_cls, seems_like_individual=True, identity=1,
            identity_certainty=0.9, contour=_SQUARE,
        )]])
        session = self._make_session(tmp_path, n_animals=1)
        result = enrich_session_with_blob_body_length(session, allow_pickle=True)
        assert result is not session
        assert result.body_length_px[0] != 999.0
        assert result.blob_body_length_source_file == "list_of_blobs.pickle"
