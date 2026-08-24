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

    def test_writes_master_fish_by_frame(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "master_fish_by_frame.csv" for p in paths)

    def test_master_csv_exists_on_disk(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "master_fish_by_frame.csv").exists()

    def test_master_csv_has_session_id_column(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
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

    def test_writes_activity_summary(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "trial_activity_summary.csv" for p in paths)

    def test_writes_group_dynamics_summary(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "group_dynamics_summary.csv" for p in paths)

    def test_returns_list_of_paths(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_utf8_encoding(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
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
        exporter.write(payload, tmp_path)
        summary_path = tmp_path / "trial_activity_summary.csv"
        assert summary_path.exists()

    def test_all_returned_paths_exist(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = CsvLongExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        for p in paths:
            assert p.exists(), f"{p} does not exist"


# ── metric merge key tests ────────────────────────────────────────────────────


def _payload_with(
    individual_metrics: dict[str, pd.DataFrame] | None = None,
    group_metrics: dict[str, pd.DataFrame] | None = None,
) -> ExportPayload:
    return ExportPayload(
        session_id="sess1",
        project_name="TestProject",
        project_hash="abcd1234efgh5678",
        app_version="0.1.0",
        fish_by_frame=_make_fish_frame_df(),
        individual_metrics=individual_metrics if individual_metrics is not None else {},
        group_metrics=group_metrics if group_metrics is not None else {},
        zone_metrics={},
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json="{}",
    )


class TestCsvLongMetricMergeKeys:
    """Metric frames must be joined on identity keys only, never on whatever
    column names two metrics happen to share.

    Every shipped metric emits a ``metric_id`` column holding its *own* id, so
    joining on all shared column names means joining IL-1 rows to IL-2 rows on
    a key that can never match — one individual is split across several
    half-empty rows instead of being widened into one.
    """

    def test_individual_metrics_sharing_incidental_column_produce_one_row_per_individual(
        self, tmp_path: Path
    ) -> None:
        individual_metrics = {
            "IL-1": pd.DataFrame(
                {
                    "session_id": ["sess1", "sess1"],
                    "individual_id": [0, 1],
                    "n_frames": [100, 100],
                    "path_length_px": [100.0, 200.0],
                }
            ),
            "IL-2": pd.DataFrame(
                {
                    "session_id": ["sess1", "sess1"],
                    "individual_id": [0, 1],
                    "n_frames": [90, 80],
                    "mean_speed_px_s": [10.0, 20.0],
                }
            ),
        }
        exporter = CsvLongExporter()
        exporter.write(_payload_with(individual_metrics=individual_metrics), tmp_path)
        df = pd.read_csv(tmp_path / "trial_activity_summary.csv")
        assert len(df) == 2

    def test_individual_metrics_sharing_incidental_column_keep_values_on_one_row(
        self, tmp_path: Path
    ) -> None:
        individual_metrics = {
            "IL-1": pd.DataFrame(
                {
                    "session_id": ["sess1", "sess1"],
                    "individual_id": [0, 1],
                    "n_frames": [100, 100],
                    "path_length_px": [100.0, 200.0],
                }
            ),
            "IL-2": pd.DataFrame(
                {
                    "session_id": ["sess1", "sess1"],
                    "individual_id": [0, 1],
                    "n_frames": [90, 80],
                    "mean_speed_px_s": [10.0, 20.0],
                }
            ),
        }
        exporter = CsvLongExporter()
        exporter.write(_payload_with(individual_metrics=individual_metrics), tmp_path)
        df = pd.read_csv(tmp_path / "trial_activity_summary.csv")
        row0 = df[df["individual_id"] == 0]
        assert len(row0) == 1
        assert row0.iloc[0]["path_length_px"] == pytest.approx(100.0)
        assert row0.iloc[0]["mean_speed_px_s"] == pytest.approx(10.0)

    def test_individual_metrics_carrying_metric_id_produce_one_row_per_individual(
        self, tmp_path: Path
    ) -> None:
        individual_metrics = {
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
        exporter = CsvLongExporter()
        exporter.write(_payload_with(individual_metrics=individual_metrics), tmp_path)
        df = pd.read_csv(tmp_path / "trial_activity_summary.csv")
        assert len(df) == 2
        row1 = df[df["individual_id"] == 1].iloc[0]
        assert row1["path_length_px"] == pytest.approx(200.0)
        assert row1["mean_speed_px_s"] == pytest.approx(20.0)

    def test_four_individual_metrics_carrying_metric_id_merge_into_one_row_per_individual(
        self, tmp_path: Path
    ) -> None:
        """Four metrics is the case a keys-only fix that still lets ``metric_id``
        reach the merge cannot survive: the second collision would need the
        ``_x``/``_y`` suffixes pandas already handed out, and pandas raises."""
        individual_metrics = {
            f"IL-{i}": pd.DataFrame(
                {
                    "session_id": ["sess1", "sess1"],
                    "individual_id": [0, 1],
                    "metric_id": [f"IL-{i}", f"IL-{i}"],
                    f"value_{i}": [float(i), float(i) * 2],
                }
            )
            for i in range(1, 5)
        }
        exporter = CsvLongExporter()
        exporter.write(_payload_with(individual_metrics=individual_metrics), tmp_path)
        df = pd.read_csv(tmp_path / "trial_activity_summary.csv")
        assert len(df) == 2
        row0 = df[df["individual_id"] == 0].iloc[0]
        for i in range(1, 5):
            assert row0[f"value_{i}"] == pytest.approx(float(i))

    def test_group_metrics_carrying_metric_id_produce_one_row_per_session(
        self, tmp_path: Path
    ) -> None:
        group_metrics = {
            "GL-1": pd.DataFrame(
                {
                    "session_id": ["sess1"],
                    "metric_id": ["GL-1"],
                    "mean_nnd_px": [5.0],
                }
            ),
            "GL-3": pd.DataFrame(
                {
                    "session_id": ["sess1"],
                    "metric_id": ["GL-3"],
                    "mean_polarisation": [0.5],
                }
            ),
        }
        exporter = CsvLongExporter()
        exporter.write(_payload_with(group_metrics=group_metrics), tmp_path)
        df = pd.read_csv(tmp_path / "group_dynamics_summary.csv")
        assert len(df) == 1
        assert df.iloc[0]["mean_nnd_px"] == pytest.approx(5.0)
        assert df.iloc[0]["mean_polarisation"] == pytest.approx(0.5)
