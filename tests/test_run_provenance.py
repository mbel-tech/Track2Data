"""
Review findings B7, B10, B11 (12 Nov 2026).

B7  sessions.csv's is_identity_free must use the same resolution as the
    metric gate (identity_free_for), not SessionRef.is_identity_free().
B10 a body-length calibration failure must be logged with its exception and
    recorded in the session's record, not a one-line warning.
B11 _pair_inputs must let OperationCancelled through, not wrap it.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)


def _manifest(folder: Path, calibration: CalibrationConfig | None = None) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="prov",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id="sess_a", folder=folder, sha256="")],
        calibration=calibration or CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"]),
    )


def test_sessions_csv_identity_free_matches_the_metric_gate(
    tiny_identity_free_session: Path, tmp_path: Path
) -> None:
    """No probe filled the ref's cache (a CLI run): the gate reads the session file."""
    from track2data.api import Engine

    folder = tmp_path / "sess_a"
    shutil.copytree(tiny_identity_free_session, folder)
    m = _manifest(folder)
    assert m.sessions[0].track_wo_identities is None
    out = tmp_path / "out"
    Engine(m).run(out, exporters=["csv_long"])
    row = pd.read_csv(out / "sessions.csv").set_index("session_id").loc["sess_a"]
    assert bool(row["is_identity_free"]) is True


def test_consistency_summaries_use_the_gate_resolution(
    tiny_identity_free_session: Path, tmp_path: Path
) -> None:
    from track2data.api import Engine

    folder = tmp_path / "sess_a"
    shutil.copytree(tiny_identity_free_session, folder)
    summaries = Engine(_manifest(folder))._session_summaries()
    assert [s.is_identity_free for s in summaries] == [True]


def test_bodylength_calibration_failure_is_logged_and_recorded(
    tiny_real_session: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import track2data.calibration.bodylength as bl
    from track2data.api import Engine

    def boom(psess, cfg):
        raise ValueError("no usable body lengths")

    monkeypatch.setattr(bl, "apply_bodylength_calibration", boom)
    folder = tmp_path / "sess_a"
    shutil.copytree(tiny_real_session, folder)
    m = _manifest(folder, CalibrationConfig(mode="bodylength"))
    out = tmp_path / "out"
    with caplog.at_level(logging.WARNING):
        result = Engine(m).run(out, exporters=["csv_long", "readme"])

    rec = [r for r in caplog.records if "Body-length calibration failed" in r.getMessage()]
    assert rec and rec[0].exc_info is not None
    (sess,) = result.sessions
    assert sess.error is None
    assert any("no usable body lengths" in i for i in sess.issues)
    row = pd.read_csv(out / "sessions.csv").set_index("session_id").loc["sess_a"]
    assert "no usable body lengths" in row["issues"]
    assert "no usable body lengths" in (out / "sess_a" / "README.md").read_text(encoding="utf-8")


def test_pair_inputs_lets_cancellation_through(
    tiny_real_session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.api import Engine
    from track2data.core.models import ViewPair
    from track2data.core.progress import OperationCancelled

    now = datetime.now(tz=UTC)
    m = ProjectManifest(
        project_name="pair",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(session_id="top", folder=tiny_real_session, sha256=""),
            SessionRef(session_id="side", folder=tiny_real_session, sha256=""),
        ],
    )
    engine = Engine(m)

    def cancelled(ref):
        raise OperationCancelled()

    monkeypatch.setattr(engine, "preprocess_ref", cancelled)
    pair = ViewPair(top_session_id="top", side_session_id="side", same_ids=True)
    with pytest.raises(OperationCancelled):
        engine._pair_inputs(pair)
