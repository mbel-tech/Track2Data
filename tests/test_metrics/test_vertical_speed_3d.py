"""IL-18, vertical speed: |vz| in cm/s of a fused (or native 3-D) session."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.core.models import KinematicsCfg
from track2data.metrics import get
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.individual import Speed3D, VerticalSpeed3D
from track2data.preprocess.kinematics import compute_kinematics

PX_PER_CM = 8.0
HEIGHT_CM = 200.0
FPS = 25.0
COLUMNS = [
    "session_id",
    "metric_id",
    "individual_id",
    "mean_vertical_speed_cm_s",
    "median_vertical_speed_cm_s",
    "max_vertical_speed_cm_s",
    "mean_vertical_speed_bl_s",
]
STATS = COLUMNS[3:]
FWD = {"kinematics": {"method": "forward_difference"}}


def _fused(pos_cm: np.ndarray, *, body_length_cm: float | None = None, kcfg=None):
    n_frames, n_animals = pos_cm.shape[:2]
    psess = _make_psess(_make_session(n_frames=n_frames, n_animals=n_animals))
    if body_length_cm is not None:
        psess.body_length_px = np.full(n_animals, body_length_cm * PX_PER_CM)
    psess.xy = pos_cm[..., :2] * PX_PER_CM
    psess.depth = pos_cm[..., 2] / HEIGHT_CM
    psess.px_per_cm = PX_PER_CM
    psess.depth_height_cm = HEIGHT_CM
    psess.kinematics = compute_kinematics(psess.xy, FPS, kcfg)
    return psess


def _ramp(n_frames: int, per_frame=(0.0, 0.0, 1.0), n_animals: int = 1) -> np.ndarray:
    t = np.arange(n_frames, dtype=float)[:, None, None]
    return np.broadcast_to(t * np.array(per_frame), (n_frames, n_animals, 3)).copy()


def _run(psess, cfg=None) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        return VerticalSpeed3D().compute(psess, cfg)


def test_it_is_registered_with_requires_depth_scale() -> None:
    cls = get("IL-18")
    assert cls is VerticalSpeed3D
    assert (cls.name, cls.label, cls.level) == (
        "vertical_speed_3d",
        "Vertical Speed (mean / median / max)",
        "individual",
    )
    assert cls.requires_identity is True
    assert cls.priority == "optional"
    assert cls.requires_depth_scale is True
    assert cls.uses_kinematics_cfg is True
    assert cls.window_safe is True
    assert cls.output_columns == COLUMNS


def test_a_constant_vertical_ramp_gives_the_ramp_speed() -> None:
    # 1 cm per frame at 25 fps = 25 cm/s.
    row = _run(_fused(_ramp(30), body_length_cm=5.0)).iloc[0]
    assert row["mean_vertical_speed_cm_s"] == pytest.approx(25.0)
    assert row["median_vertical_speed_cm_s"] == pytest.approx(25.0)
    assert row["max_vertical_speed_cm_s"] == pytest.approx(25.0)
    assert row["mean_vertical_speed_bl_s"] == pytest.approx(5.0)  # 25 cm/s / 5 cm


def test_a_dive_counts_like_a_climb() -> None:
    up = _run(_fused(_ramp(30, per_frame=(0, 0, 1.0)))).iloc[0]
    down = _run(_fused(_ramp(30, per_frame=(0, 0, -1.0)) + np.array([0, 0, 40.0]))).iloc[0]
    assert down["mean_vertical_speed_cm_s"] == pytest.approx(up["mean_vertical_speed_cm_s"])


def test_horizontal_motion_gives_zero() -> None:
    rng = np.random.default_rng(1)
    pos = np.cumsum(rng.normal(0, 1.0, (40, 2, 3)), axis=0)
    pos[..., 2] = 7.0  # constant depth
    df = _run(_fused(pos))
    assert df["mean_vertical_speed_cm_s"].to_numpy() == pytest.approx(0.0, abs=1e-9)
    assert df["max_vertical_speed_cm_s"].to_numpy() == pytest.approx(0.0, abs=1e-9)


def test_it_is_the_vertical_part_of_il17() -> None:
    # Pure vertical motion: IL-17's speed is |vz| exactly, so the two metrics agree.
    psess = _fused(_ramp(30))
    il18 = _run(psess).iloc[0]["mean_vertical_speed_cm_s"]
    il17 = Speed3D().compute(psess).iloc[0]["mean_speed_3d_cm_s"]
    assert il18 == pytest.approx(il17)


def test_it_uses_session_z_speed_when_present() -> None:
    psess = _fused(_ramp(20))
    psess.z_speed = np.full((20, 1), 3.0)
    assert _run(psess).iloc[0]["mean_vertical_speed_cm_s"] == pytest.approx(3.0)


def test_estimator_follows_the_kinematics_config() -> None:
    t = np.arange(20, dtype=float)
    pos = np.zeros((20, 1, 3))
    pos[:, 0, 2] = 0.1 * t**2
    row = _run(_fused(pos), FWD).iloc[0]
    steps = np.diff(pos[:, 0, 2]) * FPS  # the last frame is NaN and left out
    assert row["mean_vertical_speed_cm_s"] == pytest.approx(steps.mean())
    assert row["max_vertical_speed_cm_s"] == pytest.approx(steps.max())
    assert _run(_fused(pos)).iloc[0]["max_vertical_speed_cm_s"] != pytest.approx(
        row["max_vertical_speed_cm_s"]
    )
    kcfg = {"kinematics": KinematicsCfg(method="forward_difference")}
    assert _run(_fused(pos), kcfg).iloc[0]["mean_vertical_speed_cm_s"] == pytest.approx(
        steps.mean()
    )


def test_nan_depth_frames_are_excluded_not_counted_as_zero() -> None:
    psess = _fused(_ramp(30))
    psess.depth[10:13, 0] = np.nan
    row = _run(psess).iloc[0]
    assert row["mean_vertical_speed_cm_s"] == pytest.approx(25.0)
    assert row["median_vertical_speed_cm_s"] == pytest.approx(25.0)


def test_an_all_nan_animal_is_nan_and_others_unaffected() -> None:
    psess = _fused(np.concatenate([_ramp(20), _ramp(20)], axis=1))
    psess.depth[:, 1] = np.nan
    df = _run(psess)
    assert df.loc[1, STATS].isna().all()
    assert df.loc[0, "mean_vertical_speed_cm_s"] == pytest.approx(25.0)


def test_unknown_body_length_gives_nan_bl_only() -> None:
    row = _run(_fused(_ramp(20))).iloc[0]
    assert np.isnan(row["mean_vertical_speed_bl_s"])
    assert row["mean_vertical_speed_cm_s"] == pytest.approx(25.0)


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_it_is_unavailable_without_a_depth_scale(missing: str) -> None:
    psess = _fused(_ramp(20, n_animals=2))
    setattr(psess, missing, None)
    df = _run(psess)
    assert list(df.columns) == COLUMNS
    assert df["individual_id"].tolist() == [0, 1]
    assert df[STATS].isna().all().all()


def test_binned_values_match_the_windows_of_the_whole_session() -> None:
    psess = _fused(_ramp(100, per_frame=(0.6, 0.8, 1.0)))
    whole = _run(psess).loc[0, "mean_vertical_speed_cm_s"]
    windows = bin_windows(psess, 1.0)
    assert len(windows) == 4
    for w in windows:
        part = _run(slice_psess(psess, w.start_row, w.stop_row))
        assert part.loc[0, "mean_vertical_speed_cm_s"] == pytest.approx(whole)
        assert part.loc[0, "mean_vertical_speed_cm_s"] == pytest.approx(25.0)


def test_a_native_3d_session_uses_its_absolute_z() -> None:
    psess = _make_psess(_make_session(n_frames=30, n_animals=1))
    psess.px_per_cm = 1.0  # a native file is in the project unit
    psess.z = (np.arange(30, dtype=float) * 2.0)[:, None]  # 2 units per frame = 50 units/s
    psess.kinematics = compute_kinematics(psess.xy, FPS, None)
    assert _run(psess).iloc[0]["mean_vertical_speed_cm_s"] == pytest.approx(50.0)
