"""A native 3-D import exports its vertical coordinate: ``z_cm`` in the per-frame table."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_integration.test_native_3d import PATH_CM, _manifest, _native_project
from track2data.api import Engine
from track2data.core.models import WaterColumn
from track2data.exporters.csv_long import CsvLongExporter
from track2data.exporters.feather import FeatherExporter


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _native_project(tmp_path_factory.mktemp("zcol"))


def _frames(project: Path, out: Path, water: WaterColumn | None, fish: str = "fish1"):
    Engine(_manifest(project, water)).run(out, exporters=["csv_long"])
    return pd.read_csv(out / fish / "master_fish_by_frame.csv")


def test_native_export_has_absolute_z_without_a_water_column(project: Path, tmp_path: Path) -> None:
    df = _frames(project, tmp_path / "o", None)
    assert "z_cm" in df.columns
    assert "depth_fraction" not in df.columns
    # the scene climbs 1.2 cm per frame from z = 0
    np.testing.assert_allclose(df["z_cm"].to_numpy(), np.arange(11) * 1.2, atol=1e-9)


def test_z_is_the_files_coordinate_not_depth_below_the_surface(
    project: Path, tmp_path: Path
) -> None:
    df = _frames(project, tmp_path / "o", WaterColumn(surface_z=12.0, floor_z=0.0), fish="fish2")
    # fish2 is shifted +10 cm; z_cm stays the absolute value whatever the water column says
    np.testing.assert_allclose(df["z_cm"].to_numpy(), 10 + np.arange(11) * 1.2, atol=1e-9)
    assert "depth_fraction" in df.columns and "depth_cm" in df.columns


def test_il16_can_be_reproduced_from_the_exported_columns(project: Path, tmp_path: Path) -> None:
    df = _frames(project, tmp_path / "o", None)
    steps = np.sqrt(
        np.diff(df["x_cm"]) ** 2 + np.diff(df["y_cm"]) ** 2 + np.diff(df["z_cm"]) ** 2
    )
    assert steps.sum() == pytest.approx(PATH_CM, abs=1e-9)


def test_z_cm_is_nan_where_the_position_is_nan(project: Path, tmp_path: Path) -> None:
    from track2data.exporters.schema import depth_columns

    manifest = _manifest(project, None)
    engine = Engine(manifest)
    psess = engine.preprocess_ref(manifest.sessions[0])
    psess = engine.apply_calibration_and_zones(psess)
    psess.xy[3, 0] = np.nan
    cols = depth_columns(psess)
    assert np.isnan(cols["z_cm"][3]) and np.isfinite(cols["z_cm"][4])


def test_z_cm_is_written_by_the_other_per_frame_formats(project: Path, tmp_path: Path) -> None:
    manifest = _manifest(project, None)
    engine = Engine(manifest)
    psess = engine.apply_calibration_and_zones(engine.preprocess_ref(manifest.sessions[0]))
    df = engine.build_fish_by_frame(psess)
    assert "z_cm" in df.columns

    from tests.test_exporters.test_depth_columns import _payload

    payload = _payload(df)
    CsvLongExporter().write(payload, tmp_path / "csv")
    FeatherExporter().write(payload, tmp_path / "feather")
    fea = pd.read_feather(tmp_path / "feather" / "master_fish_by_frame.feather")
    np.testing.assert_allclose(fea["z_cm"].to_numpy(float), df["z_cm"].to_numpy(float))


def test_a_quality_threshold_masks_z_with_the_position(project: Path) -> None:
    manifest = _manifest(project, None)
    manifest.metrics.quality_threshold = 0.5
    engine = Engine(manifest)
    psess = engine.apply_calibration_and_zones(engine.preprocess_ref(manifest.sessions[0]))
    prob = np.ones((psess.n_frames, psess.n_animals))
    prob[3, 0] = 0.1
    psess.id_probabilities_rows = prob
    df = engine.build_fish_by_frame(psess)
    low = df[df.frame == 3].iloc[0]
    assert np.isnan(low.x_cm) and np.isnan(low.z_cm)
    assert df.z_cm.isna().sum() == 1


def test_a_metadata_column_named_z_cm_warns_and_the_tracked_z_wins(
    project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from track2data.core.models import MappingRule, MetadataSource

    csv = tmp_path / "meta.csv"
    pd.DataFrame({"session_id": ["fish1"], "z_cm": [99.0]}).to_csv(csv, index=False)
    manifest = _manifest(project, None).model_copy(
        update={
            "metadata_source": MetadataSource(path=csv, sha256="unused"),
            "mapping": MappingRule(rules={}, extra_columns=["z_cm"]),
        }
    )
    engine = Engine(manifest)
    psess = engine.apply_calibration_and_zones(engine.preprocess_ref(manifest.sessions[0]))
    with caplog.at_level(logging.WARNING):
        df = engine.build_fish_by_frame(psess)
    assert "metadata column 'z_cm' is ignored in the per-frame table" in caplog.text
    assert not (df["z_cm"] == 99.0).any()


def test_a_non_native_session_gets_no_z_column(tmp_path: Path) -> None:
    from tests.test_fusion.scene import build_scene

    engine = Engine(build_scene(tmp_path / "data"))
    fused = engine.fuse_pair(engine._manifest.view_pairs[0])
    assert "z_cm" not in engine.build_fish_by_frame(fused.psess).columns


def test_a_wide_only_run_of_a_native_project_carries_z_cm(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "o"
    Engine(_manifest(project, None)).run(out, exporters=["csv_wide"])
    df = pd.read_csv(out / "fish1" / "master_fish_by_frame.csv")
    np.testing.assert_allclose(df["z_cm"].to_numpy(), np.arange(11) * 1.2, atol=1e-9)
    assert (out / "fish1" / "trial_summary_wide.csv").exists()
