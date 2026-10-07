"""Every shipped reader returns a well-formed Session and leaves its input untouched.

This is the generic floor. Per-format correctness against independent oracles lives in
``tests/real_samples``; here the readers are held to the invariants the engine relies on but
``Session`` itself does not validate (it has no validators).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from track2data import readers


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(params=["idtrackerai", "idtrackerai_v5"])
def reader_and_folder(request: pytest.FixtureRequest) -> tuple[str, Path]:
    fixture = {"idtrackerai": "tiny_real_session", "idtrackerai_v5": "tiny_v5_session"}[
        request.param
    ]
    return request.param, request.getfixturevalue(fixture)


def test_session_is_well_formed(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    session = readers.read_session(folder, reader=name, allow_pickle=True)
    assert session.reader == name
    assert session.session_id
    assert session.raw_xy.dtype == np.float64
    assert session.raw_xy.ndim == 3
    assert session.raw_xy.shape[2] == 2
    assert not np.isinf(session.raw_xy).any()
    assert session.n_animals == session.raw_xy.shape[1]
    assert session.video.n_frames == session.raw_xy.shape[0]
    assert session.video.fps > 0


def test_the_frame_size_is_never_invented(reader_and_folder: tuple[str, Path]) -> None:
    """The IL-3 and IL-14 arena fallback uses width and height, so 0 is a silent wrong answer."""
    name, folder = reader_and_folder
    session = readers.read_session(folder, reader=name, allow_pickle=True)
    assert session.video.width_px > 0
    assert session.video.height_px > 0


def test_reading_does_not_modify_the_input_folder(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    before = _tree_hash(folder)
    readers.read_session(folder, reader=name, allow_pickle=True)
    assert _tree_hash(folder) == before


def test_a_reader_detects_the_folder_it_can_read(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    assert readers.get_reader(name).detect(folder)
