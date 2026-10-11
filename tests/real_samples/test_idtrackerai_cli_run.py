"""The public idtracker.ai samples, driven through the command line a user would type.

`test_idtrackerai_samples.py` checks the reader. This file checks the whole path the documentation
claims: `new`, `add` (with the options and consent the files need), `validate`, `run`, and the
files a run writes. Run:  pytest tests/real_samples/test_idtrackerai_cli_run.py -m contract

Video sizes are placeholders (no bare export records one): only the mechanics are tested, so no
value in cm or cm/s is asserted.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest

pytestmark = pytest.mark.contract

H5 = "idtrackerai_test_B.trajectories.h5"
CSV = ("idtrackerai_test_B.trajectories.csv", "idtrackerai_test_B.id_probabilities.csv",
       "idtrackerai_test_B.attributes.json")
NOFPS = ("idtrackerai_synthetic_no_fps.trajectories.csv", "idtrackerai_synthetic_no_fps.id_probabilities.csv")
NPY = "MoveR_sample_1.IdTrackerOutput.2602_ISA3080_Low_5.npy"

#: name -> (files as (fixture, destination), reader options, extra `add` flags, frames, animals)
CASES = {
    "h5": ([(H5, "trajectories/trajectories.h5")], ["width_px=1000", "height_px=1000"], [], 508, 8),
    "csv": (
        [(f, f"trajectories/trajectories_csv/{n}")
         for f, n in zip(CSV, ("trajectories.csv", "id_probabilities.csv", "attributes.json"), strict=True)],
        ["width_px=1000", "height_px=1000"], [], 508, 8,
    ),
    "nofps": (
        [(f, f"trajectories/trajectories_csv/{n}")
         for f, n in zip(NOFPS, ("trajectories.csv", "id_probabilities.csv"), strict=True)],
        ["width_px=1000", "height_px=1000", "fps=28"], [], 4, 2,
    ),
    "moveR_pickled": (
        [(NPY, "trajectories/trajectories.npy")], ["width_px=3840", "height_px=2160"], ["--allow-pickle"], 12033, 20,
    ),
}
METRICS = {"individual": ["IL-1", "IL-2"], "group": ["GL-1"], "diagnostic": ["D-1"]}


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def _project(tmp: Path, name: str, fx) -> tuple[Path, Path]:
    files, *_ = CASES[name]
    session = tmp / "data" / name
    for fixture, dest in files:
        target = session / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fx(fixture), target)
    project = tmp / f"{name}.t2d.json"
    assert _invoke("new", name, "-o", str(project)).exit_code == 0
    manifest = read_manifest(project)
    manifest.metrics.individual, manifest.metrics.group = METRICS["individual"], METRICS["group"]
    manifest.metrics.diagnostic = METRICS["diagnostic"]
    write_manifest(manifest, project)
    return project, session


def _add(project: Path, session: Path, name: str):
    _, options, flags, *_ = CASES[name]
    return _invoke("add", str(project), str(session), "--yes", *[f"--option={o}" for o in options], *flags)


@pytest.mark.parametrize("name", list(CASES))
def test_a_bare_export_goes_through_add_validate_and_run(tmp_path, fx, name):
    project, session = _project(tmp_path, name, fx)
    added = _add(project, session, name)
    assert added.exit_code == 0, added.output
    validated = _invoke("validate", str(project))
    assert validated.exit_code == 0, validated.output
    out = tmp_path / "out"
    ran = _invoke("run", str(project), "-o", str(out), "-e", "csv_long", "-e", "readme")
    assert ran.exit_code == 0, ran.output

    *_, n_frames, n_animals = CASES[name]
    folder = out / name
    for expected in ("metrics_long.csv", "master_fish_by_frame.csv", "manifest.json", "README.md"):
        assert (folder / expected).is_file(), f"{expected} missing from {sorted(p.name for p in folder.iterdir())}"
    frames = pd.read_csv(folder / "master_fish_by_frame.csv")
    assert len(frames) == n_frames * n_animals and frames["individual_id"].nunique() == n_animals
    assert frames["x_px"].notna().any()
    metrics = pd.read_csv(folder / "metrics_long.csv")
    assert {"IL-1", "IL-2", "D-1"} <= set(metrics["metric_id"]) and metrics["value"].notna().any()
    assert (out / "PROJECT_SUMMARY.md").is_file()


@pytest.mark.parametrize("name", ["h5", "nofps", "moveR_pickled"])
def test_validate_says_what_is_missing_before_run_does(tmp_path, fx, name):
    """Without the options (and consent) the files do not record, validate fails with the reason."""
    project, session = _project(tmp_path, name, fx)
    assert _invoke("add", str(project), str(session), "--yes").exit_code == 0
    validated = _invoke("validate", str(project))
    assert validated.exit_code == 1
    assert "IDT_DICT_MISSING_KEY" in validated.output or "IDT_PICKLE_REFUSED" in validated.output
    assert _invoke("run", str(project), "-o", str(tmp_path / "out")).exit_code == 1


def test_the_h5_and_csv_exports_of_one_session_run_to_the_same_table(tmp_path, fx):
    tables = {}
    for name in ("h5", "csv"):
        project, session = _project(tmp_path / name, name, fx)
        assert _add(project, session, name).exit_code == 0
        out = tmp_path / name / "out"
        assert _invoke("run", str(project), "-o", str(out), "-e", "csv_long").exit_code == 0
        tables[name] = pd.read_csv(out / name / "master_fish_by_frame.csv").sort_values(["individual_id", "frame"])
    h5, csv = tables["h5"], tables["csv"]
    assert (h5["frame"].to_numpy() == csv["frame"].to_numpy()).all()
    assert (h5["x_px"] - csv["x_px"]).abs().max() < 1e-2  # the CSV keeps 3 decimals; smoothing may spread it
    assert (h5["id_probability"].fillna(-1) - csv["id_probability"].fillna(-1)).abs().max() < 1e-3


def test_running_does_not_modify_the_input_folder(tmp_path, fx):
    project, session = _project(tmp_path, "h5", fx)
    before = {p.relative_to(session): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    assert _add(project, session, "h5").exit_code == 0
    assert _invoke("run", str(project), "-o", str(tmp_path / "out"), "-e", "csv_long").exit_code == 0
    after = {p.relative_to(session): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    assert after == before
