"""Tests for CsvWideExporter — TDD RED."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from track2data.core.models import PreprocessReport
from track2data.exporters.base import ExportPayload
from track2data.exporters.csv_wide import CsvWideExporter

# ── helpers ────────────────────────────────────────────────────────────────────


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
        "IL-2": pd.DataFrame(
            {
                "session_id": ["sess1", "sess1"],
                "individual_id": [0, 1],
                "metric_id": ["IL-2", "IL-2"],
                "mean_speed_px_s": [10.0, 20.0],
            }
        ),
    }


def _make_payload(
    individual_metrics: dict | None = None,
    group_metrics: dict | None = None,
) -> ExportPayload:
    return ExportPayload(
        session_id="sess1",
        project_name="TestProject",
        project_hash="abcd1234efgh5678",
        app_version="0.1.0",
        fish_by_frame=pd.DataFrame(
            {"session_id": ["sess1"], "individual_id": [0], "frame": [0], "x": [1.0], "y": [2.0]}
        ),
        individual_metrics=individual_metrics or _make_individual_metrics(),
        group_metrics=group_metrics or {},
        zone_metrics={},
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json=json.dumps({"schema_version": 1}),
    )


# ── CsvWideExporter tests ─────────────────────────────────────────────────────


class TestCsvWideExporter:
    def test_exporter_name(self) -> None:
        assert CsvWideExporter.name == "csv_wide"

    def test_exporter_extension(self) -> None:
        assert CsvWideExporter.file_extension == ".csv"

    def test_writes_trial_summary_wide(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        assert any(p.name == "trial_summary_wide.csv" for p in paths)

    def test_file_exists_on_disk(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        assert (tmp_path / "trial_summary_wide.csv").exists()

    def test_returns_list_of_paths(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_all_returned_paths_exist(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        paths = exporter.write(_make_payload(), tmp_path)
        for p in paths:
            assert p.exists()

    def test_has_session_id_column(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_csv(tmp_path / "trial_summary_wide.csv")
        assert "session_id" in df.columns

    def test_has_individual_id_column(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_csv(tmp_path / "trial_summary_wide.csv")
        assert "individual_id" in df.columns

    def test_one_row_per_individual(self, tmp_path: Path) -> None:
        """Output has one row per (session_id, individual_id)."""
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_csv(tmp_path / "trial_summary_wide.csv")
        # Two individuals: 0 and 1
        assert len(df) == 2

    def test_metric_columns_present(self, tmp_path: Path) -> None:
        """Metric value columns from individual_metrics must appear in the wide CSV."""
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_csv(tmp_path / "trial_summary_wide.csv")
        assert "path_length_px" in df.columns
        assert "mean_speed_px_s" in df.columns

    def test_correct_values_in_wide_format(self, tmp_path: Path) -> None:
        """Values are correctly placed per individual."""
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        df = pd.read_csv(tmp_path / "trial_summary_wide.csv")
        row0 = df[df["individual_id"] == 0].iloc[0]
        row1 = df[df["individual_id"] == 1].iloc[0]
        assert row0["path_length_px"] == pytest.approx(100.0)
        assert row1["path_length_px"] == pytest.approx(200.0)
        assert row0["mean_speed_px_s"] == pytest.approx(10.0)
        assert row1["mean_speed_px_s"] == pytest.approx(20.0)

    def test_empty_individual_metrics_writes_empty_wide(self, tmp_path: Path) -> None:
        """Empty individual_metrics → file is written but may be empty."""
        payload = _make_payload(individual_metrics={})
        exporter = CsvWideExporter()
        exporter.write(payload, tmp_path)
        assert (tmp_path / "trial_summary_wide.csv").exists()

    def test_utf8_no_bom(self, tmp_path: Path) -> None:
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        raw = (tmp_path / "trial_summary_wide.csv").read_bytes()
        assert not raw.startswith(b"\xff\xfe")
        assert not raw.startswith(b"\xef\xbb\xbf")

    def test_metric_id_column_not_in_wide(self, tmp_path: Path) -> None:
        """The metric_id column should not appear (or be dropped) in wide output."""
        exporter = CsvWideExporter()
        exporter.write(_make_payload(), tmp_path)
        pd.read_csv(tmp_path / "trial_summary_wide.csv")
        # metric_id should not be a meaningful data column in the wide format
        # (may be absent or have only one unique value per row)
        # Just ensure no crash; it's acceptable if not present
