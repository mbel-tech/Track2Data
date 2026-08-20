"""
Direct unit tests for track2data.api.Engine.

Complements tests/test_integration/test_end_to_end.py and
test_metadata_integration.py, which exercise Engine through full
import -> preprocess -> metrics -> export runs against real fixture
sessions. These tests target specific branches -- mostly exception
handling and fallback paths -- that a happy-path integration run
doesn't naturally hit: a session that fails to import, a metric or
exporter that raises, an unregistered metric/exporter ID, body-length
calibration, zone assignment, and preview_frame.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    ROI,
    CalibrationConfig,
    KinematicsArrays,
    MetricSelection,
    PreprocessedSession,
    PreprocessReport,
    ProjectManifest,
    Session,
    SessionRef,
    VideoInfo,
    ZoneSet,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_manifest(
    sessions: list[SessionRef] | None = None,
    calibration: CalibrationConfig | None = None,
    zones: ZoneSet | None = None,
    metrics: MetricSelection | None = None,
) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="test_project",
        created_at=now,
        updated_at=now,
        sessions=sessions or [],
        calibration=calibration or CalibrationConfig(mode="scalar", px_per_cm=10.0),
        zones=zones or ZoneSet(),
        metrics=metrics or MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
    )


def _make_session(
    session_id: str = "s1",
    n_frames: int = 40,
    n_animals: int = 2,
    video_path: Path | None = None,
    body_length_px: np.ndarray | None = None,
) -> Session:
    rng = np.random.default_rng(0)
    xy = rng.random((n_frames, n_animals, 2)) * 500
    return Session(
        session_id=session_id,
        folder=Path("/tmp") / session_id,
        reader="test",
        video=VideoInfo(
            path=video_path, fps=25.0, n_frames=n_frames, width_px=1000, height_px=1000
        ),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        body_length_px=body_length_px,
    )


def _make_psess(session: Session) -> PreprocessedSession:
    n_frames, n_animals = session.n_frames, session.n_animals
    kine = KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )
    return PreprocessedSession(
        session=session, xy=session.raw_xy, kinematics=kine, report=PreprocessReport()
    )


# ── manifest property ────────────────────────────────────────────────────────


def test_manifest_property_returns_the_manifest() -> None:
    from track2data.api import Engine

    manifest = _make_manifest()
    engine = Engine(manifest)
    assert engine.manifest is manifest


# ── import_sessions: failure handling (FR-IMP-3 partial coverage) ──────────────


def test_import_sessions_skips_a_session_that_fails_to_import(tmp_path: Path) -> None:
    """A session whose folder isn't a recognised idtracker.ai output is
    skipped, not raised -- import_sessions() logs and continues per its
    current (documented-as-imperfect, see issue #7) contract."""
    from track2data.api import Engine

    bad_folder = tmp_path / "not_a_session"
    bad_folder.mkdir()
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="bad", folder=bad_folder, sha256=hashlib.sha256(b"x").hexdigest())
        ]
    )
    engine = Engine(manifest)
    sessions = engine.import_sessions()
    assert sessions == []


# ── preprocess: body-length calibration ─────────────────────────────────────


def test_preprocess_bodylength_calibration_failure_is_caught_and_skipped() -> None:
    """No body_length_px on the session -> calibration raises internally;
    preprocess() must catch it, warn, and still return a usable psess."""
    from track2data.api import Engine

    session = _make_session(body_length_px=None)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=session.folder, sha256="x")],
        calibration=CalibrationConfig(mode="bodylength"),
    )
    engine = Engine(manifest)
    psess = engine.preprocess(session)
    assert psess.px_per_cm is None


def test_preprocess_bodylength_calibration_success() -> None:
    from track2data.api import Engine

    n_animals = 2
    session = _make_session(
        n_frames=40, n_animals=n_animals, body_length_px=np.full(n_animals, 50.0)
    )
    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=session.folder, sha256="x")],
        calibration=CalibrationConfig(mode="bodylength", bl_min_samples=10),
    )
    engine = Engine(manifest)
    psess = engine.preprocess(session)
    assert psess.body_length_cm is not None


# ── preprocess: zone assignment ──────────────────────────────────────────────


def test_preprocess_assigns_zones_when_rois_configured() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=20, n_animals=1)
    zone_set = ZoneSet(
        rois=[ROI(name="A", level="main", vertices=[(0, 0), (1000, 0), (1000, 1000), (0, 1000)])]
    )
    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=session.folder, sha256="x")],
        zones=zone_set,
    )
    engine = Engine(manifest)
    psess = engine.preprocess(session)
    assert psess.main_zone is not None
    assert psess.main_zone.shape == (session.n_frames, session.n_animals)


# ── compute_metrics: unregistered metric / metric exception ────────────────────


def test_compute_metrics_skips_unregistered_metric_id() -> None:
    from track2data.api import Engine

    manifest = _make_manifest(metrics=MetricSelection(individual=["IL-DOES-NOT-EXIST"]))
    engine = Engine(manifest)
    psess = _make_psess(_make_session())
    results = engine.compute_metrics(psess)
    assert "IL-DOES-NOT-EXIST" not in results


def test_compute_metrics_catches_a_raising_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    import track2data.metrics as metrics_module
    from track2data.api import Engine
    from track2data.metrics.base import Metric, MetricDocumentation

    class BrokenMetric(Metric):
        id = "IL-BROKEN"
        name = "broken"
        label = "Broken"
        level = "individual"
        priority = "optional"
        requires_identity = False
        output_columns = ["session_id"]
        documentation = MetricDocumentation(
            definition="test-only broken metric",
            formula_plain="raises unconditionally",
            inputs=[],
            assumptions=[],
            warnings=[],
        )

        def compute(self, session, cfg=None):
            raise RuntimeError("boom")

    monkeypatch.setitem(metrics_module._registry, "IL-BROKEN", BrokenMetric)

    manifest = _make_manifest(metrics=MetricSelection(individual=["IL-BROKEN"]))
    engine = Engine(manifest)
    psess = _make_psess(_make_session())

    results = engine.compute_metrics(psess)  # must not raise
    assert "IL-BROKEN" not in results
    # Diagnostics (always-on) still computed despite the broken metric.
    assert "D-1" in results


# ── build_fish_by_frame: zone columns ───────────────────────────────────────


def test_build_fish_by_frame_includes_zone_columns_when_present() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=2)
    psess = _make_psess(session)
    main_zone = np.full((session.n_frames, session.n_animals), "zone_A", dtype=object)
    sec_zone = np.full((session.n_frames, session.n_animals), "zone_B", dtype=object)
    from dataclasses import replace

    psess = replace(psess, main_zone=main_zone, sec_zone=sec_zone)

    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert "main_zone" in df.columns
    assert "sec_zone" in df.columns
    assert (df["main_zone"] == "zone_A").all()
    assert (df["sec_zone"] == "zone_B").all()


# ── run_session: default exporters / unregistered exporter / exporter exception ─


def test_run_session_uses_default_exporters_when_none_configured(tmp_path: Path) -> None:
    """No exporters= arg and no manifest.export_targets -> falls back to
    ["csv_long", "readme"], per run_session()'s documented default."""
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(),
    )
    engine = Engine(manifest)
    written = engine.run_session(session, tmp_path)
    names = {p.name for p in written}
    assert "master_fish_by_frame.csv" in names  # from csv_long
    assert "README.md" in names  # from readme


def test_run_session_skips_unregistered_exporter(tmp_path: Path) -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(),
    )
    engine = Engine(manifest)
    written = engine.run_session(session, tmp_path, exporters=["not_a_real_exporter"])
    assert written == []


def test_run_session_catches_a_raising_exporter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import track2data.exporters as exporters_module
    from track2data.api import Engine
    from track2data.exporters.base import Exporter

    class BrokenExporter(Exporter):
        name = "broken_exporter"
        file_extension = ".txt"

        def write(self, payload, out_dir):
            raise RuntimeError("boom")

    monkeypatch.setitem(exporters_module._registry, "broken_exporter", BrokenExporter)

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(),
    )
    engine = Engine(manifest)
    written = engine.run_session(session, tmp_path, exporters=["broken_exporter"])  # must not raise
    assert written == []


# ── preview_frame ────────────────────────────────────────────────────────────


def test_preview_frame_returns_none_without_video_path() -> None:
    from track2data.api import Engine

    session = _make_session(video_path=None)
    engine = Engine(_make_manifest())
    assert engine.preview_frame(session) is None


def test_preview_frame_delegates_to_extract_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.api import Engine

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"")
    session = _make_session(video_path=video_path)

    calls: list[tuple[Path, int]] = []

    def fake_extract_frame(path: Path, frame_index: int = 0) -> bytes | None:
        calls.append((path, frame_index))
        return b"fake-rgb-bytes"

    monkeypatch.setattr("track2data.readers.video_meta.extract_frame", fake_extract_frame)

    engine = Engine(_make_manifest())
    result = engine.preview_frame(session, frame_index=3)

    assert result == b"fake-rgb-bytes"
    assert calls == [(video_path, 3)]


# ── validate ──────────────────────────────────────────────────────────────────


def test_validate_flags_scalar_mode_without_px_per_cm() -> None:
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=Path("/tmp/s1"), sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=None),
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    issues = engine.validate()
    assert any("px_per_cm" in issue for issue in issues)


# ── progress reporting (issue #18) ──────────────────────────────────────────────


def test_import_sessions_without_progress_still_works() -> None:
    """Backward compatibility: progress is optional and defaults to None."""
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=Path("/does/not/exist"), sha256="x")]
    )
    engine = Engine(manifest)
    assert engine.import_sessions() == []  # fails to import, logged+skipped, no crash


def test_import_sessions_emits_one_event_per_session(tiny_real_session: Path) -> None:
    from track2data.api import Engine
    from track2data.core.progress import ProgressEvent

    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="s1", folder=tiny_real_session, sha256="x"),
            SessionRef(session_id="s2", folder=tiny_real_session, sha256="x"),
            SessionRef(session_id="s3", folder=tiny_real_session, sha256="x"),
        ]
    )
    engine = Engine(manifest)
    events: list[ProgressEvent] = []
    engine.import_sessions(progress=events.append)

    assert [e.stage for e in events] == ["import", "import", "import"]
    assert [e.session_id for e in events] == ["s1", "s2", "s3"]
    assert [e.current for e in events] == [1, 2, 3]
    assert all(e.total == 3 for e in events)


def test_import_sessions_cancellation_propagates_not_swallowed(
    tiny_real_session: Path,
) -> None:
    """
    The progress emit for a session must happen BEFORE that session's
    import try/except opens -- otherwise a raised OperationCancelled from
    the callback would be caught by the broad `except Exception` around
    the import attempt and silently treated as "this session failed to
    import", continuing the loop instead of actually stopping the run.
    """
    from track2data.api import Engine
    from track2data.core.progress import OperationCancelled

    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="s1", folder=tiny_real_session, sha256="x"),
            SessionRef(session_id="s2", folder=tiny_real_session, sha256="x"),
            SessionRef(session_id="s3", folder=tiny_real_session, sha256="x"),
        ]
    )
    engine = Engine(manifest)
    seen: list[str] = []

    def cancel_on_second(event) -> None:
        seen.append(event.session_id)
        if event.session_id == "s2":
            raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        engine.import_sessions(progress=cancel_on_second)

    # Stopped at s2 -- s3 was never reached, proving the exception
    # propagated out of the loop rather than being logged and skipped.
    assert seen == ["s1", "s2"]


def test_run_session_emits_preprocess_metrics_export_in_order(tmp_path: Path) -> None:
    from track2data.api import Engine
    from track2data.core.progress import ProgressEvent

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    events: list[ProgressEvent] = []

    engine.run_session(session, tmp_path, exporters=["csv_long"], progress=events.append)

    assert [e.stage for e in events] == ["preprocess", "metrics", "export"]
    assert all(e.session_id == session.session_id for e in events)
    assert all(e.total == 3 for e in events)
    assert [e.current for e in events] == [1, 2, 3]


def test_run_all_emits_run_bookends_and_session_complete(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    from track2data.api import Engine
    from track2data.core.progress import ProgressEvent

    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="s1", folder=tiny_real_session, sha256="x"),
            SessionRef(session_id="s2", folder=tiny_real_session, sha256="x"),
        ],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    events: list[ProgressEvent] = []

    engine.run_all(tmp_path, exporters=["csv_long"], progress=events.append)

    stages = [e.stage for e in events]
    assert stages[0] == "run"
    assert stages[-1] == "run"
    assert stages.count("import") == 2
    assert stages.count("session") == 2
    # preprocess/metrics/export per session, twice.
    assert stages.count("preprocess") == 2
    assert stages.count("metrics") == 2
    assert stages.count("export") == 2

    run_events = [e for e in events if e.stage == "run"]
    assert run_events[0].current == 0
    assert run_events[-1].current == run_events[-1].total


def test_run_all_per_session_call_count_is_bounded(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """A per-frame hook would queue thousands of events; this bounds the
    actual call count to a small, fixed number of stage-boundary emits."""
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=tiny_real_session, sha256="x")],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    call_count = 0

    def counter(_event) -> None:
        nonlocal call_count
        call_count += 1

    engine.run_all(tmp_path, exporters=["csv_long"], progress=counter)

    # 1 run-start + 1 import + 3 run_session stages + 1 session-complete
    # + 1 run-end = 7 for a single-session run.
    assert call_count <= 8
