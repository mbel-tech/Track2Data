"""The additive reader contract: options, naming a reader, and staying backward compatible."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from track2data import readers
from track2data.core.errors import ImportError_
from track2data.core.models import Session, VideoInfo
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter


def _session_from(folder: Path, name: str) -> Session:
    return Session(
        session_id=folder.name,
        folder=folder,
        reader=name,
        video=VideoInfo(path=None, fps=10.0, n_frames=3, width_px=10, height_px=10),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.zeros((3, 1, 2)),
    )


class LegacyReader(SessionReader):
    """Written against the original one-argument contract: read(folder) and nothing else."""

    name = "legacy_test"
    priority = 0
    calls: ClassVar[list[tuple[Path, dict[str, Any]]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "legacy.marker").exists()

    def read(self, folder: Path) -> Session:
        type(self).calls.append((folder, {}))
        return _session_from(folder, self.name)


class PickleAwareReader(SessionReader):
    """Declares accepts_allow_pickle, the way pp3's idtracker.ai readers do."""

    name = "pickle_test"
    priority = 0
    accepts_allow_pickle = True
    seen: ClassVar[list[bool]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    def read(self, folder: Path, *, allow_pickle: bool = False) -> Session:
        type(self).seen.append(allow_pickle)
        return _session_from(folder, self.name)


class OptionReader(SessionReader):
    """Declares parameters, so it is called with a resolved ``options`` mapping."""

    name = "option_test"
    priority = 0
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
        ReaderParameter(name="cutoff", label="Cutoff", kind="float", default=0.6),
    )
    seen: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "option.marker").exists()

    def read(
        self, folder: Path, *, allow_pickle: bool = False, options: Any = None
    ) -> Session:
        type(self).seen.append(dict(options or {}))
        return _session_from(folder, self.name)


@pytest.fixture
def registered() -> Iterator[None]:
    LegacyReader.calls.clear()
    PickleAwareReader.seen.clear()
    OptionReader.seen.clear()
    toys = (LegacyReader, PickleAwareReader, OptionReader)
    for cls in toys:
        readers.register(cls)
    yield
    for cls in toys:
        readers._REGISTRY.remove(cls)


def test_defaults_describe_a_plain_reader() -> None:
    assert LegacyReader.parameters == ()
    assert LegacyReader.display_name == ""
    assert LegacyReader.verification == "synthetic_only"
    assert LegacyReader.coordinate_frame == "image_px"
    assert LegacyReader.provides_body_length is False


def test_builtin_idtracker_readers_declare_themselves() -> None:
    for cls in (readers.IDTrackerAiReader, readers.IDTrackerAiV5Reader):
        assert cls.verification == "real_sample"
        assert cls.display_name
    assert readers.IDTrackerAiReader.provides_body_length is True
    assert readers.IDTrackerAiV5Reader.provides_body_length is False


def test_a_legacy_reader_still_detects_and_reads_with_one_argument(
    registered: None, tmp_path: Path
) -> None:
    (tmp_path / "legacy.marker").write_text("x")
    session = readers.read_session(tmp_path)
    assert session.reader == "legacy_test"
    assert LegacyReader.calls == [(tmp_path, {})]


def test_allow_pickle_reaches_only_readers_that_declare_it(
    registered: None, tmp_path: Path
) -> None:
    readers.read_session(tmp_path, reader="pickle_test", allow_pickle=True)
    readers.read_session(tmp_path, reader="pickle_test")
    assert PickleAwareReader.seen == [True, False]
    # A legacy reader would raise TypeError if it were handed the keyword.
    readers.read_session(tmp_path, reader="legacy_test", allow_pickle=True)
    assert LegacyReader.calls == [(tmp_path, {})]


def test_options_reach_a_reader_that_declares_parameters(
    registered: None, tmp_path: Path
) -> None:
    readers.read_session(tmp_path, reader="option_test", options={"fps": 25})
    assert OptionReader.seen == [{"fps": 25, "cutoff": 0.6}]


def test_a_missing_required_option_is_a_coded_error_not_a_default(
    registered: None, tmp_path: Path
) -> None:
    with pytest.raises(ImportError_) as err:
        readers.read_session(tmp_path, reader="option_test")
    assert err.value.code == "READER_OPTION_MISSING"
    assert err.value.subject == "fps"
    assert OptionReader.seen == []


def test_options_for_a_reader_that_takes_none_are_rejected(
    registered: None, tmp_path: Path
) -> None:
    with pytest.raises(ImportError_) as err:
        readers.read_session(tmp_path, reader="legacy_test", options={"fps": 1})
    assert err.value.code == "READER_OPTION_INVALID"
    assert LegacyReader.calls == []


def test_naming_a_reader_skips_detection(
    registered: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(folder: Path) -> None:
        raise AssertionError("detect_reader must not run when a reader is named")

    monkeypatch.setattr(readers, "detect_reader", boom)
    # No marker file exists, so detection would fail: naming the reader must not need it.
    assert readers.read_session(tmp_path, reader="legacy_test").reader == "legacy_test"


def test_an_unnamed_session_with_no_matching_reader_still_says_so(tmp_path: Path) -> None:
    with pytest.raises(ImportError_) as err:
        readers.read_session(tmp_path)
    assert err.value.code == "NO_READER"


def test_get_reader_unknown_name_is_a_coded_error() -> None:
    with pytest.raises(ImportError_) as err:
        readers.get_reader("no_such_reader")
    assert err.value.code == "READER_UNKNOWN"
    assert err.value.subject == "no_such_reader"
    assert err.value.remediation


def test_get_reader_returns_the_registered_class() -> None:
    assert readers.get_reader("idtrackerai") is readers.IDTrackerAiReader
    assert readers.get_reader("idtrackerai_v5") is readers.IDTrackerAiV5Reader


def test_reader_names_lists_the_registry_in_priority_order() -> None:
    assert readers.reader_names()[:2] == ["idtrackerai", "idtrackerai_v5"]
