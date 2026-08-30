"""Regression tests for PP-3 identity-switch correction on a known crossing.

Drop-in candidate for ``tests/test_preprocess/test_identity_switch.py``.
These encode the canonical case the module is named for: two animals cross,
the tracker swaps their labels from the crossing onward, and the corrector
is asked to undo it.

All three tests below FAIL against the implementation as of commit 0b9b860.
They are written as the specification, not as a description of current
behaviour, so they turn green only when the algorithm is fixed:

* ``test_two_animal_persistent_switch_is_corrected`` — the Tier-1 ambiguity
  gate requires a second-nearest neighbour, so with ``n_animals == 2`` it can
  never fire and the whole step is a silent no-op.
* ``test_four_animal_persistent_switch_is_corrected`` — the permutation is
  applied frame-by-frame inside ``consolidate_window`` only, so a *persistent*
  relabelling is corrected for a few frames and then reverts.
* ``test_correction_introduces_no_implausible_displacement`` — the partial
  correction leaves (and adds) displacement discontinuities far above the
  true per-frame step, which is what downstream kinematics actually sees.
"""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import IdSwitchCfg
from track2data.preprocess.identity_switch import correct_switches

N_FRAMES = 60
SWITCH_FRAME = 21
TRUE_STEP_PX = 2.0


def _crossing_pair() -> np.ndarray:
    """Two animals travelling in opposite directions, crossing mid-session."""
    t = np.arange(N_FRAMES, dtype=np.float64)
    a = np.stack([t * TRUE_STEP_PX, np.full(N_FRAMES, 100.0)], axis=1)
    b = np.stack([120.0 - t * TRUE_STEP_PX, np.full(N_FRAMES, 100.0)], axis=1)
    return np.stack([a, b], axis=1)  # (n_frames, 2, 2)


def _distractors() -> np.ndarray:
    """Two animals far from the crossing pair, moving slowly and unambiguously."""
    t = np.arange(N_FRAMES, dtype=np.float64)
    c = np.stack([np.full(N_FRAMES, 300.0), 300.0 + t * 0.5], axis=1)
    d = np.stack([np.full(N_FRAMES, 400.0), 500.0 - t * 0.5], axis=1)
    return np.stack([c, d], axis=1)


def _inject_persistent_switch(truth: np.ndarray) -> np.ndarray:
    """Swap identities 0 and 1 from SWITCH_FRAME to the end of the session."""
    obs = truth.copy()
    obs[SWITCH_FRAME:, 0, :] = truth[SWITCH_FRAME:, 1, :]
    obs[SWITCH_FRAME:, 1, :] = truth[SWITCH_FRAME:, 0, :]
    return obs


def _mean_abs_error(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.nanmean(np.abs(a - b)))


def _max_step_px(xy: np.ndarray) -> float:
    return float(np.nanmax(np.linalg.norm(np.diff(xy, axis=0), axis=2)))


def test_two_animal_persistent_switch_is_corrected() -> None:
    """A dyadic crossing is the commonest design; it must not be a no-op."""
    truth = _crossing_pair()
    obs = _inject_persistent_switch(truth)

    out, report = correct_switches(obs, IdSwitchCfg(enabled=True))

    assert report.affected_frames > 0, (
        "no frames reported corrected: the Tier-1 ratio test needs a "
        "second-nearest neighbour and cannot fire when n_animals == 2"
    )
    assert _mean_abs_error(out, truth) < 0.5 * _mean_abs_error(obs, truth)


def test_four_animal_persistent_switch_is_corrected() -> None:
    """With enough animals to trigger Tier-1, the fix must persist to the end."""
    truth = np.concatenate([_crossing_pair(), _distractors()], axis=1)
    obs = _inject_persistent_switch(truth)

    out, _ = correct_switches(obs, IdSwitchCfg(enabled=True))

    # Every frame after the switch should be back on the right identity, not
    # just the handful inside consolidate_window.
    tail_matches = np.all(
        np.isclose(out[SWITCH_FRAME:], truth[SWITCH_FRAME:]), axis=(1, 2)
    )
    assert tail_matches.all(), (
        f"{int(tail_matches.sum())}/{tail_matches.size} post-switch frames "
        "match ground truth; the permutation is applied inside the "
        "consolidate window only and then reverts"
    )


def test_correction_introduces_no_implausible_displacement() -> None:
    """Correction must not leave or add teleport-sized steps."""
    truth = np.concatenate([_crossing_pair(), _distractors()], axis=1)
    obs = _inject_persistent_switch(truth)

    out, _ = correct_switches(obs, IdSwitchCfg(enabled=True))

    assert _max_step_px(out) == pytest.approx(_max_step_px(truth), abs=1e-6), (
        f"max per-frame displacement {_max_step_px(out):.1f} px vs true "
        f"{_max_step_px(truth):.1f} px -- partial correction leaves "
        "discontinuities that propagate into speed, acceleration and IL-1"
    )


def test_clean_input_is_left_untouched() -> None:
    """Guard the property that already holds, so a fix cannot regress it."""
    truth = np.concatenate([_crossing_pair(), _distractors()], axis=1)

    out, report = correct_switches(truth.copy(), IdSwitchCfg(enabled=True))

    assert report.affected_frames == 0
    np.testing.assert_allclose(out, truth)
