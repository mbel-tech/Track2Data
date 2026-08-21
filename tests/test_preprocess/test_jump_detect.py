"""Tests for track2data.preprocess.jump_detect."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import JumpCfg, PPStepResult
from track2data.preprocess.jump_detect import detect_jumps


@pytest.fixture()
def smooth_xy() -> np.ndarray:
    """100 frames, 2 animals with smooth motion (step=5 px/frame)."""
    xy = np.zeros((100, 2, 2), dtype=np.float64)
    frames = np.arange(100, dtype=np.float64)
    xy[:, 0, 0] = frames * 5.0
    xy[:, 0, 1] = 100.0
    xy[:, 1, 0] = frames * 3.0
    xy[:, 1, 1] = 200.0
    return xy


def _inject_jump(xy: np.ndarray, animal: int, frame: int, magnitude: float = 1000.0) -> np.ndarray:
    """Insert an anomalous displacement at `frame` for `animal`."""
    out = xy.copy()
    out[frame, animal, 0] += magnitude
    return out


def test_no_jumps_returns_unchanged(smooth_xy: np.ndarray) -> None:
    """Smooth trajectory without jumps should return identical array."""
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=10.0, replacement="linear_interp")
    out, result = detect_jumps(smooth_xy, cfg)
    np.testing.assert_allclose(out, smooth_xy, rtol=1e-9)
    assert result.affected_frames == 0


def test_jump_detected_sd_method(smooth_xy: np.ndarray) -> None:
    """Large displacement triggers flag with sd_multiple method."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="nan")
    _out, result = detect_jumps(xy, cfg)
    assert result.affected_frames > 0


def test_jump_replaced_with_nan(smooth_xy: np.ndarray) -> None:
    """When replacement='nan', flagged frames are set to NaN."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="nan")
    out, result = detect_jumps(xy, cfg)
    # At least the jump frame should be NaN for animal 0
    assert result.affected_frames > 0
    # The flagged frame should be NaN for animal 0
    flagged_nan = np.isnan(out[:, 0, 0])
    assert flagged_nan.any()


def test_jump_replaced_with_linear_interp(smooth_xy: np.ndarray) -> None:
    """When replacement='linear_interp', flagged frame is interpolated, not NaN."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="linear_interp")
    out, result = detect_jumps(xy, cfg)
    assert result.affected_frames > 0
    # After interpolation, the output should NOT have NaN at frame 50 (if surrounded by valid)
    assert not np.isnan(out[50, 0, 0])


def test_jump_detected_percentile_method(smooth_xy: np.ndarray) -> None:
    """Large displacement triggers flag with percentile method.

    pct_mult=1.0 so the threshold equals the 99th percentile itself, which is
    just below the injected jump magnitude.
    """
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(
        enabled=True, method="percentile", percentile=99.0, pct_mult=1.0, replacement="nan"
    )
    _out, result = detect_jumps(xy, cfg)
    assert result.affected_frames > 0


def test_disabled_returns_unchanged(smooth_xy: np.ndarray) -> None:
    """When cfg.enabled=False, array returned unchanged."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=False)
    original = xy.copy()
    out, result = detect_jumps(xy, cfg)
    np.testing.assert_array_equal(out, original)
    assert result.affected_frames == 0


def test_returns_pp_step_result(smooth_xy: np.ndarray) -> None:
    """detect_jumps must return a PPStepResult."""
    cfg = JumpCfg(enabled=True)
    _, result = detect_jumps(smooth_xy, cfg)
    assert isinstance(result, PPStepResult)
    assert result.step_name == "jump_detect"


def test_original_not_mutated(smooth_xy: np.ndarray) -> None:
    """detect_jumps must not mutate the input array."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    original = xy.copy()
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="nan")
    detect_jumps(xy, cfg)
    np.testing.assert_array_equal(xy, original)


def test_affected_per_individual_length(smooth_xy: np.ndarray) -> None:
    """affected_per_individual must have n_animals entries."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=True)
    _, result = detect_jumps(xy, cfg)
    assert len(result.affected_per_individual) == 2


def test_only_affected_animal_flagged(smooth_xy: np.ndarray) -> None:
    """Jump in animal 0 must not affect animal 1."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="nan")
    out, _result = detect_jumps(xy, cfg)
    # Animal 1 should remain unchanged
    np.testing.assert_allclose(out[:, 1, :], smooth_xy[:, 1, :], rtol=1e-9)


def test_pre_existing_gap_survives_jump_detect(smooth_xy: np.ndarray) -> None:
    """detect_jumps must not fill NaN runs it did not itself flag.

    Regression test for a corruption bug found on the real idtracker.ai
    corpus: pd.Series.interpolate(method="linear", limit_direction="both")
    with no `limit=` bound fills *every* NaN gap in the column, not just the
    frames this step just flagged. That silently erased gap_fill's decision
    to leave long gaps (> max_gap_frames) as NaN -- on session_trial10_Segment1
    (real data), NaN count went from 9767 (post gap_fill, policy respected)
    to 0 (post jump_detect, policy erased) before this fix.
    """
    xy = smooth_xy.copy()
    # A gap gap_fill would have deliberately left unfilled (too long to
    # interpolate) -- simulates gap_fill's output, not raw input.
    xy[20:60, 0, :] = np.nan
    # An unrelated, genuine jump elsewhere in the same animal's series.
    xy = _inject_jump(xy, animal=0, frame=80, magnitude=5000.0)

    cfg = JumpCfg(enabled=True, method="sd_multiple", sd_mult=5.0, replacement="linear_interp")
    out, result = detect_jumps(xy, cfg)

    # The pre-existing long gap must survive untouched.
    assert np.all(np.isnan(out[20:60, 0, 0])), "pre-existing gap was filled by jump_detect"
    # The genuinely flagged jump frame must have been replaced (no longer NaN,
    # no longer at the anomalous magnitude).
    assert not np.isnan(out[80, 0, 0])
    assert result.affected_per_individual[0] >= 1


# ── idtracker_velocity_threshold method ─────────────────────────────────────
#
# Regression coverage: Session.velocity_threshold_px_frame (idtracker.ai's
# own outlier-displacement bound, computed from the actual tracked data) was
# captured and had zero consumers -- jump_detect only ever used the
# hardcoded sd_multiple/percentile heuristics.


def test_idtracker_velocity_threshold_flags_above_threshold(
    smooth_xy: np.ndarray,
) -> None:
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=1000.0)
    cfg = JumpCfg(enabled=True, method="idtracker_velocity_threshold", replacement="nan")
    out, result = detect_jumps(xy, cfg, velocity_threshold_px_frame=50.0)
    assert result.affected_per_individual[0] >= 1
    assert np.isnan(out[50, 0, 0])


def test_idtracker_velocity_threshold_does_not_flag_below_threshold(
    smooth_xy: np.ndarray,
) -> None:
    # smooth_xy has constant 5px/frame and 3px/frame steps -- well under 50.
    cfg = JumpCfg(enabled=True, method="idtracker_velocity_threshold", replacement="nan")
    out, result = detect_jumps(smooth_xy, cfg, velocity_threshold_px_frame=50.0)
    assert result.affected_frames == 0
    np.testing.assert_array_equal(out, smooth_xy)


def test_idtracker_velocity_threshold_falls_back_to_sd_multiple_when_none(
    smooth_xy: np.ndarray, caplog: pytest.LogCaptureFixture,
) -> None:
    """The method was requested but the session has no such value --
    must not silently flag nothing; falls back with a warning."""
    xy = _inject_jump(smooth_xy, animal=0, frame=50, magnitude=5000.0)
    cfg = JumpCfg(
        enabled=True, method="idtracker_velocity_threshold",
        sd_mult=5.0, replacement="nan",
    )
    with caplog.at_level("WARNING"):
        _out, result = detect_jumps(xy, cfg, velocity_threshold_px_frame=None)
    assert result.affected_per_individual[0] >= 1  # sd_multiple caught it
    assert any("falling back" in rec.message for rec in caplog.records)
