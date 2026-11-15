"""
A run must not report success when part of the work failed.

Review findings A2/A3 (12 Nov 2026): an exporter that raised was logged and
swallowed, an unknown exporter name was skipped, and a selected metric that
raised left no trace in the export -- the session still read as a success in
sessions.csv, PROJECT_SUMMARY.md and the GUI.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)


def _manifest(folder: Path, metrics: MetricSelection | None = None) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="failures",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id="sess_a", folder=folder, sha256="")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=metrics or MetricSelection(individual=["IL-1"]),
    )


@pytest.fixture()
def folder(tiny_real_session: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "sess_a"
    shutil.copytree(tiny_real_session, dst)
    return dst


@pytest.fixture()
def broken_exporter(monkeypatch: pytest.MonkeyPatch) -> str:
    import track2data.exporters as exporters_module
    from track2data.exporters.base import Exporter

    class BrokenExporter(Exporter):
        name = "broken_exporter"
        file_extension = ".txt"

        def write(self, payload, out_dir):
            raise RuntimeError("disk on fire")

    monkeypatch.setitem(exporters_module._registry, "broken_exporter", BrokenExporter)
    return "broken_exporter"


@pytest.fixture()
def broken_metric(monkeypatch: pytest.MonkeyPatch) -> str:
    import track2data.metrics as metrics_module
    from track2data.metrics.base import Metric, MetricDocumentation

    class BrokenMetric(Metric):
        id = "IL-999"
        name = "broken"
        label = "Broken"
        level = "individual"
        priority = "optional"
        requires_identity = False
        output_columns = ["session_id"]
        documentation = MetricDocumentation(
            definition="test-only", formula_plain="raises", inputs=[],
            assumptions=[], warnings=[],
        )

        def compute(self, session, cfg=None):
            raise RuntimeError("division by fish")

    monkeypatch.setitem(metrics_module._registry, "IL-999", BrokenMetric)
    return "IL-999"


# ── A2: exporters ────────────────────────────────────────────────────────────


def test_unknown_exporter_fails_the_run_up_front(folder: Path, tmp_path: Path) -> None:
    from track2data.api import Engine
    from track2data.core.errors import Track2DataError

    out = tmp_path / "out"
    with pytest.raises(Track2DataError, match="csv_lnog"):
        Engine(_manifest(folder)).run(out, exporters=["csv_lnog"])
    assert not (out / "sess_a").exists(), "no session may run before the name is checked"


def test_export_rejects_an_unknown_exporter(folder: Path, tmp_path: Path) -> None:
    from track2data.api import Engine
    from track2data.core.errors import Track2DataError

    with pytest.raises(Track2DataError, match="not_a_real_exporter"):
        Engine(_manifest(folder)).export(object(), tmp_path, ["not_a_real_exporter"])


def test_validation_flags_an_unknown_export_target(folder: Path) -> None:
    from track2data.api import Engine
    from track2data.core.models import ExportTarget

    m = _manifest(folder)
    m = m.model_copy(update={"export_targets": [ExportTarget(exporter_name="csv_lnog")]})
    issues = Engine(m).validate()
    assert any("csv_lnog" in i for i in issues)


def test_cli_run_with_a_mistyped_exporter_exits_non_zero(folder: Path, tmp_path: Path) -> None:
    from track2data.cli import cli

    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(_manifest(folder).model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        cli, ["run", str(manifest_path), "-o", str(tmp_path / "out"), "-e", "csv_lnog"]
    )
    assert result.exit_code != 0
    assert "csv_lnog" in result.output


def test_a_raising_exporter_marks_the_session_failed(
    folder: Path, tmp_path: Path, broken_exporter: str
) -> None:
    from track2data.api import Engine

    out = tmp_path / "out"
    result = Engine(_manifest(folder)).run(out, exporters=["csv_long", broken_exporter])
    (sess,) = result.sessions
    assert sess.error and "broken_exporter" in sess.error and "disk on fire" in sess.error
    assert sess.failed_exporters == {"broken_exporter": "RuntimeError: disk on fire"}
    # What did get written is still reported, and the summary row is kept.
    assert any(p.name == "master_fish_by_frame.csv" for p in sess.written)
    assert sess.summary is not None
    table = pd.read_csv(out / "sessions.csv")
    row = table.set_index("session_id").loc["sess_a"]
    assert "broken_exporter" in row["error"]
    assert row["fps"] > 0
    assert "sess_a" in (out / "PROJECT_SUMMARY.md").read_text(encoding="utf-8").split(
        "## Sessions that failed"
    )[1]


def test_export_raises_after_trying_every_exporter(
    folder: Path, tmp_path: Path, broken_exporter: str
) -> None:
    from track2data.api import Engine
    from track2data.core.errors import ExporterFailedError

    session = Engine(_manifest(folder)).import_session(folder)
    with pytest.raises(ExporterFailedError) as exc:
        Engine(_manifest(folder)).run_session(
            session, tmp_path, exporters=[broken_exporter, "csv_long"]
        )
    assert "broken_exporter" in exc.value.failures
    assert any(p.name == "master_fish_by_frame.csv" for p in exc.value.written)


# ── A3: metrics ──────────────────────────────────────────────────────────────


def test_compute_metrics_reports_a_failed_metric(folder: Path, broken_metric: str) -> None:
    from track2data.api import Engine

    engine = Engine(_manifest(folder, MetricSelection(individual=["IL-1", broken_metric])))
    psess = engine.preprocess(engine.import_session(folder))
    failures: dict[str, str] = {}
    results = engine.compute_metrics(psess, failures=failures)
    assert broken_metric not in results
    assert "IL-1" in results
    assert failures == {broken_metric: "RuntimeError: division by fish"}


def test_a_failed_metric_is_named_in_every_record(
    folder: Path, tmp_path: Path, broken_metric: str
) -> None:
    from track2data.api import Engine

    out = tmp_path / "out"
    m = _manifest(folder, MetricSelection(individual=["IL-1", broken_metric]))
    result = Engine(m).run(out, exporters=["csv_long", "readme"])
    (sess,) = result.sessions
    assert sess.error is None  # partial, not failed: the other metrics are good
    assert sess.failed_metrics == {broken_metric: "RuntimeError: division by fish"}

    readme = (out / "sess_a" / "README.md").read_text(encoding="utf-8")
    assert broken_metric in readme and "division by fish" in readme

    summary = (out / "PROJECT_SUMMARY.md").read_text(encoding="utf-8")
    assert broken_metric in summary and "division by fish" in summary

    table = pd.read_csv(out / "sessions.csv").set_index("session_id")
    assert broken_metric in table.loc["sess_a", "issues"]
