"""Tests for track2data.sensitivity."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SecurityConfig,
    SessionRef,
)
from track2data.sensitivity import (
    GridPoint,
    SensitivityGrid,
    run_sensitivity,
    summarise,
)


def _manifest(folder: Path) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="sensitivity",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id=folder.name,
                folder=folder,
                sha256=hashlib.sha256(str(folder).encode()).hexdigest(),
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-2"]),
        security=SecurityConfig(allow_pickle_trajectories=True),
    )


@pytest.fixture()
def engine_and_session(tiny_real_session: Path):  # type: ignore[no-untyped-def]
    """An engine plus a session long enough for smoothing to matter."""
    from track2data.api import Engine

    engine = Engine(_manifest(tiny_real_session))
    session = engine.import_session(tiny_real_session)

    rng = np.random.default_rng(3)
    n_frames, n_animals = 300, session.n_animals
    xy = np.cumsum(rng.normal(0, 4.0, (n_frames, n_animals, 2)), axis=0) + 500.0
    # A gap of 20 frames: filled at max_gap_frames >= 30, left alone below,
    # which is what makes the sweep produce different answers at all.
    xy[100:120, 0, :] = np.nan

    return engine, session.model_copy(update={"raw_xy": xy})


# ── the grid ──────────────────────────────────────────────────────────────────


def test_grid_is_the_cartesian_product() -> None:
    grid = SensitivityGrid(smoothing_windows=(3, 5), max_gap_frames=(10, 20, 30))
    assert len(grid.points()) == 6


def test_default_windows_are_odd() -> None:
    """Savitzky-Golay requires an odd window. An even one would be silently
    decremented, so the table would report a setting that was not used."""
    for window in SensitivityGrid().smoothing_windows:
        assert window % 2 == 1


def test_default_grid_brackets_the_shipped_defaults() -> None:
    """A sweep that starts at the default cannot show which side of it a
    result sits on."""
    grid = SensitivityGrid()
    assert min(grid.smoothing_windows) < 5 < max(grid.smoothing_windows)
    assert min(grid.max_gap_frames) < 30 < max(grid.max_gap_frames)


def test_grid_point_label_is_readable() -> None:
    assert GridPoint(smoothing_window=9, max_gap_frames=30).label() == "win9_gap30"


# ── the sweep ─────────────────────────────────────────────────────────────────


def test_sweep_covers_every_grid_point(engine_and_session) -> None:  # type: ignore[no-untyped-def]
    engine, session = engine_and_session
    grid = SensitivityGrid(
        smoothing_windows=(3, 9), max_gap_frames=(5, 60), metric_ids=["IL-1"]
    )

    sweep = run_sensitivity(engine, session, grid)

    settings = set(
        zip(sweep["smoothing_window"], sweep["max_gap_frames"], strict=True)
    )
    assert settings == {(3, 5), (3, 60), (9, 5), (9, 60)}


def test_sweep_is_long_format_with_units(engine_and_session) -> None:  # type: ignore[no-untyped-def]
    """Same shape as metrics_long.csv, so it joins to codebook.csv the same
    way rather than needing its own reader."""
    engine, session = engine_and_session
    grid = SensitivityGrid(
        smoothing_windows=(5,), max_gap_frames=(30,), metric_ids=["IL-1"]
    )

    sweep = run_sensitivity(engine, session, grid)

    assert list(sweep.columns) == [
        "smoothing_window", "max_gap_frames", "session_id", "individual_id",
        "metric_id", "column", "value", "unit", "error",
    ]
    assert set(sweep.loc[sweep["column"] == "path_length_cm", "unit"]) == {"cm"}


def test_the_settings_actually_change_the_numbers(engine_and_session) -> None:  # type: ignore[no-untyped-def]
    """The premise of the whole feature.

    If a heavy smoothing window produced the same path length as a light
    one, there would be nothing to report -- and something would be wrong
    with the sweep rather than reassuring about the metric.
    """
    engine, session = engine_and_session
    grid = SensitivityGrid(
        smoothing_windows=(3, 15), max_gap_frames=(30,), metric_ids=["IL-1"]
    )

    sweep = run_sensitivity(engine, session, grid)
    path = sweep[sweep["column"] == "path_length_px"]

    light = path[path["smoothing_window"] == 3]["value"].to_numpy()
    heavy = path[path["smoothing_window"] == 15]["value"].to_numpy()

    assert not np.allclose(light, heavy)
    # Smoothing removes noise-driven wiggle, so heavier filtering must give a
    # *shorter* path -- the direction IL-1's documented warning describes.
    assert (heavy < light).all()


def test_metric_ids_restrict_the_sweep(engine_and_session) -> None:  # type: ignore[no-untyped-def]
    engine, session = engine_and_session
    grid = SensitivityGrid(
        smoothing_windows=(5,), max_gap_frames=(30,), metric_ids=["IL-2"]
    )

    sweep = run_sensitivity(engine, session, grid)

    assert set(sweep["metric_id"]) == {"IL-2"}


def test_a_failing_grid_point_is_recorded_not_fatal(engine_and_session) -> None:  # type: ignore[no-untyped-def]
    """A setting that does not work on this session is a useful row in the
    table, not a reason to lose the other fifteen."""
    engine, session = engine_and_session
    # polyorder is 2, so a window of 1 cannot support the fit.
    grid = SensitivityGrid(
        smoothing_windows=(1, 5), max_gap_frames=(30,), metric_ids=["IL-1"]
    )

    sweep = run_sensitivity(engine, session, grid)

    # The workable setting still produced rows.
    assert not sweep[
        (sweep["smoothing_window"] == 5) & sweep["error"].isna()
    ].empty


# ── the summary ───────────────────────────────────────────────────────────────


def _sweep_frame(values_by_setting: dict[int, list[float]]) -> pd.DataFrame:
    rows = []
    for window, values in values_by_setting.items():
        for individual, value in enumerate(values):
            rows.append({
                "smoothing_window": window,
                "max_gap_frames": 30,
                "session_id": "s1",
                "individual_id": individual,
                "metric_id": "IL-1",
                "column": "path_length_px",
                "value": value,
                "unit": "px",
                "error": pd.NA,
            })
    return pd.DataFrame(rows)


def test_a_robust_column_has_a_coefficient_of_variation_near_zero() -> None:
    sweep = _sweep_frame({3: [100.0, 200.0], 15: [100.0, 200.0]})
    summary = summarise(sweep)
    assert summary.iloc[0]["cv"] == pytest.approx(0.0)


def test_a_setting_dependent_column_has_a_large_cv() -> None:
    sweep = _sweep_frame({3: [100.0, 200.0], 15: [200.0, 400.0]})
    summary = summarise(sweep)
    assert summary.iloc[0]["cv"] > 0.3


def test_cv_is_computed_per_individual_then_averaged() -> None:
    """Pooling across individuals would mix genuine between-animal variation
    into a number that is supposed to measure parameter sensitivity alone.

    Here the two animals differ hugely from each other (100 vs 10000) but
    neither moves at all across the grid, so the answer must be 0.
    """
    sweep = _sweep_frame({3: [100.0, 10000.0], 15: [100.0, 10000.0]})
    summary = summarise(sweep)
    assert summary.iloc[0]["cv"] == pytest.approx(0.0)


def test_summary_is_sorted_worst_first() -> None:
    """The point of the table is to be read from the top."""
    stable = _sweep_frame({3: [100.0], 15: [100.0]})
    volatile = _sweep_frame({3: [100.0], 15: [400.0]})
    volatile = volatile.assign(column="mean_speed_px_s", metric_id="IL-2")

    summary = summarise(pd.concat([stable, volatile], ignore_index=True))

    assert summary.iloc[0]["column"] == "mean_speed_px_s"


def test_summary_of_an_all_failed_sweep_is_empty_not_wrong() -> None:
    sweep = pd.DataFrame([{
        "smoothing_window": 5, "max_gap_frames": 30, "session_id": "s1",
        "individual_id": pd.NA, "metric_id": pd.NA, "column": pd.NA,
        "value": pd.NA, "unit": pd.NA, "error": "boom",
    }])

    summary = summarise(sweep)

    assert summary.empty
    assert "cv" in summary.columns


def test_a_zero_mean_column_reports_nan_rather_than_dividing_by_zero() -> None:
    """CV is undefined at a mean of zero. NaN says so; a large number would
    put a genuinely stable column at the top of the table."""
    sweep = _sweep_frame({3: [0.0], 15: [0.0]})
    summary = summarise(sweep)
    assert np.isnan(summary.iloc[0]["cv"])
