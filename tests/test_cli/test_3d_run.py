"""`run` and `validate` on a 3-D project with fusable pairs."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tests.test_fusion.scene import build_scene, fusion_settings, pair
from track2data.cli import cli
from track2data.core.manifest import write as write_manifest


def _project(tmp_path: Path, **kw: object) -> Path:
    path = tmp_path / "p3d.t2d.json"
    write_manifest(build_scene(tmp_path / "data", **kw), path)  # type: ignore[arg-type]
    return path


def test_run_3d_project_writes_pair_units_and_lists_the_skips(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli, ["run", str(_project(tmp_path, side2_fps=10.0)), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "t1+s1").is_dir()
    assert not (out / "t2+s2").exists()
    assert "[skipped] t2: pair t2+s2: frame rates differ: 25 vs 10 fps" in result.output
    assert "[skipped] lone: not in a fusable pair" in result.output
    assert "Traceback" not in result.output


def test_run_3d_project_with_no_fusable_pair_refuses(tmp_path: Path) -> None:
    pairs = [pair("t1", "s1", fusion=fusion_settings(frame_offset=1000))]
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli, ["run", str(_project(tmp_path, pairs=pairs)), "-o", str(out)]
    )
    assert result.exit_code == 2
    assert "[error] no pair is ready to fuse: pair t1+s1: " in result.output
    assert "Running" not in result.output
    assert not out.exists()


def test_validate_3d_reports_pair_issues_and_passes(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["validate", str(_project(tmp_path, side2_fps=10.0))])
    assert result.exit_code == 0, result.output
    assert "[issue] pair t2+s2: frame rates differ: 25 vs 10 fps" in result.output
    assert "[issue] session lone: not in a fusable pair" in result.output
    assert "ready to run" in result.output


def test_validate_3d_fails_when_no_pair_fuses(tmp_path: Path) -> None:
    pairs = [pair("t1", "s1", fusion=fusion_settings(frame_offset=1000))]
    result = CliRunner().invoke(cli, ["validate", str(_project(tmp_path, pairs=pairs))])
    assert result.exit_code == 1
    assert "[issue] no pair is ready to fuse: pair t1+s1: " in result.output
    assert "ready to run" not in result.output
