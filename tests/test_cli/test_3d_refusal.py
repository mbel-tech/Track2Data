"""`run` and `sensitivity` refuse a 3-D project cleanly, before doing or writing anything."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from track2data.cli import cli
from track2data.core.manifest import write as write_manifest
from track2data.core.models import MODE_3D_BLOCK_REASON, ProjectManifest, ProjectMode


@pytest.fixture
def project_3d(tmp_path: Path) -> Path:
    now = datetime.now(tz=UTC)
    path = tmp_path / "p3d.t2d.json"
    manifest = ProjectManifest(
        project_name="p3d", created_at=now, updated_at=now,
        mode=ProjectMode(dimension="3d", layout="two_videos"),
    )
    write_manifest(manifest, path)
    return path


def test_run_refuses_3d_project(project_3d: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["run", str(project_3d), "-o", str(out)])
    assert result.exit_code == 2
    assert f"[error] {MODE_3D_BLOCK_REASON}" in result.output
    assert "Running" not in result.output
    assert "Traceback" not in result.output
    assert not out.exists()


def test_sensitivity_refuses_3d_project_without_making_the_out_dir(
    project_3d: Path, tmp_path: Path
) -> None:
    out = tmp_path / "sens"
    result = CliRunner().invoke(cli, ["sensitivity", str(project_3d), "-o", str(out)])
    assert result.exit_code == 2
    assert "[error] sensitivity is not supported for 3-D projects yet" in result.output
    assert "Sweeping" not in result.output
    assert not out.exists()
