"""Performance guards for PP-3 identity-switch correction.

These exist because the step's cost is not obvious from reading it, and
because it has already been wrong in two different ways:

* the original implementation rebuilt a distance matrix with a nested
  Python loop that ``_pairwise_distances`` already computed by
  broadcasting, costing ~0.44 ms/frame (~50 s per hour-long session);
* a subsequent version physically permuted the remaining tail of the array
  at every accepted switch, which is quadratic in frame count and did not
  terminate in any useful time on a dense session.

The budgets below are deliberately loose -- roughly 20x the time observed
on a development machine -- so they do not flake on slower CI hardware
while still failing loudly if either regression returns. A quadratic
implementation exceeds them by orders of magnitude, not by a few percent.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pytest

from track2data.core.models import IdSwitchCfg
from track2data.preprocess.identity_switch import correct_switches

N_ANIMALS = 8
HOUR_SESSION_FRAMES = 108_000   # 60 min @ 30 fps


@pytest.fixture(autouse=True)
def _silence_opt_in_warning() -> object:
    """The step warns on every enabled call; that is not news here."""
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


def _random_walk(n_frames: int, seed: int = 0) -> np.ndarray:
    """Well-separated animals on independent random walks, 5% missing."""
    rng = np.random.default_rng(seed)
    xy = np.cumsum(rng.normal(0, 2.0, (n_frames, N_ANIMALS, 2)), axis=0)
    xy += rng.uniform(0, 500, (1, N_ANIMALS, 2))
    xy[rng.random((n_frames, N_ANIMALS)) < 0.05] = np.nan
    return xy


def _crowded(n_frames: int, seed: int = 1) -> np.ndarray:
    """Every animal inside one small box, so the Tier-1 gate fires constantly.

    Pathological rather than realistic: with positions this ambiguous there
    is no identity to recover. It is here purely as the worst case for
    control flow.
    """
    rng = np.random.default_rng(seed)
    return rng.uniform(0, 40, size=(n_frames, N_ANIMALS, 2))


def test_hour_long_session_stays_within_budget() -> None:
    """Full-scan path on a realistic hour-long session."""
    xy = _random_walk(HOUR_SESSION_FRAMES)
    start = time.perf_counter()
    correct_switches(xy, IdSwitchCfg(enabled=True))
    elapsed = time.perf_counter() - start
    assert elapsed < 90.0, f"full scan took {elapsed:.1f}s for an hour-long session"


def test_crowded_session_does_not_degrade_quadratically() -> None:
    """The case that used to hang: many accepted switches in one session.

    Tail-propagating each switch made this quadratic. Accumulating the
    permutation and materialising once keeps it linear.
    """
    xy = _crowded(18_000)
    start = time.perf_counter()
    _, result = correct_switches(xy, IdSwitchCfg(enabled=True))
    elapsed = time.perf_counter() - start
    assert elapsed < 30.0, (
        f"crowded 18k-frame session took {elapsed:.1f}s -- the tail-propagation "
        "regression is back"
    )
    # Sanity: this input really does exercise the accept path.
    assert result.affected_frames > 0


def test_scaling_is_linear_in_frame_count() -> None:
    """Tripling the frames must not multiply the time by ~9."""
    short = _crowded(6_000)
    long = _crowded(18_000)

    start = time.perf_counter()
    correct_switches(short, IdSwitchCfg(enabled=True))
    t_short = time.perf_counter() - start

    start = time.perf_counter()
    correct_switches(long, IdSwitchCfg(enabled=True))
    t_long = time.perf_counter() - start

    # Linear would be ~3x. Quadratic would be ~9x. Allow generous headroom
    # for timer noise on a short baseline without admitting quadratic.
    assert t_long < max(t_short * 6.0, 30.0), (
        f"3x the frames cost {t_long / max(t_short, 1e-9):.1f}x the time "
        f"({t_short:.2f}s -> {t_long:.2f}s)"
    )


def test_fragment_boundaries_are_much_cheaper_than_a_full_scan() -> None:
    """The intended path evaluates a few hundred frames, not a hundred thousand."""
    xy = _crowded(HOUR_SESSION_FRAMES)
    boundaries = set(range(0, HOUR_SESSION_FRAMES, 500))

    start = time.perf_counter()
    correct_switches(xy, IdSwitchCfg(enabled=True), swap_boundaries=boundaries)
    elapsed = time.perf_counter() - start

    assert elapsed < 20.0, (
        f"fragment-guided pass took {elapsed:.1f}s for {len(boundaries)} candidate "
        "frames; it should be evaluating only those"
    )
