"""Tests for track2data.readers.idtrackerai_detect.sniff_version.

sniff_version() is a pure filesystem heuristic with three branches:
  'v5'  -- folder/trajectories/ is a directory AND folder/video_object.npy exists
  'v4'  -- folder/trajectories.npy exists (checked only once the v5 test fails)
  None  -- neither condition is met
"""

from __future__ import annotations

from pathlib import Path

from track2data.readers.idtrackerai_detect import sniff_version


class TestSniffVersionV5:
    def test_v5_when_trajectories_dir_and_video_object_present(self, tmp_path: Path) -> None:
        (tmp_path / "trajectories").mkdir()
        (tmp_path / "video_object.npy").write_bytes(b"\x00")
        assert sniff_version(tmp_path) == "v5"

    def test_almost_v5_dir_present_but_video_object_missing_is_not_v5(
        self, tmp_path: Path
    ) -> None:
        """trajectories/ exists but video_object.npy does not -- must not return 'v5'."""
        (tmp_path / "trajectories").mkdir()
        assert sniff_version(tmp_path) != "v5"

    def test_almost_v5_dir_present_but_video_object_missing_falls_through_to_none(
        self, tmp_path: Path
    ) -> None:
        """Same setup as above; with no flat trajectories.npy either, the v4 check
        also fails, so the overall result must be None (not 'v4')."""
        (tmp_path / "trajectories").mkdir()
        assert sniff_version(tmp_path) is None

    def test_almost_v5_video_object_present_but_no_trajectories_dir_is_none(
        self, tmp_path: Path
    ) -> None:
        """video_object.npy exists but trajectories/ does not -- must not return 'v5'."""
        (tmp_path / "video_object.npy").write_bytes(b"\x00")
        assert sniff_version(tmp_path) is None


class TestSniffVersionV4:
    def test_v4_when_flat_trajectories_npy_present(self, tmp_path: Path) -> None:
        (tmp_path / "trajectories.npy").write_bytes(b"\x00")
        assert sniff_version(tmp_path) == "v4"

    def test_v4_via_fallthrough_when_trajectories_dir_exists_without_video_object(
        self, tmp_path: Path
    ) -> None:
        """v5's conditions are not met (no video_object.npy), so detection falls
        through to the v4 check, which succeeds because trajectories.npy exists
        at the root alongside the (irrelevant, empty) trajectories/ dir."""
        (tmp_path / "trajectories").mkdir()
        (tmp_path / "trajectories.npy").write_bytes(b"\x00")
        assert sniff_version(tmp_path) == "v4"

    def test_trajectories_npy_as_directory_still_satisfies_exists_check(
        self, tmp_path: Path
    ) -> None:
        """The v4 branch uses Path.exists(), not is_file(), so a directory named
        'trajectories.npy' satisfies it too -- documenting the real behavior as coded."""
        (tmp_path / "trajectories.npy").mkdir()
        assert sniff_version(tmp_path) == "v4"


class TestSniffVersionNone:
    def test_none_for_completely_empty_folder(self, tmp_path: Path) -> None:
        assert sniff_version(tmp_path) is None

    def test_none_when_trajectories_is_a_file_not_a_directory(self, tmp_path: Path) -> None:
        """'trajectories' exists but as a file, not a dir, so v5's is_dir() check
        fails; it is also a different name than 'trajectories.npy' so the v4
        check fails too."""
        (tmp_path / "trajectories").write_bytes(b"\x00")
        (tmp_path / "video_object.npy").write_bytes(b"\x00")
        assert sniff_version(tmp_path) is None
