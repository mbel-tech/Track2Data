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


# ── individual metric merge key tests ─────────────────────────────────────────


def _payload_with(individual_metrics: dict[str, pd.DataFrame]) -> ExportPayload:
    return ExportPayload(
        session_id="sess1",
        project_name="TestProject",
        project_hash="abcd1234efgh5678",
        app_version="0.1.0",
        fish_by_frame=_make_fish_frame_df(),
        individual_metrics=individual_metrics,
        group_metrics={},
        zone_metrics={},
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json="{}",
    )


class TestFeatherIndividualMetricMergeKeys:
    """Individual metric frames must be joined on identity keys only, never on
    whatever column names two metrics happen to share.

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
        exporter = FeatherExporter()
        exporter.write(_payload_with(individual_metrics), tmp_path)
        df = pd.read_feather(tmp_path / "trial_activity_summary.feather")
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
        exporter = FeatherExporter()
        exporter.write(_payload_with(individual_metrics), tmp_path)
        df = pd.read_feather(tmp_path / "trial_activity_summary.feather")
        row0 = df[df["individual_id"] == 0]
        assert len(row0) == 1
        assert row0.iloc[0]["path_length_px"] == 100.0
        assert row0.iloc[0]["mean_speed_px_s"] == 10.0

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
        exporter = FeatherExporter()
        exporter.write(_payload_with(individual_metrics), tmp_path)
        df = pd.read_feather(tmp_path / "trial_activity_summary.feather")
        assert len(df) == 2
        row1 = df[df["individual_id"] == 1].iloc[0]
        assert row1["path_length_px"] == 200.0
        assert row1["mean_speed_px_s"] == 20.0

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
        exporter = FeatherExporter()
        exporter.write(_payload_with(individual_metrics), tmp_path)
        df = pd.read_feather(tmp_path / "trial_activity_summary.feather")
        assert len(df) == 2
        row0 = df[df["individual_id"] == 0].iloc[0]
        for i in range(1, 5):
            assert row0[f"value_{i}"] == float(i)
