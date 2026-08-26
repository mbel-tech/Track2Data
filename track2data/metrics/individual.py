"""
Individual-level metrics: IL-1, IL-2, IL-3, IL-4, IL-5, IL-6, IL-7, IL-8.

Each class implements :class:`track2data.metrics.base.Metric` and returns
a :class:`pandas.DataFrame` with at least the columns ``session_id``,
``metric_id``, and ``individual_id``.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd

from track2data.core.models import PreprocessedSession
from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter
from track2data.metrics.references import (
    BENHAMOU_2004,
    BENHAMOU_2013,
    BERENS_2009,
    BJORNERAAS_2010,
    CACHAT_2010,
    EGAN_2009,
    EILAM_GOLANI_1989,
    FREUND_2013,
    HALL_1934,
    KALUEFF_2013,
    KAREIVA_SHIGESADA_1983,
    MARQUES_2018,
    MARTIN_BATESON_2007,
    MAXIMINO_2010,
    MWAFFO_2015,
    SCHNORR_2012,
    SIBLY_1990,
    SIMON_1994,
    STEWART_2012,
)

# ── IL-1: PathLength ──────────────────────────────────────────────────────────


class PathLength(Metric):
    """IL-1 — Total distance travelled (path length) per individual."""

    id = "IL-1"
    name = "path_length"
    label = "Distance Travelled"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "path_length_px",
    ]
    documentation = MetricDocumentation(
        definition="Total distance travelled by each individual over the session.",
        formula_plain="sum of ||xy[t+1,k] - xy[t,k]|| for non-NaN consecutive frame pairs",
        inputs=["PreprocessedSession.xy"],
        assumptions=["Post-smoothing xy is used; gaps produce no displacement"],
        warnings=["Under-smoothed data inflates path length"],
        citation="Standard kinematics",
        supporting_references=[MARTIN_BATESON_2007],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute path length for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row per individual with columns ``session_id``, ``metric_id``,
            ``individual_id``, ``path_length_px``, and optionally
            ``path_length_cm`` / ``path_length_bl``.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            traj = xy[:, k, :]  # (n_frames, 2)
            # Consecutive displacements, skipping pairs where either frame is NaN
            diff = traj[1:] - traj[:-1]  # (n_frames-1, 2)
            valid = ~(np.isnan(diff[:, 0]) | np.isnan(diff[:, 1]))
            path_px = float(np.sqrt((diff[valid] ** 2).sum(axis=1)).sum())

            row: dict = {
                "session_id": session.session_id,
                "metric_id": self.id,
                "individual_id": k,
                "path_length_px": path_px,
            }

            if session.px_per_cm is not None:
                row["path_length_cm"] = path_px / session.px_per_cm
                if session.body_length_cm is not None:
                    bl_cm = float(session.body_length_cm[k])
                    row["path_length_bl"] = row["path_length_cm"] / bl_cm if bl_cm != 0 else np.nan
                else:
                    row["path_length_bl"] = np.nan
            else:
                row["path_length_cm"] = np.nan
                row["path_length_bl"] = np.nan

            records.append(row)

        return pd.DataFrame(records)


# ── IL-2: Speed ───────────────────────────────────────────────────────────────


class Speed(Metric):
    """IL-2 — Mean, median, and max speed per individual."""

    id = "IL-2"
    name = "speed"
    label = "Speed (mean / median / max)"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_speed_px_s",
        "median_speed_px_s",
        "max_speed_px_s",
    ]
    documentation = MetricDocumentation(
        definition="Mean, median, and maximum speed of each individual over the session.",
        formula_plain="mean/median/max of kinematics.speed_px_s per animal (NaN excluded)",
        inputs=["PreprocessedSession.kinematics.speed_px_s"],
        assumptions=["speed_px_s is pre-computed by the kinematics pipeline"],
        warnings=["Max speed is sensitive to remaining jump artefacts"],
        citation="Standard kinematics",
        supporting_references=[BJORNERAAS_2010],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute speed statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        speed = session.kinematics.speed_px_s  # (n_frames, n_animals)
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            s = speed[:, k]
            valid = s[~np.isnan(s)]

            mean_s = float(np.mean(valid)) if len(valid) > 0 else np.nan
            median_s = float(np.median(valid)) if len(valid) > 0 else np.nan
            max_s = float(np.max(valid)) if len(valid) > 0 else np.nan

            row: dict = {
                "session_id": session.session_id,
                "metric_id": self.id,
                "individual_id": k,
                "mean_speed_px_s": mean_s,
                "median_speed_px_s": median_s,
                "max_speed_px_s": max_s,
            }

            if session.px_per_cm is not None:
                row["mean_speed_cm_s"] = (
                    mean_s / session.px_per_cm if not np.isnan(mean_s) else np.nan
                )
                if session.body_length_cm is not None:
                    bl_cm = float(session.body_length_cm[k])
                    cm_s = row["mean_speed_cm_s"]
                    row["mean_speed_bl_s"] = (
                        cm_s / bl_cm if (not np.isnan(cm_s) and bl_cm != 0) else np.nan
                    )
                else:
                    row["mean_speed_bl_s"] = np.nan
            else:
                row["mean_speed_cm_s"] = np.nan
                row["mean_speed_bl_s"] = np.nan

            records.append(row)

        return pd.DataFrame(records)


# ── IL-3: CentreDistance ──────────────────────────────────────────────────────


class CentreDistance(Metric):
    """IL-3 — Mean distance from arena centre per individual."""

    id = "IL-3"
    name = "centre_distance"
    label = "Distance from Arena Centre"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_centre_distance_px",
        # Emitted whenever an arena radius is known, which -- since the
        # radius became a derived parameter -- is every run.
        "time_in_centre_pct",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean Euclidean distance of each individual from the centre of the "
            "arena it occupies, over the session.  Also reports the fraction of "
            "time spent within the inner part of that arena (radius = "
            "arena_radius * inner_radius_fraction, default half)."
        ),
        formula_plain=(
            "d[t,k] = ||xy[t,k] - centre[k]||; "
            "mean_centre_distance_px = mean over non-NaN frames; "
            "time_in_centre_pct = fraction of non-NaN frames with "
            "d[t,k] < arena_radius[k] * inner_radius_fraction"
        ),
        inputs=["PreprocessedSession.xy", "PreprocessedSession.main_zone"],
        assumptions=[
            "The centre and radius are derived per session from the project's "
            "own main-level zone geometry, or the video frame when no zones are "
            "defined; with several main arenas each animal is measured from the "
            "one it occupies"
        ],
        warnings=[
            "For a non-circular arena, centre-distance is interpretable only "
            "with a clearly defined origin",
            "In a non-circular (e.g. rectangular) arena, centre-distance is not "
            "monotonic in distance-to-wall -- a corner-hugging animal can score "
            "the same centre-distance as one near a wall's midpoint; see IL-14 "
            "for the wall-distance-specific measure",
        ],
        primary_reference=SCHNORR_2012,
        supporting_references=[SIMON_1994, HALL_1934],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="centre", label="Arena centre", kind="float", derived=True,
            help="Derived from the project's main zone, or the video frame centre.",
        ),
        MetricParameter(
            name="arena_radius", label="Arena radius", kind="float", derived=True, unit="px",
        ),
        MetricParameter(
            name="centres", label="Arena centre per animal", kind="float", derived=True,
            help=(
                "With several main zones, each animal is measured from the arena "
                "it occupies rather than from one shared centre."
            ),
        ),
        MetricParameter(
            name="arena_radii", label="Arena radius per animal", kind="float",
            derived=True, unit="px",
        ),
        MetricParameter(
            name="inner_radius_fraction",
            label="Inner-radius fraction",
            kind="float",
            default=0.5,
            minimum=0.0,
            maximum=1.0,
            help=(
                "Fraction of arena_radius defining the 'inner' zone for "
                "time_in_centre_pct (0.5 = inner half)."
            ),
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute centre-distance statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict.  Keys:
            ``centres`` — one ``[x, y]`` arena centre per animal, so each
            animal is measured from the arena it occupies (see
            ``metrics/derived.py``). Takes precedence over ``centre``.
            ``arena_radii`` — one radius per animal, likewise.
            ``centre`` — a single ``[x, y]`` centre shared by every animal.
            ``arena_radius`` — a single radius; enables ``time_in_centre_pct``.
            ``inner_radius_fraction`` — fraction of the arena radius defining
            the "inner" zone for ``time_in_centre_pct`` (default 0.5).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_animals = session.n_animals

        # Determine centre
        if cfg is not None and "centre" in cfg:
            centre = np.asarray(cfg["centre"], dtype=np.float64)
        else:
            # Compute mean of all non-NaN positions across all animals
            all_x = xy[:, :, 0].ravel()
            all_y = xy[:, :, 1].ravel()
            valid = ~(np.isnan(all_x) | np.isnan(all_y))
            if valid.sum() > 0:
                centre = np.array([np.mean(all_x[valid]), np.mean(all_y[valid])])
            else:
                centre = np.array([0.0, 0.0])

        arena_radius: float | None = None
        if cfg is not None and "arena_radius" in cfg:
            arena_radius = float(cfg["arena_radius"])

        # Per-animal geometry, when the session provides it. Under the
        # exclusive_rois layout each animal lives in its own arena, so a
        # single shared centre would sit in the gap between arenas and
        # measure every distance from a point no animal ever occupies.
        centres_per_animal = None
        if cfg is not None and cfg.get("centres") is not None:
            centres_per_animal = np.asarray(cfg["centres"], dtype=np.float64)

        radii_per_animal = None
        if cfg is not None and cfg.get("arena_radii") is not None:
            radii_per_animal = [float(r) for r in cfg["arena_radii"]]

        inner_radius_fraction = 0.5
        if cfg is not None and "inner_radius_fraction" in cfg:
            inner_radius_fraction = float(cfg["inner_radius_fraction"])

        records: list[dict] = []
        for k in range(n_animals):
            # This animal's own arena, falling back to the session-level
            # centre/radius when no per-animal geometry was supplied.
            if centres_per_animal is not None and k < len(centres_per_animal):
                animal_centre = centres_per_animal[k]
            else:
                animal_centre = centre

            if radii_per_animal is not None and k < len(radii_per_animal):
                animal_radius: float | None = radii_per_animal[k]
            else:
                animal_radius = arena_radius

            traj = xy[:, k, :]  # (n_frames, 2)
            valid_mask = ~np.isnan(traj[:, 0])
            valid_traj = traj[valid_mask]

            if len(valid_traj) == 0:
                mean_dist = np.nan
                row: dict = {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "mean_centre_distance_px": mean_dist,
                }
                if animal_radius is not None:
                    row["time_in_centre_pct"] = np.nan
                records.append(row)
                continue

            diffs = valid_traj - animal_centre  # (n_valid, 2)
            dists = np.sqrt((diffs**2).sum(axis=1))
            mean_dist = float(dists.mean())

            row = {
                "session_id": session.session_id,
                "metric_id": self.id,
                "individual_id": k,
                "mean_centre_distance_px": mean_dist,
            }

            if animal_radius is not None:
                inner_radius = animal_radius * inner_radius_fraction
                time_in_centre = float((dists < inner_radius).mean())
                row["time_in_centre_pct"] = time_in_centre

            records.append(row)

        return pd.DataFrame(records)


# ── IL-4: Activity ────────────────────────────────────────────────────────────


class Activity(Metric):
    """IL-4 — Active / freezing fraction per individual."""

    id = "IL-4"
    name = "activity"
    label = "Activity / Freezing Fraction"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "active_fraction",
        "freezing_fraction",
        "threshold_px_s",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Fraction of frames in which each individual is classified as active "
            "(speed > threshold) or frozen (speed ≤ threshold)."
        ),
        formula_plain=(
            "active[t,k] = (speed[t,k] > threshold); "
            "active_fraction = mean over non-NaN frames"
        ),
        inputs=["PreprocessedSession.kinematics.speed_px_s"],
        assumptions=[
            "Threshold can be supplied via cfg['threshold_px_s']; "
            "otherwise estimated as mean(speed) * 0.1 pooled across all animals"
        ],
        warnings=["Threshold choice strongly affects classification"],
        primary_reference=CACHAT_2010,
        supporting_references=[STEWART_2012, KALUEFF_2013, EGAN_2009],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="threshold_px_s",
            label="Activity threshold",
            kind="float",
            unit="px/s",
            help="Speed above which an animal counts as active. Auto-computed when unset.",
        ),
        MetricParameter(
            name="threshold_multiplier",
            label="Auto-threshold multiplier",
            kind="float",
            default=0.1,
            minimum=0.0,
            help=(
                "Only used when threshold_px_s is unset: the auto threshold "
                "is mean(speed) * threshold_multiplier."
            ),
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute activity / freezing fractions for every individual.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional dict.  If ``cfg['threshold_px_s']`` is present it is used
            as the activity threshold; otherwise a data-driven threshold is
            computed as ``mean(speed_px_s) * cfg['threshold_multiplier']``
            (default multiplier 0.1).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        speed = session.kinematics.speed_px_s  # (n_frames, n_animals)

        # Determine threshold
        if cfg is not None and "threshold_px_s" in cfg:
            threshold = float(cfg["threshold_px_s"])
        else:
            threshold_multiplier = 0.1
            if cfg is not None and "threshold_multiplier" in cfg:
                threshold_multiplier = float(cfg["threshold_multiplier"])
            all_valid = speed[~np.isnan(speed)]
            threshold = (
                float(np.mean(all_valid) * threshold_multiplier) if len(all_valid) > 0 else 0.0
            )

        n_animals = session.n_animals
        records: list[dict] = []
        for k in range(n_animals):
            s = speed[:, k]
            mask = ~np.isnan(s)
            if mask.sum() == 0:
                active_frac = np.nan
                freezing_frac = np.nan
            else:
                active_frac = float((s[mask] > threshold).mean())
                freezing_frac = 1.0 - active_frac

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "active_fraction": active_frac,
                    "freezing_fraction": freezing_frac,
                    "threshold_px_s": threshold,
                }
            )

        return pd.DataFrame(records)


# ── IL-5: Tortuosity ──────────────────────────────────────────────────────────


_EPSILON = 1e-6  # guard against zero displacement


class Tortuosity(Metric):
    """IL-5 — Path tortuosity (path length / straight-line distance) per individual."""

    id = "IL-5"
    name = "tortuosity"
    label = "Tortuosity"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = ["session_id", "metric_id", "individual_id", "tortuosity"]
    documentation = MetricDocumentation(
        definition=(
            "Ratio of total path length to the straight-line (Euclidean) distance "
            "between the first and last valid positions -- the reciprocal of the "
            "straightness index D/L, computed once over the whole track (no "
            "windowing). A value of 1 indicates a perfectly straight path; higher "
            "values indicate more tortuous paths. This is one of several "
            "tortuosity estimators in the literature (straightness index, "
            "sinuosity, fractal dimension); Benhamou 2004's central finding is "
            "that these are not interchangeable and are scale-dependent, so this "
            "citation supports the straightness-index form specifically, not "
            "tortuosity in general."
        ),
        formula_plain="path_length / max(||end - start||, ε), ε=1e-6",
        inputs=["PreprocessedSession.xy"],
        assumptions=["NaN frames are excluded when computing path length and end-points"],
        warnings=[
            "Very short paths or static animals give unreliable tortuosity",
            "Whole-track D/L is scale- and duration-dependent; comparing "
            "sessions of different length or sampling rate is not meaningful "
            "without accounting for this",
        ],
        primary_reference=BENHAMOU_2004,
        supporting_references=[KAREIVA_SHIGESADA_1983, BENHAMOU_2013],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute tortuosity for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row per individual with columns ``session_id``, ``metric_id``,
            ``individual_id``, and ``tortuosity``.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            traj = xy[:, k, :]  # (n_frames, 2)
            valid_mask = ~np.isnan(traj[:, 0])
            valid_traj = traj[valid_mask]  # only non-NaN rows

            if len(valid_traj) < 2:
                tortuosity = np.nan
            else:
                # Path length over non-NaN consecutive frame pairs
                diff = traj[1:] - traj[:-1]  # (n_frames-1, 2) — may contain NaN
                valid_diff = ~(np.isnan(diff[:, 0]) | np.isnan(diff[:, 1]))
                path_len = float(np.sqrt((diff[valid_diff] ** 2).sum(axis=1)).sum())

                # Straight-line distance between first and last valid positions
                start = valid_traj[0]
                end = valid_traj[-1]
                straight = float(np.sqrt(((end - start) ** 2).sum()))
                tortuosity = path_len / max(straight, _EPSILON)

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "tortuosity": tortuosity,
                }
            )

        return pd.DataFrame(records)


# ── IL-6: Acceleration ────────────────────────────────────────────────────────


class Acceleration(Metric):
    """IL-6 — Mean absolute, RMS, and max acceleration per individual."""

    id = "IL-6"
    name = "acceleration"
    label = "Acceleration (mean abs / RMS / max)"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_abs_accel_px_s2",
        "rms_accel_px_s2",
        "max_accel_px_s2",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean absolute acceleration, root-mean-square acceleration, and maximum "
            "absolute acceleration per individual over the session."
        ),
        formula_plain=(
            "mean_abs = mean(|a[t,k]|); "
            "rms = sqrt(mean(a[t,k]^2)); "
            "max = max(|a[t,k]|) — all NaN frames excluded"
        ),
        inputs=["PreprocessedSession.kinematics.accel_px_s2"],
        assumptions=["accel_px_s2 is pre-computed by the kinematics pipeline"],
        warnings=["Remaining jump artefacts inflate max acceleration"],
        citation="Standard kinematics",
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute acceleration statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        accel = session.kinematics.accel_px_s2  # (n_frames, n_animals)
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            a = accel[:, k]
            valid = a[~np.isnan(a)]

            if len(valid) == 0:
                mean_abs = np.nan
                rms = np.nan
                max_abs = np.nan
            else:
                abs_valid = np.abs(valid)
                mean_abs = float(abs_valid.mean())
                rms = float(np.sqrt((valid**2).mean()))
                max_abs = float(abs_valid.max())

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "mean_abs_accel_px_s2": mean_abs,
                    "rms_accel_px_s2": rms,
                    "max_accel_px_s2": max_abs,
                }
            )

        return pd.DataFrame(records)


# ── IL-7: FreezingBouts ───────────────────────────────────────────────────────


def _true_run_lengths(mask: np.ndarray) -> list[int]:
    """Return the lengths of every contiguous run of ``True`` in a 1-D boolean array.

    A ``False`` entry — including one produced by excluding a NaN frame —
    always ends the current run; runs on either side of it are never
    silently merged together.
    """
    lengths: list[int] = []
    current = 0
    for val in mask:
        if val:
            current += 1
        else:
            if current > 0:
                lengths.append(current)
            current = 0
    if current > 0:
        lengths.append(current)
    return lengths


class FreezingBouts(Metric):
    """IL-7 — Freezing-bout count and duration statistics per individual."""

    id = "IL-7"
    name = "freezing_bouts"
    label = "Freezing-Bout Count & Duration"
    level = "individual"
    priority = "optional"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "freezing_bout_count",
        "mean_freezing_duration_s",
        "total_freezing_duration_s",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Number and duration of discrete freezing (immobility) bouts per "
            "individual.  A bout is a run of consecutive inactive frames "
            "(speed ≤ threshold, same threshold rule as IL-4) that is at "
            "least `min_bout_frames` frames long."
        ),
        formula_plain=(
            "inactive[t,k] = speed[t,k] <= threshold (NaN frames excluded); "
            "run-length encode inactive; keep runs >= min_bout_frames; "
            "freezing_bout_count = number of qualifying runs; "
            "total_freezing_duration_s = sum(qualifying run lengths) / fps; "
            "mean_freezing_duration_s = total_freezing_duration_s / freezing_bout_count"
        ),
        inputs=[
            "PreprocessedSession.kinematics.speed_px_s",
            "cfg['min_bout_frames'] (default 5)",
        ],
        assumptions=["Same as IL-4"],
        warnings=["Discards short pauses; min duration is study-specific"],
        primary_reference=CACHAT_2010,
        supporting_references=[SIBLY_1990],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="threshold_px_s",
            label="Freezing threshold",
            kind="float",
            unit="px/s",
            help=(
                "Speed at or below which an animal counts as inactive. "
                "Auto-computed from this session's own data when unset."
            ),
        ),
        MetricParameter(
            name="threshold_multiplier",
            label="Auto-threshold multiplier",
            kind="float",
            default=0.1,
            minimum=0.0,
            help=(
                "Only used when threshold_px_s is unset: the auto threshold is "
                "mean(speed) * threshold_multiplier. Same rule as IL-4, but set "
                "independently -- changing IL-4's does not change this one."
            ),
        ),
        MetricParameter(
            name="min_bout_frames",
            label="Minimum bout length",
            kind="int",
            default=5,
            minimum=1,
            unit="frames",
            help="Runs of consecutive inactive frames shorter than this are not a bout.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute freezing-bout statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional dict.  ``cfg['threshold_px_s']`` overrides the IL-4-style
            activity threshold (default: data-driven ``mean(speed) * 0.1``).
            ``cfg['min_bout_frames']`` overrides the minimum run length, in
            frames, required for a run of inactivity to count as a freezing
            bout (default 5).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        speed = session.kinematics.speed_px_s  # (n_frames, n_animals)

        # Threshold: the same rule as IL-4 Activity, including its
        # configurable multiplier. IL-7 used to hardcode 0.1 while
        # claiming parity, so raising IL-4's multiplier left
        # active_fraction and freezing_bout_count measured against
        # different thresholds in the same export, with nothing saying so.
        # The two are set independently -- one metric's config never
        # reaches another's cfg -- so both must be changed together.
        if cfg is not None and "threshold_px_s" in cfg:
            threshold = float(cfg["threshold_px_s"])
        else:
            threshold_multiplier = 0.1
            if cfg is not None and "threshold_multiplier" in cfg:
                threshold_multiplier = float(cfg["threshold_multiplier"])
            all_valid = speed[~np.isnan(speed)]
            threshold = (
                float(np.mean(all_valid) * threshold_multiplier) if len(all_valid) > 0 else 0.0
            )

        min_bout_frames = 5
        if cfg is not None and "min_bout_frames" in cfg:
            min_bout_frames = int(cfg["min_bout_frames"])

        fps = session.fps
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            s = speed[:, k]
            # NaN frames count as neither active nor inactive: excluding them
            # here also means they break, rather than merge, adjacent runs.
            inactive = (s <= threshold) & ~np.isnan(s)

            run_lengths = _true_run_lengths(inactive)
            qualifying = [n for n in run_lengths if n >= min_bout_frames]

            bout_count = len(qualifying)
            if bout_count > 0:
                total_duration = float(sum(qualifying) / fps)
                mean_duration = float(total_duration / bout_count)
            else:
                total_duration = 0.0
                mean_duration = 0.0

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "freezing_bout_count": bout_count,
                    "mean_freezing_duration_s": mean_duration,
                    "total_freezing_duration_s": total_duration,
                }
            )

        return pd.DataFrame(records)


# ── IL-8: TurnRate ────────────────────────────────────────────────────────────


class TurnRate(Metric):
    """IL-8 — Mean and median turn rate (heading change) per individual."""

    id = "IL-8"
    name = "turn_rate"
    label = "Turn Rate (Heading Change)"
    level = "individual"
    priority = "advanced"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_turn_rate_rad_per_s",
        "median_turn_rate_rad_per_s",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean and median rate of heading change per individual, computed "
            "from frame-to-frame heading vectors."
        ),
        formula_plain=(
            "theta[t,k] = heading_rad[t,k] = atan2(dy, dx) of the displacement "
            "vector; dtheta = wrap(theta[t+1,k] - theta[t,k]) with "
            "wrap(x) = atan2(sin(x), cos(x)); "
            "turn_rate = mean(|dtheta|) * fps (median computed analogously)"
        ),
        inputs=["PreprocessedSession.kinematics.heading_rad"],
        assumptions=["Heading is well-defined (i.e. speed > small ε)"],
        warnings=[
            "Stationary frames produce undefined heading; these are skipped",
            "Reports only turn RATE (magnitude), discarding direction -- see "
            "IL-11 for a directional / circular-statistics treatment that "
            "also reveals left/right bias",
        ],
        primary_reference=KAREIVA_SHIGESADA_1983,
        supporting_references=[MWAFFO_2015, MARQUES_2018],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute turn-rate statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row per individual.
        """
        heading = session.kinematics.heading_rad  # (n_frames, n_animals)
        fps = session.fps
        n_animals = session.n_animals

        records: list[dict] = []
        for k in range(n_animals):
            theta = heading[:, k]
            theta_t = theta[:-1]
            theta_t1 = theta[1:]
            valid = ~(np.isnan(theta_t) | np.isnan(theta_t1))

            if valid.sum() == 0:
                mean_rate = np.nan
                median_rate = np.nan
            else:
                dtheta = theta_t1[valid] - theta_t[valid]
                # Robust wrap into (-pi, pi]; deliberately not a naive modulo.
                wrapped = np.arctan2(np.sin(dtheta), np.cos(dtheta))
                turn_rates = np.abs(wrapped) * fps
                mean_rate = float(turn_rates.mean())
                median_rate = float(np.median(turn_rates))

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "mean_turn_rate_rad_per_s": mean_rate,
                    "median_turn_rate_rad_per_s": median_rate,
                }
            )

        return pd.DataFrame(records)


# ── Shared: occupancy-grid histogram (IL-9, IL-10) ───────────────────────────


def _occupancy_grid_counts(
    traj: np.ndarray, bin_size_px: float, origin: tuple[float, float] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Frame counts per visited grid cell, for a single animal's non-NaN
    trajectory -- the shared input to IL-9 (home base) and IL-10
    (roaming entropy), so the grid is binned once per call site rather
    than twice per metric.

    Returns ``(counts, cell_ids)``, both aligned: ``counts[i]`` is the
    number of frames in cell ``cell_ids[i]``. IL-10 only needs
    ``counts``; IL-9 needs ``cell_ids`` too, to check whether the same
    physical cell is the mode across two different slices of the
    trajectory -- which requires both slices to be binned against the
    same *origin*, not each against its own minimum position (two
    slices binned independently would each start numbering from
    "wherever that slice happened to start", so index 0 in one slice
    is not the same cell as index 0 in the other).
    """
    valid = ~np.isnan(traj[:, 0])
    pts = traj[valid]
    if len(pts) == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.int64)

    if origin is None:
        origin = (float(pts[:, 0].min()), float(pts[:, 1].min()))

    x_bins = np.floor((pts[:, 0] - origin[0]) / bin_size_px).astype(np.int64)
    y_bins = np.floor((pts[:, 1] - origin[1]) / bin_size_px).astype(np.int64)
    # Large fixed stride, not (y_bins.max() + 2) -- that stride varies
    # per call, so the same (x_bin, y_bin) pair would collide with a
    # DIFFERENT cell_id in another call with a different y-extent,
    # defeating the whole point of comparing cell_ids across slices.
    cell_ids = x_bins * 1_000_000 + y_bins
    unique_ids, counts = np.unique(cell_ids, return_counts=True)
    return counts.astype(np.float64), unique_ids


_DEFAULT_OCCUPANCY_BIN_PX = 20.0

_OCCUPANCY_BIN_PARAM = MetricParameter(
    name="bin_size_px",
    label="Grid bin size",
    kind="float",
    default=_DEFAULT_OCCUPANCY_BIN_PX,
    minimum=1.0,
    unit="px",
    help=(
        "Side length of each occupancy-grid cell. Not calibration-derived -- "
        "Session.body_length_reliable is always False (see METRICS_SPEC.md "
        "§2.1), so this stays in pixels and should be tuned to the arena's "
        "own pixel scale rather than assumed comparable across sessions."
    ),
)


# ── IL-9: Home-base occupancy ─────────────────────────────────────────────────


class HomeBaseOccupancy(Metric):
    """IL-9 — Highest-occupancy grid locus and its share of total time."""

    id = "IL-9"
    name = "home_base_occupancy"
    label = "Home-Base Occupancy"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "home_base_time_pct",
        "home_base_stable",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Identifies each individual's highest-occupancy grid cell (its "
            "'home base') and reports the fraction of total tracked time "
            "spent there, plus whether the same cell remains the top cell "
            "when the session is split into first and second halves."
        ),
        formula_plain=(
            "Bin non-NaN xy into bin_size_px square cells; "
            "home_base_time_pct = max(cell counts) / total valid frames; "
            "home_base_stable = True iff the top cell of the first half of "
            "the session equals the top cell of the second half"
        ),
        inputs=["PreprocessedSession.xy", "cfg['bin_size_px'] (default 20.0)"],
        assumptions=["Zone-free: no drawn regions needed, unlike Z-1..Z-9"],
        warnings=[
            "Grid resolution (bin_size_px) directly sets what counts as "
            "'the same locus' -- too coarse merges genuinely separate "
            "loci, too fine fragments one real home base into many cells",
            "home_base_stable is a binary same-cell/different-cell flag, "
            "not a continuous stability score",
        ],
        primary_reference=EILAM_GOLANI_1989,
        supporting_references=[FREUND_2013],
    )
    parameters: ClassVar[list[MetricParameter]] = [_OCCUPANCY_BIN_PARAM]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        bin_size_px = _DEFAULT_OCCUPANCY_BIN_PX
        if cfg is not None and "bin_size_px" in cfg:
            bin_size_px = float(cfg["bin_size_px"])

        xy = session.xy
        n_animals = session.n_animals
        records: list[dict] = []

        for k in range(n_animals):
            traj = xy[:, k, :]
            counts, _cell_ids = _occupancy_grid_counts(traj, bin_size_px)
            if counts.size == 0:
                home_base_pct = np.nan
                stable = False
            else:
                home_base_pct = float(counts.max() / counts.sum())

                valid_traj = traj[~np.isnan(traj[:, 0])]
                origin = (float(valid_traj[:, 0].min()), float(valid_traj[:, 1].min()))
                half = traj.shape[0] // 2
                first_counts, first_ids = _occupancy_grid_counts(
                    traj[:half], bin_size_px, origin=origin
                )
                second_counts, second_ids = _occupancy_grid_counts(
                    traj[half:], bin_size_px, origin=origin
                )
                stable = bool(
                    first_counts.size
                    and second_counts.size
                    and first_ids[np.argmax(first_counts)] == second_ids[np.argmax(second_counts)]
                )

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "home_base_time_pct": home_base_pct,
                    "home_base_stable": stable,
                }
            )

        return pd.DataFrame(records)


# ── IL-10: Roaming entropy ────────────────────────────────────────────────────


class RoamingEntropy(Metric):
    """IL-10 — Shannon entropy of the spatial-occupancy distribution."""

    id = "IL-10"
    name = "roaming_entropy"
    label = "Roaming Entropy"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "roaming_entropy_bits",
        "roaming_entropy_normalised",
        "n_visited_cells",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Shannon entropy of each individual's normalised grid-occupancy "
            "distribution -- separates an animal circling one corner "
            "(low entropy) from one exploring the whole arena (high "
            "entropy), a distinction IL-1 (total distance) cannot make."
        ),
        formula_plain=(
            "Same occupancy grid as IL-9; p_i = count_i / total valid frames "
            "over visited cells i; roaming_entropy_bits = -sum(p_i * log2(p_i)); "
            "roaming_entropy_normalised = roaming_entropy_bits / log2(n_visited_cells) "
            "(1.0 = uniform use of every visited cell), NaN when n_visited_cells <= 1"
        ),
        inputs=["PreprocessedSession.xy", "cfg['bin_size_px'] (default 20.0, shared with IL-9)"],
        assumptions=["Zone-free: no drawn regions needed, unlike Z-1..Z-9"],
        warnings=[
            "Grid resolution (bin_size_px) directly affects the entropy "
            "value -- comparing entropies computed at different bin sizes "
            "is not meaningful",
            "roaming_entropy_normalised divides by log2 of the number of "
            "CELLS VISITED, not the number of cells the arena could hold -- "
            "it measures evenness of use among visited cells, not coverage "
            "of the arena",
        ],
        primary_reference=FREUND_2013,
        supporting_references=[EILAM_GOLANI_1989],
    )
    parameters: ClassVar[list[MetricParameter]] = [_OCCUPANCY_BIN_PARAM]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        bin_size_px = _DEFAULT_OCCUPANCY_BIN_PX
        if cfg is not None and "bin_size_px" in cfg:
            bin_size_px = float(cfg["bin_size_px"])

        xy = session.xy
        n_animals = session.n_animals
        records: list[dict] = []

        for k in range(n_animals):
            traj = xy[:, k, :]
            counts, _cell_ids = _occupancy_grid_counts(traj, bin_size_px)
            n_cells = int(counts.size)

            if n_cells == 0:
                entropy_bits = np.nan
                entropy_norm = np.nan
            else:
                p = counts / counts.sum()
                entropy_bits = float(-(p * np.log2(p)).sum())
                entropy_norm = float(entropy_bits / np.log2(n_cells)) if n_cells > 1 else np.nan

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "roaming_entropy_bits": entropy_bits,
                    "roaming_entropy_normalised": entropy_norm,
                    "n_visited_cells": n_cells,
                }
            )

        return pd.DataFrame(records)


# ── IL-11: Circular statistics of heading ────────────────────────────────────


class CircularHeadingStats(Metric):
    """IL-11 — Mean heading direction, concentration, Rayleigh test, and
    left/right turn bias per individual."""

    id = "IL-11"
    name = "circular_heading_stats"
    label = "Circular Statistics of Heading"
    level = "individual"
    priority = "advanced"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_heading_rad",
        "resultant_length",
        "rayleigh_p",
        "left_right_turn_bias",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Circular-statistics summary of each individual's heading: the "
            "mean direction, the concentration r (resultant length, 0 = "
            "uniformly distributed headings, 1 = all headings identical), a "
            "Rayleigh test p-value for non-uniformity, and a signed turn-bias "
            "score (mean sign of frame-to-frame heading change: positive = "
            "net left/counter-clockwise bias, negative = net right bias). "
            "IL-8 reports only turn RATE (magnitude), discarding direction; "
            "wall-following and rotational arena artefacts are only visible "
            "here. Also the correct statistical framework for any angular "
            "metric -- arithmetic means of angles are wrong (the mean of "
            "359° and 1° is 0°, not 180°)."
        ),
        formula_plain=(
            "C = mean(cos(heading)), S = mean(sin(heading)) over non-NaN "
            "headings; mean_heading_rad = atan2(S, C); "
            "resultant_length r = sqrt(C^2 + S^2); "
            "rayleigh_p via Zar's approximation: Z = n*r^2, "
            "p = exp(-Z) * (1 + (2Z - Z^2)/(4n) - "
            "(24Z - 132Z^2 + 76Z^3 - 9Z^4)/(288n^2)); "
            "left_right_turn_bias = mean(sign(wrap(theta[t+1] - theta[t])))"
        ),
        inputs=["PreprocessedSession.kinematics.heading_rad"],
        assumptions=[
            "Heading is well-defined (i.e. speed > small ε); undefined frames are excluded"
        ],
        warnings=[
            "Undefined (NaN) resultant_length/rayleigh_p when fewer than 2 "
            "valid headings",
            "rayleigh_p tests only for non-uniformity, not for any specific "
            "mean direction -- a small p-value says headings are not random, "
            "not that they point any particular way",
        ],
        primary_reference=BERENS_2009,
        supporting_references=[KAREIVA_SHIGESADA_1983],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        heading = session.kinematics.heading_rad
        n_animals = session.n_animals
        records: list[dict] = []

        for k in range(n_animals):
            theta = heading[:, k]
            valid = ~np.isnan(theta)
            theta_valid = theta[valid]
            n = theta_valid.size

            if n < 2:
                mean_heading = np.nan
                r = np.nan
                rayleigh_p = np.nan
            else:
                c_bar = float(np.mean(np.cos(theta_valid)))
                s_bar = float(np.mean(np.sin(theta_valid)))
                mean_heading = float(np.arctan2(s_bar, c_bar))
                r = float(np.sqrt(c_bar**2 + s_bar**2))

                z = n * r**2
                rayleigh_p = float(
                    np.exp(-z)
                    * (
                        1
                        + (2 * z - z**2) / (4 * n)
                        - (24 * z - 132 * z**2 + 76 * z**3 - 9 * z**4) / (288 * n**2)
                    )
                )

            diffs = theta[1:] - theta[:-1]
            wrapped = np.arctan2(np.sin(diffs), np.cos(diffs))
            wrapped_valid = wrapped[~np.isnan(wrapped)]
            turn_bias = float(np.mean(np.sign(wrapped_valid))) if wrapped_valid.size else np.nan

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "mean_heading_rad": mean_heading,
                    "resultant_length": r,
                    "rayleigh_p": rayleigh_p,
                    "left_right_turn_bias": turn_bias,
                }
            )

        return pd.DataFrame(records)


# ── IL-14: Wall-distance thigmotaxis ──────────────────────────────────────────


class WallDistanceThigmotaxis(Metric):
    """IL-14 — Distance to the nearest arena boundary, and wall-contact time.

    IL-3 measures distance from the arena CENTRE, which conflates wall
    proximity with corner geometry in any non-circular arena -- in a
    rectangular tank the centre distance is not monotonic in wall
    distance. This measures the actual thigmotaxis construct: distance
    to the nearest boundary.
    """

    id = "IL-14"
    name = "wall_distance_thigmotaxis"
    label = "Wall-Distance Thigmotaxis"
    level = "individual"
    priority = "primary"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "individual_id",
        "mean_wall_distance_px",
        "wall_contact_time_pct",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean Euclidean distance of each individual to the nearest point "
            "on the boundary of the arena it occupies, plus the fraction of "
            "time spent within wall_contact_threshold_px of that boundary."
        ),
        formula_plain=(
            "d[t,k] = distance from xy[t,k] to the boundary of the animal's "
            "own arena polygon (Shapely Polygon.exterior.distance); "
            "mean_wall_distance_px = mean over non-NaN frames; "
            "wall_contact_time_pct = fraction of non-NaN frames with "
            "d[t,k] < wall_contact_threshold_px"
        ),
        inputs=[
            "PreprocessedSession.xy",
            "cfg['arena_polygon_vertices_per_animal'] (derived per session)",
        ],
        assumptions=[
            "The arena boundary is derived per session from the project's own "
            "main-level zone geometry (same source as IL-3), or the video "
            "frame rectangle when no zones are defined; with several main "
            "arenas each animal is measured from the one it occupies",
            "Only additive ('+') polygons contribute; subtractive exclusion "
            "holes are not treated as walls for this metric",
        ],
        warnings=[
            "Requires shapely (an optional dependency; see pyproject.toml's "
            "'zones' extra) -- unlike every other IL-* metric",
            "wall_contact_threshold_px has no calibration-derived default "
            "for the same reason as D-10: Session.body_length_reliable is "
            "always False (METRICS_SPEC.md §2.1)",
        ],
        primary_reference=SIMON_1994,
        supporting_references=[SCHNORR_2012, MAXIMINO_2010],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="arena_polygon_vertices",
            label="Arena boundary",
            kind="float",
            derived=True,
            help="Derived from the project's main zone, or the video frame rectangle.",
        ),
        MetricParameter(
            name="arena_polygon_vertices_per_animal",
            label="Arena boundary per animal",
            kind="float",
            derived=True,
            help=(
                "With several main zones, each animal is measured from the "
                "arena it occupies rather than from one shared boundary."
            ),
        ),
        MetricParameter(
            name="wall_contact_threshold_px",
            label="Wall-contact threshold",
            kind="float",
            default=20.0,
            minimum=0.0,
            unit="px",
            help="Distance from the boundary counted as 'wall contact'.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        from shapely.geometry import Point, Polygon

        xy = session.xy
        n_animals = session.n_animals

        polygons_vertices = None
        if cfg is not None and cfg.get("arena_polygon_vertices_per_animal") is not None:
            polygons_vertices = cfg["arena_polygon_vertices_per_animal"]

        fallback_vertices = None
        if cfg is not None and cfg.get("arena_polygon_vertices") is not None:
            fallback_vertices = cfg["arena_polygon_vertices"]

        threshold = 20.0
        if cfg is not None and "wall_contact_threshold_px" in cfg:
            threshold = float(cfg["wall_contact_threshold_px"])

        def _polygon_for(k: int) -> Polygon | None:
            vertices = None
            if polygons_vertices is not None and k < len(polygons_vertices):
                vertices = polygons_vertices[k]
            elif fallback_vertices is not None:
                vertices = fallback_vertices
            if not vertices:
                return None
            poly = Polygon(vertices)
            return poly if poly.is_valid else poly.buffer(0)

        records: list[dict] = []
        for k in range(n_animals):
            polygon = _polygon_for(k)
            traj = xy[:, k, :]
            valid_mask = ~np.isnan(traj[:, 0])
            valid_traj = traj[valid_mask]

            if polygon is None or len(valid_traj) == 0:
                mean_dist = np.nan
                contact_pct = np.nan
            else:
                boundary = polygon.exterior
                dists = np.array(
                    [boundary.distance(Point(p[0], p[1])) for p in valid_traj],
                    dtype=np.float64,
                )
                mean_dist = float(dists.mean())
                contact_pct = float((dists < threshold).mean())

            records.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "individual_id": k,
                    "mean_wall_distance_px": mean_dist,
                    "wall_contact_time_pct": contact_pct,
                }
            )

        return pd.DataFrame(records)


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(PathLength)
_register(Speed)
_register(CentreDistance)
_register(Activity)
_register(Tortuosity)
_register(Acceleration)
_register(FreezingBouts)
_register(TurnRate)
_register(HomeBaseOccupancy)
_register(RoamingEntropy)
_register(CircularHeadingStats)
_register(WallDistanceThigmotaxis)
