"""IL-16, 3-D path length: the length of the (X, Y, Z) track of a fused session, in cm."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.metrics import get
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.individual import PathLength, PathLength3D

PX_PER_CM = 8.0
HEIGHT_CM = 200.0
COLUMNS = [
    "session_id", "metric_id", "individual_id",
    "path_length_3d_cm", "path_length_3d_bl", "n_valid_steps",
]


def _fused(pos_cm: np.ndarray, *, body_length_cm: float | None = None):
    """A fused psess whose animals follow *pos_cm* ``(n_frames, n_animals, 3)`` (X, Y, Z in cm)."""
    n_frames, n_animals = pos_cm.shape[:2]
    psess = _make_psess(_make_session(n_frames=n_frames, n_animals=n_animals))
    if body_length_cm is not None:
        psess.body_length_px = np.full(n_animals, body_length_cm * PX_PER_CM)
    psess.xy = pos_cm[..., :2] * PX_PER_CM
    psess.depth = pos_cm[..., 2] / HEIGHT_CM
    psess.px_per_cm = PX_PER_CM
    psess.depth_height_cm = HEIGHT_CM
    return psess


def _ramp(n_frames: int, step=(3.0, 4.0, 12.0), n_animals: int = 1) -> np.ndarray:
    t = np.arange(n_frames, dtype=float)[:, None, None]
    return np.broadcast_to(t * np.array(step), (n_frames, n_animals, 3)).copy()


def _run(psess) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        return PathLength3D().compute(psess)


def test_is_registered_with_the_agreed_identity() -> None:
    cls = get("IL-16")
    assert cls is PathLength3D
    assert (cls.name, cls.label, cls.level) == (
        "path_length_3d", "3-D Distance Travelled", "individual"
    )
    assert cls.requires_identity is True
    assert cls.priority == "optional"
    assert cls.requires_depth_scale is True
    assert cls.window_safe is True
    assert cls.output_columns == COLUMNS


def test_known_3_4_12_track_is_13_cm_per_step() -> None:
    # 11 positions give 10 steps of sqrt(3^2 + 4^2 + 12^2) = 13 cm: 10 * 13 = 130 cm.
    df = _run(_fused(_ramp(11), body_length_cm=2.0))
    row = df.iloc[0]
    assert row["path_length_3d_cm"] == pytest.approx(130.0)
    assert row["path_length_3d_bl"] == pytest.approx(65.0)  # 130 cm / 2 cm
    assert row["n_valid_steps"] == 10


def test_ten_positions_have_nine_steps() -> None:
    # 10 positions -> 10 - 1 = 9 steps -> 9 * 13 = 117 cm.
    row = _run(_fused(_ramp(10))).iloc[0]
    assert row["n_valid_steps"] == 9
    assert row["path_length_3d_cm"] == pytest.approx(117.0)


def test_unknown_body_length_gives_nan_bl_only() -> None:
    row = _run(_fused(_ramp(11))).iloc[0]
    assert np.isnan(row["path_length_3d_bl"])
    assert row["path_length_3d_cm"] == pytest.approx(130.0)


def test_a_nan_depth_removes_both_adjacent_steps() -> None:
    psess = _fused(_ramp(11))
    psess.depth[5, 0] = np.nan
    row = _run(psess).iloc[0]
    assert row["n_valid_steps"] == 8
    assert row["path_length_3d_cm"] == pytest.approx(8 * 13.0)


def test_a_nan_in_x_or_y_also_removes_the_step() -> None:
    psess = _fused(_ramp(11), body_length_cm=1.0)
    psess.xy[3, 0, 0] = np.nan
    psess.xy[7, 0, 1] = np.nan
    row = _run(psess).iloc[0]
    assert row["n_valid_steps"] == 6
    assert row["path_length_3d_cm"] == pytest.approx(6 * 13.0)


def test_all_nan_animal_is_nan_with_zero_steps() -> None:
    psess = _fused(_ramp(11, n_animals=2))
    psess.depth[:, 1] = np.nan
    df = _run(psess)
    assert np.isnan(df.loc[1, "path_length_3d_cm"])
    assert np.isnan(df.loc[1, "path_length_3d_bl"])
    assert df.loc[1, "n_valid_steps"] == 0


def test_no_valid_pair_is_nan_not_zero() -> None:
    psess = _fused(_ramp(6))
    psess.depth[1::2, 0] = np.nan  # every other frame: no two consecutive finite frames
    row = _run(psess).iloc[0]
    assert row["n_valid_steps"] == 0
    assert np.isnan(row["path_length_3d_cm"])


def test_a_motionless_animal_is_zero_not_nan() -> None:
    row = _run(_fused(_ramp(6, step=(0.0, 0.0, 0.0)))).iloc[0]
    assert row["path_length_3d_cm"] == 0.0
    assert row["n_valid_steps"] == 5


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_session_without_depth_or_scale_gives_nan_columns(missing: str) -> None:
    psess = _fused(_ramp(11, n_animals=2))
    setattr(psess, missing, None)
    df = _run(psess)
    assert list(df.columns) == COLUMNS
    assert len(df) == 2
    assert df["path_length_3d_cm"].isna().all()
    assert df["path_length_3d_bl"].isna().all()
    assert (df["n_valid_steps"] == 0).all()
    assert df["individual_id"].tolist() == [0, 1]


def test_two_animals_are_independent() -> None:
    pos = np.concatenate([_ramp(11), _ramp(11, step=(0.0, 0.0, 1.0))], axis=1)
    psess = _fused(pos)
    psess.depth[4, 1] = np.nan
    df = _run(psess)
    assert df.loc[0, "path_length_3d_cm"] == pytest.approx(130.0)
    assert df.loc[0, "n_valid_steps"] == 10
    assert df.loc[1, "path_length_3d_cm"] == pytest.approx(8.0)
    assert df.loc[1, "n_valid_steps"] == 8


def test_column_order_equals_output_columns() -> None:
    df = _run(_fused(_ramp(5)))
    assert list(df.columns) == PathLength3D.output_columns
    assert (df["metric_id"] == "IL-16").all()


def test_is_at_least_the_2d_path_length() -> None:
    rng = np.random.default_rng(5)
    pos = np.cumsum(rng.normal(0, 2.0, (60, 3, 3)), axis=0)
    psess = _fused(pos)
    d3 = _run(psess).set_index("individual_id")["path_length_3d_cm"]
    d2 = PathLength().compute(psess).set_index("individual_id")["path_length_cm"]
    assert (d3 >= d2 - 1e-9).all()
    assert (d3 > d2).all()


def test_binned_sum_loses_only_the_steps_at_bin_edges() -> None:
    # 100 frames at 25 fps, 1 s bins -> 25 frames per bin, 4 bins. Each bin holds 24 steps, the
    # 3 steps across the bin edges are lost: 4 * 24 * 13 = 1248 cm against 99 * 13 = 1287 cm.
    psess = _fused(_ramp(100))
    whole = _run(psess).loc[0, "path_length_3d_cm"]
    windows = bin_windows(psess, 1.0)
    assert len(windows) == 4
    parts = [_run(slice_psess(psess, w.start_row, w.stop_row)) for w in windows]
    assert all(p.loc[0, "n_valid_steps"] == 24 for p in parts)
    summed = sum(p.loc[0, "path_length_3d_cm"] for p in parts)
    assert whole == pytest.approx(99 * 13.0)
    assert summed == pytest.approx(4 * 24 * 13.0)
    assert summed <= whole + 1e-9
    assert summed >= whole * 0.9
