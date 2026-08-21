"""Tests for the idtrackerai session detector — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from track2data.readers.idtrackerai.detect import detect


class TestDetectEmptyAndUnknown:
    def test_empty_folder_returns_none(self, tmp_path: Path) -> None:
        assert detect(tmp_path) is None

    def test_folder_with_only_video_object_returns_none(self, tmp_path: Path) -> None:
        """Old v5-style session (video_object.npy at root, no trajectories/ dict)."""
        np.save(tmp_path / "video_object.npy", {"fps": 25.0}, allow_pickle=True)
        assert detect(tmp_path) is None

    def test_trajectories_dir_no_files_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "trajectories").mkdir()
        assert detect(tmp_path) is None


class TestDetectNpy:
    def test_detects_npy_format(self, tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        np.save(traj_dir / "trajectories.npy", {}, allow_pickle=True)
        hit = detect(tmp_path)
        assert hit is not None
        assert hit.format == "npy"

    def test_hit_path_points_to_npy(self, tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        np.save(traj_dir / "trajectories.npy", {}, allow_pickle=True)
        hit = detect(tmp_path)
        assert hit is not None
        assert hit.path.name == "trajectories.npy"


class TestDetectCsvBundle:
    def test_detects_csv_bundle(self, tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        csv_dir = traj_dir / "trajectories_csv"
        csv_dir.mkdir(parents=True)
        (csv_dir / "trajectories.csv").write_text("frame,x_1,y_1\n0,100,200\n")
        hit = detect(tmp_path)
        assert hit is not None
        assert hit.format == "csv"

    def test_npy_beats_csv_bundle(self, tmp_path: Path) -> None:
        """When both npy and csv bundle are present, npy wins (priority order)."""
        traj_dir = tmp_path / "trajectories"
        csv_dir = traj_dir / "trajectories_csv"
        csv_dir.mkdir(parents=True)
        np.save(traj_dir / "trajectories.npy", {}, allow_pickle=True)
        (csv_dir / "trajectories.csv").write_text("frame,x_1\n")
        hit = detect(tmp_path)
        assert hit is not None
        assert hit.format == "npy"

    def test_all_present_formats_listed(self, tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        csv_dir = traj_dir / "trajectories_csv"
        csv_dir.mkdir(parents=True)
        np.save(traj_dir / "trajectories.npy", {}, allow_pickle=True)
        (csv_dir / "trajectories.csv").write_text("frame,x_1\n")
        hit = detect(tmp_path)
        assert hit is not None
        formats = [f for f, _ in hit.all_present]
        assert "npy" in formats
        assert "csv" in formats


class TestDetectResourceForks:
    def test_resource_fork_npy_not_detected(self, tmp_path: Path) -> None:
        """A macOS resource-fork file (._trajectories.npy) does not match any
        of detect()'s fixed candidate filenames ("trajectories.npy", etc.),
        so it is never picked up -- there is no dedicated resource-fork
        filter in detect.py itself (candidate paths are literals, so one
        would be unreachable dead code; see detect.py's module docstring).
        This test documents that the fixed-filename matching alone already
        gives the right behaviour here, not that a filter exists."""
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        (traj_dir / "._trajectories.npy").write_bytes(b"\x00\x05\x16\x07")
        assert detect(tmp_path) is None


class TestDetectWithTinyReal:
    def test_tiny_real_detected_as_npy(self, tiny_real_session: Path) -> None:
        hit = detect(tiny_real_session)
        assert hit is not None
        assert hit.format == "npy"

    def test_tiny_real_hit_has_npy_path(self, tiny_real_session: Path) -> None:
        hit = detect(tiny_real_session)
        assert hit is not None
        assert hit.path.exists()
        assert hit.path.suffix == ".npy"
