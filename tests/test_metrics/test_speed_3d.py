"""IL-17, 3-D speed: sqrt(vh^2 + vz^2) in cm/s of a fused session."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.core.models import KinematicsCfg
from track2data.metrics import get
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.individual import Speed, Speed3D
from track2data.preprocess.kinematics import compute_kinematics

PX_PER_CM = 8.0
HEIGHT_CM = 200.0
FPS = 25.0
COLUMNS = [
    "session_id", "metric_id", "individual_id",
    "mean_speed_3d_cm_s", "median_speed_3d_cm_s", "max_speed_3d_cm_s", "mean_speed_3d_bl_s",
]
FWD = {"kinematics": {"method": "forward_difference"}}


def _fused(pos_cm: np.ndarray, *, body_length_cm: float | None = None, kcfg=None):
    """A fused psess following *pos_cm* ``(n_frames, n_animals, 3)``; kinematics from *kcfg*."""
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
        return Speed3D().compute(psess, cfg)


def test_is_registered_with_the_agreed_identity() -> None:
    cls = get("IL-17")
    assert cls is Speed3D
    assert (cls.name, cls.label, cls.level) == (
        "speed_3d", "3-D Speed (mean / median / max)", "individual"
    )
    assert cls.requires_identity is True
    assert cls.priority == "optional"
    assert cls.requires_depth_scale is True
    assert cls.window_safe is True
    assert cls.output_columns == COLUMNS


def test_pure_vertical_motion_is_the_estimator_speed_of_z() -> None:
    # 1 cm per frame at 25 fps = 25 cm/s, from the same estimator applied to Z directly.
    pos = _ramp(30)
    row = _run(_fused(pos, body_length_cm=5.0)).iloc[0]
    z = np.stack([pos[:, :, 2], np.zeros_like(pos[:, :, 2])], axis=-1)
    expected = compute_kinematics(z, FPS).speed_px_s[:, 0]
    assert row["mean_speed_3d_cm_s"] == pytest.approx(expected.mean())
    assert row["mean_speed_3d_cm_s"] == pytest.approx(25.0)
    assert row["median_speed_3d_cm_s"] == pytest.approx(25.0)
    assert row["max_speed_3d_cm_s"] == pytest.approx(25.0)
    assert row["mean_speed_3d_bl_s"] == pytest.approx(5.0)  # 25 cm/s / 5 cm


def test_pure_horizontal_motion_equals_il2_in_cm_s_exactly() -> None:
    rng = np.random.default_rng(1)
    pos = np.cumsum(rng.normal(0, 1.0, (40, 2, 3)), axis=0)
    pos[..., 2] = 7.0  # constant depth: vz is exactly 0
    psess = _fused(pos)
    d3 = _run(psess).set_index("individual_id")["mean_speed_3d_cm_s"]
    d2 = Speed().compute(psess).set_index("individual_id")["mean_speed_cm_s"]
    assert d3.to_numpy() == pytest.approx(d2.to_numpy(), rel=1e-12, abs=1e-12)


def test_diagonal_motion_is_sqrt_of_horizontal_squared_plus_vertical_squared() -> None:
    # (0.6, 0.8) cm/frame horizontal = 1 cm/frame = 25 cm/s; 1 cm/frame vertical = 25 cm/s.
    pos = _ramp(30, per_frame=(0.6, 0.8, 1.0))
    row = _run(_fused(pos)).iloc[0]
    assert row["mean_speed_3d_cm_s"] == pytest.approx(np.hypot(25.0, 25.0))
    assert row["max_speed_3d_cm_s"] == pytest.approx(np.hypot(25.0, 25.0))


@pytest.mark.parametrize("cfg", [None, FWD])
def test_at_least_il2_over_frames_with_finite_vertical_speed(cfg) -> None:
    # Only over frames where vz is finite: the forward difference leaves the last frame NaN.
    rng = np.random.default_rng(7)
    pos = np.cumsum(rng.normal(0, 2.0, (60, 3, 3)), axis=0)
    kcfg = KinematicsCfg(**cfg["kinematics"]) if cfg else None
    psess = _fused(pos, kcfg=kcfg)
    d3 = _run(psess, cfg).set_index("individual_id")["mean_speed_3d_cm_s"]
    z = np.stack([pos[:, :, 2], np.zeros_like(pos[:, :, 2])], axis=-1)
    vz = compute_kinematics(z, FPS, kcfg).speed_px_s
    vh = psess.kinematics.speed_px_s / PX_PER_CM
    for k in range(3):
        ok = np.isfinite(vz[:, k]) & np.isfinite(vh[:, k])
        assert ok.sum() >= 50
        assert d3[k] >= vh[ok, k].mean() - 1e-9
        assert d3[k] > vh[ok, k].mean()


def test_estimator_follows_the_kinematics_config() -> None:
    # Quadratic depth: the forward difference and the SG derivative disagree.
    t = np.arange(20, dtype=float)
    pos = np.zeros((20, 1, 3))
    pos[:, 0, 2] = 0.1 * t ** 2
    fwd = KinematicsCfg(method="forward_difference")
    psess = _fused(pos, kcfg=fwd)
    row = _run(psess, FWD).iloc[0]
    # forward difference: (z[t+1]-z[t]) * fps for t < 19, frame 19 excluded (NaN)
    steps = np.diff(pos[:, 0, 2]) * FPS
    assert row["mean_speed_3d_cm_s"] == pytest.approx(steps.mean())
    assert row["max_speed_3d_cm_s"] == pytest.approx(steps.max())
    default = _run(_fused(pos)).iloc[0]
    assert default["max_speed_3d_cm_s"] != pytest.approx(row["max_speed_3d_cm_s"])


def test_cfg_accepts_a_kinematics_model_too() -> None:
    pos = _ramp(20)
    a = _run(_fused(pos), {"kinematics": KinematicsCfg(method="forward_difference")})
    b = _run(_fused(pos), FWD)
    assert a.loc[0, "mean_speed_3d_cm_s"] == pytest.approx(b.loc[0, "mean_speed_3d_cm_s"])


def test_nan_depth_frames_are_excluded() -> None:
    pos = _ramp(30)
    psess = _fused(pos)
    psess.depth[10:13, 0] = np.nan
    row = _run(psess).iloc[0]
    assert np.isfinite(row["mean_speed_3d_cm_s"])
    assert row["mean_speed_3d_cm_s"] == pytest.approx(25.0)
    # Excluded frames do not become zeros: the mean would drop below 25 otherwise.
    assert row["median_speed_3d_cm_s"] == pytest.approx(25.0)


def test_all_nan_animal_is_nan_without_warning_and_others_unaffected() -> None:
    pos = np.concatenate([_ramp(20), _ramp(20)], axis=1)
    psess = _fused(pos)
    psess.depth[:, 1] = np.nan
    df = _run(psess)
    assert df.loc[1, ["mean_speed_3d_cm_s", "median_speed_3d_cm_s",
                      "max_speed_3d_cm_s", "mean_speed_3d_bl_s"]].isna().all()
    assert df.loc[0, "mean_speed_3d_cm_s"] == pytest.approx(25.0)


def test_unknown_body_length_gives_nan_bl_only() -> None:
    row = _run(_fused(_ramp(20))).iloc[0]
    assert np.isnan(row["mean_speed_3d_bl_s"])
    assert row["mean_speed_3d_cm_s"] == pytest.approx(25.0)


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_session_without_depth_or_scale_gives_nan_columns(missing: str) -> None:
    psess = _fused(_ramp(20, n_animals=2))
    setattr(psess, missing, None)
    df = _run(psess)
    assert list(df.columns) == COLUMNS
    assert len(df) == 2
    assert df.drop(columns=["session_id", "metric_id", "individual_id"]).isna().all().all()
    assert df["individual_id"].tolist() == [0, 1]


def test_binned_values_match_the_windows_of_the_whole_session() -> None:
    # Constant 3-D velocity: every bin has the same speed as the whole session, edges included
    # (the SG fit is exact on a line).
    pos = _ramp(100, per_frame=(0.6, 0.8, 1.0))
    psess = _fused(pos)
    whole = _run(psess).loc[0, "mean_speed_3d_cm_s"]
    windows = bin_windows(psess, 1.0)
    assert len(windows) == 4
    for w in windows:
        part = _run(slice_psess(psess, w.start_row, w.stop_row))
        assert part.loc[0, "mean_speed_3d_cm_s"] == pytest.approx(whole)
        assert part.loc[0, "mean_speed_3d_cm_s"] == pytest.approx(np.hypot(25.0, 25.0))


def test_engine_hands_the_pipeline_kinematics_config_to_the_metric() -> None:
    from tests.test_api import _make_manifest
    from track2data.api import Engine

    manifest = _make_manifest()
    manifest.preprocess.kinematics = KinematicsCfg(method="forward_difference", window=7)
    cfg = Engine(manifest)._effective_cfg(Speed3D, _fused(_ramp(10)))
    assert cfg["kinematics"]["method"] == "forward_difference"
    assert cfg["kinematics"]["window"] == 7
    assert "kinematics" not in Engine(manifest)._effective_cfg(Speed, _fused(_ramp(10)))


def _engine_vz(method: str) -> float:
    from tests.test_api import _make_manifest
    from track2data.api import Engine
    from track2data.core.models import ProjectMode

    manifest = _make_manifest()
    manifest.mode = ProjectMode(dimension="3d", layout="two_videos")
    manifest.preprocess.kinematics = KinematicsCfg(method=method)  # type: ignore[arg-type]
    manifest.metrics.individual = ["IL-17"]
    manifest.metrics.group = []
    manifest.metrics.zone = []
    manifest.metrics.diagnostic = []
    z = (np.arange(20, dtype=float) ** 2) * 0.1  # cm, quadratic: estimators disagree
    pos = np.zeros((20, 1, 3))
    pos[..., 2] = z[:, None]
    psess = _fused(pos)
    out = Engine(manifest).compute_metrics(psess, identity_free=False)
    return float(out["IL-17"].loc[0, "max_speed_3d_cm_s"])


def test_kinematics_config_reaches_the_metric_through_compute_metrics() -> None:
    fwd = _engine_vz("forward_difference")
    sg = _engine_vz("savgol")
    z = (np.arange(20, dtype=float) ** 2) * 0.1
    # forward difference: (z[t+1] - z[t]) * fps, last frame NaN -> max at t = 18
    assert fwd == pytest.approx((z[19] - z[18]) * FPS)
    assert sg != pytest.approx(fwd)
