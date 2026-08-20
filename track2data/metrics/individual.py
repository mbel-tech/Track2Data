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
from track2data.metrics.base import Metric, MetricDocumentation

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
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean Euclidean distance of each individual from the arena centre over "
            "the session.  Optionally reports the fraction of time spent within the "
            "inner half of the arena (radius = arena_radius/2)."
        ),
        formula_plain=(
            "d[t,k] = ||xy[t,k] - centre||; "
            "mean_centre_distance_px = mean over non-NaN frames; "
            "time_in_centre_pct = fraction of non-NaN frames with d[t,k] < arena_radius/2"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=[
            "centre is taken from cfg['centre'] if provided, "
            "otherwise computed as the mean of all non-NaN positions"
        ],
        warnings=["arena_radius must be provided in cfg to compute time_in_centre_pct"],
        citation="Standard spatial analysis",
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute centre-distance statistics for every individual in *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict.  Keys:
            ``centre`` — [x, y] arena centre coordinates (pixels).
            ``arena_radius`` — arena radius in pixels; enables ``time_in_centre_pct``.

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

        records: list[dict] = []
        for k in range(n_animals):
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
                if arena_radius is not None:
                    row["time_in_centre_pct"] = np.nan
                records.append(row)
                continue

            diffs = valid_traj - centre  # (n_valid, 2)
            dists = np.sqrt((diffs**2).sum(axis=1))
            mean_dist = float(dists.mean())

            row = {
                "session_id": session.session_id,
                "metric_id": self.id,
                "individual_id": k,
                "mean_centre_distance_px": mean_dist,
            }

            if arena_radius is not None:
                inner_radius = arena_radius / 2.0
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
        citation="Standard ethology",
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute activity / freezing fractions for every individual.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional dict.  If ``cfg['threshold_px_s']`` is present it is used
            as the activity threshold; otherwise a data-driven threshold is
            computed as ``mean(speed_px_s) * 0.1``.

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
            # Mean BL-speed * 0.1, falling back to overall mean speed * 0.1
            all_valid = speed[~np.isnan(speed)]
            threshold = float(np.mean(all_valid) * 0.1) if len(all_valid) > 0 else 0.0

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
            "between the first and last valid positions.  A value of 1 indicates a "
            "perfectly straight path; higher values indicate more tortuous paths."
        ),
        formula_plain="path_length / max(||end - start||, ε), ε=1e-6",
        inputs=["PreprocessedSession.xy"],
        assumptions=["NaN frames are excluded when computing path length and end-points"],
        warnings=["Very short paths or static animals give unreliable tortuosity"],
        citation="Batschelet 1981; standard movement ecology",
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
        citation="Speed-threshold bout detection; e.g. Cachat et al. 2010",
    )

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

        # Threshold: identical rule to IL-4 Activity so the two stay consistent.
        if cfg is not None and "threshold_px_s" in cfg:
            threshold = float(cfg["threshold_px_s"])
        else:
            all_valid = speed[~np.isnan(speed)]
            threshold = float(np.mean(all_valid) * 0.1) if len(all_valid) > 0 else 0.0

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
        warnings=["Stationary frames produce undefined heading; these are skipped"],
        citation="Couzin et al. 2002",
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
