"""Property-based invariants for the preprocessing steps.

Example-based tests check the cases someone thought of. These check the
properties that must hold for *every* input, which is the right shape for
preprocessing: each step has a small number of promises it makes about what
it will and will not do to a trajectory, and those promises are what the
rest of the pipeline and every metric downstream rely on.

The promises pinned here are not hypothetical. Each corresponds to a way
one of these steps has already gone wrong, or could:

* ``jump_detect`` once interpolated across *every* pre-existing gap rather
  than only the frames it flagged, silently erasing ``gap_fill``'s policy
  that long gaps stay NaN (there is a hand-written regression for the
  specific case; this generalises it);
* ``gap_fill`` filling a gap longer than ``max_gap_frames`` would invent a
  straight line across a stretch where nothing was observed;
* any step mutating its input would corrupt ``Session.raw_xy``, which
  ``was_interpolated`` and D-11 both compare against to report what was
  measured versus reconstructed.

``hypothesis`` was a declared dev dependency with no uses anywhere. This is
what it is for.
"""

from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from track2data.core.models import GapFillCfg, IdSwitchCfg, JumpCfg, SmoothCfg
from track2data.preprocess.gap_fill import fill_gaps
from track2data.preprocess.identity_switch import correct_switches
from track2data.preprocess.jump_detect import detect_jumps
from track2data.preprocess.smoothing import smooth_trajectories

# Generated sessions stay small: these check logical properties, not
# numerical behaviour at scale, and a fast strategy gets run more often.
_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@st.composite
def trajectories(draw: st.DrawFn, min_frames: int = 6, max_frames: int = 40) -> np.ndarray:
    """An ``(n_frames, n_animals, 2)`` array with deliberately-shaped gaps.

    Gaps are drawn as explicit runs rather than as an independent coin flip
    per cell. That matters: independent flips almost never produce a run
    longer than a few frames, so a property about ``max_gap_frames`` would
    pass vacuously on nearly every example. Measured on the first version of
    this strategy, only 2 examples in 200 contained a gap long enough to
    exercise it, and none contained an animal that was never detected.

    The run lengths reach 12, comfortably past the ``max_gap_frames`` values
    the tests draw (1-8), and an animal can be missing for the whole session.
    """
    n_frames = draw(st.integers(min_value=min_frames, max_value=max_frames))
    n_animals = draw(st.integers(min_value=1, max_value=4))

    coords = draw(
        st.lists(
            st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
            min_size=n_frames * n_animals * 2,
            max_size=n_frames * n_animals * 2,
        )
    )
    xy = np.asarray(coords, dtype=np.float64).reshape(n_frames, n_animals, 2)

    for k in range(n_animals):
        if draw(st.booleans()) and draw(st.booleans()):
            # Never detected at all -- a real and awkward case: every step
            # has to leave it alone rather than divide by zero over it.
            xy[:, k, :] = np.nan
            continue
        for _ in range(draw(st.integers(min_value=0, max_value=3))):
            length = draw(st.integers(min_value=1, max_value=12))
            start = draw(st.integers(min_value=0, max_value=max(0, n_frames - 1)))
            xy[start : start + length, k, :] = np.nan

    return xy


def _nan_mask(xy: np.ndarray) -> np.ndarray:
    return np.isnan(xy[:, :, 0])


def _gap_lengths(missing: np.ndarray) -> list[tuple[int, int]]:
    """``(start, length)`` for each run of True in a 1-D bool array."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, value in enumerate(missing):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(missing) - start))
    return runs


# ── gap_fill ──────────────────────────────────────────────────────────────────


@_SETTINGS
@given(xy=trajectories(), max_gap=st.integers(min_value=1, max_value=8))
def test_gap_fill_never_touches_the_input(xy: np.ndarray, max_gap: int) -> None:
    """Session.raw_xy is what was_interpolated and D-11 compare against."""
    original = xy.copy()
    fill_gaps(xy, GapFillCfg(enabled=True, max_gap_frames=max_gap))
    np.testing.assert_array_equal(xy, original, err_msg="fill_gaps mutated its input")


@_SETTINGS
@given(xy=trajectories(), max_gap=st.integers(min_value=1, max_value=8))
def test_gap_fill_never_introduces_a_nan(xy: np.ndarray, max_gap: int) -> None:
    """It may only remove missingness, never create it."""
    out, _ = fill_gaps(xy, GapFillCfg(enabled=True, max_gap_frames=max_gap))
    assert not (_nan_mask(out) & ~_nan_mask(xy)).any()


@_SETTINGS
@given(xy=trajectories(), max_gap=st.integers(min_value=1, max_value=8))
def test_gap_fill_respects_max_gap_frames(xy: np.ndarray, max_gap: int) -> None:
    """A gap longer than the limit must survive untouched.

    Filling one would draw a straight line across a stretch where nothing
    was observed, which is exactly the claim the limit exists to refuse.
    """
    before = _nan_mask(xy)
    out, _ = fill_gaps(xy, GapFillCfg(enabled=True, max_gap_frames=max_gap))
    after = _nan_mask(out)

    for k in range(xy.shape[1]):
        for start, length in _gap_lengths(before[:, k]):
            if length > max_gap:
                assert after[start : start + length, k].all(), (
                    f"a {length}-frame gap was filled with max_gap_frames={max_gap}"
                )


@_SETTINGS
@given(xy=trajectories(), max_gap=st.integers(min_value=1, max_value=8))
def test_gap_fill_leaves_observed_positions_alone(xy: np.ndarray, max_gap: int) -> None:
    """Interpolation fills holes; it does not adjust measurements."""
    out, _ = fill_gaps(xy, GapFillCfg(enabled=True, max_gap_frames=max_gap))
    observed = ~np.isnan(xy)
    np.testing.assert_array_equal(out[observed], xy[observed])


@_SETTINGS
@given(xy=trajectories())
def test_gap_fill_disabled_is_the_identity(xy: np.ndarray) -> None:
    out, result = fill_gaps(xy, GapFillCfg(enabled=False))
    np.testing.assert_array_equal(out, xy)
    assert result.affected_frames == 0


# ── jump_detect ───────────────────────────────────────────────────────────────


@_SETTINGS
@given(
    xy=trajectories(),
    replacement=st.sampled_from(["nan", "linear_interp"]),
    sd_mult=st.floats(min_value=1.0, max_value=20.0),
)
def test_jump_detect_never_fills_a_pre_existing_gap(
    xy: np.ndarray, replacement: str, sd_mult: float
) -> None:
    """The generalised form of a real regression.

    Interpolating with ``limit_direction="both"`` used to fill every gap in
    the series, not only the frames this step flagged -- silently erasing
    gap_fill's policy that long gaps stay NaN. A frame that was missing
    before this step must still be missing after it.
    """
    before = _nan_mask(xy)
    out, _ = detect_jumps(
        xy,
        JumpCfg(enabled=True, method="sd_multiple", sd_mult=sd_mult, replacement=replacement),
    )
    after = _nan_mask(out)

    assert (after | ~before).all(), "jump_detect filled a gap it did not create"


@_SETTINGS
@given(xy=trajectories(), sd_mult=st.floats(min_value=1.0, max_value=20.0))
def test_jump_detect_never_touches_the_input(xy: np.ndarray, sd_mult: float) -> None:
    original = xy.copy()
    detect_jumps(xy, JumpCfg(enabled=True, method="sd_multiple", sd_mult=sd_mult))
    np.testing.assert_array_equal(xy, original, err_msg="detect_jumps mutated its input")


@_SETTINGS
@given(xy=trajectories())
def test_jump_detect_disabled_is_the_identity(xy: np.ndarray) -> None:
    out, result = detect_jumps(xy, JumpCfg(enabled=False))
    np.testing.assert_array_equal(out, xy)
    assert result.affected_frames == 0


# ── identity_switch ───────────────────────────────────────────────────────────


@_SETTINGS
@given(xy=trajectories(), ratio=st.floats(min_value=1.0, max_value=4.0))
def test_identity_switch_only_ever_permutes(xy: np.ndarray, ratio: float) -> None:
    """It relabels; it never changes, adds or removes a position.

    The multiset of positions in each frame must be preserved exactly --
    the previous implementation's single-frame permutations satisfied this
    too, but a future rewrite that "corrects" a coordinate would not, and
    that would be a different (and much worse) kind of step.
    """
    out, _ = correct_switches(xy, IdSwitchCfg(enabled=True, tier1_ratio=ratio))

    for t in range(xy.shape[0]):
        before = np.sort(np.nan_to_num(xy[t], nan=np.inf), axis=0)
        after = np.sort(np.nan_to_num(out[t], nan=np.inf), axis=0)
        np.testing.assert_array_equal(after, before)


@_SETTINGS
@given(xy=trajectories(), ratio=st.floats(min_value=1.0, max_value=4.0))
def test_identity_switch_never_touches_the_input(xy: np.ndarray, ratio: float) -> None:
    original = xy.copy()
    correct_switches(xy, IdSwitchCfg(enabled=True, tier1_ratio=ratio))
    np.testing.assert_array_equal(xy, original)


@_SETTINGS
@given(xy=trajectories())
def test_identity_switch_disabled_is_the_identity(xy: np.ndarray) -> None:
    out, result = correct_switches(xy, IdSwitchCfg(enabled=False))
    np.testing.assert_array_equal(out, xy)
    assert result.affected_frames == 0


# ── smoothing ─────────────────────────────────────────────────────────────────


@_SETTINGS
@given(
    xy=trajectories(),
    method=st.sampled_from(["savgol", "moving_avg"]),
    window=st.integers(min_value=3, max_value=9),
)
def test_smoothing_preserves_the_missingness_pattern(
    xy: np.ndarray, method: str, window: int
) -> None:
    """Smoothing changes values, never which frames have one.

    Filling a gap here would bypass ``max_gap_frames`` entirely and make
    ``was_interpolated`` -- which compares raw to final -- attribute the
    fill to gap_fill.
    """
    out, _ = smooth_trajectories(
        xy, SmoothCfg(enabled=True, method=method, window=window, polyorder=2)
    )
    np.testing.assert_array_equal(_nan_mask(out), _nan_mask(xy))


@_SETTINGS
@given(xy=trajectories(), window=st.integers(min_value=3, max_value=9))
def test_smoothing_never_touches_the_input(xy: np.ndarray, window: int) -> None:
    original = xy.copy()
    smooth_trajectories(xy, SmoothCfg(enabled=True, method="savgol", window=window))
    np.testing.assert_array_equal(xy, original)


@_SETTINGS
@given(xy=trajectories())
def test_smoothing_disabled_is_the_identity(xy: np.ndarray) -> None:
    out, result = smooth_trajectories(xy, SmoothCfg(enabled=False))
    np.testing.assert_array_equal(out, xy)
    assert result.affected_frames == 0


# ── shape, across every step ──────────────────────────────────────────────────


@_SETTINGS
@given(xy=trajectories())
def test_no_step_changes_the_array_shape(xy: np.ndarray) -> None:
    """Every metric indexes by (frame, animal); a step that resized either
    axis would silently misalign every downstream join."""
    for out in (
        fill_gaps(xy, GapFillCfg(enabled=True))[0],
        detect_jumps(xy, JumpCfg(enabled=True))[0],
        correct_switches(xy, IdSwitchCfg(enabled=True))[0],
        smooth_trajectories(xy, SmoothCfg(enabled=True))[0],
    ):
        assert out.shape == xy.shape
        assert out.dtype == np.float64
