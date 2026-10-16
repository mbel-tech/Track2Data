"""GL-18, 3-D inter-individual distance: GL-2 in (X, Y, Z) cm on a fused session."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.metrics import get
from track2data.metrics.group import (
    InterIndividualDistance,
    InterIndividualDistance3D,
    NearestNeighbourDistance3D,
)

PX_PER_CM = 8.0
HEIGHT_CM = 200.0
COLUMNS = [
    "session_id",
    "metric_id",
    "mean_iid_3d_cm",
    "median_iid_3d_cm",
    "mean_iid_3d_bl",
    "n_skipped_frames_3d",
    "frac_frames_used_3d",
]
STATS = COLUMNS[2:5]


def _fused(pos_cm: np.ndarray, *, body_length_cm: float | None = None):
    n_frames, n_animals = pos_cm.shape[:2]
    psess = _make_psess(_make_session(n_frames=n_frames, n_animals=n_animals))
    if body_length_cm is not None:
        psess.body_length_px = np.full(n_animals, body_length_cm * PX_PER_CM)
    psess.xy = pos_cm[..., :2] * PX_PER_CM
    psess.depth = pos_cm[..., 2] / HEIGHT_CM
    psess.px_per_cm = PX_PER_CM
    psess.depth_height_cm = HEIGHT_CM
    return psess


def _run(psess) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        return InterIndividualDistance3D().compute(psess)


def _three_fish(n_frames: int = 4) -> np.ndarray:
    # d(A,B)=5, d(A,C)=12, d(B,C)=13
    pts = np.array([[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [0.0, 0.0, 12.0]])
    return np.broadcast_to(pts, (n_frames, 3, 3)).copy()


def test_is_registered_with_the_agreed_identity() -> None:
    cls = get("GL-18")
    assert cls is InterIndividualDistance3D
    assert (cls.name, cls.label, cls.level) == (
        "inter_individual_distance_3d",
        "3-D Inter-Individual Distance",
        "group",
    )
    assert cls.requires_identity is False
    assert cls.requires_depth_scale is True
    assert cls.priority == "optional"
    assert cls.output_columns == COLUMNS


def test_two_fish_at_known_3d_separation() -> None:
    pos = np.zeros((5, 2, 3))
    pos[:, 1] = [3.0, 4.0, 12.0]  # 13 cm apart
    row = _run(_fused(pos, body_length_cm=2.0)).iloc[0]
    assert row["metric_id"] == "GL-18"
    assert row["mean_iid_3d_cm"] == pytest.approx(13.0)
    assert row["median_iid_3d_cm"] == pytest.approx(13.0)
    assert row["mean_iid_3d_bl"] == pytest.approx(6.5)
    assert row["n_skipped_frames_3d"] == 0
    assert row["frac_frames_used_3d"] == pytest.approx(1.0)


def test_three_fish_mean_pairwise() -> None:
    row = _run(_fused(_three_fish())).iloc[0]
    assert row["mean_iid_3d_cm"] == pytest.approx((5 + 12 + 13) / 3)


def test_vertical_separation_counts_unlike_gl2() -> None:
    pos = np.zeros((5, 2, 3))
    pos[:, 1, 2] = 9.0
    psess = _fused(pos)
    assert _run(psess).iloc[0]["mean_iid_3d_cm"] == pytest.approx(9.0)
    assert InterIndividualDistance().compute(psess).iloc[0]["mean_iid_px"] == pytest.approx(0.0)


def test_at_least_the_nearest_neighbour_distance() -> None:
    pos = np.random.default_rng(2).uniform(0, 40, (20, 5, 3))
    psess = _fused(pos)
    nnd = NearestNeighbourDistance3D().compute(psess).iloc[0]["mean_nnd_3d_cm"]
    assert _run(psess).iloc[0]["mean_iid_3d_cm"] >= nnd


def test_frames_with_a_nan_are_skipped_and_counted() -> None:
    psess = _fused(_three_fish(5))
    psess.depth[1, 2] = np.nan
    psess.xy[3, 0, 0] = np.nan
    row = _run(psess).iloc[0]
    assert row["n_skipped_frames_3d"] == 2
    assert row["frac_frames_used_3d"] == pytest.approx(3 / 5)
    assert row["mean_iid_3d_cm"] == pytest.approx(10.0)


def test_single_animal_session_is_refused_as_nan() -> None:
    row = _run(_fused(np.zeros((6, 1, 3)), body_length_cm=2.0)).iloc[0]
    assert np.isnan(row[STATS].astype(float)).all()
    assert row["n_skipped_frames_3d"] == 6
    assert np.isnan(row["frac_frames_used_3d"])


def test_all_frames_skipped_is_nan_not_zero() -> None:
    psess = _fused(_three_fish(4))
    psess.depth[:, 0] = np.nan
    row = _run(psess).iloc[0]
    assert np.isnan(row[STATS].astype(float)).all()
    assert row["n_skipped_frames_3d"] == 4


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_session_without_depth_or_scale_gives_nan_columns(missing: str) -> None:
    psess = _fused(_three_fish())
    setattr(psess, missing, None)
    df = _run(psess)
    assert list(df.columns) == COLUMNS and len(df) == 1
    assert np.isnan(df.iloc[0][STATS].astype(float)).all()
    assert df.iloc[0]["n_skipped_frames_3d"] == 4


def test_a_separator_row_is_not_a_frame() -> None:
    psess = _fused(_three_fish(5))
    separator = np.zeros(5, dtype=bool)
    separator[2] = True
    psess.separator_mask = separator
    psess.xy[2] = np.nan
    row = _run(psess).iloc[0]
    assert row["n_skipped_frames_3d"] == 0
    assert row["frac_frames_used_3d"] == pytest.approx(1.0)
