"""Tests for track2data.metrics.derived -- per-session derived
parameter values for metrics whose configuration cannot be user-typed
(it's a property of the session's own tracked arena). TDD RED phase.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    ROI,
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
    ZoneSet,
)
from track2data.metrics.derived import derive_metric_params

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_psess(
    width_px: int = 1000,
    height_px: int = 800,
    tmp_path: Path | None = None,
    xy: np.ndarray | None = None,
    main_zone: np.ndarray | None = None,
):
    n_frames, n_animals = 10, 2
    if xy is not None:
        n_frames, n_animals = xy.shape[0], xy.shape[1]
    else:
        xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    session = Session(
        session_id="s1",
        folder=tmp_path or Path("/tmp/s1"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=width_px, height_px=height_px),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
    )
    kine = KinematicsArrays(
        speed_px_s=np.zeros((n_frames, n_animals)),
        accel_px_s2=np.zeros((n_frames, n_animals)),
        heading_rad=np.zeros((n_frames, n_animals)),
    )
    return PreprocessedSession(
        session=session, xy=xy, kinematics=kine, main_zone=main_zone
    )


def _two_arena_zone_set() -> ZoneSet:
    """The exclusive_rois layout: two separate main arenas, a wide gap
    between them. Their pooled bounding-box midpoint (800, 200) is in
    the gap and belongs to neither."""
    return ZoneSet(
        rois=[
            ROI(name="left", level="main", vertices=[(0, 0), (400, 0), (400, 400), (0, 400)]),
            ROI(
                name="right",
                level="main",
                vertices=[(1200, 0), (1600, 0), (1600, 400), (1200, 400)],
            ),
        ]
    )


# ── dispatch: unknown / no-param metrics ─────────────────────────────────────


def test_returns_empty_dict_for_a_metric_with_no_derived_params() -> None:
    psess = _make_psess()
    assert derive_metric_params("IL-1", psess, ZoneSet()) == {}


def test_returns_empty_dict_for_an_unregistered_metric_id() -> None:
    psess = _make_psess()
    assert derive_metric_params("NOT-A-REAL-ID", psess, ZoneSet()) == {}


# ── IL-3: centre / arena_radius ──────────────────────────────────────────────


def test_il3_falls_back_to_video_centre_when_no_zones_defined() -> None:
    psess = _make_psess(width_px=1000, height_px=800)
    result = derive_metric_params("IL-3", psess, ZoneSet())
    assert result["centre"] == pytest.approx([500.0, 400.0])
    assert result["arena_radius"] == pytest.approx(400.0)  # min(1000,800)/2


def test_il3_uses_the_main_roi_centroid_when_zones_are_defined() -> None:
    psess = _make_psess()
    # A 200x200 square main-level arena, centred at (100, 100).
    roi = ROI(name="arena", level="main", vertices=[(0, 0), (200, 0), (200, 200), (0, 200)])
    zone_set = ZoneSet(rois=[roi])

    result = derive_metric_params("IL-3", psess, zone_set)

    assert result["centre"] == pytest.approx([100.0, 100.0])
    assert result["arena_radius"] == pytest.approx(100.0)


def test_il3_radius_uses_the_same_convention_with_and_without_zones() -> None:
    """Regression: the zone branch took the LONGER half-extent while the
    video branch took the SHORTER one, so the same physical arena gave a
    2x different radius depending only on whether a zone had been drawn.
    At the default inner_radius_fraction=0.5 the oversized radius put
    the 'inner' circle out at the walls, scoring wall-hugging animals as
    centre-dwelling -- inverting the thigmotaxis reading IL-3 exists to
    produce. Both branches must inscribe (min), never circumscribe."""
    psess = _make_psess(width_px=1600, height_px=800)
    no_zones = derive_metric_params("IL-3", psess, ZoneSet())

    arena = ROI(
        name="arena", level="main", vertices=[(0, 0), (1600, 0), (1600, 800), (0, 800)]
    )
    with_zone = derive_metric_params("IL-3", psess, ZoneSet(rois=[arena]))

    assert with_zone["centre"] == pytest.approx(no_zones["centre"])
    assert with_zone["arena_radius"] == pytest.approx(no_zones["arena_radius"])
    assert with_zone["arena_radius"] == pytest.approx(400.0)  # min(1600,800)/2


def test_il3_centre_stays_inside_an_arena_when_several_main_rois_exist() -> None:
    """Regression: pooling every main ROI into one bounding box put the
    centre in the empty gap between two separate arenas -- a point no
    animal ever occupies, so every centre-distance in the session was
    measured from dead space. This is the exclusive_rois layout the
    pipeline explicitly supports."""
    psess = _make_psess(width_px=1600, height_px=800)
    left = ROI(name="a", level="main", vertices=[(0, 0), (400, 0), (400, 400), (0, 400)])
    right = ROI(
        name="b", level="main", vertices=[(1200, 0), (1600, 0), (1600, 400), (1200, 400)]
    )

    result = derive_metric_params("IL-3", psess, ZoneSet(rois=[left, right]))

    cx, cy = result["centre"]
    in_left = 0 <= cx <= 400 and 0 <= cy <= 400
    in_right = 1200 <= cx <= 1600 and 0 <= cy <= 400
    assert in_left or in_right, f"centre {result['centre']} is in neither arena"
    assert result["arena_radius"] == pytest.approx(200.0)  # one arena, not the span


# ── IL-3: per-animal centres under a multi-arena layout ──────────────────────


def test_il3_derives_a_centre_per_animal_from_the_arena_it_occupies() -> None:
    """With several separate main arenas, one session-level centre is
    wrong for every animal. Each animal's centre is the arena it
    actually occupies, read from the zone assignment the pipeline
    already computed."""
    n_frames = 10
    xy = np.zeros((n_frames, 2, 2), dtype=np.float64)
    xy[:, 0, :] = [200.0, 200.0]  # animal 0 sits in the left arena
    xy[:, 1, :] = [1400.0, 200.0]  # animal 1 sits in the right arena
    main_zone = np.empty((n_frames, 2), dtype=object)
    main_zone[:, 0] = "left"
    main_zone[:, 1] = "right"
    psess = _make_psess(width_px=1600, height_px=800, xy=xy, main_zone=main_zone)

    result = derive_metric_params("IL-3", psess, _two_arena_zone_set())

    assert result["centres"][0] == pytest.approx([200.0, 200.0])
    assert result["centres"][1] == pytest.approx([1400.0, 200.0])
    assert result["arena_radii"] == pytest.approx([200.0, 200.0])


def test_il3_per_animal_centres_are_uniform_for_a_single_arena() -> None:
    """The common case must not become a special case: one arena means
    every animal shares its centre, matching the session-level value."""
    n_frames = 10
    xy = np.full((n_frames, 2, 2), 100.0)
    main_zone = np.full((n_frames, 2), "arena", dtype=object)
    psess = _make_psess(xy=xy, main_zone=main_zone)
    arena = ROI(name="arena", level="main", vertices=[(0, 0), (200, 0), (200, 200), (0, 200)])

    result = derive_metric_params("IL-3", psess, ZoneSet(rois=[arena]))

    assert np.allclose(result["centres"], [[100.0, 100.0], [100.0, 100.0]])
    assert result["centres"][0] == pytest.approx(result["centre"])
    assert result["arena_radii"][0] == pytest.approx(result["arena_radius"])


def test_il3_falls_back_to_the_session_centre_for_an_animal_in_no_arena() -> None:
    """An animal tracked entirely outside every main zone has no arena
    of its own; it gets the session-level fallback rather than an
    arbitrary one or a NaN."""
    n_frames = 10
    xy = np.zeros((n_frames, 2, 2), dtype=np.float64)
    main_zone = np.empty((n_frames, 2), dtype=object)
    main_zone[:, 0] = "left"
    main_zone[:, 1] = ""  # never inside any main zone
    psess = _make_psess(width_px=1600, height_px=800, xy=xy, main_zone=main_zone)

    result = derive_metric_params("IL-3", psess, _two_arena_zone_set())

    assert result["centres"][0] == pytest.approx([200.0, 200.0])
    assert result["centres"][1] == pytest.approx(result["centre"])


def test_il3_assigns_an_animal_to_the_arena_it_spent_most_time_in() -> None:
    """A few stray frames on the wrong side of the arena boundary must
    not move an animal's centre to the other arena."""
    n_frames = 10
    xy = np.zeros((n_frames, 2, 2), dtype=np.float64)
    main_zone = np.empty((n_frames, 2), dtype=object)
    main_zone[:, 0] = "right"
    main_zone[0:2, 0] = "left"  # 2 stray frames out of 10
    main_zone[:, 1] = "right"
    psess = _make_psess(width_px=1600, height_px=800, xy=xy, main_zone=main_zone)

    result = derive_metric_params("IL-3", psess, _two_arena_zone_set())

    assert result["centres"][0] == pytest.approx([1400.0, 200.0])


def test_il3_per_animal_centres_present_even_with_no_zones() -> None:
    """No zones at all: every animal gets the video-frame centre, still
    as a per-animal list so IL-3's compute() has one code path."""
    psess = _make_psess(width_px=1000, height_px=800)

    result = derive_metric_params("IL-3", psess, ZoneSet())

    assert np.allclose(result["centres"], [[500.0, 400.0], [500.0, 400.0]])
    assert result["arena_radii"] == pytest.approx([400.0, 400.0])


def test_il3_ignores_secondary_level_rois_for_centre() -> None:
    psess = _make_psess(width_px=1000, height_px=800)
    # Only a "secondary" ROI defined -- IL-3 must fall back to video
    # centre, not treat a secondary zone as the arena.
    roi = ROI(name="feeder", level="secondary", vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])
    zone_set = ZoneSet(rois=[roi])

    result = derive_metric_params("IL-3", psess, zone_set)

    assert result["centre"] == pytest.approx([500.0, 400.0])


# ── Z-2: roi_areas / total_arena_area ────────────────────────────────────────


def test_z2_returns_empty_dict_when_no_zones_defined() -> None:
    psess = _make_psess()
    assert derive_metric_params("Z-2", psess, ZoneSet()) == {}


def test_z2_derives_roi_areas_and_total_arena_area() -> None:
    psess = _make_psess()
    main = ROI(name="arena", level="main", vertices=[(0, 0), (100, 0), (100, 100), (0, 100)])
    sub = ROI(name="centre", level="secondary", vertices=[(25, 25), (75, 25), (75, 75), (25, 75)])
    zone_set = ZoneSet(rois=[main, sub])

    result = derive_metric_params("Z-2", psess, zone_set)

    assert result["roi_areas"]["arena"] == pytest.approx(10000.0)
    assert result["roi_areas"]["centre"] == pytest.approx(2500.0)
    # Only "main"-level zones contribute to the overall arena area.
    assert result["total_arena_area"] == pytest.approx(10000.0)


def test_z2_subtractive_rois_reduce_their_own_named_area() -> None:
    """A "-" polygon sharing a name with a "+" polygon is an exclusion
    hole (see ROI.sign) -- its area must subtract from that zone's
    total, not add a second independent zone."""
    psess = _make_psess()
    outer = ROI(
        name="arena", level="main", sign="+",
        vertices=[(0, 0), (100, 0), (100, 100), (0, 100)],
    )
    hole = ROI(
        name="arena", level="main", sign="-",
        vertices=[(40, 40), (60, 40), (60, 60), (40, 60)],
    )
    zone_set = ZoneSet(rois=[outer, hole])

    result = derive_metric_params("Z-2", psess, zone_set)

    assert result["roi_areas"]["arena"] == pytest.approx(10000.0 - 400.0)
    assert result["total_arena_area"] == pytest.approx(10000.0 - 400.0)


def test_z2_total_arena_area_falls_back_to_all_zones_when_none_are_main() -> None:
    psess = _make_psess()
    a = ROI(name="a", level="secondary", vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])
    b = ROI(name="b", level="secondary", vertices=[(0, 0), (20, 0), (20, 20), (0, 20)])
    zone_set = ZoneSet(rois=[a, b])

    result = derive_metric_params("Z-2", psess, zone_set)

    assert result["total_arena_area"] == pytest.approx(100.0 + 400.0)
