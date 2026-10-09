"""A side-view project, run the way a user runs it: Engine.run() with the real exporters.

Every piece of the camera-view feature has its own unit tests; this is the one place that proves
they work together. A main zone is drawn over the whole frame, so the water column is the frame's
own rows and the expected depth can be computed here, from the preprocessed positions, without
going through IL-15.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_integration.test_end_to_end import _minimal_manifest
from track2data.api import Engine
from track2data.core.models import ROI, MetricSelection, SceneConfig, ZoneSet

HEIGHT = 1080  # tiny_real_session's frame (tests/conftest.py)
WIDTH = 1920
PX_PER_CM = 10.0  # _minimal_manifest's scalar calibration
EXPORTERS = ["csv_long", "csv_wide", "excel", "feather", "readme"]


def _tank() -> ROI:
    return ROI(
        name="tank",
        level="main",
        vertices=[(0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)],
    )


@pytest.fixture(scope="module")
def run(tiny_real_session: Path, tmp_path_factory: pytest.TempPathFactory):
    manifest = _minimal_manifest(tiny_real_session).model_copy(
        update={
            "scene": SceneConfig(camera_view="side"),
            "zones": ZoneSet(rois=[_tank()]),
            "metrics": MetricSelection(individual=["IL-15"]),
        }
    )
    engine = Engine(manifest)
    out = tmp_path_factory.mktemp("side_view_run")
    result = engine.run(out, exporters=EXPORTERS)
    assert not result.sessions[0].error, result.sessions[0].error
    session_dir = out / tiny_real_session.name
    xy = engine.preprocess(engine.import_session(tiny_real_session)).xy
    return out, session_dir, xy


def _expected_depth(xy: np.ndarray, k: int) -> tuple[float, float]:
    """(mean depth fraction, mean depth in px) of animal k, from the positions alone."""
    y = xy[:, k, 1]
    inside = y[np.isfinite(y) & (y >= 0) & (y <= HEIGHT)]
    return float(inside.mean() / HEIGHT), float(inside.mean())


def test_every_exporter_wrote_its_files(run) -> None:
    _out, session_dir, _xy = run
    for name in (
        "metrics_long.csv",
        "trial_activity_summary.csv",
        "trial_activity_summary.feather",
        "README.md",
        "manifest.json",
    ):
        assert (session_dir / name).exists(), name
    assert list(session_dir.glob("*.xlsx"))


def test_the_long_table_has_the_depth_the_positions_imply(run) -> None:
    _out, session_dir, xy = run
    long = pd.read_csv(session_dir / "metrics_long.csv")
    rows = long[long["metric_id"] == "IL-15"]

    for k in range(xy.shape[1]):
        mine = rows[rows["individual_id"] == k].set_index("column")
        fraction, px = _expected_depth(xy, k)
        assert mine.loc["mean_depth_fraction", "value"] == pytest.approx(fraction)
        assert mine.loc["mean_depth_cm", "value"] == pytest.approx(px / PX_PER_CM)
        assert mine.loc["mean_depth_fraction", "unit"] == "fraction (0-1)"
        assert mine.loc["mean_depth_cm", "unit"] == "cm"
        assert mine.loc["frac_outside_extent", "value"] == 0.0


def test_the_extent_source_survives_in_the_wide_tables(run) -> None:
    """The long table keeps numbers only, so the categorical source must be in the wide one."""
    _out, session_dir, _xy = run
    wide = pd.read_csv(session_dir / "trial_activity_summary.csv")
    assert set(wide["depth_extent_source"]) == {"zone:tank"}
    assert wide["mean_depth_fraction"].notna().all()

    feather = pd.read_feather(session_dir / "trial_activity_summary.feather")
    assert set(feather["depth_extent_source"]) == {"zone:tank"}


def test_the_codebook_documents_every_depth_column(run) -> None:
    out, _session_dir, _xy = run
    codebook = pd.read_csv(out / "codebook.csv").set_index("column")
    for column in (
        "mean_depth_fraction",
        "median_depth_fraction",
        "sd_depth_fraction",
        "mean_depth_cm",
        "frac_outside_extent",
        "depth_extent_source",
    ):
        assert codebook.loc[column, "metric_id"] == "IL-15", column
        assert codebook.loc[column, "unit"] != "unknown", column
    assert codebook.loc["depth_extent_source", "unit"] == "categorical"


def test_the_readme_says_what_the_depth_was_measured_against(run) -> None:
    _out, session_dir, _xy = run
    text = (session_dir / "README.md").read_text(encoding="utf-8")
    assert "| Camera view | Side view |" in text
    assert f"| Water column | rows 0 to {HEIGHT} px (zone:tank) |" in text
    assert "- IL-15" in text
    assert "## Metrics skipped" not in text


def test_the_manifest_json_records_the_view_and_the_water_column(run) -> None:
    import json

    _out, session_dir, _xy = run
    data = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    assert data["scene"]["camera_view"] == "side"
    prov = data["run_metadata"]["session_provenance"]
    assert prov["camera_view"] == "side"
    assert prov["water_column"] == {
        "top_px": 0.0,
        "bottom_px": float(HEIGHT),
        "source": "zone:tank",
    }
