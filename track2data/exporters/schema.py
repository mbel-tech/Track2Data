"""Units, the codebook, and the genuinely-long metric table.

Three things a dataset needs before someone else can analyse it, and which
this project's exports did not carry:

**Units.** They exist only in column-name suffixes (``_px``, ``_cm_s``,
``_rad``), which a reader has to decode by convention. Worse, the convention
is not always right: every ``*_pct`` column in the registry holds a
*fraction* in [0, 1], not a percentage -- ``time_pct = 0.42`` means 42 %, and
a reader who trusts the suffix records 0.42 %. ``unit_for_column`` is the one
place that says what a column actually holds, and
``test_schema_units.py`` fails when a new column has no entry, so the table
cannot fall behind the registry.

**A codebook.** One row per exported column: unit, level, originating metric
and DOI. That turns "45 cited metrics" from a README claim into a
machine-readable artefact shipped with the data.

**A long table.** ``trial_activity_summary.csv`` is one row per
session x individual with a column per metric -- *wide* in tidy-data terms,
whatever its filename says, and it drops ``metric_id`` on the way. Feeding
``lme4``/``glmmTMB``/``statsmodels`` wants the long form:
``session_id, individual_id, metric_id, column, value, unit``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

#: Columns identifying a row rather than measuring anything. Excluded from the
#: long table's value rows, and marked as identifiers in the codebook.
IDENTIFIER_COLUMNS: frozenset[str] = frozenset({
    "session_id", "individual_id", "metric_id", "zone_name", "from_zone",
    "to_zone", "frame", "event", "note", "k",
})

#: Exact column -> unit, for names the suffix convention gets wrong or does
#: not cover. Each entry is a decision, not a default.
_EXPLICIT_UNITS: dict[str, str] = {
    # Named "_pct" but computed as a fraction of 1 -- see the module
    # docstring. Recorded truthfully here rather than renamed, which would
    # break every existing analysis script reading these files.
    "home_base_time_pct": "fraction (0-1)",
    "milling_time_pct": "fraction (0-1)",
    "polarised_time_pct": "fraction (0-1)",
    "swarm_time_pct": "fraction (0-1)",
    "time_in_centre_pct": "fraction (0-1)",
    "time_pct": "fraction (0-1)",
    "wall_contact_time_pct": "fraction (0-1)",

    # Fragment lengths are counted in frames, not seconds.
    "fragment_length_max": "frames",
    "fragment_length_median": "frames",
    "fragment_length_p10": "frames",
    "fragment_length_p90": "frames",

    # Probabilities and other bounded dimensionless quantities.
    "estimated_accuracy": "fraction (0-1)",
    "fraction_identified": "fraction (0-1)",
    "fragment_connectivity": "dimensionless (ratio)",
    "silhouette_score": "dimensionless (score, -1 to 1)",
    "certainty_mean": "dimensionless (score)",
    "certainty_min": "dimensionless (score)",
    "certainty_threshold_used": "dimensionless (score)",
    "path_length_ratio": "dimensionless (ratio)",
    "distortion_index": "dimensionless (ratio)",
    "id_prob_frac_above_0p9": "fraction (0-1)",
    "id_prob_median": "probability (0-1)",
    "id_prob_p10": "probability (0-1)",
    "id_prob_p90": "probability (0-1)",
    "transition_probability": "probability (0-1)",
    "rayleigh_p": "p-value",

    # Dimensionless indices and ratios.
    "area_corrected_occupancy": "dimensionless (ratio)",
    "cohesion_index": "dimensionless (index)",
    "jacobs_d": "dimensionless (-1 to 1)",
    "left_right_turn_bias": "dimensionless (-1 to 1)",
    "mean_elongation_ratio": "dimensionless (ratio)",
    "mean_neighbours_within_radius": "count",
    "mean_polarisation": "dimensionless (0-1)",
    "median_polarisation": "dimensionless (0-1)",
    "mean_rotational_order": "dimensionless (0-1)",
    "median_rotational_order": "dimensionless (0-1)",
    "resultant_length": "dimensionless (0-1)",
    "roaming_entropy_normalised": "dimensionless (0-1)",
    "tortuosity": "dimensionless (ratio)",

    # Frame counts expressed as thresholds rather than measurements.
    "min_bout_frames_used": "frames",
    "min_dwell_frames_used": "frames",
    "min_visit_frames_used": "frames",
    "n_frames_total": "frames",
    "n_frames_used": "frames",
    "n_classified_frames": "frames",
    "n_skipped_frames": "frames",
    "nan_frames_count": "frames",
    "number_of_error_frames": "frames",
    "n_interpolated": "frames",
    "n_jump_replaced": "frames",

    # Categorical.
    "bout_criterion_effective": "categorical",
    "home_base_stable": "boolean",
    "identity_stability_status": "categorical",
}

#: Suffix -> unit, longest suffix first so "_px_s2" wins over "_px_s" and
#: "_s". Order matters and is load-bearing.
_SUFFIX_UNITS: tuple[tuple[str, str], ...] = (
    ("_turn_rate_rad_per_s", "rad/s"),
    ("_rad_per_s", "rad/s"),
    ("_px_s2", "px/s^2"),
    ("_px_s", "px/s"),
    ("_cm_s", "cm/s"),
    ("_bl_s", "body-lengths/s"),
    ("_px2", "px^2"),
    ("_bits", "bits"),
    ("_rad", "rad"),
    ("_px", "px"),
    ("_cm", "cm"),
    ("_bl", "body lengths"),
    ("_pct", "fraction (0-1)"),
    ("_fraction", "fraction (0-1)"),
    ("_count", "count"),
    ("_s", "s"),
)

#: Prefix -> unit, for the ``frac_*`` / ``n_*`` naming used by the newer
#: diagnostics.
_PREFIX_UNITS: tuple[tuple[str, str], ...] = (
    ("frac_", "fraction (0-1)"),
    ("n_", "count"),
)


def unit_for_column(column: str) -> str:
    """The unit a column's values are expressed in.

    Returns ``"identifier"`` for key columns and ``"unknown"`` when no rule
    matches -- deliberately, rather than guessing. A wrong unit in a codebook
    is worse than an absent one, because it will be believed.
    """
    if column in IDENTIFIER_COLUMNS:
        return "identifier"
    if column in _EXPLICIT_UNITS:
        return _EXPLICIT_UNITS[column]
    for suffix, unit in _SUFFIX_UNITS:
        if column.endswith(suffix):
            return unit
    for prefix, unit in _PREFIX_UNITS:
        if column.startswith(prefix):
            return unit
    return "unknown"


def build_codebook(metric_ids: list[str] | None = None) -> pd.DataFrame:
    """One row per exported column, with its unit, metric and citation.

    Parameters
    ----------
    metric_ids:
        Restrict to these metrics. Defaults to the whole registry, which is
        what an export wants: a reader should be able to look up any column
        they encounter, not only the ones this particular run selected.
    """
    import pandas as pd

    import track2data.metrics as registry

    ids = metric_ids if metric_ids is not None else registry.all_ids()

    rows: list[dict[str, Any]] = []
    for metric_id in ids:
        metric_cls = registry.get(metric_id)
        if metric_cls is None:
            continue
        doc = metric_cls.documentation
        for column in metric_cls.output_columns:
            rows.append({
                "column": column,
                "unit": unit_for_column(column),
                "level": metric_cls.level,
                "metric_id": metric_cls.id,
                "metric_name": metric_cls.label,
                "definition": doc.definition,
                "citation": doc.citation or "",
                "doi": doc.citation_doi or "",
            })

    df = pd.DataFrame(
        rows,
        columns=[
            "column", "unit", "level", "metric_id", "metric_name",
            "definition", "citation", "doi",
        ],
    )
    # A column emitted by several metrics gets a row per metric: which metric
    # produced it is exactly what a reader of a merged table needs.
    return df.sort_values(["column", "metric_id"]).reset_index(drop=True)


def long_table(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Melt per-metric result frames into one long table.

    ``session_id, individual_id, zone_name, metric_id, column, value, unit`` --
    one row per measured value. Unlike ``trial_activity_summary.csv`` this
    keeps ``metric_id``, so a value can always be traced back to the metric
    (and through the codebook, to the paper) that defines it.

    Non-numeric measurements (a status string, a zone transition's event) are
    dropped: a long table's ``value`` column has to have one dtype to be
    usable in a model formula, and those are carried in the wide tables
    already.
    """
    import pandas as pd

    key_columns = ["session_id", "individual_id", "zone_name", "from_zone", "to_zone"]
    frames: list[pd.DataFrame] = []

    for metric_id, df in metrics.items():
        if df is None or df.empty:
            continue
        present_keys = [c for c in key_columns if c in df.columns]
        value_columns = [
            c
            for c in df.columns
            if c not in IDENTIFIER_COLUMNS
            and c not in present_keys
            and pd.api.types.is_numeric_dtype(df[c])
        ]
        if not value_columns:
            continue

        melted = df.melt(
            id_vars=present_keys,
            value_vars=value_columns,
            var_name="column",
            value_name="value",
        )
        melted["metric_id"] = metric_id
        frames.append(melted)

    ordered = [
        "session_id", "individual_id", "zone_name", "from_zone", "to_zone",
        "metric_id", "column", "value", "unit",
    ]
    if not frames:
        return pd.DataFrame(columns=ordered)

    out = pd.concat(frames, ignore_index=True)
    out["unit"] = out["column"].map(unit_for_column)
    for column in ordered:
        if column not in out.columns:
            out[column] = pd.NA
    out = out[ordered]

    sort_keys = [c for c in ("session_id", "individual_id", "metric_id", "column")
                 if c in out.columns]
    return out.sort_values(sort_keys, na_position="last").reset_index(drop=True)
