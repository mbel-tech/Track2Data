"""Recompute metrics across a grid of preprocessing settings.

The strongest methodological objection this class of tool attracts is that
the preprocessing choices, not the animals, drive the result. It is a fair
objection: the smoothing window and ``max_gap_frames`` are free parameters
chosen by the analyst, and nothing in a normal export shows how much of a
reported number depends on them.

This answers it directly. Re-run the same session across a grid of settings
and report, per metric column, how far the value moves. A user who can
attach that table to a manuscript is in a much better position at review
than one asserting the choice did not matter.

What the output says
--------------------
``sensitivity.csv`` -- one row per (setting, session, individual, column):
the raw value at every point in the grid.

``sensitivity_summary.csv`` -- one row per column: the spread across the
grid, as a **coefficient of variation** (SD / |mean|) so columns in
different units are comparable, plus the min and max and which settings
produced them. This is the actionable table: a column with CV near zero is
robust to the choice, and one at 0.3 is not a finding about the animals.

Deliberately not a single "is this robust?" verdict. Where the line sits
depends on the effect size someone is claiming, which this module cannot
know -- reporting the number and letting the analyst judge is the honest
version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from track2data.api import Engine
    from track2data.core.models import Session

#: Smoothing windows spanning "barely filtered" to "heavily filtered". Odd
#: values only -- Savitzky-Golay requires an odd window, and silently
#: decrementing an even one would report a setting that was not used.
DEFAULT_SMOOTHING_WINDOWS: tuple[int, ...] = (3, 5, 9, 15)

#: Gap lengths from "fill almost nothing" to "fill a full second at 30 fps".
#: The default is 30; the grid brackets it rather than starting there, so a
#: user can see which side of the default their result sits on.
DEFAULT_MAX_GAP_FRAMES: tuple[int, ...] = (5, 15, 30, 60)


@dataclass(frozen=True)
class GridPoint:
    """One combination of preprocessing settings."""

    smoothing_window: int
    max_gap_frames: int

    def label(self) -> str:
        return f"win{self.smoothing_window}_gap{self.max_gap_frames}"


@dataclass
class SensitivityGrid:
    """The settings to sweep. Defaults bracket the shipped defaults."""

    smoothing_windows: tuple[int, ...] = DEFAULT_SMOOTHING_WINDOWS
    max_gap_frames: tuple[int, ...] = DEFAULT_MAX_GAP_FRAMES
    #: Metrics to recompute. Empty means "whatever the project selected",
    #: which is the right default: sweeping metrics nobody asked for costs
    #: time and produces a table nobody reads.
    metric_ids: list[str] = field(default_factory=list)

    def points(self) -> list[GridPoint]:
        return [
            GridPoint(smoothing_window=w, max_gap_frames=g)
            for w in self.smoothing_windows
            for g in self.max_gap_frames
        ]


def _config_for(base: Any, point: GridPoint) -> Any:
    """A copy of *base* with this grid point's settings applied."""
    smoothing = base.smoothing.model_copy(
        update={"enabled": True, "window": point.smoothing_window}
    )
    gap_fill = base.gap_fill.model_copy(
        update={"enabled": True, "max_gap_frames": point.max_gap_frames}
    )
    return base.model_copy(update={"smoothing": smoothing, "gap_fill": gap_fill})


def run_sensitivity(
    engine: Engine,
    session: Session,
    grid: SensitivityGrid | None = None,
) -> pd.DataFrame:
    """Recompute *session*'s metrics at every point of *grid*.

    Returns one row per (grid point, individual, metric column) with the
    value, the settings that produced it, and the unit -- long format, so it
    joins to ``codebook.csv`` like every other table this tool writes.

    A grid point whose preprocessing or metric computation fails is skipped
    with its error recorded rather than aborting the sweep: a setting that
    does not work on this session is itself a useful thing to see in the
    table.
    """
    import pandas as pd

    from track2data.core.models import SENSITIVITY_3D_REFUSAL
    from track2data.exporters.schema import unit_for_column

    if engine.manifest.mode.dimension == "3d":  # raised, not recorded per grid point
        raise ValueError(SENSITIVITY_3D_REFUSAL)
    grid = grid or SensitivityGrid()
    base_config = engine.manifest.preprocess

    rows: list[dict[str, Any]] = []
    for point in grid.points():
        config = _config_for(base_config, point)
        try:
            from track2data.preprocess.pipeline import run as run_pipeline

            psess = run_pipeline(session, config)
            psess = engine.apply_calibration_and_zones(psess)
            results = engine.compute_metrics(psess)
        except Exception as exc:  # recorded in the table, not swallowed
            rows.append({
                "smoothing_window": point.smoothing_window,
                "max_gap_frames": point.max_gap_frames,
                "session_id": session.session_id,
                "individual_id": pd.NA,
                "metric_id": pd.NA,
                "column": pd.NA,
                "value": pd.NA,
                "unit": pd.NA,
                "error": str(exc),
            })
            continue

        wanted = grid.metric_ids or list(results)
        for metric_id, df in results.items():
            if metric_id not in wanted or df is None or df.empty:
                continue
            for column in df.columns:
                if column in ("session_id", "metric_id", "individual_id", "zone_name"):
                    continue
                if not pd.api.types.is_numeric_dtype(df[column]):
                    continue
                for _, record in df.iterrows():
                    rows.append({
                        "smoothing_window": point.smoothing_window,
                        "max_gap_frames": point.max_gap_frames,
                        "session_id": session.session_id,
                        "individual_id": record.get("individual_id", pd.NA),
                        "metric_id": metric_id,
                        "column": column,
                        "value": record[column],
                        "unit": unit_for_column(column),
                        "error": pd.NA,
                    })

    return pd.DataFrame(
        rows,
        columns=[
            "smoothing_window", "max_gap_frames", "session_id", "individual_id",
            "metric_id", "column", "value", "unit", "error",
        ],
    )


def summarise(sweep: pd.DataFrame) -> pd.DataFrame:
    """Per metric column: how far did it move across the grid?

    The headline number is the **coefficient of variation** (SD / |mean|),
    which is unitless and therefore comparable between a path length in cm
    and a bounded fraction. A column at ~0 is robust to the preprocessing
    choice; one at 0.3 is substantially a statement about the settings.

    Computed per individual first and then averaged, not pooled across
    individuals -- pooling would mix genuine between-animal variation into
    what is supposed to measure parameter sensitivity alone.
    """
    import numpy as np
    import pandas as pd

    usable = sweep[sweep["error"].isna()].copy()
    if usable.empty:
        return pd.DataFrame(
            columns=[
                "metric_id", "column", "unit", "cv", "min", "max",
                "range_pct_of_mean", "n_settings",
            ]
        )

    def _cv(values: pd.Series) -> float:
        mean = values.mean()
        if not np.isfinite(mean) or mean == 0:
            return float("nan")
        return float(values.std(ddof=0) / abs(mean))

    per_individual = (
        usable.groupby(["metric_id", "column", "unit", "individual_id"], dropna=False)[
            "value"
        ]
        .agg(cv=_cv, min="min", max="max", n_settings="count")
        .reset_index()
    )

    summary = (
        per_individual.groupby(["metric_id", "column", "unit"], dropna=False)
        .agg(
            cv=("cv", "mean"),
            min=("min", "min"),
            max=("max", "max"),
            n_settings=("n_settings", "max"),
        )
        .reset_index()
    )

    span = summary["max"] - summary["min"]
    midpoint = (summary["max"].abs() + summary["min"].abs()) / 2
    summary["range_pct_of_mean"] = np.where(midpoint > 0, 100 * span / midpoint, np.nan)

    return summary.sort_values("cv", ascending=False, na_position="last").reset_index(
        drop=True
    )
