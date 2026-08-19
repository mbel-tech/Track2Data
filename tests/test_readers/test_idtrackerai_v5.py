"""
Tests for IDTrackerAiV5Reader — written before implementation (TDD RED).

These tests verify:
  - detect()  correctly identifies valid / invalid session folders
  - read()    returns a well-formed Session with correct shapes and values
  - Prefer    trajectories_wo_gaps.npy over trajectories.npy
  - Fallback  to trajectories.npy when wo_gaps absent
  - Transpose (n_animals, n_frames, 2) → (n_frames, n_animals, 2)
  - identity-stability detection based on NaN coverage threshold
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# Import constants from conftest (pytest makes them available via the module)
from tests.conftest import (
    TINY_V5_FPS,
    TINY_V5_FRAME0,
    TINY_V5_GAP_FRAMES,
    TINY_V5_HEIGHT,
    TINY_V5_N_ANIMALS,
    TINY_V5_N_FRAMES,
    TINY_V5_WIDTH,
)
from track2data.core.errors import DataValidationError
from track2data.core.models import Session
from track2data.readers.idtrackerai_v5 import IDTrackerAiV5Reader


@pytest.fixture(scope="module")
def reader() -> IDTrackerAiV5Reader:
    return IDTrackerAiV5Reader()


# ── detect() ──────────────────────────────────────────────────────────────────

class TestDetect:
    def test_detects_valid_v5_session(self, tiny_v5_session: Path) -> None:
        assert IDTrackerAiV5Reader.detect(tiny_v5_session) is True

    def test_rejects_empty_folder(self, empty_folder: Path) -> None:
        assert IDTrackerAiV5Reader.detect(empty_folder) is False

    def test_rejects_folder_missing_video_object(self, tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        np.save(traj_dir / "trajectories.npy", np.zeros((10, 2, 2)))
        # no video_object.npy
        assert IDTrackerAiV5Reader.detect(tmp_path) is False

    def test_rejects_folder_missing_trajectories_dir(self, tmp_path: Path) -> None:
        np.save(tmp_path / "video_object.npy", {"fps": 25.0})
        # no trajectories/ subdir
        assert IDTrackerAiV5Reader.detect(tmp_path) is False


# ── read() — basic structure ───────────────────────────────────────────────────

class TestReadBasic:
    def test_returns_session_instance(self, reader: IDTrackerAiV5Reader,
                                       tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert isinstance(s, Session)

    def test_session_id_is_folder_name(self, reader: IDTrackerAiV5Reader,
                                        tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.session_id == tiny_v5_session.name

    def test_folder_stored(self, reader: IDTrackerAiV5Reader,
                            tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.folder == tiny_v5_session

    def test_reader_name_recorded(self, reader: IDTrackerAiV5Reader,
                                   tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.reader == "idtrackerai_v5"


# ── read() — trajectory shape & values ────────────────────────────────────────

class TestReadTrajectory:
    def test_raw_xy_shape(self, reader: IDTrackerAiV5Reader,
                           tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.raw_xy.shape == (TINY_V5_N_FRAMES, TINY_V5_N_ANIMALS, 2)

    def test_raw_xy_dtype_float64(self, reader: IDTrackerAiV5Reader,
                                   tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.raw_xy.dtype == np.float64

    def test_n_animals_correct(self, reader: IDTrackerAiV5Reader,
                                tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.n_animals == TINY_V5_N_ANIMALS

    def test_n_frames_property(self, reader: IDTrackerAiV5Reader,
                                tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.n_frames == TINY_V5_N_FRAMES

    def test_prefers_wo_gaps(self, reader: IDTrackerAiV5Reader,
                              tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.trajectory_variant == "wo_gaps"

    def test_wo_gaps_has_no_nans_at_gap_frames(self, reader: IDTrackerAiV5Reader,
                                                tiny_v5_session: Path) -> None:
        """Reader chose wo_gaps → the NaN gap for animal 0 should be filled."""
        s = reader.read(tiny_v5_session)
        for f in TINY_V5_GAP_FRAMES:
            assert not np.isnan(s.raw_xy[f, 0, 0]), f"NaN still present at frame {f}"

    def test_frame0_values_correct(self, reader: IDTrackerAiV5Reader,
                                    tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        np.testing.assert_allclose(s.raw_xy[0], TINY_V5_FRAME0, rtol=1e-9)

    def test_fallback_to_with_gaps(self, reader: IDTrackerAiV5Reader,
                                    tiny_v5_no_wo_gaps: Path) -> None:
        s = reader.read(tiny_v5_no_wo_gaps)
        assert s.trajectory_variant == "with_gaps"

    def test_fallback_has_nans_at_gap_frames(self, reader: IDTrackerAiV5Reader,
                                              tiny_v5_no_wo_gaps: Path) -> None:
        s = reader.read(tiny_v5_no_wo_gaps)
        for f in TINY_V5_GAP_FRAMES:
            assert np.isnan(s.raw_xy[f, 0, 0]), f"Expected NaN at frame {f}"

    def test_transposed_input_corrected(self, reader: IDTrackerAiV5Reader,
                                         tiny_v5_transposed: Path) -> None:
        """(n_animals, n_frames, 2) input must be transposed to canonical form."""
        s = reader.read(tiny_v5_transposed)
        assert s.raw_xy.shape == (TINY_V5_N_FRAMES, TINY_V5_N_ANIMALS, 2)


# ── read() — video metadata ───────────────────────────────────────────────────

class TestReadVideoMeta:
    def test_fps_correct(self, reader: IDTrackerAiV5Reader,
                          tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.video.fps == pytest.approx(TINY_V5_FPS)

    def test_n_frames_from_video(self, reader: IDTrackerAiV5Reader,
                                  tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.video.n_frames == TINY_V5_N_FRAMES

    def test_width_px(self, reader: IDTrackerAiV5Reader,
                       tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.video.width_px == TINY_V5_WIDTH

    def test_height_px(self, reader: IDTrackerAiV5Reader,
                        tiny_v5_session: Path) -> None:
        s = reader.read(tiny_v5_session)
        assert s.video.height_px == TINY_V5_HEIGHT

    def test_video_path_none_when_unreachable(self, reader: IDTrackerAiV5Reader,
                                               tiny_v5_session: Path) -> None:
        """dummy_video.mp4 does not exist → video.path should be None."""
        s = reader.read(tiny_v5_session)
        assert s.video.path is None


# ── read() — identity stability ───────────────────────────────────────────────

class TestIdentityStability:
    def test_stable_when_coverage_above_threshold(self, reader: IDTrackerAiV5Reader,
                                                   tiny_v5_session: Path) -> None:
        """All animals have ≥50% coverage → has_stable_identities = True."""
        s = reader.read(tiny_v5_session)
        assert s.has_stable_identities is True

    def test_unstable_when_animal_below_threshold(self, reader: IDTrackerAiV5Reader,
                                                   tmp_path: Path) -> None:
        """One animal with <50% coverage → has_stable_identities = False."""
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        xy = np.zeros((100, 4, 2), dtype=np.float64)
        xy[:60, 0, :] = np.nan  # animal 0 has only 40% valid frames
        np.save(traj_dir / "trajectories_wo_gaps.npy", xy)
        video_obj = {
            "fps": 25.0, "frame_number": 100,
            "height": 1080, "width": 1920,
            "paths_to_video_files": [],
        }
        np.save(tmp_path / "video_object.npy", video_obj)
        s = reader.read(tmp_path)
        assert s.has_stable_identities is False

    def test_body_length_px_is_none_when_absent(self, reader: IDTrackerAiV5Reader,
                                                  tiny_v5_session: Path) -> None:
        """tiny_v5 has no body-length data → body_length_px must be None."""
        s = reader.read(tiny_v5_session)
        assert s.body_length_px is None


# ── Error handling ─────────────────────────────────────────────────────────────

class TestReadErrors:
    def test_raises_on_2d_trajectory(self, reader: IDTrackerAiV5Reader,
                                      tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        np.save(traj_dir / "trajectories_wo_gaps.npy", np.zeros((100, 4)))  # 2-D
        np.save(tmp_path / "video_object.npy", {"fps": 25.0, "frame_number": 100,
                                                  "height": 1080, "width": 1920})
        with pytest.raises(DataValidationError, match="TRAJ_BAD_NDIM"):
            reader.read(tmp_path)

    def test_raises_when_no_trajectory_file(self, reader: IDTrackerAiV5Reader,
                                             tmp_path: Path) -> None:
        traj_dir = tmp_path / "trajectories"
        traj_dir.mkdir()
        # no .npy files inside trajectories/
        np.save(tmp_path / "video_object.npy", {"fps": 25.0, "frame_number": 100,
                                                  "height": 1080, "width": 1920})
        with pytest.raises(DataValidationError, match="TRAJ_NOT_FOUND"):
            reader.read(tmp_path)
