"""Agreement between the views and the frame-offset suggestion."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.fusion.agreement import agreement, suggest_offset
from track2data.fusion.fuse import fuse

from .builders import FLOOR_ROW, LABELS, SURFACE_ROW, TANK_CM, make_pair, make_psess, settings

SIDE_SCALE = (FLOOR_ROW - SURFACE_ROW) / TANK_CM  # side px per cm
TOP_SCALE = 2.0


def walk(n: int, k: int, seed: int = 0) -> np.ndarray:
    """A random walk per fish (px), seeded; enough movement to pin down a lag."""
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, 3, size=(n, k)), axis=0) + 200


def build(top_h, *, n=None, side_h=None, lag=0, y_axis=False, **pair_kw):
    """A pair whose side horizontal (px) is the top horizontal in cm, scaled, with an origin."""
    n = n or top_h.shape[0]
    top_xy = np.zeros((n, 3, 2))
    top_xy[:, :, 1 if y_axis else 0] = top_h
    top_xy[:, :, 0 if y_axis else 1] = 7.0
    if side_h is None:
        side_h = np.roll(top_h, lag, axis=0) / TOP_SCALE * SIDE_SCALE + 55.0
    side_xy = np.zeros((n, 3, 2))
    side_xy[:, :, 0] = side_h
    side_xy[:, :, 1] = 200.0
    top, side, pair = make_pair(n_frames=n, **pair_kw)
    top = make_psess("t", top_xy, labels=list(LABELS), px_per_cm=TOP_SCALE)
    side = make_psess("s", side_xy, labels=list(LABELS))
    return top, side, pair


def test_agreement_constant_offset_and_noise_fish():
    rng = np.random.default_rng(1)
    t = rng.normal(size=(200, 2)) * 5
    s = t + 3.0
    s[:, 1] = rng.normal(size=200) * 5
    overall, per = agreement(t, s)
    assert per[0] == pytest.approx(0.0, abs=1e-12)
    assert per[1] > 1.0 and per[1] != per[0]
    assert overall > 1.0
    o2, p2 = agreement(t[:, :1], s[:, :1])
    assert o2 == pytest.approx(0.0, abs=1e-12) and p2 == [pytest.approx(0.0, abs=1e-12)]


def test_agreement_too_few_and_all_nan():
    t = np.arange(20.0).reshape(10, 2)
    s = t.copy()
    s[:, 1] = np.nan
    s[:2, 1] = 1.0  # only 2 jointly valid samples for fish 1
    overall, per = agreement(t, s)
    assert per[0] == pytest.approx(0.0) and per[1] is None
    assert overall == pytest.approx(0.0)
    nan = np.full((10, 2), np.nan)
    assert agreement(nan, nan) == (None, [None, None])
    assert agreement(np.empty((0, 2)), np.empty((0, 2))) == (None, [None, None])


def test_fuse_consistent_flip_and_axis():
    h = walk(100, 3)
    top, side, pair = build(h)
    r = fuse(top, side, pair, same_video=False).report
    assert r.agreement_rms_cm < 0.01 and not r.agreement_warning
    assert set(r.agreement_per_fish_cm) == set(LABELS)

    # the side view mirrored: warns unless flip is set
    mirrored = -(h / TOP_SCALE * SIDE_SCALE) + 900.0
    top, side, pair = build(h, side_h=mirrored)
    r = fuse(top, side, pair, same_video=False).report
    assert r.agreement_warning and r.agreement_rms_cm > 1.0
    top, side, pair = build(h, side_h=mirrored, fusion=settings(flip=True))
    r = fuse(top, side, pair, same_video=False).report
    assert r.agreement_rms_cm < 0.01 and not r.agreement_warning

    # horizontal_axis="y" compares with the top y
    top, side, pair = build(h, y_axis=True, fusion=settings(horizontal_axis="y"))
    assert fuse(top, side, pair, same_video=False).report.agreement_rms_cm < 0.01
    top, side, pair = build(h, y_axis=True)  # axis x: top x is constant, so it disagrees
    assert fuse(top, side, pair, same_video=False).report.agreement_rms_cm > 1.0


def test_fuse_uncalibrated_top_skips_agreement():
    top, side, pair = make_pair(px_per_cm=None)
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.agreement_skipped == "top view not calibrated"
    assert fused.report.agreement_rms_cm is None and fused.report.agreement_per_fish_cm == {}
    assert not fused.report.agreement_warning and fused.report.suggested_offset is None
    assert np.isfinite(fused.psess.depth).all()


@pytest.mark.parametrize("noise_cm,warn", [(0.9, False), (1.3, True)])
def test_warning_threshold(noise_cm, warn):
    # top range is exactly 10 cm per fish: a +-noise_cm alternating error has RMS == noise_cm
    n = 100
    ramp = np.linspace(0, 10 * TOP_SCALE, n)[:, None] * np.ones((1, 3))
    err = noise_cm * SIDE_SCALE * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)[:, None]
    top, side, pair = build(ramp, side_h=ramp / TOP_SCALE * SIDE_SCALE + err)
    r = fuse(top, side, pair, same_video=False).report
    assert r.agreement_rms_cm == pytest.approx(noise_cm, rel=0.05)
    assert r.agreement_warning is warn


def test_suggest_offset_recovers_lag():
    h = walk(400, 3)
    # side frame = top frame + 7, so side[i + 7] == top[i]: build() rolls the side by +7
    top, side, pair = build(h, lag=7)
    assert suggest_offset(top, side, pair) == 7
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.suggested_offset is None  # fuse leaves the (slow) scan to the caller
    # fusing at the suggested offset makes the views agree
    pair.fusion = pair.fusion.model_copy(update={"frame_offset": 7})
    assert fuse(top, side, pair, same_video=False).report.agreement_rms_cm < 0.01
    top, side, pair = build(h, lag=-4)
    assert suggest_offset(top, side, pair) == -4


def test_suggest_offset_none_cases():
    h = walk(400, 3)
    top, side, pair = build(h, lag=0)
    assert suggest_offset(top, side, pair) is None

    rng = np.random.default_rng(5)
    noise = rng.normal(0, 30, size=(400, 3))
    top, side, pair = build(rng.normal(0, 30, size=(400, 3)), side_h=noise)
    assert suggest_offset(top, side, pair) is None

    top, side, pair = build(h[:8], lag=3)  # too short for 30 samples
    assert suggest_offset(top, side, pair) is None

    sparse = h.copy()
    top, side, pair = build(sparse, lag=7)
    side.xy[np.arange(400) % 50 != 0] = np.nan  # 8 rows left (< 30 samples)
    assert suggest_offset(top, side, pair) is None

    top, side, pair = build(h, lag=7)
    top.px_per_cm = None
    assert suggest_offset(top, side, pair) is None
    top, side, pair = build(h, lag=7)
    pair.fusion = None
    assert suggest_offset(top, side, pair) is None


def test_fuse_never_fills_suggestion():
    h = walk(400, 3)
    top, side, pair = build(h, lag=7)
    assert fuse(top, side, pair, same_video=True).report.suggested_offset is None
    assert fuse(top, side, pair, same_video=False).report.suggested_offset is None


def test_timing_smoke_100k_frames():
    import time

    n = 100_000
    h = walk(n, 3, seed=2)
    top, side, pair = build(h, lag=7)
    t0 = time.perf_counter()
    assert suggest_offset(top, side, pair) == 7
    scan = time.perf_counter() - t0
    t0 = time.perf_counter()
    fuse(top, side, pair, same_video=False)
    assert scan < 3.0 and time.perf_counter() - t0 < 1.0


def test_suggest_offset_with_frame_gaps_matches_consecutive_path():
    h = walk(400, 3)
    top, side, pair = build(h, lag=7)
    top.frame_index = np.arange(400) * 1  # same frames, but forces nothing special
    gap = np.arange(400) + (np.arange(400) >= 200)  # one skipped frame in both views
    top.frame_index = gap
    side.frame_index = gap
    assert suggest_offset(top, side, pair) == 7
