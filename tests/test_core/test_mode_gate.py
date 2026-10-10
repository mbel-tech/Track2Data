"""The engine refuses to compute a 3-D project that has no fusable pair."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from track2data.api import Engine
from track2data.core.models import (
    MODE_3D_BLOCK_REASON,
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    SessionRef,
)


def _engine(dimension: str = "3d") -> Engine:
    now = datetime.now(tz=UTC)
    mode = (
        ProjectMode(dimension="3d", layout="single_video_two_panels")
        if dimension == "3d"
        else ProjectMode()
    )
    manifest = ProjectManifest(
        project_name="gate",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id="s1", folder=Path("/nonexistent/s1"), reader="test", sha256="0" * 64
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
        mode=mode,
    )
    return Engine(manifest)


def test_validate_reports_3d_block() -> None:
    issues = _engine("3d").validate()
    assert issues[0] == MODE_3D_BLOCK_REASON


def test_2d_validate_has_no_mode_issue() -> None:
    assert MODE_3D_BLOCK_REASON not in _engine("2d").validate()


def test_run_refuses_3d(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        _engine().run(tmp_path)


def test_run_all_refuses_3d(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        _engine().run_all(tmp_path)


def test_run_session_refuses_3d(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"use run\(\) for a 3-D project"):
        _engine().run_session(object(), tmp_path)  # type: ignore[arg-type]


def test_export_refuses_3d(tmp_path: Path) -> None:
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON):
        _engine().export(object(), out)
    assert not out.exists()


def test_compute_metrics_refuses_3d() -> None:
    with pytest.raises(ValueError, match="3-D projects compute fused sessions only"):
        _engine().compute_metrics(object())  # type: ignore[arg-type]


def test_run_sensitivity_refuses_3d() -> None:
    from track2data.sensitivity import run_sensitivity

    with pytest.raises(ValueError, match="sensitivity is not supported for 3-D projects yet"):
        run_sensitivity(_engine(), object())  # type: ignore[arg-type]
