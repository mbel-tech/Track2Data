"""GL-16, 3-D nearest-neighbour distance: GL-1 in (X, Y, Z) cm on a fused session."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.metrics import get
from track2data.metrics.binning import bin_windows, slice_psess
from track2data.metrics.group import NearestNeighbourDistance, NearestNeighbourDistance3D

PX_PER_CM = 8.0
HEIGHT_CM = 200.0
COLUMNS = [
    "session_id", "metric_id", "mean_nnd_3d_cm", "median_nnd_3d_cm",
    "mean_nnd_3d_bl", "n_skipped_frames_3d",
]
STATS = COLUMNS[2:5]


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


def _run(psess) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        return NearestNeighbourDistance3D().compute(psess)


def _three_fish(n_frames: int = 4) -> np.ndarray:
    pts = np.array([[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [0.0, 0.0, 12.0]])
    return np.broadcast_to(pts, (n_frames, 3, 3)).copy()


def test_is_registered_with_the_agreed_identity() -> None:
    cls = get("GL-16")
    assert cls is NearestNeighbourDistance3D
    assert (cls.name, cls.label, cls.level) == (
        "nearest_neighbour_distance_3d", "3-D Nearest-Neighbour Distance", "group"
    )
    assert cls.requires_identity is False
    assert cls.priority == "optional"
    assert cls.requires_depth_scale is True
    assert cls.window_safe is True
    assert cls.output_columns == COLUMNS


def test_three_fish_known_points() -> None:
    # A=(0,0,0), B=(3,4,0), C=(0,0,12): d(A,B)=5, d(A,C)=12, d(B,C)=13.
    # NND: A->B 5, B->A 5, C->A 12; per-frame mean = 22/3.
    df = _run(_fused(_three_fish(), body_length_cm=2.0))
    row = df.iloc[0]
    assert list(df.columns) == COLUMNS and len(df) == 1
    assert row["metric_id"] == "GL-16"
    assert row["mean_nnd_3d_cm"] == pytest.approx(22.0 / 3.0)
    assert row["median_nnd_3d_cm"] == pytest.approx(22.0 / 3.0)
    assert row["mean_nnd_3d_bl"] == pytest.approx(22.0 / 3.0 / 2.0)
    assert row["n_skipped_frames_3d"] == 0


def test_mean_and_median_over_frames() -> None:
    # Two fish on a vertical line: separation 2, 4, 12 cm over three frames.
    pos = np.zeros((3, 2, 3))
    pos[:, 1, 2] = [2.0, 4.0, 12.0]
    row = _run(_fused(pos)).iloc[0]
    assert row["mean_nnd_3d_cm"] == pytest.approx(6.0)
    assert row["median_nnd_3d_cm"] == pytest.approx(4.0)


def test_vertical_separation_counts_unlike_gl1() -> None:
    # Same X, Y, different Z: GL-1 sees 0 cm, GL-16 sees the depth difference.
    pos = np.zeros((5, 2, 3))
    pos[:, 1, 2] = 9.0
    psess = _fused(pos)
    assert _run(psess).iloc[0]["mean_nnd_3d_cm"] == pytest.approx(9.0)
    assert NearestNeighbourDistance().compute(psess).iloc[0]["mean_nnd_cm"] == pytest.approx(0.0)


def test_frame_with_any_nan_component_is_skipped_and_counted() -> None:
    pos = _three_fish(5)
    psess = _fused(pos)
    psess.depth[1, 2] = np.nan
    psess.xy[3, 0, 0] = np.nan
    row = _run(psess).iloc[0]
    assert row["n_skipped_frames_3d"] == 2
    assert row["mean_nnd_3d_cm"] == pytest.approx(22.0 / 3.0)


def test_one_fish_is_nan_and_every_frame_skipped() -> None:
    row = _run(_fused(np.zeros((6, 1, 3)), body_length_cm=2.0)).iloc[0]
    assert np.isnan(row[STATS].astype(float)).all()
    assert row["n_skipped_frames_3d"] == 6


def test_all_frames_skipped_is_nan_not_zero() -> None:
    psess = _fused(_three_fish(4))
    psess.depth[:, 0] = np.nan
    row = _run(psess).iloc[0]
    assert np.isnan(row[STATS].astype(float)).all()
    assert row["n_skipped_frames_3d"] == 4


def test_unknown_body_length_gives_nan_bl_only() -> None:
    row = _run(_fused(_three_fish())).iloc[0]
    assert np.isnan(row["mean_nnd_3d_bl"])
    assert row["mean_nnd_3d_cm"] == pytest.approx(22.0 / 3.0)


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_session_without_depth_or_scale_gives_nan_columns(missing: str) -> None:
    psess = _fused(_three_fish())
    setattr(psess, missing, None)
    df = _run(psess)
    assert list(df.columns) == COLUMNS
    assert len(df) == 1
    assert np.isnan(df.iloc[0][STATS].astype(float)).all()
    assert df.iloc[0]["n_skipped_frames_3d"] == 4


def test_equals_gl1_when_depth_is_constant_including_the_bl_convention() -> None:
    rng = np.random.default_rng(3)
    pos = rng.uniform(0, 50, (30, 4, 3))
    pos[..., 2] = 7.0
    psess = _fused(pos, body_length_cm=2.5)
    g3 = _run(psess).iloc[0]
    g1 = NearestNeighbourDistance().compute(psess).iloc[0]
    assert g3["mean_nnd_3d_cm"] == pytest.approx(g1["mean_nnd_cm"], rel=1e-12)
    assert g3["mean_nnd_3d_bl"] == pytest.approx(g1["mean_nnd_bl"], rel=1e-12)
    assert g3["n_skipped_frames_3d"] == g1["n_skipped_frames"]


def test_at_least_gl1_per_frame_where_both_are_valid() -> None:
    # Frame by frame (one-frame sessions), over frames where GL-1 and GL-16 are both valid.
    # GL-1 may keep frames GL-16 skips (missing depth), so the comparison is not unconditional.
    rng = np.random.default_rng(5)
    pos = rng.uniform(0, 50, (25, 4, 3))
    psess = _fused(pos)
    psess.depth[4, 1] = np.nan
    psess.depth[9, 0] = np.nan
    n_both = 0
    for t in range(25):
        one = slice_psess(psess, t, t + 1)
        g3 = _run(one).iloc[0]
        g1 = NearestNeighbourDistance().compute(one).iloc[0]
        if t in (4, 9):
            assert np.isnan(g3["mean_nnd_3d_cm"]) and g3["n_skipped_frames_3d"] == 1
            assert np.isfinite(g1["mean_nnd_cm"])  # GL-1 keeps the frame
            continue
        assert g3["mean_nnd_3d_cm"] >= g1["mean_nnd_cm"] - 1e-12
        n_both += 1
    assert n_both == 23


def test_binned_values_match_the_windows_of_the_whole_session() -> None:
    # Identical geometry in every frame: every bin equals the whole session.
    psess = _fused(_three_fish(100), body_length_cm=2.0)
    whole = _run(psess).iloc[0]
    windows = bin_windows(psess, 1.0)
    assert len(windows) == 4
    for w in windows:
        part = _run(slice_psess(psess, w.start_row, w.stop_row)).iloc[0]
        assert part["mean_nnd_3d_cm"] == pytest.approx(whole["mean_nnd_3d_cm"])
        assert part["mean_nnd_3d_bl"] == pytest.approx(whole["mean_nnd_3d_bl"])
        assert part["n_skipped_frames_3d"] == 0


def test_binned_means_average_to_the_whole_session_mean() -> None:
    # Two fish, separation grows per bin; equal-length bins: the whole mean is the mean of bins.
    pos = np.zeros((100, 2, 3))
    pos[:, 1, 2] = np.repeat([1.0, 3.0, 5.0, 7.0], 25)
    psess = _fused(pos)
    whole = _run(psess).iloc[0]["mean_nnd_3d_cm"]
    windows = bin_windows(psess, 1.0)
    parts = [_run(slice_psess(psess, w.start_row, w.stop_row)).iloc[0]["mean_nnd_3d_cm"]
             for w in windows]
    assert parts == pytest.approx([1.0, 3.0, 5.0, 7.0])
    assert np.mean(parts) == pytest.approx(whole)
