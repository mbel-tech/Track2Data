"""Tests for the NPY format loader — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.readers.idtrackerai.formats.npy import load_npy


class TestLoadNpy:
    def test_returns_dict_from_pickled_npy(self, tmp_path: Path) -> None:
        traj_dict = {"trajectories": np.zeros((5, 2, 2)), "version": "6.0.13"}
        path = tmp_path / "trajectories.npy"
        np.save(path, traj_dict, allow_pickle=True)
        result = load_npy(path)
        assert isinstance(result, dict)
        assert "trajectories" in result

    def test_version_key_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "trajectories.npy"
        np.save(path, {"version": "6.0.13"}, allow_pickle=True)
        result = load_npy(path)
        assert result["version"] == "6.0.13"

    def test_loads_tiny_real_npy(self, tiny_real_session: Path) -> None:
        npy_path = tiny_real_session / "trajectories" / "trajectories.npy"
        result = load_npy(npy_path)
        assert isinstance(result, dict)

    def test_tiny_real_has_all_17_keys(self, tiny_real_session: Path) -> None:
        from track2data.readers.idtrackerai.key_aliases import KNOWN_TRAJECTORY_KEYS
        npy_path = tiny_real_session / "trajectories" / "trajectories.npy"
        result = load_npy(npy_path)
        for key in KNOWN_TRAJECTORY_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_id_probabilities_shape_is_n_m_1(self, tiny_real_session: Path) -> None:
        """Real files ship (N, M, 1) — loader must not squeeze, normaliser does that."""
        npy_path = tiny_real_session / "trajectories" / "trajectories.npy"
        result = load_npy(npy_path)
        probs = result["id_probabilities"]
        assert probs.ndim == 3
        assert probs.shape[2] == 1

    def test_trajectory_shape_is_n_m_2(self, tiny_real_session: Path) -> None:
        npy_path = tiny_real_session / "trajectories" / "trajectories.npy"
        result = load_npy(npy_path)
        traj = result["trajectories"]
        assert traj.ndim == 3
        assert traj.shape[2] == 2
        assert traj.shape[0] == 10   # N_FRAMES
        assert traj.shape[1] == 2    # N_ANIMALS

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import ImportError_
        with pytest.raises(ImportError_):
            load_npy(tmp_path / "does_not_exist.npy")

    def test_non_dict_npy_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "raw_array.npy"
        np.save(path, np.zeros((10, 2, 2)), allow_pickle=False)
        from track2data.core.errors import DataValidationError
        with pytest.raises(DataValidationError):
            load_npy(path)
