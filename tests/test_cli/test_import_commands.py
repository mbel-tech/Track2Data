"""`track2data list-readers`, `scan` and `add`: the confirm flow without a window.

The same steps as the GUI -- point at a folder, see which software the output looks like, confirm
or amend, fill in what the files do not say -- from a shell, for batch and HPC work. The rules
live in ConfirmDraft; these tests check the commands are a faithful view of it.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.toy_reader import OPTIONS
from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest
from track2data.core.models import ProjectManifest, SessionRef


def invoke(*args: str, input: str | None = None):
    return CliRunner().invoke(cli, list(args), input=input)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    now = datetime.now(tz=UTC)
    path = tmp_path / "p.t2d.json"
    write_manifest(ProjectManifest(project_name="p", created_at=now, updated_at=now), path)
    return path


@pytest.fixture
def idtracker_root(tiny_real_session: Path, tmp_path: Path) -> Path:
    root = tmp_path / "trajectories"
    for name in ("s1", "s2", "s3"):
        shutil.copytree(tiny_real_session, root / name)
    return root


OPTION_ARGS = [f"--option={k}={v}" for k, v in OPTIONS.items()]


class TestListReaders:
    def test_names_every_registered_reader_with_its_software(self) -> None:
        out = invoke("list-readers")
        assert out.exit_code == 0
        assert "idtrackerai" in out.output
        assert "idtracker.ai" in out.output
        assert "idtrackerai_v5" in out.output

    def test_says_which_readers_were_tested_against_real_output(self) -> None:
        out = invoke("list-readers")
        assert "real_sample" in out.output

    def test_lists_a_readers_options_and_marks_the_required_ones(self, toy_reader: None) -> None:
        out = invoke("list-readers")
        assert "toy_csv" in out.output
        assert "fps*" in out.output  # required
        assert "synthetic_only" in out.output

    def test_json_is_the_same_facts_for_a_program(self, toy_reader: None) -> None:
        readers = {r["name"]: r for r in json.loads(invoke("list-readers", "--json").output)}
        toy = readers["toy_csv"]
        assert toy["display_name"] == "Toy tracker"
        assert toy["verification"] == "synthetic_only"
        assert [p["name"] for p in toy["parameters"] if p["required"]] == [
            "fps",
            "width_px",
            "height_px",
        ]
        assert readers["idtrackerai"]["verification"] == "real_sample"


class TestScan:
    def test_reports_the_software_confidence_and_sessions(self, idtracker_root: Path) -> None:
        out = invoke("scan", str(idtracker_root))
        assert out.exit_code == 0
        assert "idtracker.ai" in out.output
        assert "HIGH" in out.output
        assert "3 sessions" in out.output
        assert "s1" in out.output

    def test_a_folder_with_nothing_recognisable_says_what_it_did_see(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / "a.csv").write_text("a,b\n1,2\n")
        out = invoke("scan", str(tmp_path))
        assert out.exit_code == 0
        assert "No tracking output" in out.output
        assert ".csv" in out.output and ".txt" in out.output

    def test_json_carries_the_groups_and_the_evidence(self, idtracker_root: Path) -> None:
        data = json.loads(invoke("scan", str(idtracker_root), "--json").output)
        assert data["truncated"] is False
        (group,) = data["groups"]
        best = group["detections"][0]
        assert best["reader"] == "idtrackerai"
        assert best["confidence"] == "HIGH"
        assert best["verification"] == "real_sample"
        assert [s["session_id"] for s in best["sessions"]] == ["s1", "s2", "s3"]
        assert best["evidence"]

    def test_json_for_an_empty_scan_is_valid_and_has_no_groups(self, tmp_path: Path) -> None:
        data = json.loads(invoke("scan", str(tmp_path), "--json").output)
        assert data["groups"] == []

    def test_several_roots_are_scanned_together(self, idtracker_root: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        shutil.copytree(idtracker_root / "s1", other / "s9")
        data = json.loads(invoke("scan", str(idtracker_root), str(other), "--json").output)
        ids = [s["session_id"] for g in data["groups"] for s in g["detections"][0]["sessions"]]
        assert sorted(ids) == ["s1", "s2", "s3", "s9"]

    def test_a_deeper_tree_needs_a_deeper_look(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        shutil.copytree(tiny_real_session, tmp_path / "root" / "a" / "b" / "session")
        default = json.loads(invoke("scan", str(tmp_path / "root"), "--json").output)
        deeper = json.loads(
            invoke("scan", str(tmp_path / "root"), "--max-depth", "5", "--json").output
        )
        assert default["groups"] == []
        assert len(deeper["groups"]) == 1

    def test_finding_nothing_says_how_to_look_deeper(self, tmp_path: Path) -> None:
        out = invoke("scan", str(tmp_path))
        assert "--max-depth" in out.output

    def test_a_path_that_does_not_exist_is_an_error(self, tmp_path: Path) -> None:
        out = invoke("scan", str(tmp_path / "nope"))
        assert out.exit_code != 0


class TestAdd:
    def test_adds_every_detected_session_after_confirmation(
        self, project: Path, idtracker_root: Path
    ) -> None:
        out = invoke("add", str(project), str(idtracker_root), input="y\n")
        assert out.exit_code == 0, out.output
        sessions = read_manifest(project).sessions
        assert [s.session_id for s in sessions] == ["s1", "s2", "s3"]
        assert {s.reader for s in sessions} == {"idtrackerai"}
        assert {s.reader_chosen_by for s in sessions} == {"detected"}
        assert {s.reader_confidence for s in sessions} == {"HIGH"}

    def test_says_what_it_found_before_it_asks(self, project: Path, idtracker_root: Path) -> None:
        out = invoke("add", str(project), str(idtracker_root), input="y\n")
        assert out.output.index("idtracker.ai") < out.output.index("Add 3 session")

    def test_declining_adds_nothing_and_leaves_the_file_alone(
        self, project: Path, idtracker_root: Path
    ) -> None:
        before = project.read_bytes()
        out = invoke("add", str(project), str(idtracker_root), input="n\n")
        assert out.exit_code != 0
        assert project.read_bytes() == before

    def test_yes_skips_the_question(self, project: Path, idtracker_root: Path) -> None:
        out = invoke("add", str(project), str(idtracker_root), "--yes")
        assert out.exit_code == 0
        assert len(read_manifest(project).sessions) == 3

    def test_a_dry_run_shows_the_plan_and_changes_nothing(
        self, project: Path, idtracker_root: Path
    ) -> None:
        before = project.read_bytes()
        out = invoke("add", str(project), str(idtracker_root), "--dry-run")
        assert out.exit_code == 0
        assert "s1" in out.output
        assert project.read_bytes() == before

    def test_nothing_recognised_is_an_error_and_changes_nothing(
        self, project: Path, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        before = project.read_bytes()
        out = invoke("add", str(project), str(empty), "--yes")
        assert out.exit_code != 0
        assert "No tracking output" in out.output
        assert project.read_bytes() == before

    def test_sessions_can_be_left_out_and_renamed(
        self, project: Path, idtracker_root: Path
    ) -> None:
        out = invoke(
            "add", str(project), str(idtracker_root), "--yes",
            "--exclude", "s2", "--rename", "s3=third",
        )  # fmt: skip
        assert out.exit_code == 0, out.output
        assert [s.session_id for s in read_manifest(project).sessions] == ["s1", "third"]

    def test_a_session_the_project_already_has_is_not_added_twice(
        self, project: Path, idtracker_root: Path
    ) -> None:
        invoke("add", str(project), str(idtracker_root), "--yes")
        again = invoke("add", str(project), str(idtracker_root), "--yes")
        assert again.exit_code != 0  # nothing left to add
        assert "already in the project" in again.output
        assert "Tick" not in again.output  # not the app's wording for a shell
        assert len(read_manifest(project).sessions) == 3

    def test_the_reader_can_be_named_when_it_is_one_of_those_that_recognised_it(
        self, project: Path, idtracker_root: Path
    ) -> None:
        out = invoke("add", str(project), str(idtracker_root), "--yes", "--reader", "idtrackerai")
        assert out.exit_code == 0, out.output
        assert {s.reader_chosen_by for s in read_manifest(project).sessions} == {"detected"}

    def test_a_reader_that_did_not_recognise_it_is_refused_and_the_offer_is_named(
        self, project: Path, idtracker_root: Path
    ) -> None:
        out = invoke("add", str(project), str(idtracker_root), "--yes", "--reader", "nope")
        assert out.exit_code != 0
        assert "nope" in out.output and "idtrackerai" in out.output
        assert read_manifest(project).sessions == []


class TestAddWithOptions:
    @pytest.fixture
    def toy_root(self, toy_reader: None, toy_folder: Path) -> Path:
        return toy_folder.parent

    def test_the_options_the_files_do_not_record_must_be_given(
        self, project: Path, toy_root: Path
    ) -> None:
        out = invoke("add", str(project), str(toy_root), "--yes")
        assert out.exit_code != 0
        for option in ("fps", "width_px", "height_px"):
            assert option in out.output
        assert "--option" in out.output  # says how to give them
        assert read_manifest(project).sessions == []

    def test_given_they_are_saved_on_every_session(self, project: Path, toy_root: Path) -> None:
        out = invoke("add", str(project), str(toy_root), "--yes", *OPTION_ARGS)
        assert out.exit_code == 0, out.output
        (ref,) = read_manifest(project).sessions
        assert ref.reader == "toy_csv"
        assert ref.reader_options == OPTIONS

    def test_a_value_out_of_range_is_reported_not_saved(
        self, project: Path, toy_root: Path
    ) -> None:
        args = [a for a in OPTION_ARGS if not a.startswith("--option=fps")]
        out = invoke("add", str(project), str(toy_root), "--yes", *args, "--option=fps=fast")
        assert out.exit_code != 0
        assert "fps" in out.output
        assert read_manifest(project).sessions == []

    def test_an_option_the_reader_does_not_have_is_refused(
        self, project: Path, toy_root: Path
    ) -> None:
        out = invoke(
            "add", str(project), str(toy_root), "--yes", *OPTION_ARGS, "--option=colour=red"
        )
        assert out.exit_code != 0
        assert "colour" in out.output

    def test_the_project_it_creates_runs(
        self, project: Path, toy_root: Path, tmp_path: Path
    ) -> None:
        from track2data.api import Engine
        from track2data.core.models import CalibrationConfig, MetricSelection

        invoke("add", str(project), str(toy_root), "--yes", *OPTION_ARGS)
        manifest = read_manifest(project).model_copy(
            update={
                "calibration": CalibrationConfig(mode="scalar", px_per_cm=10.0),
                "metrics": MetricSelection(individual=["IL-1"]),
            }
        )
        result = Engine(manifest).run(tmp_path / "out", exporters=["csv_long"])
        assert [r.error for r in result.sessions] == [None]


class TestEntryPoints:
    def test_python_dash_m_track2data_runs_the_cli(self) -> None:
        import subprocess
        import sys

        done = subprocess.run(
            [sys.executable, "-m", "track2data", "list-readers"], capture_output=True, text=True
        )
        assert done.returncode == 0
        assert "idtrackerai" in done.stdout


def test_a_ref_added_by_the_command_equals_the_one_the_draft_builds(
    project: Path, idtracker_root: Path
) -> None:
    from track2data.readers.confirm import ConfirmDraft
    from track2data.readers.scan import scan

    invoke("add", str(project), str(idtracker_root), "--yes")
    expected: list[SessionRef] = ConfirmDraft(scan([idtracker_root])).to_session_refs()
    assert read_manifest(project).sessions == expected
