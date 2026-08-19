"""Tests for FeatherExporter — TDD RED."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from track2data.core.models import PreprocessReport
from track2data.exporters.base import ExportPayload
from track2data.exporters.feather import FeatherExporter

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_fish_frame_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": ["sess1", "sess1", "sess1"],
            "individual_id": [0, 0, 1],
            "frame": [0, 1, 0],
            "x": [1.0, 2.0, 3.0],
            "y": [4.0, 5.0, 6.0],
        }
    )


def _make_individual_metrics() -> dict[str, pd.DataFrame]:
    return {
        "IL-1": pd.DataFrame(
            {
                "session_id": ["sess1", "sess1"],
                "individual_id": [0, 1],
                "metric_id": ["IL-1", "IL-1"],
                "path_length_px": [100.0, 200.0],
            }
        ),
    }


def _make_payload() -> ExportPayload:
    return ExportPayload(
        session_id="sess1",
        project_name="TestProject",
        project_hash="abcd1234efgh5678",
        app_version="0.1.0",
        fish_by_frame=_make_fish_frame_df(),
        individual_metrics=_make_individual_metrics(),
        group_metrics={},
        zone_metrics={},
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json=json.dumps({"schema_version": 1}),
    )


# ── FeatherExporter tests ─────────────────────────────────────────────────────


class TestFeatherExporter:
    def test_exporter_name(self) -> None:
        assert FeatherExporter.name == "feather"

    def test_exporter_extension(self) -> None:
        assert FeatherExporter.file_extension == ".feather"

    def test_returns_list_of_paths(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_all_returned_paths_exist(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        for p in paths:
            assert p.exists()

    def test_writes_master_fish_by_frame_feather(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        assert any(p.name == "master_fish_by_frame.feather" for p in paths)

    def test_master_fish_feather_exists_on_disk(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        exporter.write(_make_payload(), tmp_path)
        assert (tmp_path / "master_fish_by_frame.feather").exists()

    def test_writes_trial_activity_summary_feather(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        assert any(p.name == "trial_activity_summary.feather" for p in paths)

    def test_trial_activity_feather_exists_on_disk(self, tmp_path: Path) -> None:
        exporter = FeatherExporter()
        exporter.write(_make_payload(), tmp_path)
        assert (tmp_path / "trial_activity_summary.feather").exists()

    def test_master_fish_feather_readable(self, tmp_path: Path) -> None:
        """master_fish_by_frame.feather is a valid feather file readable by pandas."""
        exporter = FeatherExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_feather(tmp_path / "master_fish_by_frame.feather")
        assert "session_id" in df.columns
        assert len(df) == 3

    def test_trial_activity_feather_readable(self, tmp_path: Path) -> None:
        """trial_activity_summary.feather is a valid feather file readable by pandas."""
        exporter = FeatherExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_feather(tmp_path / "trial_activity_summary.feather")
        assert len(df) >= 0  # may be empty if no individual metrics

    def test_master_fish_data_round_trip(self, tmp_path: Path) -> None:
        """Data in feather file matches original fish_by_frame DataFrame."""
        exporter = FeatherExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_feather(tmp_path / "master_fish_by_frame.feather")
        assert "individual_id" in df.columns
        assert "frame" in df.columns
        assert set(df["individual_id"].unique()) == {0, 1}

    def test_feather_extensions_in_paths(self, tmp_path: Path) -> None:
        """All returned paths end with .feather."""
        exporter = FeatherExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        for p in paths:
            assert p.suffix == ".feather"

    def test_empty_fish_by_frame_handled(self, tmp_path: Path) -> None:
        """Empty fish_by_frame DataFrame is handled without crash."""
        payload = ExportPayload(
            session_id="s",
            project_name="P",
            project_hash="a" * 16,
            app_version="0.1.0",
            fish_by_frame=pd.DataFrame(
                {"session_id": [], "individual_id": [], "frame": [], "x": [], "y": []}
            ).astype({"session_id": "object", "individual_id": "int64", "frame": "int64"}),
            individual_metrics={},
            group_metrics={},
            zone_metrics={},
            diagnostic_metrics={},
            preprocess_report=PreprocessReport(),
            manifest_json="{}",
        )
        exporter = FeatherExporter()
        exporter.write(payload, tmp_path)
        assert (tmp_path / "master_fish_by_frame.feather").exists()
