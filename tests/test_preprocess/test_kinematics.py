"""Tests for track2data.preprocess.kinematics."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.preprocess.kinematics import compute_kinematics


@pytest.fixture()
def simple_xy() -> np.ndarray:
    """100 frames, 4 animals. Animal 0 moves right at 5 px/frame."""
    xy = np.zeros((100, 4, 2), dtype=np.float64)
    frames = np.arange(100, dtype=np.float64)
    xy[:, 0, 0] = 100.0 + frames * 5.0  # step=5 px, horizontal
    xy[:, 0, 1] = 200.0
    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 4.0  # step=4 px, vertical
    xy[:, 2, 0] = 960.0 + 100.0 * np.cos(frames * 0.1)
    xy[:, 2, 1] = 540.0 + 100.0 * np.sin(frames * 0.1)
    xy[:, 3, 0] = 800.0
    xy[:, 3, 1] = 600.0  # static
    return xy


def test_speed_horizontal_animal(simple_xy: np.ndarray) -> None:
    """Animal 0 moves 5 px/frame at 25 fps → speed = 125 px/s."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    # All frames except last should have speed 125
    assert kin.speed_px_s.shape == (100, 4)
    np.testing.assert_allclose(kin.speed_px_s[:-1, 0], 125.0, rtol=1e-9)


def test_speed_last_frame_is_nan(simple_xy: np.ndarray) -> None:
    """Speed at the last frame is undefined → NaN."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert np.isnan(kin.speed_px_s[-1, 0])


def test_speed_vertical_animal(simple_xy: np.ndarray) -> None:
    """Animal 1 moves 4 px/frame vertically at 25 fps → speed = 100 px/s."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    np.testing.assert_allclose(kin.speed_px_s[:-1, 1], 100.0, rtol=1e-9)


def test_static_animal_speed_zero(simple_xy: np.ndarray) -> None:
    """Animal 3 is static → speed = 0."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    np.testing.assert_allclose(kin.speed_px_s[:-1, 3], 0.0, atol=1e-12)


def test_heading_horizontal_is_zero(simple_xy: np.ndarray) -> None:
    """Animal 0 moves in +x direction → heading = 0 rad."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    np.testing.assert_allclose(kin.heading_rad[:-1, 0], 0.0, atol=1e-12)


def test_heading_vertical_is_pi_over_2(simple_xy: np.ndarray) -> None:
    """Animal 1 moves in +y direction → heading = pi/2."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    np.testing.assert_allclose(kin.heading_rad[:-1, 1], np.pi / 2, atol=1e-9)


def test_heading_nan_at_last_frame(simple_xy: np.ndarray) -> None:
    """Heading at last frame is NaN (no displacement)."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert np.isnan(kin.heading_rad[-1, 0])


def test_heading_nan_for_zero_displacement(simple_xy: np.ndarray) -> None:
    """Static animal (zero displacement) → heading = NaN."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert np.all(np.isnan(kin.heading_rad[:-1, 3]))


def test_accel_shape(simple_xy: np.ndarray) -> None:
    """Acceleration array must be (n_frames, n_animals)."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert kin.accel_px_s2.shape == (100, 4)


def test_accel_constant_speed_is_zero(simple_xy: np.ndarray) -> None:
    """Constant speed → acceleration = 0 (except last two frames)."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    np.testing.assert_allclose(kin.accel_px_s2[:-2, 0], 0.0, atol=1e-9)


def test_accel_nan_at_last_two_frames(simple_xy: np.ndarray) -> None:
    """Acceleration is NaN at the last two frames."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert np.isnan(kin.accel_px_s2[-1, 0])
    assert np.isnan(kin.accel_px_s2[-2, 0])


def test_nan_positions_propagate_to_speed() -> None:
    """NaN in xy propagates to speed at that frame and the preceding frame."""
    xy = np.zeros((10, 2, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(10) * 5.0
    xy[5, 0, :] = np.nan  # NaN at frame 5
    kin = compute_kinematics(xy, fps=1.0)
    # speed at frame 5 (would use xy[5] and xy[6]) → NaN
    assert np.isnan(kin.speed_px_s[5, 0])
    # speed at frame 4 (uses xy[4] and xy[5]) → NaN
    assert np.isnan(kin.speed_px_s[4, 0])


def test_output_dtype(simple_xy: np.ndarray) -> None:
    """All output arrays should be float64."""
    kin = compute_kinematics(simple_xy, fps=25.0)
    assert kin.speed_px_s.dtype == np.float64
    assert kin.accel_px_s2.dtype == np.float64
    assert kin.heading_rad.dtype == np.float64
