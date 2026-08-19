"""Tests for ReadmeExporter and ExcelExporter — TDD RED."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from track2data.core.models import PreprocessReport
from track2data.exporters.base import ExportPayload
from track2data.exporters.readme import ReadmeExporter

# ── shared fixture ─────────────────────────────────────────────────────────────


@pytest.fixture()
def minimal_payload() -> ExportPayload:
    fish_df = pd.DataFrame(
        {
            "session_id": ["s1", "s1"],
            "individual_id": [0, 1],
            "frame": [0, 0],
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
        }
    )
    return ExportPayload(
        session_id="s1",
        project_name="MyProject",
        project_hash="1234567890abcdef",
        app_version="0.1.0",
        fish_by_frame=fish_df,
        individual_metrics={
            "IL-1": pd.DataFrame({"session_id": ["s1"], "individual_id": [0], "val": [1.0]})
        },
        group_metrics={"GL-1": pd.DataFrame({"session_id": ["s1"], "metric": [2.0]})},
        zone_metrics={
            "Z-1": pd.DataFrame({"session_id": ["s1"], "zone_name": ["A"], "time_s": [1.0]})
        },
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json=json.dumps({"schema_version": 1, "project_name": "MyProject"}),
    )


# ── ReadmeExporter ────────────────────────────────────────────────────────────


class TestReadmeExporter:
    def test_exporter_name(self) -> None:
        assert ReadmeExporter.name == "readme"

    def test_exporter_extension(self) -> None:
        assert ReadmeExporter.file_extension == ".md"

    def test_writes_readme_md(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "README.md" for p in paths)

    def test_readme_exists_on_disk(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "README.md").exists()

    def test_readme_contains_project_name(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "MyProject" in content

    def test_readme_contains_app_version(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "0.1.0" in content

    def test_readme_contains_project_hash(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "1234567890abcdef" in content

    def test_readme_contains_metric_ids(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "IL-1" in content
        assert "GL-1" in content

    def test_writes_manifest_json(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "manifest.json" for p in paths)

    def test_manifest_json_exists_on_disk(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "manifest.json").exists()

    def test_manifest_json_is_valid_json(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_manifest_contains_project_name(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data.get("project_name") == "MyProject"

    def test_returns_two_paths(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert len(paths) == 2

    def test_all_paths_exist(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        for p in paths:
            assert p.exists(), f"{p} does not exist"
