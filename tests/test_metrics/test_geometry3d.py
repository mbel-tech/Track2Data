"""3-D positions in cm of a fused session, and the depth-scale availability rule."""

from __future__ import annotations

import numpy as np
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.metrics import geometry3d
from track2data.metrics.availability import depth_scale_reason
from track2data.metrics.base import Metric


def _fused(*, x=80.0, y=40.0, depth=0.5, px_per_cm=8.0, height=20.0, n_animals=1):
    psess = _make_psess(_make_session(n_frames=3, n_animals=n_animals))
    psess.xy = np.tile(np.array([x, y]), (3, n_animals, 1)).astype(float)
    psess.depth = np.full((3, n_animals), depth, dtype=float)
    psess.px_per_cm = px_per_cm
    psess.depth_height_cm = height
    return psess


def test_positions_cm_converts_px_and_depth_fraction() -> None:
    pos = geometry3d.positions_cm(_fused())
    assert pos is not None
    assert pos.shape == (3, 1, 3)
    assert pos.dtype == np.float64
    np.testing.assert_allclose(pos[0, 0], (10.0, 5.0, 10.0))


@pytest.mark.parametrize("component", ["x", "y", "depth"])
def test_a_nan_component_makes_the_whole_position_nan(component: str) -> None:
    psess = _fused(n_animals=2)
    if component == "x":
        psess.xy[1, 0, 0] = np.nan
    elif component == "y":
        psess.xy[1, 0, 1] = np.nan
    else:
        psess.depth[1, 0] = np.nan
    pos = geometry3d.positions_cm(psess)
    assert pos is not None
    assert np.isnan(pos[1, 0]).all()
    assert np.isfinite(pos[1, 1]).all()
    assert np.isfinite(pos[0, 0]).all()


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_no_3d_positions_without_depth_scale_or_height(missing: str) -> None:
    psess = _fused()
    setattr(psess, missing, None)
    assert geometry3d.positions_cm(psess) is None


def test_body_length_cm_needs_body_length_and_scale() -> None:
    psess = _fused()
    assert np.isnan(geometry3d.body_length_cm(psess, 0))  # no body length known
    psess.body_length_px = np.array([16.0])
    assert psess.body_length_in_px() is not None
    assert geometry3d.body_length_cm(psess, 0) == pytest.approx(2.0)
    psess.px_per_cm = None
    assert np.isnan(geometry3d.body_length_cm(psess, 0))


class _Flagged(Metric):
    id = "IL-FLAG"
    requires_depth_scale = True


class _Plain(Metric):
    id = "IL-PLAIN"


def _reason(cls=_Flagged, **kw):
    args = {
        "dimension": "3d",
        "calibration_mode": "scalar",
        "has_depth": True,
        "px_per_cm": 8.0,
        "depth_height_cm": 20.0,
    }
    args.update(kw)
    return depth_scale_reason(cls, **args)


def test_depth_scale_reason_branches_in_order() -> None:
    assert _reason(dimension="2d", has_depth=False) == "needs a fused 3-D session"
    # 2-D wins over a bodylength calibration and a missing scale
    assert (
        _reason(dimension="2d", has_depth=False, calibration_mode="bodylength", px_per_cm=None)
        == "needs a fused 3-D session"
    )
    assert (
        _reason(calibration_mode="bodylength", px_per_cm=None)
        == "needs a cm scale for the top view (use scalar or session calibration)"
    )
    assert _reason(px_per_cm=None) == "needs a cm scale for the top view"
    assert _reason(depth_height_cm=None) == "needs a cm scale for the top view"
    assert _reason() is None
    assert _reason(calibration_mode="session") is None


def test_a_metric_without_the_flag_is_never_ruled_out() -> None:
    assert Metric.requires_depth_scale is False
    assert _reason(_Plain, dimension="2d", has_depth=False) is None
