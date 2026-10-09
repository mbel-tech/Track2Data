#!/usr/bin/env python3
"""Starter analysis of a Track2Data export, in Python.

    python examples/analysis/analyse.py out/

Reads ``metrics_long.csv``, joins the codebook for units and D-11 for data
quality, and sets up the model this design actually calls for -- animals
nested in sessions, not treated as independent observations.

A starting point, not a recommendation for your experiment. Needs pandas;
the model at the end needs statsmodels.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

MIN_COVERAGE = 0.80  # state whatever you choose in your methods section


def load(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return ``(long, codebook, sessions)`` for a run directory."""
    # all_sessions/ holds the same rows stacked; reading it too would count every row twice.
    long_files = sorted(
        f for f in run_dir.rglob("metrics_long.csv") if f.parent.name != "all_sessions"
    )
    if not long_files:
        sys.exit(f"no metrics_long.csv under {run_dir} -- did the run write there?")

    long = pd.concat([pd.read_csv(f) for f in long_files], ignore_index=True)
    codebook = pd.read_csv(run_dir / "codebook.csv")
    sessions = pd.read_csv(run_dir / "sessions.csv")
    return long, codebook, sessions


def check_poolable(sessions: pd.DataFrame) -> None:
    """Refuse to proceed silently across sessions that are not comparable.

    Not boilerplate: fps scales speed, acceleration and path length, and
    group size changes every group metric by construction. Pooling across
    either without accounting for it gives a wrong answer that looks fine.
    """
    if sessions["fps"].nunique() > 1:
        rates = ", ".join(str(f) for f in sorted(sessions["fps"].dropna().unique()))
        print(
            f"WARNING: sessions differ in frame rate ({rates}). Speed and path "
            "length are not comparable across them -- model fps as a covariate, "
            "or analyse the groups separately."
        )
    if sessions["n_animals"].nunique() > 1:
        print(
            "WARNING: sessions differ in group size. Group-level metrics (GL-*) "
            "are not comparable across them."
        )


def main() -> None:
    run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    long, codebook, sessions = load(run_dir)

    check_poolable(sessions)

    print("\n-- sessions --")
    print(
        sessions[
            ["session_id", "fps", "duration_s", "n_animals", "is_calibrated"]
        ].to_string(index=False)
    )

    # ── data quality ─────────────────────────────────────────────────────────
    # D-11 reports how many frames each metric actually used, and what
    # fraction of those were measured rather than interpolated. A ratio from
    # 200 frames and one from 20,000 look identical in a table; this is how
    # you tell them apart.
    quality = (
        long[long["metric_id"] == "D-11"]
        .pivot_table(
            index=["session_id", "individual_id"], columns="column", values="value"
        )
        .reset_index()
    )
    print("\n-- data quality per individual --")
    print(quality.to_string(index=False))

    usable = quality.loc[
        quality["frac_frames_used"] >= MIN_COVERAGE, ["session_id", "individual_id"]
    ]
    dropped = len(quality) - len(usable)
    if dropped:
        print(f"\nexcluding {dropped} individual(s) below {MIN_COVERAGE:.0%} coverage")

    # ── per-individual table ─────────────────────────────────────────────────
    individual = (
        long[
            long["zone_name"].isna()
            & long["individual_id"].notna()
            & (long["metric_id"] != "D-11")
        ]
        .merge(usable, on=["session_id", "individual_id"])
        .pivot_table(
            index=["session_id", "individual_id"], columns="column", values="value"
        )
        .reset_index()
    )
    print("\n-- per-individual metrics --")
    print(individual.to_string(index=False))

    # Units come from the codebook, never from guessing at the column name.
    units = codebook.drop_duplicates("column").set_index("column")["unit"]
    print(f"\npath_length_cm is measured in: {units.get('path_length_cm')}")
    print(
        f"time_pct is measured in:       {units.get('time_pct')}"
        "  <- a FRACTION, not a percentage"
    )

    # ── the model ────────────────────────────────────────────────────────────
    # The session-level grouping is the point. Four fish in one tank are not
    # four independent observations: they interact, share water, and share
    # every disturbance. Ignoring that inflates n by the group size and
    # shrinks every p-value to match.
    if individual["session_id"].nunique() < 2:
        print(
            "\nOnly one session here, so the mixed model is left as a comment: "
            "there is no between-session variance to estimate from one tank."
        )
        print(
            "With several sessions and a between-session treatment:\n"
            "\n"
            "    import statsmodels.formula.api as smf\n"
            "    model = smf.mixedlm(\n"
            '        "mean_speed_cm_s ~ treatment",\n'
            "        data=individual,\n"
            '        groups=individual["session_id"],\n'
            "    ).fit()\n"
            "    print(model.summary())\n"
            "\n"
            "For a *total* rather than a rate -- path length, visit counts, bout\n"
            "counts -- unequal session durations matter. Use an offset instead of\n"
            "the raw total:\n"
            "\n"
            "    import numpy as np\n"
            "    import statsmodels.api as sm\n"
            "    model = smf.glm(\n"
            '        "n_visits ~ treatment",\n'
            "        data=individual,\n"
            "        family=sm.families.Poisson(),\n"
            '        offset=np.log(individual["duration_s"]),\n'
            "    ).fit()\n"
        )
        return

    import statsmodels.formula.api as smf

    joined = individual.merge(
        sessions[["session_id", "duration_s", "fps"]], on="session_id"
    )
    model = smf.mixedlm(
        "mean_speed_cm_s ~ 1", data=joined, groups=joined["session_id"]
    ).fit()
    print("\n-- intercept-only mixed model (replace ~ 1 with your design) --")
    print(model.summary())


if __name__ == "__main__":
    main()
