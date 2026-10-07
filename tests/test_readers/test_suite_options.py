"""The real-sample suite hands options to readers at BOTH of its read call sites.

``provide_video_info`` is the suite's single hook for what a format does not record (fps, frame
size). Readers receive it as *options*, never through a sidecar file in the input folder
(FR-IMP-5), so the helpers below must work with readers that declare parameters and with the
scaffolding readers that do not.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.real_samples import fixtures
from track2data.core.models import Session, VideoInfo
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter

INFO = {"fps": 30.0, "width_px": 10, "height_px": 20}


def _session(folder: Path, name: str) -> Session:
    return Session(
        session_id=folder.name,
        folder=folder,
        reader=name,
        video=VideoInfo(path=None, fps=30.0, n_frames=2, width_px=10, height_px=20),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.zeros((2, 1, 2)),
    )


class DeclaringReader(SessionReader):
    name = "suite_declaring"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="fps", kind="float", required=True),
        ReaderParameter(name="width_px", label="width", kind="int", required=True),
        ReaderParameter(name="height_px", label="height", kind="int", required=True),
    )
    seen: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return True

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        type(self).seen.append(dict(options))
        return _session(folder, self.name)


class PlainReader(SessionReader):
    name = "suite_plain"
    calls: ClassVar[list[Path]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return True

    def read(self, folder: Path) -> Session:
        type(self).calls.append(folder)
        return _session(folder, self.name)


def test_provided_video_info_is_retrievable_as_options(tmp_path: Path) -> None:
    fixtures.provide_video_info(tmp_path, INFO)
    assert fixtures.options_for(tmp_path) == INFO
    assert fixtures.options_for(tmp_path / "elsewhere") is None


def test_options_follow_a_copy_of_the_folder(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    fixtures.provide_video_info(original, INFO)
    copy = tmp_path / "copy"
    shutil.copytree(original, copy)
    assert fixtures.options_for(copy) is None  # a bare copy knows nothing
    fixtures.copy_options(original, copy)
    assert fixtures.options_for(copy) == INFO


def test_a_reader_that_declares_parameters_receives_the_options(tmp_path: Path) -> None:
    DeclaringReader.seen.clear()
    fixtures.provide_video_info(tmp_path, INFO)
    fixtures.read_with_options(DeclaringReader, tmp_path)
    assert DeclaringReader.seen == [INFO]


def test_a_reader_that_declares_none_is_called_the_legacy_way(tmp_path: Path) -> None:
    PlainReader.calls.clear()
    fixtures.provide_video_info(tmp_path, INFO)
    fixtures.read_with_options(PlainReader, tmp_path)
    assert PlainReader.calls == [tmp_path]
