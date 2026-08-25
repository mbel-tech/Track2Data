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


def _make_psess(width_px: int = 1000, height_px: int = 800, tmp_path: Path | None = None):
    n_frames, n_animals = 10, 2
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
    return PreprocessedSession(session=session, xy=xy, kinematics=kine)


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
