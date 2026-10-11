"""A bare idtracker.ai export through `add` and `validate` (no session.json, no video size).

Public idtracker.ai samples carry no video size, and the older pickled ones need consent. A user
must be able to give both from the command line, and `validate` must say what is missing before
`run` fails on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest
from track2data.core.models import ProjectManifest

TRAJ = "x1,y1,x2,y2\n" + "".join(f"{i},{i + 1},{i + 2},{i + 3}\n" for i in range(40))
SIZE = ["--option=width_px=640", "--option=height_px=480", "--option=fps=25"]


def invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


@pytest.fixture
def csv_root(tmp_path: Path) -> Path:
    d = tmp_path / "data" / "bare" / "trajectories" / "trajectories_csv"
    d.mkdir(parents=True)
    (d / "trajectories.csv").write_text(TRAJ)
    return tmp_path / "data" / "bare"


@pytest.fixture
def pickled_root(tmp_path: Path) -> Path:
    d = tmp_path / "data" / "old" / "trajectories"
    d.mkdir(parents=True)
    xy = np.arange(40 * 2 * 2, dtype=float).reshape(40, 2, 2)
    payload = {"trajectories": xy, "frames_per_second": 25.0}
    np.save(d / "trajectories.npy", payload, allow_pickle=True)
    return tmp_path / "data" / "old"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    now = datetime.now(tz=UTC)
    path = tmp_path / "p.t2d.json"
    manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now)
    manifest.metrics.individual = ["IL-1"]
    write_manifest(manifest, path)
    return path


def test_add_accepts_the_idtrackerai_video_options(csv_root: Path, project: Path) -> None:
    out = invoke("add", str(project), str(csv_root), "--yes", *SIZE)
    assert out.exit_code == 0, out.output
    ref = read_manifest(project).sessions[0]
    assert ref.reader == "idtrackerai"
    assert ref.reader_options == {"width_px": 640, "height_px": 480, "fps": 25.0}


def test_validate_reports_a_missing_video_size_before_run(csv_root: Path, project: Path) -> None:
    assert invoke("add", str(project), str(csv_root), "--yes").exit_code == 0
    out = invoke("validate", str(project))
    assert out.exit_code == 1
    assert "bare" in out.output and "IDT_DICT_MISSING_KEY" in out.output


def test_validate_passes_once_the_options_are_given(csv_root: Path, project: Path) -> None:
    assert invoke("add", str(project), str(csv_root), "--yes", *SIZE).exit_code == 0
    out = invoke("validate", str(project))
    assert out.exit_code == 0, out.output
    assert "ready to run" in out.output


def test_validate_reports_session_problems_even_when_no_metric_is_selected(
    csv_root: Path, project: Path
) -> None:
    assert invoke("add", str(project), str(csv_root), "--yes").exit_code == 0
    manifest = read_manifest(project)
    manifest.metrics.individual = []
    write_manifest(manifest, project)
    out = invoke("validate", str(project))
    assert out.exit_code == 1
    assert "No metrics selected" in out.output and "IDT_DICT_MISSING_KEY" in out.output


def test_validate_reports_a_pickle_that_has_no_consent(pickled_root: Path, project: Path) -> None:
    size = ["--option=width_px=640", "--option=height_px=480"]
    assert invoke("add", str(project), str(pickled_root), "--yes", *size).exit_code == 0
    out = invoke("validate", str(project))
    assert out.exit_code == 1
    assert "IDT_PICKLE_REFUSED" in out.output


def test_add_allow_pickle_records_the_consent_in_the_project(
    pickled_root: Path, project: Path
) -> None:
    size = ["--option=width_px=640", "--option=height_px=480"]
    out = invoke("add", str(project), str(pickled_root), "--yes", "--allow-pickle", *size)
    assert out.exit_code == 0, out.output
    assert read_manifest(project).security.allow_pickle_trajectories is True
    assert "executes code" in out.output  # the consequence is stated, not hidden
    assert invoke("validate", str(project)).exit_code == 0


def test_add_without_the_flag_leaves_consent_off(pickled_root: Path, project: Path) -> None:
    invoke("add", str(project), str(pickled_root), "--yes")
    assert read_manifest(project).security.allow_pickle_trajectories is False
