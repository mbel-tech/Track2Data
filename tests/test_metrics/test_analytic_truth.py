"""Metrics recovered from trajectories whose true value is known in closed form.

R-parity proves this pipeline agrees with an existing R pipeline. It cannot
show that *either* is right — two implementations of the same misreading
agree perfectly. These tests construct trajectories whose metric value is
derivable on paper, then check the code returns it.

That is what turns "cited" into "verified", and it is the acceptance
criterion the PP-3 rewrite is measured against: a preprocessing step that
quietly relabels or displaces positions shows up here as a metric that no
longer recovers its own analytic answer.

Each case is deliberately something a reader can check by hand:

* a straight track of known step length -> IL-1 path length, IL-2 speed;
* animals on a fixed lattice -> GL-1 nearest-neighbour distance, exactly;
* a square wave in and out of a zone -> Z-1 dwell time, exactly;
* a closed circle -> IL-5 tortuosity, from circumference over displacement;
* a correlated random walk -> IL-1 within tolerance of E[n * step].

Preprocessing runs with smoothing off. Smoothing is a deliberate distortion
of position, so leaving it on would mean testing the filter rather than the
metric; PP-1/PP-2 stay on because their contract is to be no-ops on clean,
gapless input, and a case where they are not is a bug these tests should
catch.
"""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.models import (
    ROI,
    GapFillCfg,
    IdSwitchCfg,
    JumpCfg,
    PreprocessConfig,
    PreprocessedSession,
    Session,
    SmoothCfg,
    VideoInfo,
    ZoneSet,
)
from track2data.metrics.group import NearestNeighbourDistance
from track2data.metrics.individual import PathLength, Speed, Tortuosity
from track2data.metrics.zone import TimeInZone
from track2data.preprocess.pipeline import run as run_pipeline

FPS = 30.0

#: Position-preserving preprocessing. Smoothing is off deliberately -- see
#: the module docstring.
_CLEAN = PreprocessConfig(
    gap_fill=GapFillCfg(enabled=True),
    jump=JumpCfg(enabled=False),
    identity_switch=IdSwitchCfg(enabled=False),
    smoothing=SmoothCfg(enabled=False),
)


def _session(xy: np.ndarray, session_id: str = "truth") -> Session:
    n_frames, n_animals, _ = xy.shape
    return Session(
        session_id=session_id,
        folder=".",
        reader="analytic",
        video=VideoInfo(fps=FPS, n_frames=n_frames, width_px=1000, height_px=1000),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )


def _preprocess(xy: np.ndarray) -> PreprocessedSession:
    return run_pipeline(_session(xy), _CLEAN)


# ── IL-1 path length ──────────────────────────────────────────────────────────


def test_path_length_of_a_straight_track_is_steps_times_step_length() -> None:
    """n frames at a constant step of s px travel exactly (n-1) * s.

    The simplest closed form there is, and the one every other individual
    metric is built on top of.
    """
    n_frames, step = 300, 4.0
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(n_frames) * step

    df = PathLength().compute(_preprocess(xy))

    assert df.iloc[0]["path_length_px"] == pytest.approx((n_frames - 1) * step)


def test_path_length_of_a_closed_circle_is_its_circumference() -> None:
    """A polygon inscribed in a circle is slightly shorter than the arc, by a
    factor cos-corrected in the sample count -- so the tolerance is a real
    discretisation bound, not a fudge."""
    n_frames, radius = 720, 100.0
    theta = np.linspace(0.0, 2 * np.pi, n_frames)
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = radius * np.cos(theta)
    xy[:, 0, 1] = radius * np.sin(theta)

    df = PathLength().compute(_preprocess(xy))

    circumference = 2 * np.pi * radius
    # Chord-vs-arc error for n segments is O(1/n^2); 720 samples puts it
    # well under 0.01%.
    assert df.iloc[0]["path_length_px"] == pytest.approx(circumference, rel=1e-4)


def test_path_length_of_a_correlated_random_walk_matches_its_expectation() -> None:
    """A walk of n steps of fixed length s covers exactly (n-1) * s, however
    it turns. Direction is irrelevant to path length, which is exactly the
    property that makes it robust -- and exactly why it is inflated by
    positional noise (see IL-1's documented warning)."""
    rng = np.random.default_rng(7)
    n_frames, step = 2000, 3.0

    heading = np.cumsum(rng.normal(0.0, 0.2, n_frames))
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[1:, 0, 0] = np.cumsum(step * np.cos(heading[1:]))
    xy[1:, 0, 1] = np.cumsum(step * np.sin(heading[1:]))

    df = PathLength().compute(_preprocess(xy))

    assert df.iloc[0]["path_length_px"] == pytest.approx((n_frames - 1) * step, rel=1e-9)


def test_path_length_is_calibrated_consistently() -> None:
    """The cm column has to be the px column divided by px_per_cm, not a
    separately-derived quantity that could drift from it."""
    n_frames, step, px_per_cm = 200, 5.0, 10.0
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(n_frames) * step

    psess = _preprocess(xy)
    psess.px_per_cm = px_per_cm
    row = PathLength().compute(psess).iloc[0]

    assert row["path_length_cm"] == pytest.approx(row["path_length_px"] / px_per_cm)
    assert row["path_length_cm"] == pytest.approx((n_frames - 1) * step / px_per_cm)


# ── IL-2 speed ────────────────────────────────────────────────────────────────


def test_constant_speed_is_recovered_in_real_units() -> None:
    """s px per frame at f fps is s*f px/s. Pins the fps conversion, which is
    the single place a frame-rate mix-up would show up as a wrong number
    rather than an error."""
    n_frames, step = 300, 4.0
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(n_frames) * step

    row = Speed().compute(_preprocess(xy)).iloc[0]

    expected = step * FPS
    assert row["mean_speed_px_s"] == pytest.approx(expected, rel=1e-6)
    assert row["median_speed_px_s"] == pytest.approx(expected, rel=1e-6)
    assert row["max_speed_px_s"] == pytest.approx(expected, rel=1e-6)


def test_speed_scales_with_frame_rate_exactly() -> None:
    """The same pixel motion at twice the frame rate is twice the speed.

    This is the arithmetic behind the mixed-frame-rate warning in
    sessions.csv: two sessions of identical behaviour, recorded at different
    rates, do not produce comparable speeds -- and here that is a factor of
    exactly two, not an approximation.
    """
    n_frames, step = 200, 3.0
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(n_frames) * step

    slow = _session(xy)
    fast = slow.model_copy(
        update={"video": slow.video.model_copy(update={"fps": FPS * 2})}
    )

    slow_speed = Speed().compute(run_pipeline(slow, _CLEAN)).iloc[0]["mean_speed_px_s"]
    fast_speed = Speed().compute(run_pipeline(fast, _CLEAN)).iloc[0]["mean_speed_px_s"]

    assert fast_speed == pytest.approx(2 * slow_speed, rel=1e-9)


def test_a_stationary_animal_has_exactly_zero_speed() -> None:
    xy = np.full((200, 1, 2), 250.0, dtype=np.float64)
    row = Speed().compute(_preprocess(xy)).iloc[0]
    assert row["mean_speed_px_s"] == 0.0
    assert row["max_speed_px_s"] == 0.0


# ── GL-1 nearest-neighbour distance ───────────────────────────────────────────


def test_nnd_on_a_square_lattice_is_the_lattice_spacing() -> None:
    """On a grid of spacing d, every animal's nearest neighbour is exactly d
    away. Exact, not approximate: no tolerance is needed and none is given."""
    spacing, side, n_frames = 50.0, 3, 100
    positions = np.array(
        [[i * spacing, j * spacing] for i in range(side) for j in range(side)],
        dtype=np.float64,
    )
    xy = np.repeat(positions[np.newaxis, :, :], n_frames, axis=0)

    row = NearestNeighbourDistance().compute(_preprocess(xy)).iloc[0]

    assert row["mean_nnd_px"] == pytest.approx(spacing)
    assert row["median_nnd_px"] == pytest.approx(spacing)


def test_nnd_of_a_pair_is_their_separation() -> None:
    """The two-animal case, where nearest-neighbour distance is just the
    distance between them -- and where a 3-4-5 triangle makes the expected
    value checkable at a glance."""
    n_frames = 50
    xy = np.zeros((n_frames, 2, 2), dtype=np.float64)
    xy[:, 1, 0] = 30.0
    xy[:, 1, 1] = 40.0

    row = NearestNeighbourDistance().compute(_preprocess(xy)).iloc[0]

    assert row["mean_nnd_px"] == pytest.approx(50.0)


def test_nnd_is_unaffected_by_translating_the_whole_group() -> None:
    """Nearest-neighbour distance is a property of the configuration, not of
    where in the arena it sits."""
    spacing, n_frames = 40.0, 60
    base = np.array([[0.0, 0.0], [spacing, 0.0], [0.0, spacing]], dtype=np.float64)

    still = np.repeat(base[np.newaxis, :, :], n_frames, axis=0)
    drifting = still + np.arange(n_frames)[:, np.newaxis, np.newaxis] * 5.0

    a = NearestNeighbourDistance().compute(_preprocess(still)).iloc[0]["mean_nnd_px"]
    b = NearestNeighbourDistance().compute(_preprocess(drifting)).iloc[0]["mean_nnd_px"]

    assert a == pytest.approx(spacing)
    assert b == pytest.approx(spacing)


# ── Z-1 time in zone ──────────────────────────────────────────────────────────


def _zoned(xy: np.ndarray) -> PreprocessedSession:
    """Preprocess with an inner square zone and a surrounding outer one."""
    from track2data.zones.geometry import assign_zones

    zone_set = ZoneSet(
        rois=[
            ROI(
                name="inner",
                level="main",
                vertices=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            ),
            ROI(
                name="outer",
                level="main",
                vertices=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
            ),
        ]
    )
    psess = _preprocess(xy)
    main, sec = assign_zones(psess.xy, zone_set)
    psess.main_zone = main
    psess.sec_zone = sec
    return psess


def test_a_square_wave_in_and_out_of_a_zone_gives_exact_dwell_time() -> None:
    """600 frames at 30 fps, alternating 60 frames in and 60 out: exactly
    half the session inside, so exactly 10 s.

    Whole seconds by construction, so the expected value is not a rounded
    approximation of anything.
    """
    n_frames, block = 600, 60
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    inside = (np.arange(n_frames) // block) % 2 == 0
    xy[inside, 0, :] = 50.0     # inside the inner square
    xy[~inside, 0, :] = 500.0   # outside it, inside "outer"

    df = TimeInZone().compute(_zoned(xy))
    inner = df[df["zone_name"] == "inner"].iloc[0]

    assert inner["time_s"] == pytest.approx((n_frames / 2) / FPS)
    assert inner["time_s"] == pytest.approx(10.0)
    assert inner["time_pct"] == pytest.approx(0.5)


def test_an_animal_that_never_leaves_a_zone_spends_the_whole_session_there() -> None:
    n_frames = 300
    xy = np.full((n_frames, 1, 2), 50.0, dtype=np.float64)

    df = TimeInZone().compute(_zoned(xy))
    inner = df[df["zone_name"] == "inner"].iloc[0]

    assert inner["time_s"] == pytest.approx(n_frames / FPS)
    assert inner["time_pct"] == pytest.approx(1.0)


def test_time_pct_is_a_fraction_not_a_percentage() -> None:
    """The column is named _pct and holds a value in [0, 1]. codebook.csv
    documents it truthfully; this makes sure the two never diverge."""
    n_frames, block = 400, 100
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    quarter = (np.arange(n_frames) // block) == 0
    xy[quarter, 0, :] = 50.0
    xy[~quarter, 0, :] = 500.0

    df = TimeInZone().compute(_zoned(xy))
    inner = df[df["zone_name"] == "inner"].iloc[0]

    assert inner["time_pct"] == pytest.approx(0.25)
    assert 0.0 <= inner["time_pct"] <= 1.0


# ── IL-5 tortuosity ───────────────────────────────────────────────────────────


def test_a_straight_line_has_tortuosity_one() -> None:
    """Path length equals net displacement, so the ratio is exactly 1 -- the
    definitional floor of the measure."""
    n_frames, step = 200, 4.0
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = np.arange(n_frames) * step

    assert Tortuosity().compute(_preprocess(xy)).iloc[0]["tortuosity"] == pytest.approx(
        1.0, rel=1e-9
    )


def test_a_half_circle_has_tortuosity_pi_over_two() -> None:
    """Arc length pi*r over a net displacement of 2r (the diameter): the
    ratio is pi/2 ~ 1.5708, independent of radius."""
    n_frames, radius = 721, 100.0
    theta = np.linspace(0.0, np.pi, n_frames)
    xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
    xy[:, 0, 0] = radius * np.cos(theta)
    xy[:, 0, 1] = radius * np.sin(theta)

    value = Tortuosity().compute(_preprocess(xy)).iloc[0]["tortuosity"]

    assert value == pytest.approx(np.pi / 2, rel=1e-4)


def test_tortuosity_does_not_depend_on_scale() -> None:
    """Doubling every coordinate doubles both the path and the displacement,
    so a shape's tortuosity is the same however large it is drawn."""
    n_frames = 361
    theta = np.linspace(0.0, np.pi, n_frames)

    def semicircle(radius: float) -> np.ndarray:
        xy = np.zeros((n_frames, 1, 2), dtype=np.float64)
        xy[:, 0, 0] = radius * np.cos(theta)
        xy[:, 0, 1] = radius * np.sin(theta)
        return xy

    small = Tortuosity().compute(_preprocess(semicircle(10.0))).iloc[0]["tortuosity"]
    large = Tortuosity().compute(_preprocess(semicircle(500.0))).iloc[0]["tortuosity"]

    assert small == pytest.approx(large, rel=1e-9)


# ── the point of the suite ────────────────────────────────────────────────────


def test_an_identity_swap_leaves_group_structure_but_ruins_individual_paths() -> None:
    """Why this suite is PP-3's acceptance criterion.

    Swapping two animals' labels part-way through a session leaves every
    frame's *configuration* untouched -- so GL-1 is unchanged, and a
    group-level check would notice nothing -- while adding a spurious jump
    to each individual's path. A correction step that reports success must
    restore IL-1, not merely leave GL-1 alone.
    """
    n_frames, step, switch_at = 200, 3.0, 100
    truth = np.zeros((n_frames, 2, 2), dtype=np.float64)
    truth[:, 0, 0] = np.arange(n_frames) * step
    truth[:, 1, 0] = np.arange(n_frames) * step
    truth[:, 1, 1] = 300.0

    swapped = truth.copy()
    swapped[switch_at:, 0, :] = truth[switch_at:, 1, :]
    swapped[switch_at:, 1, :] = truth[switch_at:, 0, :]

    true_path = PathLength().compute(_preprocess(truth))["path_length_px"]
    swapped_path = PathLength().compute(_preprocess(swapped))["path_length_px"]
    true_nnd = NearestNeighbourDistance().compute(_preprocess(truth)).iloc[0]["mean_nnd_px"]
    swapped_nnd = NearestNeighbourDistance().compute(_preprocess(swapped)).iloc[0]["mean_nnd_px"]

    # Group structure is identical -- the swap is invisible here.
    assert swapped_nnd == pytest.approx(true_nnd)
    # Individual paths are not: each gains the 300 px inter-animal jump.
    assert np.allclose(true_path, (n_frames - 1) * step)
    assert (swapped_path > true_path + 250.0).all()
