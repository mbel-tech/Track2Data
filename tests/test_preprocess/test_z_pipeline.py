"""The vertical axis of a native 3-D file goes through the same preprocessing as xy."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from track2data.core.models import (
    GapFillCfg,
    IdSwitchCfg,
    JumpCfg,
    PreprocessConfig,
    Session,
    SmoothCfg,
    VideoInfo,
)
from track2data.preprocess.pipeline import run


def _session(xy: np.ndarray, z: np.ndarray, intervals=None) -> Session:
    return Session(
        velocity_threshold_px_frame=20.0,
        session_id="s",
        folder=Path("/tmp/s"),
        reader="test",
        video=VideoInfo(fps=30.0, n_frames=len(xy), width_px=0, height_px=0),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        raw_z=z.reshape(len(z), 1),
        has_pixel_frame=False,
        coordinate_unit="cm",
        tracking_intervals=intervals,
    )


def _cfg(*, gap=False, jump=False, smooth=None, across=False, max_gap=30) -> PreprocessConfig:
    return PreprocessConfig(
        gap_fill=GapFillCfg(
            enabled=gap, max_gap_frames=max_gap, across_tracking_intervals=across
        ),
        jump=JumpCfg(
            enabled=jump, method="idtracker_velocity_threshold", replacement="linear_interp"
        ),
        identity_switch=IdSwitchCfg(enabled=False),
        smoothing=smooth or SmoothCfg(enabled=False),
    )


def _line(n: int = 60):
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = np.arange(n, dtype=float)
    z = np.arange(n, dtype=float) * 0.5
    return xy, z


def _path(z: np.ndarray) -> float:
    return float(np.nansum(np.abs(np.diff(z))))


def test_z_is_smoothed_with_the_xy_settings() -> None:
    rng = np.random.default_rng(0)
    xy, _ = _line(300)
    z = np.full(300, 5.0) + rng.normal(0.0, 0.2, 300)
    cfg = _cfg(smooth=SmoothCfg(enabled=True, method="savgol", window=25, polyorder=2))

    psess = run(_session(xy, z), cfg)

    assert psess.z is not None
    # a flat true track: smoothing must remove most of the noise path, not leave it raw
    assert _path(psess.z[:, 0]) < 0.25 * _path(z)


def test_z_is_unchanged_when_smoothing_and_gap_fill_are_off() -> None:
    xy, z = _line()
    z = z + np.random.default_rng(1).normal(0, 0.1, len(z))
    psess = run(_session(xy, z), _cfg())
    assert psess.z is not None
    np.testing.assert_array_equal(psess.z[:, 0], z)


def test_short_z_gap_is_filled_like_xy() -> None:
    xy, z = _line()
    xy[10:15] = np.nan
    z[10:15] = np.nan
    psess = run(_session(xy, z), _cfg(gap=True))
    assert psess.z is not None
    np.testing.assert_allclose(psess.z[10:15, 0], np.arange(10, 15) * 0.5)


def test_z_gap_longer_than_max_stays_missing() -> None:
    xy, z = _line()
    xy[10:20] = np.nan
    z[10:20] = np.nan
    psess = run(_session(xy, z), _cfg(gap=True, max_gap=5))
    assert psess.z is not None
    assert np.isnan(psess.z[10:20, 0]).all()


def test_a_z_gap_xy_does_not_have_is_not_invented_beyond_the_anchors() -> None:
    """The leading edge has no left anchor, so it stays missing exactly as xy would."""
    xy, z = _line()
    z[:3] = np.nan
    psess = run(_session(xy, z), _cfg(gap=True))
    assert psess.z is not None
    assert np.isnan(psess.z[:3, 0]).all()


def test_jump_replaced_z_is_refilled_not_kept_raw() -> None:
    xy, z = _line()
    xy[30, 0, 0] += 500.0  # triangulation glitch in the horizontal plane
    z[30] += 40.0  # and in the vertical one
    cfg = _cfg(gap=True, jump=True)

    psess = run(_session(xy, z), cfg)

    assert psess.jump_replaced is not None and psess.jump_replaced[30, 0]
    assert psess.z is not None
    np.testing.assert_allclose(psess.z[30, 0], 0.5 * (z[29] + z[31]))


def test_jump_replaced_z_stays_missing_when_gap_fill_is_off() -> None:
    xy, z = _line()
    xy[30, 0, 0] += 500.0
    psess = run(_session(xy, z), _cfg(jump=True))
    assert psess.z is not None
    assert np.isnan(psess.z[30, 0])


def test_z_is_bridged_across_a_tracking_interval_gap_like_xy() -> None:
    n = 20
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = np.arange(n, dtype=float)
    z = np.arange(n, dtype=float) + 100.0
    session = _session(xy, z, intervals=[(0, 10), (12, 22)])

    psess = run(session, _cfg(gap=True, across=True), bridge_allowed=True)

    assert psess.z is not None and psess.tracked_mask is not None
    assert psess.separator_mask is not None
    bridged = ~psess.tracked_mask & ~psess.separator_mask
    assert bridged.any()
    # anchors: z=109 at video frame 9, z=110 at frame 12; video frames 10 and 11 lie on the line
    np.testing.assert_allclose(psess.z[bridged, 0], [109 + 1 / 3, 109 + 2 / 3])


def test_separator_rows_stay_missing_in_z() -> None:
    xy, z = _line(22)
    session = _session(xy, z, intervals=[(0, 10), (1000, 1012)])
    psess = run(session, _cfg(gap=True, smooth=SmoothCfg(enabled=True)))
    assert psess.separator_mask is not None and psess.separator_mask.any()
    assert psess.z is not None
    assert np.isnan(psess.z[psess.separator_mask]).all()


def _noisy_helix(n: int = 600, sigma: float = 0.2):
    """p7 of the 3-D review: a helix with 2 mm (0.2 cm) noise on every axis, 30 fps."""
    rng = np.random.default_rng(3)
    t = np.arange(n) / 30.0
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = 10 * np.cos(2 * np.pi * 0.2 * t) + rng.normal(0, sigma, n)
    xy[:, 0, 1] = 10 * np.sin(2 * np.pi * 0.2 * t) + rng.normal(0, sigma, n)
    true_z = 5 + 2 * np.sin(2 * np.pi * 0.1 * t)
    return xy, true_z + rng.normal(0, sigma, n), true_z


def test_vertical_path_falls_with_the_smoothing_window_toward_the_truth() -> None:
    """Before: the vertical path was 129 cm at every window against a true 16 cm."""
    xy, z, true_z = _noisy_helix()
    paths = []
    for window in (5, 15, 41):
        cfg = _cfg(smooth=SmoothCfg(enabled=True, method="savgol", window=window, polyorder=2))
        psess = run(_session(xy, z), cfg)
        assert psess.z is not None
        paths.append(_path(psess.z[:, 0]))

    assert paths[0] > paths[1] > paths[2]
    assert paths[2] < 0.25 * _path(z)
    assert paths[2] < 1.5 * _path(true_z)


def test_a_sensitivity_grid_point_changes_z() -> None:
    from track2data.core.models import PreprocessConfig as Cfg
    from track2data.sensitivity import GridPoint, _config_for

    xy, z, _ = _noisy_helix()
    session = _session(xy, z)
    narrow = run(session, _config_for(Cfg(), GridPoint(smoothing_window=5, max_gap_frames=10)))
    wide = run(session, _config_for(Cfg(), GridPoint(smoothing_window=41, max_gap_frames=10)))
    assert narrow.z is not None and wide.z is not None
    assert _path(wide.z[:, 0]) < _path(narrow.z[:, 0])
