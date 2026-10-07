"""Tests for track2data.preprocess.kinematics.

Two estimators live here and they differ at the edges, so the tests are
explicit about which one they are pinning:

* ``savgol`` (default) is centred, so it produces a value at *every* frame,
  including the last, and a gap does not poison its neighbours;
* ``forward_difference`` is the pre-0.2 estimator, retained for one release.
  Its boundary NaNs and neighbour poisoning are artefacts of the method, not
  properties of the data, and several tests below used to assert them as
  though they were the contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import KinematicsCfg
from track2data.preprocess.kinematics import compute_kinematics

SAVGOL = KinematicsCfg(method="savgol")
LEGACY = KinematicsCfg(method="forward_difference")


@pytest.fixture()
def simple_xy() -> np.ndarray:
    """100 frames, 4 animals with known, exactly-representable motion.

    Animal 0: +5 px/frame in x. Animal 1: +4 px/frame in y.
    Animal 2: diagonal (+3, +4) px/frame. Animal 3: static.
    """
    xy = np.zeros((100, 4, 2), dtype=np.float64)
    frames = np.arange(100, dtype=np.float64)
    xy[:, 0, 0] = frames * 5.0
    xy[:, 1, 1] = frames * 4.0
    xy[:, 2, 0] = frames * 3.0
    xy[:, 2, 1] = frames * 4.0
    xy[:, 3, 0] = 500.0
    xy[:, 3, 1] = 500.0
    return xy


# ── shared contract (both estimators) ─────────────────────────────────────────


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_shapes_and_dtype(simple_xy: np.ndarray, cfg: KinematicsCfg) -> None:
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    for arr in (kin.speed_px_s, kin.accel_px_s2, kin.heading_rad):
        assert arr.shape == (100, 4)
        assert arr.dtype == np.float64


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_constant_velocity_speed(simple_xy: np.ndarray, cfg: KinematicsCfg) -> None:
    """5 px/frame at 25 fps is 125 px/s, whichever estimator is used."""
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    np.testing.assert_allclose(kin.speed_px_s[:-1, 0], 125.0, rtol=1e-9)


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_diagonal_speed_is_the_hypotenuse(
    simple_xy: np.ndarray, cfg: KinematicsCfg
) -> None:
    """(3, 4) px/frame at 25 fps is 5 px/frame -> 125 px/s."""
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    np.testing.assert_allclose(kin.speed_px_s[:-1, 2], 125.0, rtol=1e-9)


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_static_animal_has_zero_speed_and_no_heading(
    simple_xy: np.ndarray, cfg: KinematicsCfg
) -> None:
    """A still animal has no direction of travel, so heading must be NaN.

    Exactly zero, not nearly zero: an animal reported as moving at 1e-12 px/s
    would be given a heading invented from rounding error, and any turning
    metric downstream would consume it as real.
    """
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    np.testing.assert_array_equal(kin.speed_px_s[:-1, 3], 0.0)
    assert np.all(np.isnan(kin.heading_rad[:-1, 3]))


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_heading_directions(simple_xy: np.ndarray, cfg: KinematicsCfg) -> None:
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    np.testing.assert_allclose(kin.heading_rad[:-1, 0], 0.0, atol=1e-9)
    np.testing.assert_allclose(kin.heading_rad[:-1, 1], np.pi / 2, atol=1e-9)


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_constant_speed_means_zero_acceleration(
    simple_xy: np.ndarray, cfg: KinematicsCfg
) -> None:
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=cfg)
    np.testing.assert_allclose(kin.accel_px_s2[:-2, 0], 0.0, atol=1e-9)


@pytest.mark.parametrize("cfg", [SAVGOL, LEGACY], ids=["savgol", "forward_difference"])
def test_missing_positions_stay_missing(cfg: KinematicsCfg) -> None:
    """A frame with no position cannot have a speed."""
    xy = np.zeros((10, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(10) * 5.0
    xy[5, 0, :] = np.nan

    kin = compute_kinematics(xy, fps=1.0, cfg=cfg)

    assert np.isnan(kin.speed_px_s[5, 0])


# ── savgol: what the estimator was changed to fix ─────────────────────────────


def test_savgol_reports_speed_at_every_frame(simple_xy: np.ndarray) -> None:
    """The last frame is not a special case.

    A forward difference has nowhere to look at the final frame, so it
    reported NaN. That was a property of the arithmetic, not of the data --
    the animal's speed at the last frame is perfectly well defined, and a
    centred estimator gives it.
    """
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=SAVGOL)

    assert not np.isnan(kin.speed_px_s[-1, 0])
    assert not np.isnan(kin.heading_rad[-1, 0])
    np.testing.assert_allclose(kin.speed_px_s[-1, 0], 125.0, rtol=1e-9)


def test_savgol_reports_acceleration_at_every_frame(simple_xy: np.ndarray) -> None:
    """Likewise the last two frames, which the difference-of-differences lost."""
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=SAVGOL)
    assert not np.isnan(kin.accel_px_s2[-1, 0])
    assert not np.isnan(kin.accel_px_s2[-2, 0])


def test_savgol_speed_is_not_offset_by_half_a_frame() -> None:
    """The estimate at frame t must describe frame t.

    On a trajectory whose speed changes over time, a forward difference
    assigned to frame *t* actually estimates the speed at *t + 1/2*. Here the
    animal accelerates uniformly, so the true speed at frame t is known
    exactly and the offset is directly measurable.
    """
    fps = 10.0
    n = 60
    t = np.arange(n, dtype=np.float64) / fps
    accel = 20.0                       # px/s^2
    xy = np.zeros((n, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = 0.5 * accel * t ** 2  # x = ½at², so speed = a·t

    kin_sg = compute_kinematics(xy, fps=fps, cfg=SAVGOL)
    kin_fd = compute_kinematics(xy, fps=fps, cfg=LEGACY)

    true_speed = accel * t
    mid = slice(5, n - 5)

    np.testing.assert_allclose(kin_sg.speed_px_s[mid, 0], true_speed[mid], rtol=1e-6)
    # The old estimator is high by half a frame's worth of speed change,
    # a·Δt/2 = 20/(2·10) = 1.0 px/s, everywhere.
    offset = kin_fd.speed_px_s[mid, 0] - true_speed[mid]
    np.testing.assert_allclose(offset, accel / (2 * fps), rtol=1e-6)


def test_savgol_recovers_a_known_constant_acceleration() -> None:
    """Acceleration is the rate of change of speed, and must come out right."""
    fps = 10.0
    n = 60
    t = np.arange(n, dtype=np.float64) / fps
    true_accel = 20.0
    xy = np.zeros((n, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = 0.5 * true_accel * t ** 2

    kin = compute_kinematics(xy, fps=fps, cfg=SAVGOL)

    np.testing.assert_allclose(kin.accel_px_s2[5:-5, 0], true_accel, rtol=1e-6)


def test_savgol_acceleration_is_tangential_not_the_vector_magnitude() -> None:
    """An animal circling at constant speed is not accelerating, as IL-6
    defines it.

    The magnitude of the acceleration *vector* is non-zero here (centripetal),
    so this pins which of the two quantities the column reports -- switching
    silently between them would redefine the metric rather than improve it.
    """
    fps = 50.0
    n = 200
    theta = np.linspace(0, 2 * np.pi, n)
    xy = np.zeros((n, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = 100.0 * np.cos(theta)
    xy[:, 0, 1] = 100.0 * np.sin(theta)

    kin = compute_kinematics(xy, fps=fps, cfg=SAVGOL)

    np.testing.assert_allclose(kin.accel_px_s2[10:-10, 0], 0.0, atol=1e-3)
    assert np.all(kin.speed_px_s[10:-10, 0] > 0)


def test_savgol_does_not_let_a_gap_poison_its_neighbours() -> None:
    """Derivatives are taken per contiguous segment.

    The forward difference at frame 4 reached into frame 5, so a single
    missing position destroyed two speed values. Segmenting means only the
    missing frame is missing.
    """
    xy = np.zeros((20, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(20) * 5.0
    xy[10, 0, :] = np.nan

    kin = compute_kinematics(xy, fps=1.0, cfg=SAVGOL)

    assert np.isnan(kin.speed_px_s[10, 0])
    assert not np.isnan(kin.speed_px_s[9, 0])
    assert not np.isnan(kin.speed_px_s[11, 0])


def test_savgol_never_bridges_a_gap() -> None:
    """Filtering across a gap would invent motion that was never observed."""
    xy = np.full((30, 1, 2), np.nan)
    xy[:10, 0, 0] = np.arange(10) * 5.0
    xy[:10, 0, 1] = 0.0
    xy[20:, 0, 0] = 1000.0 + np.arange(10) * 5.0
    xy[20:, 0, 1] = 0.0

    kin = compute_kinematics(xy, fps=1.0, cfg=SAVGOL)

    assert np.all(np.isnan(kin.speed_px_s[10:20, 0]))
    # The 1000 px jump across the gap must not appear as speed anywhere.
    assert np.nanmax(kin.speed_px_s[:, 0]) < 10.0


def test_segment_too_short_for_the_fit_reports_nothing() -> None:
    """Refusing to estimate beats estimating from fewer points than the fit
    needs."""
    xy = np.full((20, 1, 2), np.nan)
    xy[5:7, 0, :] = [[0.0, 0.0], [5.0, 0.0]]  # a 2-frame island, polyorder 2

    kin = compute_kinematics(xy, fps=1.0, cfg=SAVGOL)

    assert np.all(np.isnan(kin.speed_px_s[:, 0]))


def test_polyorder_below_two_gives_no_acceleration() -> None:
    """A linear fit has no second derivative; NaN says so, 0 would lie."""
    xy = np.zeros((40, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(40) * 5.0

    kin = compute_kinematics(
        xy, fps=1.0, cfg=KinematicsCfg(method="savgol", window=5, polyorder=1)
    )

    assert np.all(np.isnan(kin.accel_px_s2[:, 0]))
    assert not np.isnan(kin.speed_px_s[10, 0])


# ── forward_difference: the retained legacy behaviour ─────────────────────────


def test_legacy_is_the_default_when_selected(simple_xy: np.ndarray) -> None:
    """Reproducing pre-0.2 numbers has to actually reproduce them."""
    kin = compute_kinematics(simple_xy, fps=25.0, cfg=LEGACY)

    assert np.isnan(kin.speed_px_s[-1, 0])
    assert np.isnan(kin.heading_rad[-1, 0])
    assert np.isnan(kin.accel_px_s2[-1, 0])
    assert np.isnan(kin.accel_px_s2[-2, 0])


def test_legacy_gap_poisons_the_preceding_frame() -> None:
    """Pinned as a known artefact of the retained estimator, not as a goal."""
    xy = np.zeros((10, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(10) * 5.0
    xy[5, 0, :] = np.nan

    kin = compute_kinematics(xy, fps=1.0, cfg=LEGACY)

    assert np.isnan(kin.speed_px_s[5, 0])
    assert np.isnan(kin.speed_px_s[4, 0])


def test_savgol_is_the_default() -> None:
    """The better estimator is what a caller gets without asking."""
    assert KinematicsCfg().method == "savgol"

    xy = np.zeros((40, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(40) * 5.0

    default = compute_kinematics(xy, fps=25.0)
    explicit = compute_kinematics(xy, fps=25.0, cfg=SAVGOL)

    np.testing.assert_array_equal(default.speed_px_s, explicit.speed_px_s)
