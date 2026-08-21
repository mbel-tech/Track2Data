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


# ── import_sessions: failure handling (issue #7 / FR-IMP-3) ────────────────────


def test_import_sessions_raises_on_a_session_that_fails_to_import(tmp_path: Path) -> None:
    """FR-IMP-3: flag failures with an actionable message, never silently.
    A session whose folder isn't a recognised idtracker.ai output must
    raise -- not be logged and dropped -- so a bad session in a project
    is impossible to miss."""
    from track2data.api import Engine
    from track2data.core.errors import Track2DataError

    bad_folder = tmp_path / "not_a_session"
    bad_folder.mkdir()
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="bad", folder=bad_folder, sha256=hashlib.sha256(b"x").hexdigest())
        ]
    )
    engine = Engine(manifest)
    with pytest.raises(Track2DataError) as exc_info:
        engine.import_sessions()
    # Actionable: names the offending folder, not just "something failed".
    assert str(bad_folder) in str(exc_info.value)


def test_import_sessions_stops_at_the_first_failure(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """Fail loud means fail immediately -- a later, importable session
    must never be silently attempted/skipped past a broken one."""
    from track2data.api import Engine
    from track2data.core.errors import Track2DataError

    bad_folder = tmp_path / "not_a_session"
    bad_folder.mkdir()
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="bad", folder=bad_folder, sha256="x"),
            SessionRef(session_id="good", folder=tiny_real_session, sha256="x"),
        ]
    )
    engine = Engine(manifest)
    with pytest.raises(Track2DataError):
        engine.import_sessions()


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


# ── build_fish_by_frame: tracking_intervals frame/time offset ──────────────
#
# Regression coverage: frame/time_s used to be the raw array position,
# ignoring Session.tracking_intervals. A session tracked with
# --tracking_intervals "[9000,18000]" would export frame=0..8999 for data
# that is really frames 9000..17999. All 70 real corpus sessions happen to
# have a single trivial interval [0, n_frames], so this can only be
# verified synthetically -- see also the direct unit tests on
# api._map_array_index_to_true_frame.


def test_frame_column_offset_by_tracking_interval_start() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=5, n_animals=1)
    session = session.model_copy(update={"tracking_intervals": [(9000, 9005)]})
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["frame"]) == [9000, 9001, 9002, 9003, 9004]
    assert df["in_tracking_interval"].all()


def test_time_s_reflects_gap_between_multiple_intervals() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=4, n_animals=1)
    session = session.model_copy(
        update={"tracking_intervals": [(0, 2), (150, 152)], "video": session.video.model_copy(
            update={"fps": 1.0}
        )}
    )
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["frame"]) == [0, 1, 150, 151]
    assert list(df["time_s"]) == [0.0, 1.0, 150.0, 151.0]


def test_mismatched_tracking_intervals_falls_back_to_array_position() -> None:
    """Intervals that don't reconcile with n_frames (e.g. a partial
    session.json) must not corrupt the frame axis -- fall back to today's
    behaviour and mark in_tracking_interval as unknown (NaN), not False."""
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    session = session.model_copy(update={"tracking_intervals": [(0, 3)]})  # sums to 3, not 10
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["frame"]) == list(range(10))
    assert df["in_tracking_interval"].isna().all()


def test_no_tracking_intervals_falls_back_to_array_position() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=5, n_animals=1)  # tracking_intervals defaults to None
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["frame"]) == [0, 1, 2, 3, 4]
    assert df["in_tracking_interval"].isna().all()


# ── build_fish_by_frame: identities_labels / identities_colors ─────────────
#
# Regression coverage: identities_labels was on Session and unused;
# identities_colors wasn't even read. A user who spent time naming/
# colouring identities in the Validator got bare 0..N-1 individual_id
# integers back in the export.


def test_individual_label_column_present_when_labels_set() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=3, n_animals=2)
    session = session.model_copy(update={"identities_labels": ["Alpha", "Beta"]})
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert set(df.loc[df["individual_id"] == 0, "individual_label"]) == {"Alpha"}
    assert set(df.loc[df["individual_id"] == 1, "individual_label"]) == {"Beta"}


def test_individual_color_column_present_when_colors_set() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=3, n_animals=2)
    session = session.model_copy(
        update={"identities_colors": ["#ff0000", "#00ff00"]}
    )
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert set(df.loc[df["individual_id"] == 0, "individual_color"]) == {"#ff0000"}
    assert set(df.loc[df["individual_id"] == 1, "individual_color"]) == {"#00ff00"}


def test_no_label_color_columns_when_absent() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=3, n_animals=2)
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert "individual_label" not in df.columns
    assert "individual_color" not in df.columns


def test_labels_shorter_than_n_animals_does_not_crash() -> None:
    """A malformed/partial identities_labels must degrade to None per
    row, not IndexError the whole export."""
    from track2data.api import Engine

    session = _make_session(n_frames=2, n_animals=2)
    session = session.model_copy(update={"identities_labels": ["OnlyOne"]})
    psess = _make_psess(session)
    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert set(df.loc[df["individual_id"] == 0, "individual_label"]) == {"OnlyOne"}
    assert df.loc[df["individual_id"] == 1, "individual_label"].isna().all()


# ── build_fish_by_frame: was_interpolated ───────────────────────────────────
#
# Regression coverage: trajectory_variant was a Session-level constant
# (always "with_gaps"), so nothing in the export could distinguish a
# measured position from a reconstructed one.


def test_was_interpolated_true_where_raw_nan_now_filled() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=5, n_animals=1)
    raw_xy = session.raw_xy.copy()
    raw_xy[2, 0, :] = np.nan  # frame 2 was originally missing
    session = session.model_copy(update={"raw_xy": raw_xy})

    n_frames, n_animals = session.n_frames, session.n_animals
    kine = KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )
    filled_xy = raw_xy.copy()
    filled_xy[2, 0, :] = [123.0, 456.0]  # gap_fill filled it in
    psess = PreprocessedSession(
        session=session, xy=filled_xy, kinematics=kine, report=PreprocessReport()
    )

    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["was_interpolated"]) == [False, False, True, False, False]


def test_was_interpolated_false_when_still_nan() -> None:
    """A gap left unfilled (too long) must not be marked interpolated --
    it's still missing, not reconstructed."""
    from track2data.api import Engine

    session = _make_session(n_frames=3, n_animals=1)
    raw_xy = session.raw_xy.copy()
    raw_xy[1, 0, :] = np.nan
    session = session.model_copy(update={"raw_xy": raw_xy})
    psess = _make_psess(session)  # xy = raw_xy unchanged, still NaN at frame 1

    engine = Engine(_make_manifest())
    df = engine.build_fish_by_frame(psess)
    assert list(df["was_interpolated"]) == [False, False, False]


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


# ── build_fish_by_frame: quality_threshold gate ─────────────────────────────
#
# Regression coverage: MetricSelection.quality_threshold was collected by the
# UI, saved in the manifest, and read by zero lines of the engine -- setting
# "0.9" and exporting produced a manifest that asserted a filter that was
# never applied. See core/models.py's quality_threshold docstring.


def test_quality_threshold_zero_masks_nothing() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=2)
    session = session.model_copy(
        update={"id_probabilities": np.full((10, 2), 0.5)}
    )
    psess = _make_psess(session)
    engine = Engine(_make_manifest(metrics=MetricSelection(quality_threshold=0.0)))
    df = engine.build_fish_by_frame(psess)
    assert df["x_px"].isna().sum() == 0
    assert "id_probability" in df.columns


def test_quality_threshold_masks_only_low_confidence_rows() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=4, n_animals=2)
    probs = np.array([[0.95, 0.2], [0.95, 0.2], [0.95, 0.2], [0.95, 0.2]])
    session = session.model_copy(update={"id_probabilities": probs})
    psess = _make_psess(session)
    engine = Engine(_make_manifest(metrics=MetricSelection(quality_threshold=0.5)))
    df = engine.build_fish_by_frame(psess)

    animal0 = df[df["individual_id"] == 0]
    animal1 = df[df["individual_id"] == 1]
    assert animal0["x_px"].isna().sum() == 0
    assert animal1["x_px"].isna().sum() == len(animal1)
    assert animal1["y_px"].isna().sum() == len(animal1)
    assert animal1["speed_px_s"].isna().sum() == len(animal1)
    # session_id/individual_id/frame/time_s survive the mask -- the row is
    # still locatable, only its measured values are withheld.
    assert animal1["frame"].isna().sum() == 0


def test_quality_threshold_masks_calibrated_columns_too() -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=2, n_animals=1)
    session = session.model_copy(update={"id_probabilities": np.array([[0.1], [0.1]])})
    psess = _make_psess(session)
    from dataclasses import replace

    psess = replace(psess, px_per_cm=10.0)
    engine = Engine(_make_manifest(metrics=MetricSelection(quality_threshold=0.5)))
    df = engine.build_fish_by_frame(psess)
    assert df["x_cm"].isna().all()
    assert df["speed_cm_s"].isna().all()


def test_quality_threshold_without_id_probabilities_warns_and_masks_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A configured threshold with no id_probabilities to evaluate it
    against must not silently pretend the filter was applied."""
    from track2data.api import Engine

    session = _make_session(n_frames=5, n_animals=2)  # id_probabilities=None
    psess = _make_psess(session)
    engine = Engine(_make_manifest(metrics=MetricSelection(quality_threshold=0.9)))
    with caplog.at_level("WARNING"):
        df = engine.build_fish_by_frame(psess)
    assert df["x_px"].isna().sum() == 0
    assert df["id_probability"].isna().all()
    assert any("quality_threshold" in rec.message for rec in caplog.records)


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


def test_import_sessions_without_progress_still_works(tiny_real_session: Path) -> None:
    """Backward compatibility: progress is optional and defaults to None."""
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[SessionRef(session_id="s1", folder=tiny_real_session, sha256="x")]
    )
    engine = Engine(manifest)
    sessions = engine.import_sessions()
    assert len(sessions) == 1


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


# ── build_payload / export extraction, Engine.run()/RunResult (issue #19) ──────


def test_engine_has_export_method() -> None:
    from track2data.api import Engine

    assert hasattr(Engine, "export")
    assert callable(Engine.export)


def test_export_writes_only_requested_exporters(tmp_path: Path) -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(metrics=MetricSelection(individual=["IL-1"]))
    engine = Engine(manifest)
    psess = engine.preprocess(session)
    metric_results = engine.compute_metrics(psess)
    payload = engine.build_payload(psess, metric_results)

    written = engine.export(payload, tmp_path, exporters=["csv_long"])

    assert len(written) > 0
    assert all(p.exists() for p in written)
    # csv_long writes 3 files; readme/excel weren't requested.
    assert not (tmp_path / "README.md").exists()


def test_build_payload_buckets_metrics_by_level(tmp_path: Path) -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=2)
    manifest = _make_manifest(
        metrics=MetricSelection(individual=["IL-1"], group=["GL-1"], zone=[], diagnostic=[])
    )
    engine = Engine(manifest)
    psess = engine.preprocess(session)
    metric_results = engine.compute_metrics(psess)

    payload = engine.build_payload(psess, metric_results)

    assert "IL-1" in payload.individual_metrics
    assert "GL-1" in payload.group_metrics
    assert "IL-1" not in payload.group_metrics
    assert "GL-1" not in payload.individual_metrics
    assert all(k.startswith("D-") for k in payload.diagnostic_metrics)
    assert set(payload.diagnostic_metrics) == {"D-1", "D-2", "D-3", "D-4", "D-5"}


def test_run_session_still_returns_list_of_paths_unchanged(tmp_path: Path) -> None:
    """run_session's signature/return type must be exactly preserved by the
    build_payload/export extraction -- CLI and existing callers depend on it."""
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(metrics=MetricSelection(individual=["IL-1"]))
    engine = Engine(manifest)

    written = engine.run_session(session, tmp_path, exporters=["csv_long"])

    assert isinstance(written, list)
    assert all(isinstance(p, Path) for p in written)
    assert len(written) > 0


def test_run_two_sessions_produces_non_colliding_output(tmp_path: Path) -> None:
    """
    The overwrite regression test. Before this fix, run_all() passed the
    same out_dir to every session's run_session() call, so session 2's
    master_fish_by_frame.csv silently clobbered session 1's.
    """
    from track2data.api import Engine

    session_a = _make_session(session_id="session_a", n_frames=10, n_animals=1)
    session_b = _make_session(session_id="session_b", n_frames=15, n_animals=1)
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="session_a", folder=session_a.folder, sha256="x"),
            SessionRef(session_id="session_b", folder=session_b.folder, sha256="x"),
        ],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)

    # import_session() auto-detects by folder; monkeypatch it to hand back
    # our two in-memory sessions instead of reading real folders from disk.
    sessions_by_folder = {session_a.folder: session_a, session_b.folder: session_b}
    engine.import_session = lambda folder: sessions_by_folder[Path(folder)]  # type: ignore[method-assign]

    result = engine.run(tmp_path, exporters=["csv_long"])

    csv_a = tmp_path / "session_a" / "master_fish_by_frame.csv"
    csv_b = tmp_path / "session_b" / "master_fish_by_frame.csv"
    assert csv_a.exists()
    assert csv_b.exists()

    import pandas as pd

    df_a = pd.read_csv(csv_a)
    df_b = pd.read_csv(csv_b)
    assert len(df_a) == 10  # session_a's n_frames * n_animals
    assert len(df_b) == 15  # session_b's n_frames * n_animals -- distinct, not clobbered
    assert len(result.sessions) == 2


def test_run_all_also_uses_non_colliding_per_session_dirs(tmp_path: Path) -> None:
    """run_all() is a thin wrapper over run() -- must inherit the fix too."""
    from track2data.api import Engine

    session_a = _make_session(session_id="session_a", n_frames=10, n_animals=1)
    session_b = _make_session(session_id="session_b", n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="session_a", folder=session_a.folder, sha256="x"),
            SessionRef(session_id="session_b", folder=session_b.folder, sha256="x"),
        ],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    sessions_by_folder = {session_a.folder: session_a, session_b.folder: session_b}
    engine.import_session = lambda folder: sessions_by_folder[Path(folder)]  # type: ignore[method-assign]

    written = engine.run_all(tmp_path, exporters=["csv_long"])

    assert (tmp_path / "session_a" / "master_fish_by_frame.csv").exists()
    assert (tmp_path / "session_b" / "master_fish_by_frame.csv").exists()
    assert len(written) > 2  # 3 files/session * 2 sessions


def test_session_run_result_does_not_retain_fish_by_frame_and_is_picklable(
    tmp_path: Path,
) -> None:
    from track2data.api import Engine
    from track2data.core.models import SessionRunResult

    # Structural check: fish_by_frame (or any full per-frame table) is not
    # even a field this dataclass can hold, not just "empty this time".
    field_names = {f.name for f in __import__("dataclasses").fields(SessionRunResult)}
    assert "fish_by_frame" not in field_names

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    engine.import_session = lambda folder: session  # type: ignore[method-assign]

    result = engine.run(tmp_path, exporters=["csv_long"])

    import pickle

    pickled = pickle.dumps(result.sessions[0])
    restored = pickle.loads(pickled)
    assert restored.session_id == session.session_id


def test_run_captures_per_session_error_without_aborting_batch(tmp_path: Path) -> None:
    from track2data.api import Engine

    good = _make_session(session_id="good", n_frames=10, n_animals=1)
    bad = _make_session(session_id="bad", n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="good", folder=good.folder, sha256="x"),
            SessionRef(session_id="bad", folder=bad.folder, sha256="x"),
        ],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    sessions_by_folder = {good.folder: good, bad.folder: bad}
    engine.import_session = lambda folder: sessions_by_folder[Path(folder)]  # type: ignore[method-assign]

    real_preprocess = engine.preprocess

    def flaky_preprocess(session):
        if session.session_id == "bad":
            raise RuntimeError("simulated preprocessing failure")
        return real_preprocess(session)

    engine.preprocess = flaky_preprocess  # type: ignore[method-assign]

    result = engine.run(tmp_path, exporters=["csv_long"])

    by_id = {s.session_id: s for s in result.sessions}
    assert by_id["good"].error is None
    assert len(by_id["good"].written) > 0
    assert by_id["bad"].error is not None
    assert "simulated preprocessing failure" in by_id["bad"].error
    assert by_id["bad"].written == []


def test_run_captures_an_import_failure_as_a_per_session_error_without_aborting_batch(
    tmp_path: Path, tiny_real_session: Path
) -> None:
    """Engine.run() is the batch orchestrator: unlike import_sessions()
    (which now fails loud, see #7), a session that fails to *import*
    inside run() must be captured as that session's SessionRunResult.error
    -- exactly like a preprocess/metrics/export failure already is --
    rather than silently vanishing from RunResult.sessions."""
    from track2data.api import Engine

    bad_folder = tmp_path / "not_a_session"
    bad_folder.mkdir()
    manifest = _make_manifest(
        sessions=[
            SessionRef(session_id="bad", folder=bad_folder, sha256="x"),
            SessionRef(session_id="good", folder=tiny_real_session, sha256="x"),
        ],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)

    result = engine.run(tmp_path, exporters=["csv_long"])

    by_id = {s.session_id: s for s in result.sessions}
    assert len(result.sessions) == 2  # both sessions present, not just the good one
    assert by_id["bad"].error is not None
    assert str(bad_folder) in by_id["bad"].error
    assert by_id["bad"].written == []
    assert by_id["good"].error is None
    assert len(by_id["good"].written) > 0


def test_run_all_is_a_thin_wrapper_returning_run_written(tmp_path: Path) -> None:
    from track2data.api import Engine

    session = _make_session(n_frames=10, n_animals=1)
    manifest = _make_manifest(
        sessions=[SessionRef(session_id=session.session_id, folder=session.folder, sha256="x")],
        metrics=MetricSelection(individual=["IL-1"]),
    )
    engine = Engine(manifest)
    engine.import_session = lambda folder: session  # type: ignore[method-assign]

    written = engine.run_all(tmp_path, exporters=["csv_long"])
    assert isinstance(written, list)
    assert len(written) > 0
