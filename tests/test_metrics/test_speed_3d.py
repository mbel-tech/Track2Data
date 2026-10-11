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


# ── vertical speed from the whole series ─────────────────────────────────────


def _curved(n_frames: int = 100) -> np.ndarray:
    """A track with non-constant velocity in all three axes (bin edges differ when re-estimated)."""
    t = np.arange(n_frames, dtype=float)
    pos = np.zeros((n_frames, 1, 3))
    pos[:, 0, 0] = 0.02 * t**2
    pos[:, 0, 1] = 3.0 * np.sin(t / 7.0)
    pos[:, 0, 2] = 0.05 * t**2 + 4.0 * np.cos(t / 5.0)
    return pos


@pytest.mark.parametrize("kcfg", [KinematicsCfg(), KinematicsCfg(method="forward_difference")])
def test_vertical_speed_helper_matches_the_estimator(kcfg) -> None:
    from track2data.metrics.geometry3d import vertical_speed

    pos = _curved(40)
    psess = _fused(pos)
    vz = vertical_speed(psess, kcfg)
    assert vz is not None
    z = psess.depth * HEIGHT_CM  # what the session carries (depth is a fraction)
    expected = compute_kinematics(
        np.stack([z, np.where(np.isnan(z), np.nan, 0.0)], axis=-1), FPS, kcfg
    ).speed_px_s
    np.testing.assert_array_equal(vz, expected)
    vh = psess.kinematics.speed_px_s / PX_PER_CM
    row = _run(psess, {"kinematics": kcfg.model_dump()}).iloc[0]
    speed = np.sqrt(vh[:, 0] ** 2 + vz[:, 0] ** 2)
    assert row["mean_speed_3d_cm_s"] == np.nanmean(speed)


def test_vertical_speed_is_none_without_z_or_scale() -> None:
    from track2data.metrics.geometry3d import vertical_speed

    psess = _fused(_curved(20))
    psess.px_per_cm = None
    assert vertical_speed(psess, KinematicsCfg()) is None
    psess = _fused(_curved(20))
    psess.depth = None
    assert vertical_speed(psess, KinematicsCfg()) is None


def test_binned_iL17_bins_are_slices_of_the_whole_series() -> None:  # noqa: N802
    from tests.test_api import _make_manifest
    from track2data.api import Engine
    from track2data.core.models import ProjectMode

    pos = _curved(300)
    psess = _fused(pos)
    manifest = _make_manifest()
    manifest.mode = ProjectMode(dimension="3d", layout="two_videos")
    manifest.metrics.individual = ["IL-17"]
    manifest.metrics.group = []
    manifest.metrics.zone = []
    manifest.metrics.diagnostic = []
    manifest.metrics.timepoint_minutes = 0.05  # 3 s = 75 frames
    out = Engine(manifest).compute_metrics(psess, identity_free=False)["IL-17"]

    from track2data.metrics.geometry3d import vertical_speed

    vz = vertical_speed(psess, manifest.preprocess.kinematics)
    assert vz is not None
    speed = np.sqrt((psess.kinematics.speed_px_s / PX_PER_CM) ** 2 + vz**2)[:, 0]
    windows = bin_windows(psess, 3.0)
    assert len(windows) >= 2
    assert len(out) == len(windows)
    differs = False
    for (_, row), w in zip(out.iterrows(), windows, strict=True):
        seg = speed[w.start_row : w.stop_row]
        assert row["mean_speed_3d_cm_s"] == pytest.approx(np.nanmean(seg), abs=1e-9)
        old = _run(slice_psess(psess, w.start_row, w.stop_row))
        old_val = old.loc[0, "mean_speed_3d_cm_s"]
        differs |= abs(old_val - np.nanmean(seg)) > 1e-9
    assert differs  # the per-bin re-estimate used to disagree on this track


def test_speed3d_without_precomputed_z_speed_still_works() -> None:
    psess = _fused(_curved(30))
    assert psess.z_speed is None
    row = _run(psess).iloc[0]
    assert np.isfinite(row["mean_speed_3d_cm_s"])


def test_precomputed_z_speed_is_used_when_present() -> None:
    psess = _fused(_ramp(30))
    psess.z_speed = np.full((30, 1), 100.0)
    row = _run(psess).iloc[0]
    expected = np.sqrt((psess.kinematics.speed_px_s[:, 0] / PX_PER_CM) ** 2 + 100.0**2)
    assert row["max_speed_3d_cm_s"] == np.nanmax(expected)


def _seeded_fused(kcfg: KinematicsCfg):
    """Seeded two-animal fused track with an x/y gap (finite depth) and a depth gap."""
    rng = np.random.default_rng(20261011)
    n = 120
    t = np.arange(n, dtype=float)
    pos = np.zeros((n, 2, 3))
    for k in range(2):
        pos[:, k, 0] = np.cumsum(rng.normal(0.4, 0.3, n))
        pos[:, k, 1] = np.cumsum(rng.normal(0.0, 0.3, n))
        pos[:, k, 2] = 60 + 20 * np.sin(t / 9.0 + k) + np.cumsum(rng.normal(0, 0.4, n))
    pos[30:34, 0, :2] = np.nan
    pos[70:73, 1, 2] = np.nan
    return _fused(pos, kcfg=kcfg)


# (mean, median, max) per animal produced by the code before IL-17 used a precomputed series
# (5799178~1), on _seeded_fused.
_OLD_IL17 = {
    "savgol": [
        (40.02410495798584, 43.76816657992043, 64.70894210370179),
        (34.743342910391156, 36.033716279115204, 61.76882120826629),
    ],
    "forward_difference": [
        (41.636852817038736, 42.63615359292312, 77.09759102340973),
        (36.598683220214184, 35.622211341832205, 73.79758399916882),
    ],
}


@pytest.mark.parametrize("method", ["savgol", "forward_difference"])
def test_whole_session_iL17_is_unchanged(method: str) -> None:  # noqa: N802
    from tests.test_api import _make_manifest
    from track2data.api import Engine
    from track2data.core.models import ProjectMode

    kcfg = KinematicsCfg(method=method)  # type: ignore[arg-type]
    psess = _seeded_fused(kcfg)
    manifest = _make_manifest()
    manifest.mode = ProjectMode(dimension="3d", layout="two_videos")
    manifest.preprocess.kinematics = kcfg
    manifest.metrics.individual = ["IL-17"]
    manifest.metrics.group = []
    manifest.metrics.zone = []
    manifest.metrics.diagnostic = []
    cols = ["mean_speed_3d_cm_s", "median_speed_3d_cm_s", "max_speed_3d_cm_s"]
    engine = Engine(manifest).compute_metrics(psess, identity_free=False)["IL-17"]
    direct = _run(psess, {"kinematics": kcfg.model_dump()})
    for df in (engine, direct):
        np.testing.assert_array_equal(df[cols].to_numpy(), np.array(_OLD_IL17[method]))


def _engine_for(individual: list[str]):
    from tests.test_api import _make_manifest
    from track2data.api import Engine
    from track2data.core.models import ProjectMode

    manifest = _make_manifest()
    manifest.mode = ProjectMode(dimension="3d", layout="two_videos")
    manifest.metrics.individual = individual
    manifest.metrics.group = []
    manifest.metrics.zone = []
    manifest.metrics.diagnostic = []
    return Engine(manifest)


def test_z_speed_helper_returns_the_same_object_without_a_kinematics_metric() -> None:
    psess = _seeded_fused(KinematicsCfg())
    assert _engine_for(["IL-2"])._with_whole_session_z_speed(psess, set()) is psess


def test_z_speed_helper_returns_the_same_object_when_il17_is_skipped() -> None:
    psess = _seeded_fused(KinematicsCfg())
    assert _engine_for(["IL-17"])._with_whole_session_z_speed(psess, {"IL-17"}) is psess


def test_z_speed_helper_sets_the_series_on_a_copy() -> None:
    psess = _seeded_fused(KinematicsCfg())
    engine = _engine_for(["IL-17"])
    out = engine._with_whole_session_z_speed(psess, set())
    assert out is not psess
    assert out.z_speed is not None and out.z_speed.shape == (120, 2)
    assert psess.z_speed is None  # the caller's session is not modified
    engine.compute_metrics(psess, identity_free=False)
    assert psess.z_speed is None
