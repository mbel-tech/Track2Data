"""Shared metric-frame merge: key columns only, no _x/_y for duplicated metadata."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track2data.exporters._merge import merge_metric_frames


def _frames(treatment_b: str = "ctrl") -> dict[str, pd.DataFrame]:
    return {
        "IL-1": pd.DataFrame(
            {"session_id": ["s", "s"], "individual_id": [0, 1], "metric_id": "IL-1",
             "path": [1.0, 2.0], "treatment": "ctrl"}
        ),
        "IL-2": pd.DataFrame(
            {"session_id": ["s", "s"], "individual_id": [0, 1], "metric_id": "IL-2",
             "speed": [3.0, 4.0], "treatment": treatment_b}
        ),
    }


def test_identical_shared_column_is_kept_once() -> None:
    out = merge_metric_frames(_frames())
    assert list(out.columns) == ["session_id", "individual_id", "path", "treatment", "speed"]
    assert len(out) == 2


def test_differing_shared_column_is_not_silently_dropped() -> None:
    out = merge_metric_frames(_frames(treatment_b="drug"))
    assert {"treatment_x", "treatment_y"} <= set(out.columns)


def test_nan_equals_nan_when_deciding_a_column_is_a_duplicate() -> None:
    frames = _frames()
    for df in frames.values():
        df["weight"] = np.nan
    out = merge_metric_frames(frames)
    assert "weight" in out.columns and "weight_x" not in out.columns


def test_bin_index_is_a_key_when_both_frames_have_it() -> None:
    a = pd.DataFrame({"session_id": "s", "individual_id": [0, 0], "bin_index": [0, 1], "p": [1, 2]})
    b = pd.DataFrame({"session_id": "s", "individual_id": [0, 0], "bin_index": [0, 1], "q": [3, 4]})
    out = merge_metric_frames({"A": a, "B": b})
    assert len(out) == 2  # no row multiplication
    assert list(out["q"]) == [3, 4]


def test_group_frames_merge_on_session_id() -> None:
    a = pd.DataFrame({"session_id": ["s", "t"], "x": [1, 2]})
    b = pd.DataFrame({"session_id": ["s", "t"], "y": [3, 4]})
    out = merge_metric_frames({"A": a, "B": b})
    assert list(out.columns) == ["session_id", "x", "y"] and len(out) == 2


def test_empty_input() -> None:
    assert merge_metric_frames({}).empty


def test_frames_without_shared_keys_are_concatenated_sideways() -> None:
    a = pd.DataFrame({"x": [1, 2]})
    b = pd.DataFrame({"y": [3, 4]})
    out = merge_metric_frames({"A": a, "B": b})
    assert list(out.columns) == ["x", "y"]


@pytest.mark.parametrize("module", ["csv_long", "csv_wide", "feather", "excel"])
def test_every_exporter_uses_the_shared_merge(module: str, tmp_path) -> None:
    import importlib

    mod = importlib.import_module(f"track2data.exporters.{module}")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "merge_metric_frames" in src


def test_exports_with_metadata_and_two_metrics_have_no_suffixed_columns(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """The original bug: metadata broadcast onto each metric frame produced
    treatment_x / treatment_y in every multi-metric export."""
    import shutil
    from datetime import UTC, datetime

    from track2data.api import Engine
    from track2data.core.models import (
        CalibrationConfig,
        MappingRule,
        MetadataSource,
        MetricSelection,
        ProjectManifest,
        SessionRef,
    )

    folder = tmp_path / "sess"
    shutil.copytree(tiny_real_session, folder)
    meta = tmp_path / "meta.csv"
    meta.write_text("session_id,treatment\nsess,ctrl\n", encoding="utf-8")
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p", created_at=now, updated_at=now,
        sessions=[SessionRef(session_id="sess", folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-2"], group=["GL-1", "GL-2"]),
        metadata_source=MetadataSource(path=meta, sha256="x"),
        mapping=MappingRule(rules={"session_id": "session_id", "treatment": "treatment"}),
    )
    out = tmp_path / "out"
    result = Engine(manifest).run(out, exporters=["csv_long", "csv_wide", "feather", "excel"])
    assert result.sessions[0].error is None
    for csv in out.rglob("*.csv"):
        cols = pd.read_csv(csv, nrows=1).columns
        assert not [c for c in cols if c.endswith(("_x", "_y"))], (csv.name, list(cols))
    sheet = pd.read_excel(next(out.rglob("*.xlsx")), sheet_name="Activity Summary")
    assert not [c for c in sheet.columns if str(c).endswith(("_x", "_y"))]
    assert len(sheet) == 2
    assert sheet["path_length_px"].notna().all() and sheet["mean_speed_px_s"].notna().all()


class TestBinnedAfterWholeSession:
    """A whole-session frame (NaN bins) merged with a binned one must keep the bin boundaries."""

    def _frames(self) -> dict[str, pd.DataFrame]:
        nan = np.nan
        return {
            "whole": pd.DataFrame(
                {"session_id": ["s"], "individual_id": [0], "bin_index": [nan],
                 "bin_start_s": [nan], "bin_end_s": [nan], "total": [9.0]}
            ),
            "binned": pd.DataFrame(
                {"session_id": ["s", "s"], "individual_id": [0, 0], "bin_index": [0, 1],
                 "bin_start_s": [0.0, 60.0], "bin_end_s": [60.0, 120.0], "path": [1.0, 2.0]}
            ),
        }

    def test_the_bin_boundaries_survive_in_either_order(self) -> None:
        frames = self._frames()
        for order in (list(frames), list(reversed(list(frames)))):
            out = merge_metric_frames({k: frames[k] for k in order})
            binned = out[out["bin_index"].notna()].sort_values("bin_index")
            assert list(binned["bin_start_s"]) == [0.0, 60.0]
            assert list(binned["bin_end_s"]) == [60.0, 120.0]
            assert list(binned["path"]) == [1.0, 2.0]

    def test_a_row_only_the_second_frame_has_is_filled_from_it(self) -> None:
        frames = {
            "a": pd.DataFrame(
                {"session_id": ["s"], "individual_id": [0], "treatment": ["ctrl"], "x": [1.0]}
            ),
            "b": pd.DataFrame(
                {"session_id": ["s", "s"], "individual_id": [0, 1], "treatment": "ctrl",
                 "y": [2.0, 3.0]}
            ),
        }
        out = merge_metric_frames(frames)
        assert list(out["treatment"]) == ["ctrl", "ctrl"]
        assert "treatment_x" not in out.columns
