"""Tests for CsvLongExporter — TDD RED."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from track2data.core.models import PreprocessReport
from track2data.exporters.base import ExportPayload
from track2data.exporters.csv_long import CsvLongExporter


# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_fish_frame_df() -> pd.DataFrame:
    """Minimal per-frame DataFrame with 3 rows in shuffled order."""
    return pd.DataFrame(
        {
            "session_id": ["sess1", "sess1", "sess1"],
            "individual_id": [1, 0, 0],
            "frame": [2, 1, 0],
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
                "mean_speed_cm_s": [1.5, 2.0],
            }
        )
    }


def _make_group_metrics() -> dict[str, pd.DataFrame]:
    return {
        "GL-1": pd.DataFrame(
            {
                "session_id": ["sess1"],
                "mean_NN_dist_cm": [5.0],
            }
        )
    }


@pytest.fixture()
def minimal_payload() -> ExportPayload:
    return ExportPayload(
        session_id="sess1",
        project_name="TestProject",
        project_hash="abcd1234efgh5678",
        app_version="0.1.0",
        fish_by_frame=_make_fish_frame_df(),
        individual_metrics=_make_individual_metrics(),
        group_metrics=_make_group_metrics(),
        zone_metrics={},
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json=json.dumps({"schema_version": 1, "project_name": "TestProject"}),
    )


# ── CsvLongExporter tests ─────────────────────────────────────────────────────


class TestCsvLongExporter:
    def test_exporter_name(self) -> None:
        assert CsvLongExporter.name == "csv_long"

    def test_exporter_extension(self) -> None:
        assert CsvLongExporter.file_extension == ".csv"

    def test_writes_master_fish_by_frame(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "master_fish_by_frame.csv" for p in paths)

    def test_master_csv_exists_on_disk(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "master_fish_by_frame.csv").exists()

    def test_master_csv_has_session_id_column(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        exporter.write(minimal_payload, tmp_path)
        df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")
        assert "session_id" in df.columns

    def test_csv_sorted_by_session_individual_frame(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        """Output must be sorted by session_id, individual_id, frame."""
        exporter = CsvLongExporter()
        exporter.write(minimal_payload, tmp_path)
        df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")
        # After sort: (sess1,0,0), (sess1,0,1), (sess1,1,2)
        expected_frames = [0, 1, 2]
        assert list(df["frame"]) == expected_frames

    def test_writes_activity_summary(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "trial_activity_summary.csv" for p in paths)

    def test_writes_group_dynamics_summary(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "group_dynamics_summary.csv" for p in paths)

    def test_returns_list_of_paths(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_utf8_encoding(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        exporter.write(minimal_payload, tmp_path)
        raw = (tmp_path / "master_fish_by_frame.csv").read_bytes()
        # Should not have BOM
        assert not raw.startswith(b"\xff\xfe")
        assert not raw.startswith(b"\xef\xbb\xbf")

    def test_empty_individual_metrics_writes_empty_summary(
        self, tmp_path: Path
    ) -> None:
        payload = ExportPayload(
            session_id="s",
            project_name="P",
            project_hash="a" * 16,
            app_version="0.1.0",
            fish_by_frame=pd.DataFrame({"session_id": [], "individual_id": [], "frame": []}),
            individual_metrics={},
            group_metrics={},
            zone_metrics={},
            diagnostic_metrics={},
            preprocess_report=PreprocessReport(),
            manifest_json="{}",
        )
        exporter = CsvLongExporter()
        paths = exporter.write(payload, tmp_path)
        summary_path = tmp_path / "trial_activity_summary.csv"
        assert summary_path.exists()

    def test_all_returned_paths_exist(self, tmp_path: Path, minimal_payload: ExportPayload) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        for p in paths:
            assert p.exists(), f"{p} does not exist"
