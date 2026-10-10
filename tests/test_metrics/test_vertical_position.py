"""IL-15 (vertical position / depth) against tracks with a known answer.

Depth is the fraction of the water column between the surface (0) and the floor (1). Image rows
grow downward, so a larger y is deeper.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
)
from track2data.metrics import get
from track2data.metrics.individual import VerticalPosition

TOP, BOTTOM = 100.0, 700.0
TANK = {"top_px": TOP, "bottom_px": BOTTOM, "source": "zone:tank"}


def _psess(y: np.ndarray, px_per_cm: float | None = None) -> PreprocessedSession:
    """One or more animals; *y* is (frames,) or (frames, animals)."""
    y = np.asarray(y, dtype=np.float64)
    if y.ndim == 1:
        y = y[:, None]
    n_frames, n_animals = y.shape
    xy = np.stack([np.full_like(y, 50.0), y], axis=2)
    session = Session(
        session_id="s1",
        folder=Path("/tmp/s1"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=1000, height_px=800),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )
    return PreprocessedSession(session=session, xy=xy, kinematics=kine, px_per_cm=px_per_cm)


def _compute(y, cfg=None, **kw):
    return VerticalPosition().compute(_psess(y, **kw), cfg)


def test_it_is_registered_as_a_side_view_individual_metric() -> None:
    cls = get("IL-15")
    assert cls is VerticalPosition
    assert cls.level == "individual"
    assert cls.requires_identity is True
    assert cls.valid_camera_views == frozenset({"side"})


def test_the_output_columns_are_exactly_the_declared_ones() -> None:
    df = _compute(np.full(10, 400.0), {"water_column": TANK})
    assert list(df.columns) == VerticalPosition.output_columns


def test_an_animal_at_a_known_depth_reports_it() -> None:
    row = _compute(np.full(20, 400.0), {"water_column": TANK}).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)
    assert row["median_depth_fraction"] == pytest.approx(0.5)
    assert row["sd_depth_fraction"] == pytest.approx(0.0)
    assert row["frac_outside_extent"] == 0.0
    assert row["depth_extent_source"] == "zone:tank"


def test_depth_zero_is_the_surface_and_one_is_the_floor() -> None:
    surface = _compute(np.full(5, TOP), {"water_column": TANK}).iloc[0]
    floor = _compute(np.full(5, BOTTOM), {"water_column": TANK}).iloc[0]
    assert surface["mean_depth_fraction"] == pytest.approx(0.0)
    assert floor["mean_depth_fraction"] == pytest.approx(1.0)


def test_a_steady_descent_has_the_textbook_mean_median_and_sd() -> None:
    n = 101
    row = _compute(np.linspace(TOP, BOTTOM, n), {"water_column": TANK}).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)
    assert row["median_depth_fraction"] == pytest.approx(0.5)
    # n evenly spaced points on [0, 1], sample SD (ddof=1): sqrt(n (n + 1) / (12 (n - 1)^2))
    assert row["sd_depth_fraction"] == pytest.approx(np.sqrt(n * (n + 1) / (12 * (n - 1) ** 2)))


def test_the_median_is_not_the_mean_for_a_skewed_track() -> None:
    y = np.array([TOP] * 8 + [BOTTOM] * 2)
    row = _compute(y, {"water_column": TANK}).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.2)
    assert row["median_depth_fraction"] == pytest.approx(0.0)


def test_frames_outside_the_water_column_are_dropped_and_counted_never_clipped() -> None:
    # 6 frames at mid-depth, 2 above the surface (reflection), 2 below the floor
    y = np.array([400.0] * 6 + [50.0, 60.0] + [800.0, 900.0])
    row = _compute(y, {"water_column": TANK}).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)  # clipping would pull it off 0.5
    assert row["frac_outside_extent"] == pytest.approx(0.4)


def test_the_boundary_rows_themselves_are_inside() -> None:
    row = _compute(np.array([TOP, BOTTOM]), {"water_column": TANK}).iloc[0]
    assert row["frac_outside_extent"] == 0.0
    assert row["mean_depth_fraction"] == pytest.approx(0.5)


def test_missing_frames_are_not_counted_as_outside() -> None:
    y = np.array([400.0, np.nan, np.nan, 400.0])
    row = _compute(y, {"water_column": TANK}).iloc[0]
    assert row["frac_outside_extent"] == 0.0
    assert row["mean_depth_fraction"] == pytest.approx(0.5)


def test_depth_in_centimetres_is_the_distance_below_the_surface() -> None:
    row = _compute(np.full(10, 400.0), {"water_column": TANK}, px_per_cm=10.0).iloc[0]
    assert row["mean_depth_cm"] == pytest.approx(30.0)  # (400 - 100) px / 10 px per cm


def test_uncalibrated_depth_in_centimetres_is_nan_not_absent() -> None:
    df = _compute(np.full(10, 400.0), {"water_column": TANK})
    assert "mean_depth_cm" in df.columns
    assert np.isnan(df.iloc[0]["mean_depth_cm"])


def test_one_frame_in_the_water_has_a_depth_but_no_spread() -> None:
    row = _compute(np.array([400.0, np.nan, 50.0]), {"water_column": TANK}).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)
    assert np.isnan(row["sd_depth_fraction"])
    assert row["frac_outside_extent"] == pytest.approx(0.5)


def test_an_animal_never_seen_has_nan_values_but_keeps_the_source() -> None:
    row = _compute(np.full(10, np.nan), {"water_column": TANK}).iloc[0]
    assert np.isnan(row["mean_depth_fraction"])
    assert np.isnan(row["frac_outside_extent"])
    assert row["depth_extent_source"] == "zone:tank"


def test_an_animal_entirely_outside_the_water_has_no_depth_but_reports_why() -> None:
    row = _compute(np.full(10, 900.0), {"water_column": TANK}).iloc[0]
    assert np.isnan(row["mean_depth_fraction"])
    assert row["frac_outside_extent"] == 1.0


def test_with_no_derived_extent_every_value_is_nan_and_the_columns_are_still_there() -> None:
    """The schema contract calls compute() directly, with no engine gating or derivation."""
    df = _compute(np.full(10, 400.0), None)
    assert list(df.columns) == VerticalPosition.output_columns
    row = df.iloc[0]
    assert np.isnan(row["mean_depth_fraction"])
    assert row["depth_extent_source"] == "none:not_derived"


def test_a_missing_extent_passes_its_reason_through() -> None:
    gone = {"top_px": None, "bottom_px": None, "source": "none:no_main_zone"}
    row = _compute(np.full(10, 400.0), {"water_column": gone}).iloc[0]
    assert np.isnan(row["mean_depth_fraction"])
    assert row["depth_extent_source"] == "none:no_main_zone"


def test_a_zero_height_extent_is_refused() -> None:
    flat = {"top_px": 300.0, "bottom_px": 300.0, "source": "zone:line"}
    row = _compute(np.full(10, 300.0), {"water_column": flat}).iloc[0]
    assert np.isnan(row["mean_depth_fraction"])
    assert row["depth_extent_source"].startswith("none:")


def test_each_animal_gets_its_own_row() -> None:
    y = np.stack([np.full(10, TOP), np.full(10, BOTTOM)], axis=1)
    df = _compute(y, {"water_column": TANK})
    assert list(df["individual_id"]) == [0, 1]
    assert df["mean_depth_fraction"].tolist() == pytest.approx([0.0, 1.0])


def test_a_large_share_outside_the_extent_is_logged(caplog) -> None:
    y = np.array([400.0] * 5 + [900.0] * 5)
    with caplog.at_level(logging.WARNING, logger="track2data.metrics.individual"):
        _compute(y, {"water_column": TANK})
    assert any("IL-15" in r.getMessage() and "outside" in r.getMessage() for r in caplog.records)


def test_a_small_share_outside_the_extent_is_not_logged(caplog) -> None:
    y = np.array([400.0] * 99 + [900.0])
    with caplog.at_level(logging.WARNING, logger="track2data.metrics.individual"):
        _compute(y, {"water_column": TANK})
    assert not any("IL-15" in r.getMessage() for r in caplog.records)


# ── fused sessions: IL-15 reads the depth array ───────────────────────────────


def _fused(depth, height_cm=20.0, outside=None):
    depth = np.asarray(depth, dtype=np.float64)
    if depth.ndim == 1:
        depth = depth[:, None]
    ps = _psess(np.full(depth.shape, 400.0))
    ps.depth = depth
    ps.depth_height_cm = height_cm
    ps.depth_outside = (
        np.zeros(depth.shape[1], dtype=int) if outside is None else np.asarray(outside, dtype=int)
    )
    return ps


def test_fused_depth_gives_exact_statistics_in_cm() -> None:
    ps = _fused([0.25, 0.5, 0.75])
    row = VerticalPosition().compute(ps, None).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)
    assert row["median_depth_fraction"] == pytest.approx(0.5)
    assert row["sd_depth_fraction"] == pytest.approx(0.25)
    assert row["mean_depth_cm"] == pytest.approx(10.0)
    assert row["frac_outside_extent"] == 0.0
    assert row["depth_extent_source"] == "fusion"


def test_fused_depth_ignores_zone_column_and_px_per_cm() -> None:
    ps = _fused([0.25, 0.75])
    ps.px_per_cm = 3.0
    row = VerticalPosition().compute(ps, {"water_column": TANK}).iloc[0]
    assert row["mean_depth_cm"] == pytest.approx(10.0)
    assert row["depth_extent_source"] == "fusion"


def test_fused_nan_gaps_are_ignored() -> None:
    ps = _fused([0.25, np.nan, 0.75, np.nan])
    row = VerticalPosition().compute(ps, None).iloc[0]
    assert row["mean_depth_fraction"] == pytest.approx(0.5)
    assert row["sd_depth_fraction"] == pytest.approx(np.std([0.25, 0.75], ddof=1))


def test_fused_frac_outside_uses_outside_counts_and_finite_counts() -> None:
    ps = _fused([0.5, 0.5, 0.5], outside=[1])
    row = VerticalPosition().compute(ps, None).iloc[0]
    assert row["frac_outside_extent"] == pytest.approx(1 / 4)


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_fused_all_nan_animal_is_nan_without_warning() -> None:
    depth = np.array([[0.5, np.nan], [0.5, np.nan]])
    ps = _fused(depth, outside=[0, 3])
    df = VerticalPosition().compute(ps, None)
    ok, empty = df.iloc[0], df.iloc[1]
    assert ok["mean_depth_fraction"] == pytest.approx(0.5)
    assert np.isnan(empty["mean_depth_fraction"])
    assert np.isnan(empty["median_depth_fraction"])
    assert np.isnan(empty["sd_depth_fraction"])
    assert np.isnan(empty["mean_depth_cm"])
    assert empty["frac_outside_extent"] == pytest.approx(1.0)  # 3 / (3 + 0)
    assert list(df.columns) == VerticalPosition.output_columns


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_fused_nothing_at_all_gives_nan_fraction() -> None:
    ps = _fused(np.full((3, 1), np.nan), outside=[0])
    row = VerticalPosition().compute(ps, None).iloc[0]
    assert np.isnan(row["frac_outside_extent"])


def test_fused_unknown_height_gives_nan_cm() -> None:
    ps = _fused([0.25, 0.75], height_cm=None)
    row = VerticalPosition().compute(ps, None).iloc[0]
    assert np.isnan(row["mean_depth_cm"])
    assert row["mean_depth_fraction"] == pytest.approx(0.5)


def test_fused_single_sample_has_no_sd() -> None:
    row = VerticalPosition().compute(_fused([0.4]), None).iloc[0]
    assert np.isnan(row["sd_depth_fraction"])


def test_uses_depth_flag() -> None:
    from track2data.metrics.base import Metric

    assert VerticalPosition.uses_depth is True
    assert Metric.uses_depth is False
