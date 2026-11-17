"""D-054 wiring: setting minimums, the correlated-metrics warning, schema units, binned runs."""

from __future__ import annotations

import numpy as np
import pytest

from track2data import metrics
from track2data.core.models import MetricSelection
from track2data.exporters.schema import unit_for_column
from track2data.metrics.correlated import CORRELATED_GROUPS, correlated_selection_notes
from track2data.metrics.group import ConvexHullArea, GroupElongation, TopologicalNeighbourCounts
from track2data.metrics.individual import CircularHeadingStats
from tests.test_api import _identity_free_ref, _make_manifest

# ── settings below their minimum are refused ──────────────────────────────────


def _issues(config: dict) -> list[str]:
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[_identity_free_ref()],
        metrics=MetricSelection(group=["GL-13"], config={"GL-13": config}),
    )
    blocking, _notes = Engine(manifest).validation_issues()
    return blocking


@pytest.mark.parametrize("bad", [0, -2])
def test_k_max_below_one_blocks_the_project(bad: int) -> None:
    assert any("k_max" in i and "at least 1" in i for i in _issues({"k_max": bad}))


def test_k_max_of_one_is_accepted() -> None:
    assert not any("k_max" in i for i in _issues({"k_max": 1}))


# ── correlated metrics ────────────────────────────────────────────────────────


def test_every_correlated_id_is_a_registered_metric() -> None:
    registered = set(metrics.all_ids())
    for group in CORRELATED_GROUPS:
        assert set(group.ids) <= registered, group.title


def test_no_note_for_one_metric_per_group() -> None:
    assert correlated_selection_notes(["GL-4", "IL-1", "Z-1"]) == []


def test_note_names_the_group_and_its_members() -> None:
    notes = correlated_selection_notes(["GL-4", "GL-10", "GL-1"])
    assert any("GL-4" in n and "GL-10" in n and "independent" in n for n in notes)


def test_project_validation_carries_the_note_without_blocking() -> None:
    from track2data.api import Engine

    manifest = _make_manifest(
        sessions=[_identity_free_ref()],
        metrics=MetricSelection(group=["GL-4", "GL-10"]),
    )
    blocking, notes = Engine(manifest).validation_issues()
    assert not any("independent" in b for b in blocking)
    assert any("GL-4" in n and "GL-10" in n for n in notes)


# ── schema units for the new columns ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("column", "unit"),
    [
        ("mean_hull_area_cm2", "cm^2"),
        ("median_hull_area_cm2", "cm^2"),
        ("mean_kth_nn_distance_cm", "cm"),
        ("radius_px_used", "px"),
        ("median_elongation_ratio", "dimensionless (ratio)"),
        ("axis_consistency", "dimensionless (0-1)"),
        ("frac_collinear_frames", "fraction (0-1)"),
        ("frac_zero_distance", "fraction (0-1)"),
        ("n_frames_used", "frames"),
        ("n_headings", "count"),
        ("n_turns", "count"),
        ("note", "identifier"),
    ],
)
def test_new_columns_have_a_unit(column: str, unit: str) -> None:
    assert unit_for_column(column) == unit


@pytest.mark.parametrize(
    "cls", [ConvexHullArea, TopologicalNeighbourCounts, GroupElongation, CircularHeadingStats]
)
def test_affected_metrics_declare_frames_used_and_note(cls) -> None:
    assert "n_frames_used" in cls.output_columns
    assert "note" in cls.output_columns


def test_il11_declares_the_rest_threshold_setting() -> None:
    params = {p.name: p for p in CircularHeadingStats.parameters}
    assert params["min_speed_px_s"].default == 0.0
    assert params["min_speed_px_s"].minimum == 0.0


def test_gl13_k_max_minimum_is_one() -> None:
    params = {p.name: p for p in TopologicalNeighbourCounts.parameters}
    assert params["k_max"].minimum == 1
    assert np.isfinite(params["radius_px"].default)
