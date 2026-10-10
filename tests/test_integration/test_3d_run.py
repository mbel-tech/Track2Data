"""A 3-D project end to end: real v5 session folders with a known depth, run serially and across
two worker processes, exported, and read back."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_fusion.scene import (
    DEPTHS,
    LABELS,
    N_FRAMES,
    TANK_CM,
    build_scene,
)
from track2data.api import Engine
from track2data.core.models import ProjectMode

EXPORTERS = ["csv_long", "csv_wide", "feather", "readme"]
_STAMP = re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+\+00:00")
OLD_SESSIONS_HEADER = (
    "session_id,reader,fps,n_frames,duration_s,n_animals,width_px,height_px,calibration_mode,"
    "length_unit,px_per_cm,is_calibrated,is_identity_free,trajectory_source,trajectory_sha256,"
    "error,length_calibration_n,length_calibration_rel_sd"
)


def _files(root: Path) -> dict[str, bytes]:
    """Every written file's bytes with the "generated at" stamps masked."""
    return {
        str(p.relative_to(root)): _STAMP.sub(b"<time>", p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("e2e3d")
    manifest = build_scene(base / "data")
    Engine(manifest).run(base / "serial", exporters=EXPORTERS)
    Engine(manifest).run(base / "parallel", exporters=EXPORTERS, n_workers=2)
    return base / "serial", base / "parallel"


def test_serial_and_parallel_runs_write_identical_files(runs: tuple[Path, Path]) -> None:
    serial, parallel = (_files(r) for r in runs)
    assert serial.keys() == parallel.keys()
    assert [n for n in serial if serial[n] != parallel[n]] == []
    assert {n.split("/")[0] for n in serial} >= {"t1+s1", "t2+s2", "sessions.csv", "skipped.csv"}
    assert not any(n.startswith(("t1/", "s1/", "t2/", "s2/", "lone/")) for n in serial)


def test_exported_depth_matches_the_scene(runs: tuple[Path, Path]) -> None:
    for unit in ("t1+s1", "t2+s2"):
        frames = pd.read_csv(runs[0] / unit / "master_fish_by_frame.csv")
        assert {"depth_fraction", "depth_cm"} <= set(frames.columns)
        assert len(frames) == N_FRAMES * len(LABELS)
        by_fish = frames.groupby("individual_id")["depth_fraction"].mean()
        np.testing.assert_allclose(by_fish.to_numpy(), DEPTHS, atol=0.02)
        np.testing.assert_allclose(
            frames["depth_cm"], frames["depth_fraction"] * TANK_CM, equal_nan=True
        )


def test_il15_mean_depth_cm_matches_the_scene(runs: tuple[Path, Path]) -> None:
    long = pd.read_csv(runs[0] / "t1+s1" / "metrics_long.csv")
    rows = long[(long["metric_id"] == "IL-15") & (long["column"] == "mean_depth_cm")]
    got = rows.sort_values("individual_id")["value"].to_numpy(dtype=float)
    np.testing.assert_allclose(got, np.array(DEPTHS) * TANK_CM, rtol=0.05)


def test_the_unpaired_session_is_listed_with_its_reason(runs: tuple[Path, Path]) -> None:
    skipped = pd.read_csv(runs[0] / "skipped.csv")
    assert skipped.to_dict("records") == [{"session_id": "lone", "reason": "not in a fusable pair"}]
    summary = (runs[0] / "PROJECT_SUMMARY.md").read_text(encoding="utf-8")
    assert "## Skipped sessions" in summary and "not in a fusable pair" in summary


def test_the_readme_and_sessions_table_carry_the_fusion_rows(runs: tuple[Path, Path]) -> None:
    readme = (runs[0] / "t1+s1" / "README.md").read_text(encoding="utf-8")
    assert "## 3-D fusion" in readme
    assert "| Tank height | 20 cm |" in readme
    assert "| Fish fused | 3 |" in readme
    table = pd.read_csv(runs[0] / "sessions.csv")
    assert list(table["session_id"]) == ["t1+s1", "t2+s2"]
    assert set(table["unit_kind"]) == {"pair"}
    assert list(table["top_session_id"]) == ["t1", "t2"]
    assert list(table["side_session_id"]) == ["s1", "s2"]
    assert set(table["fusion_tank_height_cm"]) == {TANK_CM}
    # the fixture reader records no trajectory file, so there is nothing to hash
    assert "side_trajectory_sha256" in table.columns


def test_a_2d_project_is_untouched(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": []}
    )
    out = tmp_path / "out"
    result = Engine(manifest).run(out, exporters=EXPORTERS)
    assert [r.session_id for r in result.sessions] == ["t1", "s1", "t2", "s2", "lone"]
    assert (out / "sessions.csv").read_text(encoding="utf-8").splitlines()[0] == OLD_SESSIONS_HEADER
    assert not (out / "skipped.csv").exists()
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in {".csv", ".md", ".json"}:
            text = path.read_text(encoding="utf-8")
            assert "3-D fusion" not in text and "Skipped sessions" not in text
    frames = pd.read_csv(out / "t1" / "master_fish_by_frame.csv")
    assert "depth_fraction" not in frames.columns and "depth_cm" not in frames.columns
