"""Tests for the CSV bundle format loader — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.readers.idtrackerai.formats.csv_bundle import load_csv_bundle


class TestLoadCsvBundle:
    def test_loads_trajectories_from_tiny_real(self, tiny_real_session: Path) -> None:
        csv_dir = tiny_real_session / "trajectories" / "trajectories_csv"
        result = load_csv_bundle(csv_dir)
        assert "trajectories" in result
        assert result["trajectories"].shape[2] == 2  # x, y columns

    def test_trajectory_shape_n_m_2(self, tiny_real_session: Path) -> None:
        csv_dir = tiny_real_session / "trajectories" / "trajectories_csv"
        result = load_csv_bundle(csv_dir)
        traj = result["trajectories"]
        assert traj.ndim == 3
        assert traj.shape[0] == 10   # N_FRAMES
        assert traj.shape[1] == 2    # N_ANIMALS
        assert traj.shape[2] == 2    # x, y

    def test_loads_id_probabilities(self, tiny_real_session: Path) -> None:
        csv_dir = tiny_real_session / "trajectories" / "trajectories_csv"
        result = load_csv_bundle(csv_dir)
        assert "id_probabilities" in result
        probs = result["id_probabilities"]
        assert probs.ndim == 2  # CSV bundle gives (N, M) directly
        assert probs.shape == (10, 2)

    def test_reads_attributes_json(self, tiny_real_session: Path) -> None:
        csv_dir = tiny_real_session / "trajectories" / "trajectories_csv"
        result = load_csv_bundle(csv_dir)
        assert result.get("version") == "6.0.13"
        assert result.get("frames_per_second") == pytest.approx(25.0)

    def test_missing_csv_dir_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import ImportError_
        with pytest.raises(ImportError_):
            load_csv_bundle(tmp_path / "does_not_exist")

    def test_result_is_dict(self, tiny_real_session: Path) -> None:
        csv_dir = tiny_real_session / "trajectories" / "trajectories_csv"
        result = load_csv_bundle(csv_dir)
        assert isinstance(result, dict)
