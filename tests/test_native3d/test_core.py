"""Core of native 3-D files: absolute z, the water column, the pipeline layout, geometry."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from tests.test_api import _make_psess, _make_session
from track2data.calibration.water_column import apply_water_column
from track2data.core.models import (
    CalibrationConfig,
    GapFillCfg,
    PreprocessConfig,
    Session,
    VideoInfo,
    WaterColumn,
)
from track2data.metrics import geometry3d
from track2data.metrics.binning import slice_psess
from track2data.preprocess.pipeline import run


def _psess_with_z(z_values):
    z = np.asarray(z_values, dtype=float).reshape(-1, 1)
    psess = _make_psess(_make_session(n_frames=len(z), n_animals=1))
    psess.z = z
    return psess


def _session_z(intervals, n: int = 20) -> Session:
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = np.arange(n)
    raw_z = (np.arange(n, dtype=float) + 100.0).reshape(n, 1)
    return Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=5000, width_px=0, height_px=0),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        raw_z=raw_z,
        has_pixel_frame=False,
        coordinate_unit="cm",
        tracking_intervals=intervals,
    )


def test_water_column_validation() -> None:
    for bad in [(1.0, 1.0), (float("nan"), 1.0), (0.0, float("inf")), (float("-inf"), 2.0)]:
        with pytest.raises(ValidationError):
            WaterColumn(surface_z=bad[0], floor_z=bad[1])
    assert WaterColumn(surface_z=20.0, floor_z=0.0).floor_z == 0.0
    assert CalibrationConfig().water_column is None


def test_apply_water_column_exact() -> None:
    out = apply_water_column(
        _psess_with_z([0, 5, 20, 25, -1]), WaterColumn(surface_z=0.0, floor_z=20.0)
    )
    assert out.depth is not None and out.depth_outside_mask is not None
    np.testing.assert_allclose(out.depth[:, 0], [0, 0.25, 1, np.nan, np.nan])
    assert out.depth_height_cm == 20.0
    assert out.depth_outside_mask[:, 0].tolist() == [False, False, False, True, True]
    assert out.depth_outside is not None and out.depth_outside.tolist() == [2]


def test_apply_water_column_reversed() -> None:
    out = apply_water_column(
        _psess_with_z([20, 15, 0]), WaterColumn(surface_z=20.0, floor_z=0.0)
    )
    assert out.depth is not None
    np.testing.assert_allclose(out.depth[:, 0], [0, 0.25, 1])
    assert out.depth_height_cm == 20.0


def test_water_column_is_on_the_files_axis_whatever_the_flip() -> None:
    """The same physical fish (3 below a surface at 0, floor at 20 down) written with z up and no
    flip, or with z down and flip, gets the same depth for the same entered column."""
    up = _psess_with_z([-3.0, -10.0])
    up.session.raw_attrs = {"native_3d": {"flip": False}}
    down = _psess_with_z([3.0 * -1, -10.0])  # the reader negated the file's +3, +10
    down.session.raw_attrs = {"native_3d": {"flip": True}}
    # file axis for the flipped file: surface 0, floor +20 (down), values +3 and +10
    flipped = apply_water_column(down, WaterColumn(surface_z=0.0, floor_z=20.0))
    plain = apply_water_column(up, WaterColumn(surface_z=0.0, floor_z=-20.0))
    assert flipped.depth is not None and plain.depth is not None
    np.testing.assert_allclose(flipped.depth[:, 0], [0.15, 0.5])
    np.testing.assert_allclose(plain.depth[:, 0], flipped.depth[:, 0])


def test_apply_water_column_without_z_is_unchanged() -> None:
    psess = _make_psess(_make_session(n_frames=3, n_animals=1))
    assert apply_water_column(psess, WaterColumn(surface_z=0, floor_z=1)) is psess


def test_pipeline_lays_out_z_with_xy() -> None:
    gap = _session_z([(0, 10), (1000, 1010)])
    psess = run(gap, PreprocessConfig())
    assert psess.z is not None
    assert psess.z.shape == psess.xy.shape[:2]
    assert psess.separator_mask is not None and psess.tracked_mask is not None
    assert psess.separator_mask.any()
    assert np.isnan(psess.z[psess.separator_mask]).all()
    assert gap.raw_z is not None
    np.testing.assert_array_equal(psess.z[psess.tracked_mask], gap.raw_z)

    whole = _session_z(None)
    plain = run(whole, PreprocessConfig())
    assert whole.raw_z is not None
    np.testing.assert_array_equal(plain.z, whole.raw_z)
    assert plain.z is not whole.raw_z


def test_slice_psess_slices_z() -> None:
    psess = _psess_with_z(np.arange(10.0))
    assert psess.z is not None
    sliced = slice_psess(psess, 2, 5)
    assert sliced.z is not None
    np.testing.assert_array_equal(sliced.z[:, 0], [2.0, 3.0, 4.0])


def _native(z_value, **kw):
    psess = _make_psess(_make_session(n_frames=3, n_animals=1))
    psess.xy = np.tile(np.array([80.0, 40.0]), (3, 1, 1))
    psess.px_per_cm = 8.0
    if z_value is not None:
        psess.z = np.full((3, 1), z_value, dtype=float)
    for k, v in kw.items():
        setattr(psess, k, v)
    return psess


def test_positions_cm_uses_z_without_depth() -> None:
    pos = geometry3d.positions_cm(_native(12.0))
    assert pos is not None
    np.testing.assert_allclose(pos[0, 0], (10.0, 5.0, 12.0))


def test_positions_cm_none_without_z_or_depth() -> None:
    assert geometry3d.positions_cm(_native(None)) is None
    assert geometry3d.positions_cm(_native(12.0, px_per_cm=None)) is None


def test_pixel_sessions_unchanged() -> None:
    session = _make_session(n_frames=4, n_animals=1)
    assert session.has_pixel_frame is True
    assert session.raw_z is None and session.coordinate_unit is None
    psess = run(session, PreprocessConfig())
    assert psess.z is None


def test_engine_derives_depth_after_calibration() -> None:
    from tests.test_api import _make_manifest
    from track2data.api import Engine

    manifest = _make_manifest()
    manifest.calibration = CalibrationConfig(
        mode="scalar", px_per_cm=8.0, water_column=WaterColumn(surface_z=0.0, floor_z=20.0)
    )
    psess = Engine(manifest).apply_calibration_and_zones(_psess_with_z([0, 10, 30]))
    assert psess.depth is not None
    np.testing.assert_allclose(psess.depth[:, 0], [0, 0.5, np.nan])
    assert psess.depth_height_cm == 20.0


def test_apply_water_column_non_finite_z_is_missing_not_outside() -> None:
    out = apply_water_column(
        _psess_with_z([np.nan, np.inf, -np.inf, 3.0]), WaterColumn(surface_z=0.0, floor_z=10.0)
    )
    assert out.depth is not None and out.depth_outside_mask is not None
    np.testing.assert_allclose(out.depth[:, 0], [np.nan, np.nan, np.nan, 0.3])
    assert not out.depth_outside_mask.any()
    assert out.depth_outside is not None and out.depth_outside.tolist() == [0]


def test_z_through_a_bridged_gap_is_nan_not_interpolated() -> None:
    session = _session_z([(0, 10), (12, 22)])
    cfg = PreprocessConfig(gap_fill=GapFillCfg(across_tracking_intervals=True))
    psess = run(session, cfg, bridge_allowed=True)
    assert psess.z is not None and psess.tracked_mask is not None
    assert psess.separator_mask is not None
    bridged = ~psess.tracked_mask & ~psess.separator_mask
    assert bridged.any()
    assert np.isnan(psess.z[bridged]).all()
    assert np.isfinite(psess.xy[bridged]).any()


def test_keep_animals_filters_raw_z() -> None:
    from track2data.views.panels import keep_animals

    s = _session_z(None, n=5)
    s = s.model_copy(
        update={
            "n_animals": 3,
            "raw_xy": np.zeros((5, 3, 2)),
            "raw_z": np.arange(15.0).reshape(5, 3),
        }
    )
    out = keep_animals(s, [2, 0])
    assert out.raw_z is not None
    np.testing.assert_array_equal(out.raw_z, s.raw_z[:, [2, 0]])
    bad = s.model_copy(update={"raw_z": np.zeros((5, 2))})
    assert keep_animals(bad, [0]).raw_z is None


def test_fuse_refuses_native_3d_sessions() -> None:
    from tests.test_fusion.builders import make_pair
    from track2data.fusion.fuse import FusionError, fuse

    for which in ("top", "side"):
        top, side, pair = make_pair()
        target = top if which == "top" else side
        target.session = target.session.model_copy(update={"has_pixel_frame": False})
        with pytest.raises(FusionError, match="native 3-D sessions have no views to fuse"):
            fuse(top, side, pair, same_video=False)
