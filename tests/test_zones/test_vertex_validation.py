"""validate_vertices: what an interactive zone edit may and may not produce."""

from __future__ import annotations

import math

import pytest

from track2data.core.errors import ZoneValidationError
from track2data.zones.geometry import _make_valid_polygon, validate_vertices

TRIANGLE = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]


def _problem(vertices: list) -> str:
    with pytest.raises(ZoneValidationError) as err:
        validate_vertices(vertices)
    assert err.value.code == "ZONE_INVALID_SHAPE"
    assert err.value.remediation
    return str(err.value)


def test_a_normal_triangle_passes() -> None:
    validate_vertices(TRIANGLE)


def test_a_concave_polygon_passes() -> None:
    validate_vertices([(0, 0), (10, 0), (10, 10), (5, 4), (0, 10)])


def test_the_collinear_triangle_from_the_bug_report_is_rejected() -> None:
    # Moving the last vertex of the triangle to (5, 0) puts all three on the x axis.
    assert "area" in _problem([(0, 0), (10, 0), (5, 0)])


def test_fewer_than_three_vertices_is_rejected() -> None:
    assert "3" in _problem([(0, 0), (1, 1)])


def test_repeated_vertices_leave_too_few_distinct_points() -> None:
    assert "distinct" in _problem([(0, 0), (0, 0), (5, 5), (5, 5)])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_coordinates_are_rejected(bad: float) -> None:
    assert "finite" in _problem([(0, 0), (10, 0), (bad, 10)])


def test_a_self_intersecting_bowtie_is_rejected() -> None:
    message = _problem([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert "cross" in message


def test_a_sliver_with_no_usable_area_is_rejected() -> None:
    assert "area" in _problem([(0, 0), (1000, 0), (500, 1e-12)])


def test_imported_tracker_polygons_are_still_repaired_not_rejected() -> None:
    """The engine's buffer(0) repair for roi_list polygons is a separate, deliberate path."""
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    assert not _make_valid_polygon(bowtie).is_empty
