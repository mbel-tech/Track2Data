"""idtracker.ai's two readers: detect() and discover() agree, and the v5 layout reaches its reader.

Before the scan work, auto-detection gave the unified reader every folder with a
``trajectories/trajectories.npy``, including the legacy v5 layout (a raw float array beside a
``video_object.npy``). Reading it then failed with IDT_FORMAT_AMBIGUOUS and the v5 reader was
never tried, even though its own ``detect`` accepted the folder.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from track2data import readers
from track2data.core.errors import ImportError_
from track2data.readers.index import build_index
from track2data.readers.peek import Peeker


@pytest.mark.parametrize("reader_name", ["idtrackerai", "idtrackerai_v5"])
@pytest.mark.parametrize(
    "fixture",
    ["tiny_real_session", "tiny_v5_session", "tiny_identity_free_session", "empty_folder"],
)
def test_detect_agrees_with_whether_discover_finds_the_folder(
    request: pytest.FixtureRequest, reader_name: str, fixture: str
) -> None:
    folder: Path = request.getfixturevalue(fixture)
    reader = readers.get_reader(reader_name)
    index = build_index([folder])
    found = reader.discover(index, Peeker(index=index))
    discovered = any(s.source == folder for d in found for s in d.sessions)
    assert reader.detect(folder) is discovered


class TestTheV5LayoutReachesTheV5Reader:
    def test_the_unified_reader_declines_it(self, tiny_v5_session: Path) -> None:
        assert not readers.IDTrackerAiReader.detect(tiny_v5_session)

    def test_auto_detection_picks_the_v5_reader(self, tiny_v5_session: Path) -> None:
        assert readers.detect_reader(tiny_v5_session) is readers.IDTrackerAiV5Reader

    def test_reading_without_naming_the_reader_works(self, tiny_v5_session: Path) -> None:
        session = readers.read_session(tiny_v5_session, allow_pickle=True)
        assert session.reader == "idtrackerai_v5"

    def test_a_pickled_dict_beside_a_video_object_stays_with_the_unified_reader(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        folder = tmp_path / "both"
        shutil.copytree(tiny_real_session, folder)
        (folder / "video_object.npy").write_bytes(b"placeholder")
        assert readers.detect_reader(folder) is readers.IDTrackerAiReader

    def test_a_raw_array_with_no_video_object_is_still_claimed_and_still_explained(
        self, tmp_path: Path
    ) -> None:
        # Declining it would turn a precise error into "no reader recognised the folder".
        (tmp_path / "trajectories").mkdir()
        np.save(tmp_path / "trajectories" / "trajectories.npy", np.zeros((3, 1, 2)))
        assert readers.IDTrackerAiReader.detect(tmp_path)
        with pytest.raises(ImportError_) as err:
            readers.read_session(tmp_path, allow_pickle=True)
        assert err.value.code == "IDT_FORMAT_AMBIGUOUS"

    def test_an_unreadable_header_leaves_the_claim_with_the_unified_reader(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "trajectories").mkdir()
        (tmp_path / "trajectories" / "trajectories.npy").write_bytes(b"not numpy")
        (tmp_path / "video_object.npy").write_bytes(b"placeholder")
        assert readers.IDTrackerAiReader.detect(tmp_path)
