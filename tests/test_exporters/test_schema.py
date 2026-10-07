"""Tests for track2data.exporters.schema — units, codebook, long table."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import track2data.metrics as metrics_registry
from track2data.exporters.schema import (
    IDENTIFIER_COLUMNS,
    build_codebook,
    long_table,
    unit_for_column,
)


def _all_declared_columns() -> set[str]:
    columns: set[str] = set()
    for metric_id in metrics_registry.all_ids():
        metric_cls = metrics_registry.get(metric_id)
        assert metric_cls is not None
        columns |= set(metric_cls.output_columns)
    return columns


# ── units ─────────────────────────────────────────────────────────────────────


def test_every_registry_column_has_a_known_unit() -> None:
    """The guard that keeps the unit table from falling behind the registry.

    A new metric with an unrecognised column name fails here rather than
    shipping a codebook row reading "unknown" -- which is the one thing a
    codebook must never say about a column it is documenting.
    """
    unknown = sorted(c for c in _all_declared_columns() if unit_for_column(c) == "unknown")
    assert not unknown, (
        f"no unit rule for: {unknown}. Add an entry to _EXPLICIT_UNITS, or a "
        "suffix rule, in track2data/exporters/schema.py."
    )


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("path_length_px", "px"),
        ("path_length_cm", "cm"),
        ("path_length_bl", "body lengths"),
        ("mean_speed_px_s", "px/s"),
        ("mean_speed_cm_s", "cm/s"),
        ("mean_speed_bl_s", "body-lengths/s"),
        ("max_accel_px_s2", "px/s^2"),
        ("mean_hull_area_px2", "px^2"),
        ("mean_heading_rad", "rad"),
        ("mean_turn_rate_rad_per_s", "rad/s"),
        ("mean_dwell_s", "s"),
        ("roaming_entropy_bits", "bits"),
    ],
)
def test_suffix_units(column: str, expected: str) -> None:
    assert unit_for_column(column) == expected


def test_longer_suffixes_win() -> None:
    """"_px_s2" must not be read as "_s", nor "_px_s" as "_px"."""
    assert unit_for_column("max_accel_px_s2") == "px/s^2"
    assert unit_for_column("max_speed_px_s") == "px/s"
    assert unit_for_column("mean_centre_distance_px") == "px"


@pytest.mark.parametrize(
    "column",
    [
        "time_pct",
        "time_in_centre_pct",
        "home_base_time_pct",
        "wall_contact_time_pct",
        "polarised_time_pct",
        "milling_time_pct",
        "swarm_time_pct",
    ],
)
def test_pct_columns_are_documented_as_fractions_not_percentages(column: str) -> None:
    """Every ``*_pct`` column in this project holds a value in [0, 1].

    ``time_pct = 0.42`` means 42 %, but a reader trusting the suffix records
    0.42 %. The name is kept for backward compatibility -- renaming it would
    break every existing analysis script -- so the codebook has to be the
    thing that tells the truth.
    """
    assert unit_for_column(column) == "fraction (0-1)"


def test_identifier_columns_are_not_given_a_measurement_unit() -> None:
    for column in ("session_id", "individual_id", "metric_id", "zone_name"):
        assert unit_for_column(column) == "identifier"


def test_unknown_column_says_unknown_rather_than_guessing() -> None:
    """A wrong unit is worse than an absent one, because it is believed."""
    assert unit_for_column("some_future_quantity") == "unknown"


def test_frame_counts_are_frames_not_seconds() -> None:
    """``fragment_length_median`` ends in a word, not a unit suffix; without
    an explicit entry the ``_s``-style rules would be tempting and wrong."""
    assert unit_for_column("fragment_length_median") == "frames"
    assert unit_for_column("n_frames_used") == "frames"


# ── codebook ──────────────────────────────────────────────────────────────────


def test_codebook_covers_every_declared_column() -> None:
    codebook = build_codebook()
    assert set(codebook["column"]) == _all_declared_columns()


def test_codebook_carries_the_citation_and_doi() -> None:
    """"45 cited metrics" becomes a machine-readable artefact, not a claim."""
    codebook = build_codebook()
    row = codebook[codebook["column"] == "mean_nnd_px"].iloc[0]

    assert row["metric_id"] == "GL-1"
    assert row["level"] == "group"
    assert row["doi"]
    assert row["citation"]


def test_codebook_has_a_row_per_metric_for_a_shared_column() -> None:
    """``session_id`` is emitted by everything; which metric produced a row is
    exactly what a reader of a merged table needs."""
    codebook = build_codebook()
    shared = codebook[codebook["column"] == "session_id"]
    assert len(shared) == len(metrics_registry.all_ids())


def test_codebook_can_be_restricted_to_selected_metrics() -> None:
    codebook = build_codebook(["IL-1"])
    assert set(codebook["metric_id"]) == {"IL-1"}
    assert "path_length_px" in set(codebook["column"])


def test_codebook_ignores_an_unknown_metric_id() -> None:
    assert build_codebook(["NOPE-1"]).empty


def test_codebook_column_order_is_stable() -> None:
    assert list(build_codebook(["IL-1"]).columns) == [
        "column", "unit", "level", "metric_id", "metric_name",
        "definition", "citation", "doi",
    ]


# ── long table ────────────────────────────────────────────────────────────────


def _individual_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": ["s1", "s1"],
        "metric_id": ["IL-1", "IL-1"],
        "individual_id": [0, 1],
        "path_length_px": [100.0, 200.0],
        "path_length_cm": [10.0, 20.0],
        "path_length_bl": [np.nan, np.nan],
    })


def _group_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": ["s1"],
        "metric_id": ["GL-1"],
        "mean_nnd_px": [42.0],
    })


def test_long_table_is_one_row_per_value() -> None:
    out = long_table({"IL-1": _individual_frame()})
    # 2 individuals x 3 value columns.
    assert len(out) == 6


def test_long_table_keeps_metric_id() -> None:
    """The wide summary drops it during the merge; a value that cannot be
    traced back to its metric cannot be traced to the paper defining it."""
    out = long_table({"IL-1": _individual_frame(), "GL-1": _group_frame()})
    assert set(out["metric_id"]) == {"IL-1", "GL-1"}


def test_long_table_carries_the_unit_per_row() -> None:
    out = long_table({"IL-1": _individual_frame()})
    units = dict(zip(out["column"], out["unit"], strict=True))
    assert units["path_length_px"] == "px"
    assert units["path_length_cm"] == "cm"
    assert units["path_length_bl"] == "body lengths"


def test_long_table_mixes_levels_in_one_shape() -> None:
    """Group rows have no individual_id; that is a NaN, not a separate file."""
    out = long_table({"IL-1": _individual_frame(), "GL-1": _group_frame()})
    group_rows = out[out["metric_id"] == "GL-1"]
    assert len(group_rows) == 1
    assert pd.isna(group_rows.iloc[0]["individual_id"])


def test_long_table_drops_non_numeric_measurements() -> None:
    """``value`` needs one dtype to be usable in a model formula."""
    df = pd.DataFrame({
        "session_id": ["s1"],
        "metric_id": ["D-5"],
        "identity_stability_status": ["stable"],
        "estimated_accuracy": [0.97],
    })

    out = long_table({"D-5": df})

    assert set(out["column"]) == {"estimated_accuracy"}


def test_long_table_never_melts_an_identity_column() -> None:
    out = long_table({"IL-1": _individual_frame()})
    assert not (set(out["column"]) & IDENTIFIER_COLUMNS)


def test_long_table_column_order_is_stable() -> None:
    assert list(long_table({"IL-1": _individual_frame()}).columns) == [
        "session_id", "individual_id", "zone_name", "from_zone", "to_zone",
        "metric_id", "column", "value", "unit",
    ]


def test_empty_input_still_has_the_columns() -> None:
    out = long_table({})
    assert out.empty
    assert "value" in out.columns
    assert "unit" in out.columns


def test_metric_frame_with_no_numeric_columns_is_skipped() -> None:
    df = pd.DataFrame({"session_id": ["s1"], "metric_id": ["X"], "note": ["n/a"]})
    assert long_table({"X": df}).empty


def test_zone_keys_survive_the_melt() -> None:
    """A zone metric's rows are meaningless without knowing which zone."""
    df = pd.DataFrame({
        "session_id": ["s1", "s1"],
        "metric_id": ["Z-1", "Z-1"],
        "individual_id": [0, 0],
        "zone_name": ["inner", "outer"],
        "time_pct": [0.3, 0.7],
    })

    out = long_table({"Z-1": df})

    assert set(out["zone_name"]) == {"inner", "outer"}
    assert set(out["unit"]) == {"fraction (0-1)"}


def test_empty_and_missing_metric_frames_are_skipped() -> None:
    """A metric that produced nothing must not become a row of nothing."""
    empty = pd.DataFrame(columns=["session_id", "metric_id", "path_length_px"])

    out = long_table({"IL-1": _individual_frame(), "EMPTY": empty, "NONE": None})

    assert set(out["metric_id"]) == {"IL-1"}
