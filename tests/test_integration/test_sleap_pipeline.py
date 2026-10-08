"""A SLEAP analysis file through the real pipeline: saved reader, run, export, cache.

Named tracks give per-individual metrics; an untracked project (positional slots) is
identity-free by construction and the pipeline must say so rather than compute per-animal numbers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.support.sleap import random_tracks, write_sleap_analysis
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

NODES = ["snout", "centre", "tail"]
OPTIONS = {"fps": 30.0, "width_px": 640, "height_px": 480, "keypoint": "centre"}


def _engine(path: Path, cache_dir: Path | None = None) -> Engine:
    now = datetime.now(tz=UTC)
    return Engine(
        ProjectManifest(
            project_name="sleap",
            created_at=now,
            updated_at=now,
            sessions=[
                SessionRef(
                    session_id="trial1",
                    folder=path,
                    sha256="",
                    reader="sleap_analysis",
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


@pytest.fixture
def named(tmp_path: Path) -> Path:
    return write_sleap_analysis(
        tmp_path / "in" / "trial1.analysis.h5",
        random_tracks(120, 2, 3),
        node_names=NODES,
        track_names=["mouseA", "mouseB"],
    )


def test_the_project_runs_end_to_end(named: Path, tmp_path: Path) -> None:
    engine = _engine(named)
    assert engine.validate() == []
    result = engine.run(tmp_path / "out", exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]
    assert any((tmp_path / "out" / "trial1").glob("*.csv"))


def test_the_export_names_the_software_and_the_node(named: Path, tmp_path: Path) -> None:
    _engine(named).run(tmp_path / "out", exporters=["csv_long", "readme"])
    text = (tmp_path / "out" / "trial1" / "README.md").read_text("utf-8")
    assert "| Software | SLEAP (analysis HDF5)" in text
    assert "keypoint `centre` (chosen by the user" in text
    assert "`trial1.analysis.h5`" in text


def test_the_manifest_json_names_the_node(named: Path, tmp_path: Path) -> None:
    _engine(named).run(tmp_path / "out", exporters=["csv_long", "readme"])
    manifest = json.loads((tmp_path / "out" / "trial1" / "manifest.json").read_text("utf-8"))
    prov = manifest["run_metadata"]["session_provenance"]
    assert prov["keypoint_selection"]["keypoint"] == "centre"
    assert prov["keypoint_selection"]["n_keypoints"] == 3


def test_an_untracked_project_is_identity_free_and_says_so(tmp_path: Path) -> None:
    path = write_sleap_analysis(
        tmp_path / "in" / "trial1.analysis.h5",
        random_tracks(120, 3, 3),
        node_names=NODES,
        track_names=None,
    )
    engine = _engine(path)
    session = engine.import_ref(engine.manifest.sessions[0])
    assert session.has_stable_identities is False and session.track_wo_identities is True
    result = engine.run(tmp_path / "out", exporters=["csv_long", "readme"])
    text = (tmp_path / "out" / "trial1" / "README.md").read_text("utf-8")
    assert [r.error for r in result.sessions] == [None]
    assert "Treated as identity-free | True" in text


def test_an_edited_file_is_not_served_from_the_cache(named: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    ref = _engine(named, cache).manifest.sessions[0]
    first = _engine(named, cache).preprocess_ref(ref).session
    write_sleap_analysis(
        named, random_tracks(120, 2, 3, seed=9), node_names=NODES, track_names=["mouseA", "mouseB"]
    )
    edited = _engine(named, cache).preprocess_ref(ref).session
    assert not np.allclose(first.raw_xy, edited.raw_xy, equal_nan=True)
