"""Tests for the HDF5 format loader (trajectories.h5).

trajectories.h5 is idtracker.ai's own default output format
(trajectories_formats defaults to ['h5', 'npy', 'csv'] --
session_idtrackerai.md:73) and every unmodified 6.x session ships it.
Schema verified empirically against the 70-session real corpus -- see
formats/h5.py's module docstring.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from track2data.readers.idtrackerai.formats.h5 import load_h5


def _write_h5(path: Path, *, with_areas: bool = True, length_unit: float = -1.0) -> None:
    n_frames, n_animals = 5, 2
    with h5py.File(path, "w") as f:
        f.create_dataset("trajectories", data=np.zeros((n_frames, n_animals, 2)))
        f.create_dataset("id_probabilities", data=np.ones((n_frames, n_animals, 1)) * 0.9)
        if with_areas:
            areas = f.create_group("areas")
            areas.create_dataset("mean", data=np.array([150.0, 160.0]))
            areas.create_dataset("median", data=np.array([149.0, 158.0]))
            areas.create_dataset("std", data=np.array([2.0, 3.0]))
        f.create_group("identities_groups")  # empty group == {} (exclusive_rois=False)
        f.create_group("setup_points")
        f.attrs["version"] = "6.0.13"
        f.attrs["height"] = 1080
        f.attrs["width"] = 1920
        f.attrs["frames_per_second"] = 25.0
        f.attrs["body_length"] = 150.15
        f.attrs["fraction_identified"] = 0.822
        f.attrs["length_unit"] = length_unit
        f.attrs["identities_labels"] = np.array(["1", "2"], dtype=object)
        f.attrs["video_paths"] = np.array(["/Volumes/Expansion/tiny_real.mp4"], dtype=object)


class TestLoadH5:
    def test_returns_dict_with_trajectories(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        assert isinstance(result, dict)
        assert "trajectories" in result

    def test_trajectory_shape_is_n_m_2(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        traj = result["trajectories"]
        assert traj.shape == (5, 2, 2)

    def test_id_probabilities_shape_is_n_m_1(self, tmp_path: Path) -> None:
        """Matches the npy loader's contract -- normaliser does the squeeze."""
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        probs = result["id_probabilities"]
        assert probs.ndim == 3
        assert probs.shape[2] == 1

    def test_areas_group_becomes_dict_of_arrays(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        assert set(result["areas"].keys()) == {"mean", "median", "std"}
        assert result["areas"]["mean"].shape == (2,)

    def test_empty_group_becomes_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        assert result["identities_groups"] == {}
        assert result["setup_points"] == {}

    def test_attrs_merged_into_payload(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        assert result["version"] == "6.0.13"
        assert result["height"] == 1080
        assert result["frames_per_second"] == pytest.approx(25.0)

    def test_string_array_attrs_become_plain_lists(self, tmp_path: Path) -> None:
        """h5py returns object-dtype ndarrays for string attrs; must be plain list[str]."""
        path = tmp_path / "trajectories.h5"
        _write_h5(path)
        result = load_h5(path)
        assert result["identities_labels"] == ["1", "2"]
        assert isinstance(result["identities_labels"], list)

    def test_length_unit_sentinel_minus_one_present_verbatim(self, tmp_path: Path) -> None:
        """h5 ships -1 (not None/NaN) when uncalibrated; Normaliser handles the <= 0 case."""
        path = tmp_path / "trajectories.h5"
        _write_h5(path, length_unit=-1.0)
        result = load_h5(path)
        assert result["length_unit"] == -1.0

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import ImportError_
        with pytest.raises(ImportError_):
            load_h5(tmp_path / "does_not_exist.h5")

    def test_missing_trajectories_dataset_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.h5"
        with h5py.File(path, "w") as f:
            f.attrs["version"] = "6.0.13"
        from track2data.core.errors import DataValidationError
        with pytest.raises(DataValidationError):
            load_h5(path)
