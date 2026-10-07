"""probe() must be refused pickled data exactly as read() is.

Two changes met here. ``SessionReader.probe`` is the cheap path the GUI uses to describe a
folder; the pickle-consent gate refuses trajectory formats whose deserialisation executes code
unless the project opted in. A probe opens the same file a read does, so it needs the same
consent -- otherwise the GUI would either fail every pickled session or load it unasked.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from track2data import readers
from track2data.core.errors import ImportError_
from track2data.core.models import Session, VideoInfo
from track2data.readers import probe_session
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter


def _session(folder: Path, reader: str) -> Session:
    return Session(
        session_id="p",
        folder=Path(folder),
        reader=reader,
        video=VideoInfo(path=None, fps=25.0, n_frames=2, width_px=4, height_px=4),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.zeros((2, 1, 2)),
    )


class _Consenting(SessionReader):
    """Reads something that executes code on load, so it asks for consent. No probe of its own."""

    name = "probe_consenting"
    accepts_allow_pickle: ClassVar[bool] = True
    seen: ClassVar[list[bool]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (Path(folder) / "consenting.marker").exists()

    def read(self, folder: Path, *, allow_pickle: bool = False) -> Session:
        type(self).seen.append(allow_pickle)
        return _session(folder, self.name)


class _Plain(SessionReader):
    """A reader written before the consent gate existed: one-argument read, no probe."""

    name = "probe_plain"
    seen: ClassVar[list[Path]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (Path(folder) / "plain.marker").exists()

    def read(self, folder: Path) -> Session:  # type: ignore[override]
        type(self).seen.append(Path(folder))
        return _session(folder, self.name)


@pytest.fixture
def stub_readers() -> Iterator[None]:
    _Consenting.seen.clear()
    _Plain.seen.clear()
    readers.register(_Consenting)
    readers.register(_Plain)
    yield
    readers._REGISTRY.remove(_Consenting)
    readers._REGISTRY.remove(_Plain)


class TestTheDefaultProbe:
    def test_hands_the_consent_on_to_a_reader_that_asks_for_it(
        self, stub_readers: None, tmp_path: Path
    ) -> None:
        (tmp_path / "consenting.marker").write_text("x")
        probe_session(tmp_path, allow_pickle=True)
        probe_session(tmp_path)
        assert _Consenting.seen == [True, False]

    def test_does_not_pass_it_to_a_reader_that_never_heard_of_it(
        self, stub_readers: None, tmp_path: Path
    ) -> None:
        (tmp_path / "plain.marker").write_text("x")
        session = probe_session(tmp_path, allow_pickle=True)
        assert session.reader == "probe_plain"
        assert _Plain.seen == [tmp_path]


class TestTheUnifiedIdtrackerReader:
    @staticmethod
    def _only_the_pickled_file(tiny_real_session: Path, tmp_path: Path) -> Path:
        """tiny_real also carries a CSV bundle, which a refused read quietly falls back to."""
        folder = tmp_path / "pickled_only"
        shutil.copytree(tiny_real_session, folder)
        shutil.rmtree(folder / "trajectories" / "trajectories_csv")
        return folder

    def test_is_refused_without_consent(self, tiny_real_session: Path, tmp_path: Path) -> None:
        folder = self._only_the_pickled_file(tiny_real_session, tmp_path)
        with pytest.raises(ImportError_) as err:
            probe_session(folder)
        # Surfaces either directly or wrapped by the format-fallback walk once nothing
        # inert remains; the project store matches on the same text.
        assert "IDT_PICKLE_REFUSED" in str(err.value)

    def test_is_allowed_with_consent(self, tiny_real_session: Path, tmp_path: Path) -> None:
        folder = self._only_the_pickled_file(tiny_real_session, tmp_path)
        assert probe_session(folder, allow_pickle=True).n_animals == 2

    def test_a_folder_that_also_has_a_csv_bundle_probes_without_consent(
        self, tiny_real_session: Path
    ) -> None:
        assert probe_session(tiny_real_session).n_animals == 2

    def test_probes_the_same_numbers_a_read_would(self, tiny_real_session: Path) -> None:
        from track2data.readers import read_session

        light = probe_session(tiny_real_session, allow_pickle=True)
        full = read_session(tiny_real_session, allow_pickle=True)
        assert np.array_equal(light.raw_xy, full.raw_xy, equal_nan=True)


def test_probing_a_folder_nobody_recognises_names_the_folder(tmp_path: Path) -> None:
    with pytest.raises(ImportError_) as err:
        probe_session(tmp_path)
    assert err.value.code == "NO_READER"


# ── a probe that replays a saved reader and its options ──────────────────────


class _NeedsFps(SessionReader):
    """Needs an option its files do not record; never found by detection."""

    name = "probe_needs_fps"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
    )
    seen: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    def read(self, folder: Path, *, options: Any = None) -> Session:  # type: ignore[override]
        type(self).seen.append(dict(options))
        return _session(folder, self.name)


@pytest.fixture
def needs_fps() -> Iterator[None]:
    _NeedsFps.seen.clear()
    readers.register(_NeedsFps)
    yield
    readers._REGISTRY.remove(_NeedsFps)


class TestProbeWithASavedReader:
    def test_the_default_probe_hands_the_saved_options_to_read(
        self, needs_fps: None, tmp_path: Path
    ) -> None:
        probe_session(tmp_path, reader="probe_needs_fps", options={"fps": 25.0})
        assert _NeedsFps.seen == [{"fps": 25.0}]

    def test_a_missing_required_option_is_named_and_never_defaulted(
        self, needs_fps: None, tmp_path: Path
    ) -> None:
        with pytest.raises(ImportError_) as err:
            probe_session(tmp_path, reader="probe_needs_fps")
        assert err.value.code == "READER_OPTION_MISSING"
        assert err.value.subject == "fps"
        assert _NeedsFps.seen == []

    def test_a_named_reader_skips_detection(
        self, stub_readers: None, tmp_path: Path
    ) -> None:
        # no consenting.marker here, so detection would find nothing
        session = probe_session(tmp_path, reader="probe_consenting", allow_pickle=True)
        assert session.reader == "probe_consenting"
        assert _Consenting.seen == [True]

    def test_a_reader_that_is_not_registered_is_an_error_not_a_fall_back(
        self, stub_readers: None, tmp_path: Path
    ) -> None:
        (tmp_path / "plain.marker").write_text("x")  # detection WOULD succeed
        with pytest.raises(ImportError_) as err:
            probe_session(tmp_path, reader="no_such_reader")
        assert err.value.code == "READER_UNKNOWN"
