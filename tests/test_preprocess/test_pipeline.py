"""Tests for track2data.preprocess.pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import (
    GapFillCfg,
    IdSwitchCfg,
    JumpCfg,
    PreprocessConfig,
    PreprocessedSession,
    Session,
    SmoothCfg,
    VideoInfo,
)
from track2data.preprocess.pipeline import run

# ── Helper to build a minimal Session ──────────────────────────────────────────


def _make_session(xy: np.ndarray, session_id: str = "test") -> Session:
    n_frames, n_animals, _ = xy.shape
    return Session(
        session_id=session_id,
        folder=".",
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=1920, height_px=1080),
        n_animals=n_animals,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )


@pytest.fixture()
def tiny_session() -> Session:
    """100 frames, 4 animals. Animal 0 has a 5-frame NaN gap."""
    xy = np.zeros((100, 4, 2), dtype=np.float64)
    frames = np.arange(100, dtype=np.float64)
    xy[:, 0, 0] = 100.0 + frames * 5.0
    xy[:, 0, 1] = 200.0
    xy[20:25, 0, :] = np.nan
    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 4.0
    xy[:, 2, 0] = 960.0 + 100.0 * np.cos(frames * 0.1)
    xy[:, 2, 1] = 540.0 + 100.0 * np.sin(frames * 0.1)
    xy[:, 3, 0] = 800.0
    xy[:, 3, 1] = 600.0
    return _make_session(xy)


def test_run_returns_preprocessed_session(tiny_session: Session) -> None:
    """run() must return a PreprocessedSession."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert isinstance(result, PreprocessedSession)


def test_raw_xy_not_modified(tiny_session: Session) -> None:
    """pipeline.run must not mutate session.raw_xy."""
    original = tiny_session.raw_xy.copy()
    cfg = PreprocessConfig()
    run(tiny_session, cfg)
    np.testing.assert_array_equal(tiny_session.raw_xy, original)


def test_output_xy_shape(tiny_session: Session) -> None:
    """Output xy shape must match input raw_xy shape."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.xy.shape == tiny_session.raw_xy.shape


def test_kinematics_computed(tiny_session: Session) -> None:
    """PreprocessedSession.kinematics must be populated."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.kinematics is not None
    assert result.kinematics.speed_px_s.shape == (100, 4)
    assert result.kinematics.accel_px_s2.shape == (100, 4)
    assert result.kinematics.heading_rad.shape == (100, 4)


def test_report_has_steps(tiny_session: Session) -> None:
    """PreprocessReport must include at least one step."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert len(result.report.steps) > 0


def test_gap_filled_by_pipeline(tiny_session: Session) -> None:
    """Gap at frames 20-24 for animal 0 should be filled by pipeline."""
    cfg = PreprocessConfig(gap_fill=GapFillCfg(enabled=True, max_gap_frames=30))
    result = run(tiny_session, cfg)
    assert not np.any(np.isnan(result.xy[20:25, 0, :]))


def test_all_steps_in_report(tiny_session: Session) -> None:
    """All expected step names should appear in the report."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    step_names = {s.step_name for s in result.report.steps}
    assert "gap_fill" in step_names
    assert "jump_detect" in step_names
    assert "smoothing" in step_names
    assert "validate_coverage" in step_names


def test_session_id_property(tiny_session: Session) -> None:
    """PreprocessedSession.session_id should match the input session."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.session_id == "test"


def test_fps_property(tiny_session: Session) -> None:
    """PreprocessedSession.fps should match the session fps."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.fps == 25.0


def test_n_frames_property(tiny_session: Session) -> None:
    """PreprocessedSession.n_frames should match raw_xy."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.n_frames == 100


def test_n_animals_property(tiny_session: Session) -> None:
    """PreprocessedSession.n_animals should match raw_xy."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.n_animals == 4


def test_all_disabled_pipeline() -> None:
    """With all steps disabled, output xy should be identical to raw_xy (modulo smoothing)."""
    xy = np.ones((50, 2, 2), dtype=np.float64) * 5.0
    session = _make_session(xy)
    cfg = PreprocessConfig(
        gap_fill=GapFillCfg(enabled=False),
        jump=JumpCfg(enabled=False),
        identity_switch=IdSwitchCfg(enabled=False),
        smoothing=SmoothCfg(enabled=False),
    )
    result = run(session, cfg)
    np.testing.assert_array_equal(result.xy, xy)


def test_report_total_affected_frames(tiny_session: Session) -> None:
    """PreprocessReport.total_affected_frames should be non-negative."""
    cfg = PreprocessConfig()
    result = run(tiny_session, cfg)
    assert result.report.total_affected_frames >= 0


def test_pipeline_passes_velocity_threshold_to_jump_detect() -> None:
    """Session.velocity_threshold_px_frame must reach detect_jumps() when
    JumpCfg.method='idtracker_velocity_threshold' -- regression coverage
    for the pipeline-level wiring, not just the jump_detect unit itself."""
    xy = np.zeros((60, 1, 2), dtype=np.float64)
    frames = np.arange(60, dtype=np.float64)
    xy[:, 0, 0] = frames * 3.0
    xy[:, 0, 1] = 0.0
    xy[30, 0, 0] += 500.0  # injected jump

    session = _make_session(xy)
    session = session.model_copy(update={"velocity_threshold_px_frame": 20.0})
    cfg = PreprocessConfig(
        gap_fill=GapFillCfg(enabled=False),
        jump=JumpCfg(
            enabled=True, method="idtracker_velocity_threshold", replacement="nan"
        ),
        identity_switch=IdSwitchCfg(enabled=False),
        smoothing=SmoothCfg(enabled=False),
    )
    psess = run(session, cfg)
    jump_step = next(s for s in psess.report.steps if s.step_name == "jump_detect")
    assert jump_step.affected_frames >= 1


# ── Fragment-guided identity-switch wiring ────────────────────────────────────


def _fragments_with_boundary_at(end_frame: int, n_animals: int) -> dict:
    """Minimal list_of_fragments.json payload with one swap boundary.

    Shaped the way readers/idtrackerai/fragments.py documents the real file:
    'end_frame' is exclusive, 'identity' is 1-based, and only the keys in
    FRAGMENT_ALWAYS_PRESENT may be assumed. A fragment whose
    identity_is_fixed is not True contributes its end_frame as a frame where
    a swap is physically possible.
    """
    return {
        "n_animals": n_animals,
        "fragments": [
            {
                "identifier": 0,
                "start_frame": 0,
                "end_frame": end_frame,
                "is_an_individual": True,
                "identity": 1,
            },
            {
                "identifier": 1,
                "start_frame": end_frame,
                "end_frame": 60,
                "is_an_individual": True,
                "identity_is_fixed": True,
                "identity": 2,
            },
        ],
    }


def _crossing_with_persistent_switch(switch_at: int = 21) -> tuple[np.ndarray, np.ndarray]:
    """Two animals crossing, labels swapped from *switch_at* onward."""
    t = np.arange(60, dtype=np.float64)
    a = np.stack([t * 2.0, np.full(60, 100.0)], axis=1)
    b = np.stack([120.0 - t * 2.0, np.full(60, 100.0)], axis=1)
    truth = np.stack([a, b], axis=1)
    obs = truth.copy()
    obs[switch_at:, 0, :] = truth[switch_at:, 1, :]
    obs[switch_at:, 1, :] = truth[switch_at:, 0, :]
    return truth, obs


def test_identity_switch_receives_fragment_boundaries() -> None:
    """Session.fragments must reach correct_switches, the way the crossing mask
    already reaches fill_gaps.

    A swap is physically possible only at a fragment boundary, so this is the
    difference between correcting the real switch and scanning every frame
    hoping to find it.
    """
    switch_at = 21
    truth, obs = _crossing_with_persistent_switch(switch_at)

    session = _make_session(obs)
    session = session.model_copy(
        update={"fragments": _fragments_with_boundary_at(switch_at, n_animals=2)}
    )
    cfg = PreprocessConfig(
        gap_fill=GapFillCfg(enabled=False),
        jump=JumpCfg(enabled=False),
        identity_switch=IdSwitchCfg(enabled=True),
        smoothing=SmoothCfg(enabled=False),
    )

    psess = run(session, cfg)

    step = next(s for s in psess.report.steps if s.step_name == "identity_switch")
    assert step.affected_frames > 0
    np.testing.assert_allclose(psess.xy, truth)


def test_identity_switch_without_fragments_still_runs() -> None:
    """Fragment data is a bonus, never a requirement -- same policy as gap_fill."""
    switch_at = 21
    truth, obs = _crossing_with_persistent_switch(switch_at)

    session = _make_session(obs)
    assert session.fragments is None
    cfg = PreprocessConfig(
        gap_fill=GapFillCfg(enabled=False),
        jump=JumpCfg(enabled=False),
        identity_switch=IdSwitchCfg(enabled=True),
        smoothing=SmoothCfg(enabled=False),
    )

    psess = run(session, cfg)

    np.testing.assert_allclose(psess.xy, truth)
