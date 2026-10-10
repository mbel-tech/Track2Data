"""The 3-D metrics (IL-16, IL-17, GL-16) end to end on the physical test scene: exported values
against the scene's known 3-D path, the skip under body-length calibration, and a 2-D control."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_fusion import scene
from tests.test_fusion.scene import FPS, N_FRAMES, TANK_CM, build_scene
from tests.test_integration.test_3d_run import OLD_SESSIONS_HEADER, _files
from track2data.api import Engine
from track2data.core.models import CalibrationConfig, MetricSelection, ProjectMode

IDS = {"individual": ["IL-1", "IL-2", "IL-16", "IL-17"], "group": ["GL-1", "GL-16"]}
EXPORTERS = ["csv_long", "readme"]
SKIP_MODE = "needs a cm scale for the top view (use scalar or session calibration)"
# The scene: every fish moves 1 px/frame in x (0.1 cm at 10 px/cm) at a constant depth, so the
# 3-D path equals the horizontal one. Fish are 1 cm apart in x, 2 cm in y and 5 cm in depth.
STEP_CM = 0.1
NND_CM = math.sqrt(1**2 + 2**2 + (0.25 * TANK_CM) ** 2)


def _selection(**kw: list[str]) -> MetricSelection:
    return MetricSelection(zone=[], diagnostic=[], **{**IDS, **kw})


def _long(out: Path, unit: str = "t1+s1") -> pd.DataFrame:
    return pd.read_csv(out / unit / "metrics_long.csv")


def _value(long: pd.DataFrame, metric: str, column: str, fish: int | None = None) -> float:
    rows = long[(long["metric_id"] == metric) & (long["column"] == column)]
    if fish is not None:
        rows = rows[rows["individual_id"] == fish]
    assert len(rows) == 1, (metric, column, len(rows))
    return float(rows["value"].iloc[0])


@pytest.fixture(scope="module")
def scalar_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("m3d")
    manifest = build_scene(base / "data").model_copy(update={"metrics": _selection()})
    Engine(manifest).run(base / "out", exporters=EXPORTERS)
    return base / "out"


def test_exported_values_match_the_scene(scalar_run: Path) -> None:
    long = _long(scalar_run)
    steps = N_FRAMES - 1
    for fish in range(3):
        assert _value(long, "IL-16", "n_valid_steps", fish) == steps
        np.testing.assert_allclose(
            _value(long, "IL-16", "path_length_3d_cm", fish), steps * STEP_CM, rtol=0.02
        )
        np.testing.assert_allclose(
            _value(long, "IL-17", "mean_speed_3d_cm_s", fish), STEP_CM * FPS, rtol=0.02
        )
        # the scene has no vertical movement: 3-D equals the horizontal metrics
        np.testing.assert_allclose(
            _value(long, "IL-16", "path_length_3d_cm", fish),
            _value(long, "IL-1", "path_length_cm", fish),
            rtol=1e-6,
        )
        np.testing.assert_allclose(
            _value(long, "IL-17", "mean_speed_3d_cm_s", fish),
            _value(long, "IL-2", "mean_speed_cm_s", fish),
            rtol=1e-6,
        )
    nnd = _value(long, "GL-16", "mean_nnd_3d_cm")
    np.testing.assert_allclose(nnd, NND_CM, rtol=0.02)
    assert nnd > _value(long, "GL-1", "mean_nnd_cm")
    assert _value(long, "GL-16", "n_skipped_frames_3d") == 0


def test_both_units_have_the_3d_tables(scalar_run: Path) -> None:
    for unit in ("t1+s1", "t2+s2"):
        ids = set(_long(scalar_run, unit)["metric_id"])
        assert {"IL-16", "IL-17", "GL-16"} <= ids


def test_bodylength_calibration_skips_the_3d_metrics_with_the_reason(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"metrics": _selection(), "calibration": CalibrationConfig(mode="bodylength")}
    )
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=EXPORTERS)
    ids = set(_long(out)["metric_id"])
    assert ids.isdisjoint({"IL-16", "IL-17", "GL-16"})
    assert {"IL-1", "IL-2", "GL-1"} <= ids
    readme = (out / "t1+s1" / "README.md").read_text(encoding="utf-8")
    assert "## Metrics skipped" in readme
    for mid in ("IL-16", "IL-17", "GL-16"):
        assert mid in readme
    assert SKIP_MODE in readme


def test_a_2d_project_skips_the_3d_metrics_and_is_unchanged(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": [], "metrics": _selection()}
    )
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=EXPORTERS)
    assert (out / "sessions.csv").read_text(encoding="utf-8").splitlines()[0] == OLD_SESSIONS_HEADER
    for unit in ("t1", "s1", "t2", "s2", "lone"):
        ids = set(_long(out, unit)["metric_id"])
        assert ids.isdisjoint({"IL-16", "IL-17", "GL-16"})
        assert {"IL-1", "IL-2", "GL-1"} <= ids
        readme = (out / unit / "README.md").read_text(encoding="utf-8")
        assert "needs a fused 3-D session" in readme
    # the same selection without the 3-D ids gives the same table as the 2-D control
    control = manifest.model_copy(
        update={"metrics": _selection(individual=["IL-1", "IL-2"], group=["GL-1"])}
    )
    out2 = tmp_path / "out2"
    Engine(control).run(out2, exporters=EXPORTERS)
    pd.testing.assert_frame_equal(_long(out, "t1"), _long(out2, "t1"))


def _sinking_side(shift: float = 0.0) -> np.ndarray:
    """Side rows 150 + 50 k + t: every fish sinks 1 px/frame (0.1 cm/frame in a 20 cm column)."""
    out = scene.top_xy(shift)
    t = np.arange(N_FRAMES, dtype=float)
    for k in range(3):
        out[:, k, 1] = 150.0 + 50.0 * k + t
    return out


@pytest.fixture(scope="module")
def sinking_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("m3d_sink")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scene, "side_xy", _sinking_side)
        manifest = build_scene(base / "data")
    manifest = manifest.model_copy(
        update={"metrics": _selection(individual=["IL-16", "IL-17"], group=["GL-1", "GL-16"])}
    )
    exporters = [*EXPORTERS, "csv_wide", "feather"]
    Engine(manifest).run(base / "serial", exporters=exporters)
    Engine(manifest).run(base / "parallel", exporters=exporters, n_workers=2)
    return base / "serial", base / "parallel"


def test_changing_depth_end_to_end(sinking_runs: tuple[Path, Path]) -> None:
    long = _long(sinking_runs[0])
    step = math.hypot(0.1, 0.1)
    for fish in (0, 1):
        assert _value(long, "IL-16", "n_valid_steps", fish) == 99
        np.testing.assert_allclose(
            _value(long, "IL-16", "path_length_3d_cm", fish), 99 * step, rtol=1e-4
        )
    # fish 2 reaches the floor row (300) at frame 50 and is outside the water column after it
    assert _value(long, "IL-16", "n_valid_steps", 2) == 50
    np.testing.assert_allclose(_value(long, "IL-16", "path_length_3d_cm", 2), 50 * step, rtol=1e-3)
    for fish in range(3):
        np.testing.assert_allclose(
            _value(long, "IL-17", "mean_speed_3d_cm_s", fish), FPS * step, rtol=1e-3
        )
    np.testing.assert_allclose(_value(long, "GL-16", "mean_nnd_3d_cm"), NND_CM, rtol=1e-3)
    assert _value(long, "GL-16", "n_skipped_frames_3d") == 49
    assert _value(long, "GL-1", "n_skipped_frames") == 0


def test_merged_group_table_keeps_gl1_and_gl16_skip_counts_apart(sinking_runs: tuple[Path, Path]) -> None:
    table = pd.read_csv(sinking_runs[0] / "t1+s1" / "group_dynamics_summary.csv")
    assert not [c for c in table.columns if c.endswith(("_x", "_y"))]
    assert table["n_skipped_frames"].iloc[0] == 0
    assert table["n_skipped_frames_3d"].iloc[0] == 49
    from track2data.exporters.schema import unit_for_column

    assert unit_for_column("n_skipped_frames_3d") == unit_for_column("n_skipped_frames") == "frames"


def test_serial_and_parallel_runs_agree_for_the_3d_metrics(sinking_runs: tuple[Path, Path]) -> None:
    serial, parallel = (_files(r) for r in sinking_runs)
    assert serial.keys() == parallel.keys()
    assert [n for n in serial if serial[n] != parallel[n]] == []
    assert b"path_length_3d_cm" in serial["t1+s1/metrics_long.csv"]
