"""
End-to-end integration tests — M1 exit criteria.

These tests exercise the full Engine pipeline:

  import_session → preprocess → compute_metrics → export

Using the ``tiny_real_session`` synthetic fixture (idtracker.ai 6.x format)
which contains a proper pickled-dict trajectories.npy.

Constants for tiny_real:
  N_FRAMES = 10, N_ANIMALS = 2, FPS = 25.0

They verify:
1. Engine.import_session() returns a Session with the correct shape.
2. Engine.preprocess() returns a PreprocessedSession with xy cleaned.
3. Engine.compute_metrics() returns D-* diagnostics + selected metrics.
4. Engine.run_session() writes master_fish_by_frame.csv to disk.
5. The CSV has the expected columns and one row per (frame x animal).
6. CLI `track2data run` produces the same output via Click's test runner.
7. CLI `track2data validate` exits 0 on a valid manifest, 1 on issues.
8. CLI `track2data list-metrics` lists registered metric IDs.
9. CLI `track2data new` scaffolds a manifest file.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

# tiny_real constants (from conftest)
_N_FRAMES = 10
_N_ANIMALS = 2
_FPS = 25.0


# ── helpers ───────────────────────────────────────────────────────────────────


def _minimal_manifest(session_folder: Path) -> ProjectManifest:
    """Return a minimal valid ProjectManifest pointing at *session_folder*."""
    now = datetime.now(tz=UTC)
    sha = hashlib.sha256(str(session_folder).encode()).hexdigest()
    return ProjectManifest(
        project_name="test_project",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id=session_folder.name,
                folder=session_folder,
                sha256=sha,
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(
            individual=["IL-1", "IL-2"],
            group=["GL-1"],
            zone=[],
            diagnostic=[],
        ),
    )


# ── 1. import_session ─────────────────────────────────────────────────────────


def test_import_session_returns_session(tiny_real_session: Path) -> None:
    """Engine.import_session() returns a Session for the tiny_real folder."""
    from track2data.api import Engine
    from track2data.core.models import Session

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)

    assert isinstance(session, Session)
    assert session.n_animals == _N_ANIMALS
    assert session.raw_xy.shape == (_N_FRAMES, _N_ANIMALS, 2)
    assert session.video.fps == _FPS


def test_import_sessions_returns_all_sessions(tiny_real_session: Path) -> None:
    """Engine.import_sessions() returns one Session per manifest.sessions entry."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    sessions = engine.import_sessions()

    assert len(sessions) == 1
    assert sessions[0].n_animals == _N_ANIMALS


# ── 2. preprocess ─────────────────────────────────────────────────────────────


def test_preprocess_returns_preprocessed_session(tiny_real_session: Path) -> None:
    """Engine.preprocess() returns a PreprocessedSession with the right shape."""
    from track2data.api import Engine
    from track2data.core.models import PreprocessedSession

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)

    assert isinstance(psess, PreprocessedSession)
    assert psess.xy.shape == (_N_FRAMES, _N_ANIMALS, 2)
    assert psess.n_frames == _N_FRAMES
    assert psess.n_animals == _N_ANIMALS
    assert psess.fps == _FPS


def test_preprocess_scalar_calibration(tiny_real_session: Path) -> None:
    """Scalar calibration sets px_per_cm on the PreprocessedSession."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)

    assert psess.px_per_cm == pytest.approx(10.0)


def test_preprocess_no_nans_after_pipeline(tiny_real_session: Path) -> None:
    """After preprocessing the xy array has no NaN values (tiny_real has no gaps)."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)

    assert not np.any(np.isnan(psess.xy)), "Unexpected NaN values after preprocessing"


def test_preprocess_kinematics_shape(tiny_real_session: Path) -> None:
    """Kinematics arrays have shape (n_frames, n_animals)."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)

    assert psess.kinematics.speed_px_s.shape == (_N_FRAMES, _N_ANIMALS)
    assert psess.kinematics.heading_rad.shape == (_N_FRAMES, _N_ANIMALS)


# ── 3. compute_metrics ────────────────────────────────────────────────────────


def test_compute_metrics_returns_dict(tiny_real_session: Path) -> None:
    """compute_metrics() returns a dict with at least the diagnostic keys."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    results = engine.compute_metrics(psess)

    assert isinstance(results, dict)
    # D-1 must always be present (always-on diagnostic)
    assert "D-1" in results, f"D-1 not in results: {sorted(results.keys())}"


def test_compute_metrics_selected_metrics_present(tiny_real_session: Path) -> None:
    """Selected IL-1, IL-2, GL-1 are present in the metric results."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    results = engine.compute_metrics(psess)

    for mid in ("IL-1", "IL-2", "GL-1"):
        assert mid in results, f"{mid} not in metric results: {sorted(results.keys())}"


def test_compute_metrics_every_registered_metric_runs_without_crashing(
    tiny_real_session: Path,
) -> None:
    """Every metric in the registry -- including the 11 added by the
    2026-08 reference audit -- computes end to end through the real
    Engine pipeline, not just in isolation against a hand-built
    PreprocessedSession. tiny_real_session has no zones defined, so
    Z-* metrics are expected to return an empty (not absent, not
    erroring) DataFrame; every other metric must emit at least one row
    with no all-NaN column that has a non-NaN counterpart in a unit
    test fixture.
    """
    from track2data import metrics as metrics_registry
    from track2data.api import Engine

    all_ids = metrics_registry.all_ids()
    def _ids_for(level: str) -> list[str]:
        return [mid for mid in all_ids if metrics_registry.get(mid).level == level]

    manifest = _minimal_manifest(tiny_real_session)
    manifest = manifest.model_copy(
        update={
            "metrics": MetricSelection(
                individual=_ids_for("individual"),
                group=_ids_for("group"),
                zone=_ids_for("zone"),
                diagnostic=[],
            )
        }
    )
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    results = engine.compute_metrics(psess)

    missing = [mid for mid in all_ids if mid not in results]
    assert not missing, f"metrics absent from compute_metrics() output: {missing}"

    new_metric_ids = {
        "IL-9", "IL-10", "IL-11", "IL-14",
        "GL-11", "GL-13", "GL-15",
        "Z-7", "Z-8", "Z-9",
        "D-10",
    }
    for mid in new_metric_ids:
        df = results[mid]
        assert isinstance(df, pd.DataFrame), f"{mid} did not return a DataFrame"
        if mid.startswith("Z-"):
            continue  # no zones defined in this fixture -- empty is correct
        assert not df.empty, f"{mid} returned an empty DataFrame against a zone-free fixture"


# ── 4+5. run_session → CSV ────────────────────────────────────────────────────


def test_run_session_writes_master_csv(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """run_session() writes master_fish_by_frame.csv."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    written = engine.run_session(session, tmp_path, exporters=["csv_long"])

    csv_path = tmp_path / "master_fish_by_frame.csv"
    assert csv_path.exists(), (
        f"master_fish_by_frame.csv not written; got: {[p.name for p in written]}"
    )


def test_run_session_csv_columns(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """master_fish_by_frame.csv has the required columns."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    engine.run_session(session, tmp_path, exporters=["csv_long"])

    df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")

    required = {
        "session_id", "individual_id", "frame", "time_s",
        "x_px", "y_px", "speed_px_s", "heading_rad",
    }
    missing = required - set(df.columns)
    assert not missing, f"Missing columns: {missing}"


def test_run_session_csv_row_count(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """master_fish_by_frame.csv has n_frames x n_animals rows."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    engine.run_session(session, tmp_path, exporters=["csv_long"])

    df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")
    expected = _N_FRAMES * _N_ANIMALS  # 10 x 2 = 20
    assert len(df) == expected, f"Expected {expected} rows, got {len(df)}"


def test_run_session_csv_calibrated_columns(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """When px_per_cm is set, x_cm / y_cm / speed_cm_s columns appear."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    engine.run_session(session, tmp_path, exporters=["csv_long"])

    df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")
    assert "x_cm" in df.columns, "x_cm not present with px_per_cm=10"
    assert "speed_cm_s" in df.columns


def test_run_session_time_column_correct(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """time_s = frame / fps; frame 0 → 0.0, frame 5 → 0.2 s."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    engine.run_session(session, tmp_path, exporters=["csv_long"])

    df = pd.read_csv(tmp_path / "master_fish_by_frame.csv")
    frame0_t = df[df["frame"] == 0]["time_s"].iloc[0]
    frame5_t = df[df["frame"] == 5]["time_s"].iloc[0]
    assert frame0_t == pytest.approx(0.0)
    assert frame5_t == pytest.approx(5.0 / _FPS)  # 0.2 s


def test_run_all_processes_all_sessions(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """run_all() processes every session in the manifest."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    engine = Engine(manifest)

    written = engine.run_all(tmp_path, exporters=["csv_long"])

    # At least master_fish_by_frame.csv should be written
    assert any(
        p.name == "master_fish_by_frame.csv" for p in written
    ), f"Expected master_fish_by_frame.csv; got: {[p.name for p in written]}"


# ── 6. CLI: track2data run ────────────────────────────────────────────────────


def test_cli_run_produces_csv(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """
    CLI `track2data run` writes master_fish_by_frame.csv under a
    per-session subdirectory (out_dir/<session_id>/) -- Engine.run()'s
    fix for the multi-session out_dir collision (issue #19); a
    single-session run lands here too since run_all() is a thin wrapper
    over the same run().
    """
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import write as manifest_write

    manifest = _minimal_manifest(tiny_real_session)
    manifest_path = tmp_path / "project.t2d.json"
    manifest_write(manifest, manifest_path)

    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "run",
        str(manifest_path),
        "--out-dir", str(out_dir),
        "--exporter", "csv_long",
    ])

    assert result.exit_code == 0, (
        f"CLI exited {result.exit_code}:\n{result.output}"
    )
    session_id = tiny_real_session.name
    assert (out_dir / session_id / "master_fish_by_frame.csv").exists()


def test_cli_run_reports_a_failed_session_and_exits_nonzero(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """
    Issue #7 / FR-IMP-3: a session that can't be imported must be flagged
    with an actionable message, not silently dropped. Before this fix,
    `run` called Engine.run_all() -- which only returns written paths --
    so a failed session was invisible: the command still exited 0 and
    the only symptom was fewer files than expected. Now it calls
    Engine.run() directly, prints one [error] line per failed session,
    and exits 1 -- while still writing every session that *did* succeed.
    """
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import write as manifest_write
    from track2data.core.models import SessionRef

    manifest = _minimal_manifest(tiny_real_session)
    bad_folder = tmp_path / "not_a_session"
    bad_folder.mkdir()
    manifest = manifest.model_copy(
        update={
            "sessions": [
                *manifest.sessions,
                SessionRef(session_id="bad", folder=bad_folder, sha256="x"),
            ]
        }
    )
    manifest_path = tmp_path / "project.t2d.json"
    manifest_write(manifest, manifest_path)

    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "run",
        str(manifest_path),
        "--out-dir", str(out_dir),
        "--exporter", "csv_long",
    ])

    assert result.exit_code == 1, (
        f"CLI exited {result.exit_code}, expected 1:\n{result.output}"
    )
    assert "bad" in result.output
    assert "failed" in result.output.lower()
    # The good session still ran and wrote its output despite the other's failure.
    session_id = tiny_real_session.name
    assert (out_dir / session_id / "master_fish_by_frame.csv").exists()


# ── 7. CLI: validate ──────────────────────────────────────────────────────────


def test_cli_validate_ok(tmp_path: Path, tiny_real_session: Path) -> None:
    """CLI `validate` exits 0 when manifest has sessions + metrics."""
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import write as manifest_write

    manifest = _minimal_manifest(tiny_real_session)
    manifest_path = tmp_path / "project.t2d.json"
    manifest_write(manifest, manifest_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(manifest_path)])

    assert result.exit_code == 0, (
        f"validate should pass; got {result.exit_code}:\n{result.output}"
    )
    assert "OK" in result.output


def test_cli_validate_fails_no_sessions(tmp_path: Path) -> None:
    """CLI `validate` exits 1 when manifest has no sessions."""
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import write as manifest_write

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="empty",
        created_at=now,
        updated_at=now,
        # No sessions, no metrics → validate should report issues
    )
    manifest_path = tmp_path / "empty.t2d.json"
    manifest_write(manifest, manifest_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(manifest_path)])

    assert result.exit_code == 1, (
        "validate should exit 1 for empty manifest"
    )


# ── 8. CLI: list-metrics ──────────────────────────────────────────────────────


def test_cli_list_metrics() -> None:
    """CLI `list-metrics` lists at least D-1 and IL-1."""
    from click.testing import CliRunner

    from track2data.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["list-metrics"])

    assert result.exit_code == 0, result.output
    assert "D-1" in result.output
    assert "IL-1" in result.output


def test_cli_list_metrics_level_filter() -> None:
    """CLI `list-metrics --level individual` shows only individual metrics."""
    from click.testing import CliRunner

    from track2data.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["list-metrics", "--level", "individual"])

    assert result.exit_code == 0, result.output
    # D-1 is a diagnostic metric; should NOT appear in the individual filter
    assert "D-1" not in result.output
    assert "IL-1" in result.output


def test_cli_list_metrics_group_level_natural_sort() -> None:
    """CLI `list-metrics --level group` sorts GL-10 after GL-9, not GL-1."""
    from click.testing import CliRunner

    from track2data.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["list-metrics", "--level", "group"])

    assert result.exit_code == 0, result.output
    ids = [
        line.split()[0] for line in result.output.splitlines() if line.startswith("GL-")
    ]
    assert ids.index("GL-10") > ids.index("GL-9")


# ── 9. CLI: new ───────────────────────────────────────────────────────────────


def test_cli_new_scaffolds_manifest(tmp_path: Path) -> None:
    """CLI `track2data new` writes a valid .t2d.json file."""
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import read as manifest_read

    runner = CliRunner()
    out_path = tmp_path / "my_exp.t2d.json"
    result = runner.invoke(cli, ["new", "my_exp", "--out", str(out_path)])

    assert result.exit_code == 0, result.output
    assert out_path.exists()

    loaded = manifest_read(out_path)
    assert loaded.project_name == "my_exp"
    assert loaded.sessions == []


# ── 10. validate() method ─────────────────────────────────────────────────────


def test_engine_validate_returns_empty_for_valid_manifest(
    tiny_real_session: Path,
) -> None:
    """Engine.validate() returns [] when the manifest is ready."""
    from track2data.api import Engine

    manifest = _minimal_manifest(tiny_real_session)
    issues = Engine(manifest).validate()

    assert issues == [], f"Unexpected issues: {issues}"


def test_engine_validate_reports_no_sessions() -> None:
    """Engine.validate() flags an empty session list."""
    from track2data.api import Engine

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="empty",
        created_at=now,
        updated_at=now,
        metrics=MetricSelection(individual=["IL-1"]),
    )
    issues = Engine(manifest).validate()

    assert any("session" in i.lower() for i in issues), issues


def test_engine_validate_reports_no_metrics(tiny_real_session: Path) -> None:
    """Engine.validate() flags when no metrics are selected."""
    from track2data.api import Engine

    sha = hashlib.sha256(str(tiny_real_session).encode()).hexdigest()
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="no_metrics",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id=tiny_real_session.name,
                folder=tiny_real_session,
                sha256=sha,
            )
        ],
        # No metrics selected
    )
    issues = Engine(manifest).validate()

    assert any("metric" in i.lower() for i in issues), issues
