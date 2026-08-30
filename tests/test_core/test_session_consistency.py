"""Tests for track2data.core.session_consistency."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import Session, VideoInfo
from track2data.core.session_consistency import (
    SessionSummary,
    heterogeneity_warnings,
    sessions_table,
)


def _summary(
    session_id: str = "s1",
    *,
    fps: float = 30.0,
    n_frames: int = 900,
    n_animals: int = 4,
    width_px: int = 1920,
    height_px: int = 1080,
    length_unit: float | None = None,
    calibration_mode: str = "bodylength",
    px_per_cm: float | None = 10.0,
) -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        reader="idtrackerai_v5",
        fps=fps,
        n_frames=n_frames,
        n_animals=n_animals,
        width_px=width_px,
        height_px=height_px,
        length_unit=length_unit,
        calibration_mode=calibration_mode,
        px_per_cm=px_per_cm,
    )


# ── SessionSummary ────────────────────────────────────────────────────────────


def test_duration_derived_from_fps_and_frames() -> None:
    assert _summary(fps=30.0, n_frames=900).duration_s == pytest.approx(30.0)


def test_duration_is_nan_when_fps_unusable() -> None:
    """A zero fps must not raise here -- it is exactly the broken metadata
    this module exists to surface."""
    assert math.isnan(_summary(fps=0.0).duration_s)


def test_from_session_reads_the_session_not_the_manifest() -> None:
    xy = np.zeros((120, 3, 2), dtype=np.float64)
    session = Session(
        session_id="probe",
        folder=".",
        reader="idtrackerai_v5",
        video=VideoInfo(fps=60.0, n_frames=120, width_px=800, height_px=600),
        n_animals=3,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        length_unit=12.5,
    )

    summary = SessionSummary.from_session(
        session, calibration_mode="session", px_per_cm=12.5
    )

    assert summary.session_id == "probe"
    assert summary.fps == 60.0
    assert summary.n_frames == 120
    assert summary.n_animals == 3
    assert summary.length_unit == 12.5
    assert summary.calibration_mode == "session"
    assert summary.is_calibrated


# ── heterogeneity_warnings ────────────────────────────────────────────────────


def test_homogeneous_project_warns_about_nothing() -> None:
    summaries = [_summary("a"), _summary("b"), _summary("c")]
    assert heterogeneity_warnings(summaries) == []


def test_single_session_project_warns_about_nothing() -> None:
    """With one session there is nothing to disagree with."""
    assert heterogeneity_warnings([_summary("only")]) == []
    assert heterogeneity_warnings([]) == []


def test_mixed_frame_rates_are_reported() -> None:
    """The headline case: 30 fps and 60 fps sessions pooled in one project."""
    summaries = [_summary("a", fps=30.0), _summary("b", fps=60.0)]

    warnings = heterogeneity_warnings(summaries)

    assert len(warnings) == 1
    assert "frame rate" in warnings[0]
    # Must name the sessions, not just count them.
    assert "a" in warnings[0]
    assert "b" in warnings[0]


def test_mixed_calibration_availability_is_reported() -> None:
    summaries = [
        _summary("calibrated", px_per_cm=10.0),
        _summary("raw", px_per_cm=None),
    ]

    warnings = heterogeneity_warnings(summaries)

    assert len(warnings) == 1
    assert "raw" in warnings[0]
    assert "NaN" in warnings[0]


def test_mixed_calibration_mode_is_reported() -> None:
    summaries = [
        _summary("a", calibration_mode="bodylength"),
        _summary("b", calibration_mode="scalar"),
    ]

    warnings = heterogeneity_warnings(summaries)

    assert any("different methods" in w for w in warnings)


def test_mixed_group_size_is_reported() -> None:
    """Group metrics depend on group size by construction."""
    summaries = [_summary("a", n_animals=4), _summary("b", n_animals=8)]

    warnings = heterogeneity_warnings(summaries)

    assert any("numbers of animals" in w for w in warnings)


def test_mixed_resolution_is_reported() -> None:
    summaries = [
        _summary("a", width_px=1920, height_px=1080),
        _summary("b", width_px=1280, height_px=720),
    ]

    warnings = heterogeneity_warnings(summaries)

    assert any("resolution" in w for w in warnings)


def test_several_disagreements_are_reported_independently() -> None:
    """One fix per warning: collapsing them would hide the second problem."""
    summaries = [
        _summary("a", fps=30.0, n_animals=4),
        _summary("b", fps=60.0, n_animals=8),
    ]

    warnings = heterogeneity_warnings(summaries)

    assert len(warnings) == 2


def test_session_names_are_truncated_but_counted() -> None:
    """A 70-session project must not produce an unreadable wall of ids."""
    summaries = [_summary(f"s{i}", fps=30.0) for i in range(10)]
    summaries.append(_summary("odd_one", fps=60.0))

    warning = heterogeneity_warnings(summaries)[0]

    assert "more" in warning
    assert "odd_one" in warning


# ── sessions_table ────────────────────────────────────────────────────────────


def test_sessions_table_has_one_row_per_session() -> None:
    df = sessions_table([_summary("a"), _summary("b")])
    assert list(df["session_id"]) == ["a", "b"]


def test_sessions_table_carries_the_facts_needed_to_filter() -> None:
    df = sessions_table([_summary("a", fps=30.0, n_frames=900, n_animals=4)])
    row = df.iloc[0]
    assert row["fps"] == 30.0
    assert row["n_frames"] == 900
    assert row["duration_s"] == pytest.approx(30.0)
    assert row["n_animals"] == 4
    assert bool(row["is_calibrated"]) is True


def test_failed_sessions_still_get_a_row() -> None:
    """"Excluded because it failed" and "never in the project" are different
    facts, and a reader of the export can only tell them apart if the failed
    session is present."""
    df = sessions_table(
        [_summary("ok"), _summary("broken")],
        errors={"broken": "trajectory file not found"},
    )

    assert len(df) == 2
    assert df.loc[df["session_id"] == "ok", "error"].isna().all()
    assert "not found" in df.loc[df["session_id"] == "broken", "error"].iloc[0]


def test_sessions_table_column_order_is_stable() -> None:
    """The file is a published contract; column order is part of it."""
    df = sessions_table([_summary("a")])
    assert list(df.columns) == [
        "session_id", "reader", "fps", "n_frames", "duration_s", "n_animals",
        "width_px", "height_px", "calibration_mode", "length_unit",
        "px_per_cm", "is_calibrated", "is_identity_free",
        "trajectory_source", "trajectory_sha256", "error",
    ]


def test_empty_sessions_table_still_has_the_columns() -> None:
    df = sessions_table([])
    assert len(df) == 0
    assert "session_id" in df.columns


def test_session_that_failed_before_summarising_still_gets_a_row() -> None:
    """A run where a session died at import must not silently produce a
    shorter table -- that reads as a smaller study."""
    import pandas as pd

    df = sessions_table(
        [_summary("ok")],
        errors={"never_read": "trajectory file not found"},
    )

    assert list(df["session_id"]) == ["ok", "never_read"]
    failed = df.iloc[1]
    assert failed["error"] == "trajectory file not found"
    assert pd.isna(failed["fps"])
    assert pd.isna(failed["n_animals"])


def test_table_of_only_failures_still_names_them() -> None:
    df = sessions_table([], errors={"a": "boom", "b": "boom"})
    assert list(df["session_id"]) == ["a", "b"]


# ── provenance (trajectory hash) ──────────────────────────────────────────────


def test_from_session_records_the_file_that_was_read() -> None:
    """The reader falls back between formats, so the file that produced the
    numbers cannot be re-derived from the folder afterwards."""
    xy = np.zeros((10, 2, 2), dtype=np.float64)
    session = Session(
        session_id="s",
        folder=".",
        reader="idtrackerai",
        video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=100),
        n_animals=2,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        trajectory_source=Path("sessions") / "s" / "trajectories" / "trajectories.npy",
    )

    summary = SessionSummary.from_session(
        session, calibration_mode="scalar", trajectory_sha256="abc123"
    )

    # The name, not the absolute path: the path is machine-specific and would
    # make otherwise-identical exports differ.
    assert summary.trajectory_source == "trajectories.npy"
    assert summary.trajectory_sha256 == "abc123"


def test_summary_without_a_hash_says_so_rather_than_guessing() -> None:
    """Pre-flight reports skip hashing; the field must be empty, not wrong."""
    summary = _summary("a")
    assert summary.trajectory_sha256 == ""
    assert summary.trajectory_source is None


def test_sessions_table_reports_a_missing_hash_as_null() -> None:
    """An empty string in a checksum column reads as "hashed to nothing"."""
    import pandas as pd

    df = sessions_table([_summary("a")])
    assert pd.isna(df.iloc[0]["trajectory_sha256"])
