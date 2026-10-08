"""A DeepLabCut file through the real pipeline: saved reader, run, export.

What is checked is the seam between the new reader and everything that was written for
idtracker.ai: the cache, the metadata join, the per-session output folder, and an export that
says where the numbers came from (software, options, which keypoint stood for the animal).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

OPTIONS = {"fps": 25.0, "width_px": 640, "height_px": 480, "keypoint": "snout"}


@pytest.fixture
def dlc_file(tmp_path: Path) -> Path:
    return write_dlc_csv(
        tmp_path / "in" / "trial1DLC.csv",
        random_pose(120, 2, 3),
        bodyparts=["snout", "tail", "ear"],
        individuals=["mouseA", "mouseB"],
    )


def _engine(path: Path, cache_dir: Path | None = None) -> Engine:
    now = datetime.now(tz=UTC)
    return Engine(
        ProjectManifest(
            project_name="dlc",
            created_at=now,
            updated_at=now,
            sessions=[
                SessionRef(
                    session_id="trial1",
                    folder=path,
                    sha256="",
                    reader="deeplabcut",
                    reader_options=dict(OPTIONS),
                    reader_chosen_by="detected",
                    reader_confidence="HIGH",
                )
            ],
            calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
            metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
        ),
        cache_dir=cache_dir,
    )


def test_the_project_runs_end_to_end(dlc_file: Path, tmp_path: Path) -> None:
    engine = _engine(dlc_file)
    assert engine.validate() == []
    result = engine.run(tmp_path / "out", exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]
    assert any((tmp_path / "out" / "trial1").glob("*.csv"))


def test_the_export_says_which_keypoint_stood_for_the_animal(
    dlc_file: Path, tmp_path: Path
) -> None:
    _engine(dlc_file).run(tmp_path / "out", exporters=["csv_long", "readme"])
    text = (tmp_path / "out" / "trial1" / "README.md").read_text("utf-8")
    assert "| Software | DeepLabCut" in text
    assert "keypoint `snout` (chosen by the user" in text
    assert "`trial1DLC.csv`" in text and "fps=25.0" in text


def test_the_identity_diagnostic_is_not_assessed_for_a_tracker_with_no_identification_score(
    dlc_file: Path, tmp_path: Path
) -> None:
    result = _engine(dlc_file).run(tmp_path / "out", exporters=["csv_long"])
    d5 = result.sessions[0].diagnostics["D-5"]
    assert d5["identity_stability_status"].iloc[0] == "not_assessed"


def test_the_manifest_json_names_the_keypoint(dlc_file: Path, tmp_path: Path) -> None:
    _engine(dlc_file).run(tmp_path / "out", exporters=["csv_long", "readme"])
    manifest = json.loads((tmp_path / "out" / "trial1" / "manifest.json").read_text("utf-8"))
    prov = manifest["run_metadata"]["session_provenance"]
    assert prov["keypoint_selection"]["keypoint"] == "snout"
    assert prov["keypoint_selection"]["n_keypoints"] == 3


def test_an_edited_file_is_not_served_from_the_cache(dlc_file: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    ref = _engine(dlc_file, cache).manifest.sessions[0]
    first = _engine(dlc_file, cache).preprocess_ref(ref).session
    same = _engine(dlc_file, cache).preprocess_ref(ref).session
    assert np.array_equal(first.raw_xy, same.raw_xy, equal_nan=True)  # the cache serves it

    write_dlc_csv(
        dlc_file,
        random_pose(120, 2, 3, seed=9),
        bodyparts=["snout", "tail", "ear"],
        individuals=["mouseA", "mouseB"],
    )
    edited = _engine(dlc_file, cache).preprocess_ref(ref).session

    assert not np.allclose(first.raw_xy, edited.raw_xy, equal_nan=True)


def test_two_different_files_never_share_a_cache_entry(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    names = ["snout", "tail", "ear"]
    a = write_dlc_csv(tmp_path / "a.csv", random_pose(60, 1, 3, seed=1), bodyparts=names)
    b = write_dlc_csv(tmp_path / "b.csv", random_pose(60, 1, 3, seed=2), bodyparts=names)
    sa = _engine(a, cache).preprocess_ref(_engine(a, cache).manifest.sessions[0]).session
    sb = _engine(b, cache).preprocess_ref(_engine(b, cache).manifest.sessions[0]).session
    assert not np.allclose(sa.raw_xy, sb.raw_xy, equal_nan=True)
