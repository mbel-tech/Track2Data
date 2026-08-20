"""
Metadata → Engine integration tests.

metadata/{schema,loader,mapping,join}.py were fully implemented and unit
tested but never wired into Engine -- a project's Metadata wizard stage had
no effect on exported output. These tests exercise that wiring:

  ProjectManifest.metadata_source/mapping -> Engine.build_fish_by_frame()
  and Engine.compute_metrics() results carry the matched canonical fields.

Uses the ``tiny_real_session`` fixture (N_FRAMES=10, N_ANIMALS=2, FPS=25.0).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from track2data.core.models import (
    CalibrationConfig,
    MappingRule,
    MetadataSource,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)


def _manifest_with_metadata(
    session_folder: Path,
    metadata_path: Path,
    rule: MappingRule,
) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    sha = hashlib.sha256(str(session_folder).encode()).hexdigest()
    return ProjectManifest(
        project_name="test_project",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(session_id=session_folder.name, folder=session_folder, sha256=sha)
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-2"], group=["GL-1"]),
        metadata_source=MetadataSource(path=metadata_path, sha256="unused"),
        mapping=rule,
    )


def _manifest_without_metadata(session_folder: Path) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    sha = hashlib.sha256(str(session_folder).encode()).hexdigest()
    return ProjectManifest(
        project_name="test_project",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(session_id=session_folder.name, folder=session_folder, sha256=sha)
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-2"], group=["GL-1"]),
    )


def _write_metadata_csv(tmp_path: Path, session_id: str) -> Path:
    csv_path = tmp_path / "metadata.csv"
    pd.DataFrame(
        {
            "session_id": [session_id],
            "treatment": ["drug_a"],
            "timepoint": ["T1"],
        }
    ).to_csv(csv_path, index=False)
    return csv_path


# ── build_fish_by_frame ─────────────────────────────────────────────────────────


def test_fish_by_frame_attaches_matched_metadata(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """A matched session's metadata columns appear on every row."""
    from track2data.api import Engine

    csv_path = _write_metadata_csv(tmp_path, tiny_real_session.name)
    rule = MappingRule(rules={"treatment": "treatment", "timepoint": "timepoint"})
    manifest = _manifest_with_metadata(tiny_real_session, csv_path, rule)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    df = engine.build_fish_by_frame(psess)

    assert "treatment" in df.columns
    assert "timepoint" in df.columns
    assert (df["treatment"] == "drug_a").all()
    assert (df["timepoint"] == "T1").all()


def test_fish_by_frame_no_metadata_columns_when_unconfigured(
    tiny_real_session: Path,
) -> None:
    """No metadata_source configured -> output is unchanged (regression guard)."""
    from track2data.api import Engine

    manifest = _manifest_without_metadata(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    df = engine.build_fish_by_frame(psess)

    assert "treatment" not in df.columns
    assert "timepoint" not in df.columns


def test_fish_by_frame_unmatched_session_gets_no_metadata_columns(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """metadata_source configured but this session has no matching row."""
    from track2data.api import Engine

    csv_path = _write_metadata_csv(tmp_path, "some_other_session_entirely")
    rule = MappingRule(rules={"treatment": "treatment", "timepoint": "timepoint"})
    manifest = _manifest_with_metadata(tiny_real_session, csv_path, rule)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    df = engine.build_fish_by_frame(psess)

    assert "treatment" not in df.columns
    assert "timepoint" not in df.columns


def test_fish_by_frame_metadata_individual_id_does_not_overwrite_real_index(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """
    A metadata column that aliases to canonical individual_id (e.g. fish_id)
    must never overwrite the real per-row fish index (0..n_animals-1). The
    join is session-level only; individual_id here would just be a constant
    broadcast across every row of the session, corrupting real identity.
    """
    from track2data.api import Engine

    csv_path = tmp_path / "metadata.csv"
    pd.DataFrame(
        {
            "session_id": [tiny_real_session.name],
            "fish_id": ["NOT_A_REAL_INDEX"],
            "treatment": ["drug_a"],
        }
    ).to_csv(csv_path, index=False)
    rule = MappingRule(rules={"treatment": "treatment"})
    manifest = _manifest_with_metadata(tiny_real_session, csv_path, rule)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    df = engine.build_fish_by_frame(psess)

    assert "treatment" in df.columns
    assert set(df["individual_id"].unique()) == {0, 1}


# ── compute_metrics ──────────────────────────────────────────────────────────────


def test_compute_metrics_attaches_matched_metadata(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """Metric result frames (IL-*/GL-*) also carry the matched fields."""
    from track2data.api import Engine

    csv_path = _write_metadata_csv(tmp_path, tiny_real_session.name)
    rule = MappingRule(rules={"treatment": "treatment", "timepoint": "timepoint"})
    manifest = _manifest_with_metadata(tiny_real_session, csv_path, rule)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    results = engine.compute_metrics(psess)

    assert "treatment" in results["IL-1"].columns
    assert (results["IL-1"]["treatment"] == "drug_a").all()
    assert "treatment" in results["GL-1"].columns


def test_compute_metrics_no_metadata_columns_when_unconfigured(
    tiny_real_session: Path,
) -> None:
    from track2data.api import Engine

    manifest = _manifest_without_metadata(tiny_real_session)
    engine = Engine(manifest)

    session = engine.import_session(tiny_real_session)
    psess = engine.preprocess(session)
    results = engine.compute_metrics(psess)

    assert "treatment" not in results["IL-1"].columns
