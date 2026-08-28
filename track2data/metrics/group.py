"""
Group-level metrics: GL-1, GL-3, GL-5, GL-7.

Each class implements :class:`track2data.metrics.base.Metric` and returns
a :class:`pandas.DataFrame` with at least the columns ``session_id`` and
``metric_id``.  Group metrics produce one row per session (no
``individual_id`` column).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, QhullError, cKDTree
from scipy.spatial.distance import pdist

from track2data.core.models import PreprocessedSession
from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter
from track2data.metrics.references import (
    BALLERINI_2008,
    BERNARDIN_STIEFELHAGEN_2008,
    CLARK_EVANS_1954,
    COUZIN_2002,
    DELCOURT_PONCIN_2012,
    KRAUSE_RUXTON_2002,
    MILLER_GERLAI_2007,
    MOHR_1947,
    PITCHER_1973,
    TUNSTROM_2013,
    VICSEK_1995,
)

# GL-6's two cohesion definitions. Kept beside the metric's own
# `choices` declaration so the schema the ⚙ dialog offers and the values
# compute() accepts cannot drift apart.
_COHESION_SOURCES = ("nnd", "iid")

# ── GL-1: NearestNeighbourDistance ────────────────────────────────────────────


class NearestNeighbourDistance(Metric):
    """GL-1 — Mean nearest-neighbour distance (NND) across the group."""

    id = "GL-1"
    name = "nearest_neighbour_distance"
    label = "Nearest-Neighbour Distance"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_nnd_px",
        "median_nnd_px",
        "n_skipped_frames",
    ]
    documentation = MetricDocumentation(
        definition=(
            "For each frame the nearest-neighbour distance is computed per animal "
            "(minimum Euclidean distance to any other animal) using a kd-tree. "
            "The group NND per frame is the mean across animals.  The metric "
            "reports the mean and median of frame-level group NNDs."
        ),
        formula_plain=(
            "per-frame per-animal: min_j≠k ||xy[t,k] - xy[t,j]||; "
            "group_nnd[t] = mean_k; metric = mean/median over frames"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["Frames where any animal has NaN position are skipped"],
        warnings=["Skipped-frame count is reported; high counts may bias the metric"],
        # Not Couzin et al. 2002 -- that citation and its DOI were
        # copy-pasted here from GL-3/GL-8, which genuinely do trace to
        # it. Couzin 2002 is about collective memory and spatial
        # sorting. NND as a statistic originates with Clark & Evans;
        # Pitcher is its application to fish schooling specifically.
        primary_reference=CLARK_EVANS_1954,
        supporting_references=[PITCHER_1973, KRAUSE_RUXTON_2002],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute nearest-neighbour distance statistics for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row with group NND statistics.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames, n_animals = xy.shape[0], xy.shape[1]

        if n_animals < 2:
            return pd.DataFrame(
                [
                    {
                        "session_id": session.session_id,
                        "metric_id": self.id,
                        "mean_nnd_px": np.nan,
                        "median_nnd_px": np.nan,
                        "n_skipped_frames": n_frames,
                    }
                ]
            )

        frame_nnds: list[float] = []
        n_skipped = 0

        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            # Skip frame if any animal has NaN
            if np.isnan(positions).any():
                n_skipped += 1
                continue

            tree = cKDTree(positions)
            # k=2: nearest is self (distance 0), second nearest is the actual NN
            dists, _ = tree.query(positions, k=2)
            nnd_per_animal = dists[:, 1]  # distance to nearest *other* animal
            frame_nnds.append(float(nnd_per_animal.mean()))

        if len(frame_nnds) == 0:
            mean_nnd = np.nan
            median_nnd = np.nan
        else:
            arr = np.array(frame_nnds)
            mean_nnd = float(arr.mean())
            median_nnd = float(np.median(arr))

        row: dict = {
            "session_id": session.session_id,
            "metric_id": self.id,
            "mean_nnd_px": mean_nnd,
            "median_nnd_px": median_nnd,
            "n_skipped_frames": n_skipped,
        }

        if session.px_per_cm is not None:
            row["mean_nnd_cm"] = mean_nnd / session.px_per_cm if not np.isnan(mean_nnd) else np.nan
            if session.body_length_cm is not None:
                mean_bl_cm = float(np.nanmean(session.body_length_cm))
                cm_val = row["mean_nnd_cm"]
                row["mean_nnd_bl"] = (
                    cm_val / mean_bl_cm if (not np.isnan(cm_val) and mean_bl_cm != 0) else np.nan
                )
            else:
                row["mean_nnd_bl"] = np.nan
        else:
            row["mean_nnd_cm"] = np.nan
            row["mean_nnd_bl"] = np.nan

        return pd.DataFrame([row])


# ── GL-3: Polarisation ────────────────────────────────────────────────────────


class Polarisation(Metric):
    """GL-3 — Group polarisation (alignment of heading vectors)."""

    id = "GL-3"
    name = "polarisation"
    label = "Polarisation"
    level = "group"
    priority = "primary"
    # Polarisation is built from heading vectors, and a heading is
    # arctan2 of xy[t+1] - xy[t] at a *fixed row index*
    # (preprocess/kinematics.py). On an identity-free session that
    # difference is between two unrelated animals, so the alignment it
    # reports is noise. METRICS_SPEC.md section 4.5 has always listed
    # GL-3 as not identity-free derivable; the flag now says so too.
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_polarisation",
        "median_polarisation",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Polarisation measures the alignment of individual heading vectors. "
            "A value of 1 means all individuals move in exactly the same direction; "
            "0 means perfectly random headings."
        ),
        formula_plain=(
            "Φ[t] = ||(1/N) Σ_k ê_k[t]|| "
            "where ê_k is the unit heading vector of moving animal k; "
            "stationary animals (speed ≈ 0) are excluded per frame"
        ),
        inputs=[
            "PreprocessedSession.kinematics.heading_rad",
            "PreprocessedSession.kinematics.speed_px_s",
        ],
        assumptions=[
            "Animals with speed ≈ 0 (below 1e-6 px/s) are excluded from each frame",
            "Frames with fewer than 2 valid headings are skipped",
        ],
        warnings=["Results may be biased when many animals are stationary"],
        # The polar order parameter |mean unit heading| is Vicsek's; Couzin
        # 2002 applies it (and the rotational-order parameter, GL-8) to
        # animal-group simulation specifically.
        primary_reference=VICSEK_1995,
        supporting_references=[COUZIN_2002, TUNSTROM_2013],
    )

    _STATIONARY_THRESHOLD = 1e-6  # px/s — animals slower than this are excluded
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="stationary_threshold_px_s",
            label="Stationary threshold",
            kind="float",
            default=1e-6,
            minimum=0.0,
            unit="px/s",
            help="Animals slower than this are excluded from each frame's heading average.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute group polarisation for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional dict.  ``cfg['stationary_threshold_px_s']`` overrides the
            default threshold of 1e-6 px/s for classifying animals as stationary.

        Returns
        -------
        pd.DataFrame
            One row with mean and median polarisation.
        """
        heading = session.kinematics.heading_rad  # (n_frames, n_animals)
        speed = session.kinematics.speed_px_s    # (n_frames, n_animals)

        stationary_thr: float = self._STATIONARY_THRESHOLD
        if cfg is not None:
            stationary_thr = float(cfg.get("stationary_threshold_px_s", stationary_thr))

        n_frames = heading.shape[0]
        frame_polars: list[float] = []

        for t in range(n_frames):
            h_t = heading[t]  # (n_animals,)
            s_t = speed[t]    # (n_animals,)

            # Exclude stationary animals and animals with NaN heading/speed
            moving = (
                (~np.isnan(h_t))
                & (~np.isnan(s_t))
                & (s_t > stationary_thr)
            )
            if moving.sum() < 2:
                continue  # skip frame

            # Unit heading vectors
            cos_h = np.cos(h_t[moving])
            sin_h = np.sin(h_t[moving])
            mean_cos = cos_h.mean()
            mean_sin = sin_h.mean()
            pol = float(np.sqrt(mean_cos**2 + mean_sin**2))
            frame_polars.append(pol)

        if len(frame_polars) == 0:
            mean_pol = np.nan
            median_pol = np.nan
        else:
            arr = np.array(frame_polars)
            mean_pol = float(arr.mean())
            median_pol = float(np.median(arr))

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_polarisation": mean_pol,
                    "median_polarisation": median_pol,
                }
            ]
        )


# ── GL-5: CentroidSpeed ───────────────────────────────────────────────────────


class CentroidSpeed(Metric):
    """GL-5 — Speed of the group centroid over time."""

    id = "GL-5"
    name = "centroid_speed"
    label = "Centroid Speed"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = ["session_id", "metric_id", "mean_centroid_speed_px_s"]
    documentation = MetricDocumentation(
        definition=(
            "The group centroid is computed each frame as the mean position of all "
            "animals with valid (non-NaN) positions.  Centroid speed is the frame-to-"
            "frame displacement of the centroid multiplied by fps."
        ),
        formula_plain=(
            "C[t] = mean(xy[t, valid, :]); "
            "centroid_speed[t] = ||C[t+1] - C[t]|| * fps"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["NaN animal positions are excluded from the centroid computation"],
        warnings=[
            "Highly variable valid-animal counts across frames may bias the metric",
            "Centroid speed is NOT the mean of individual speeds -- it can be "
            "near zero even while every animal moves fast, whenever the group "
            "mills or the animals' velocities cancel",
        ],
        citation="Standard kinematics applied to the group centroid; no single originating work",
        supporting_references=[TUNSTROM_2013],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute centroid speed for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row with mean (and optionally cm/s) centroid speed.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        fps = session.fps
        n_frames = session.n_frames

        # Compute centroid per frame, ignoring NaN animals
        centroid = np.full((n_frames, 2), np.nan)
        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            valid = ~np.isnan(positions[:, 0])
            if valid.sum() > 0:
                centroid[t] = positions[valid].mean(axis=0)

        # Frame-to-frame centroid speed
        d_centroid = centroid[1:] - centroid[:-1]  # (n_frames-1, 2)
        valid_pairs = ~(np.isnan(d_centroid[:, 0]) | np.isnan(d_centroid[:, 1]))
        speeds = np.sqrt((d_centroid[valid_pairs] ** 2).sum(axis=1)) * fps

        mean_speed_px_s = float(speeds.mean()) if len(speeds) > 0 else np.nan

        row: dict = {
            "session_id": session.session_id,
            "metric_id": self.id,
            "mean_centroid_speed_px_s": mean_speed_px_s,
        }

        if session.px_per_cm is not None:
            row["mean_centroid_speed_cm_s"] = (
                mean_speed_px_s / session.px_per_cm
                if not np.isnan(mean_speed_px_s)
                else np.nan
            )
        else:
            row["mean_centroid_speed_cm_s"] = np.nan

        return pd.DataFrame([row])


# ── GL-7: NNMatchedSpeed ──────────────────────────────────────────────────────


class NNMatchedSpeed(Metric):
    """GL-7 — Identity-free speed via greedy nearest-neighbour assignment."""

    id = "GL-7"
    name = "nn_matched_speed"
    label = "NN-Matched Speed"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = ["session_id", "metric_id", "mean_matched_speed_px_s"]
    documentation = MetricDocumentation(
        definition=(
            "An identity-free estimate of individual speed.  For each consecutive "
            "frame pair, a greedy nearest-neighbour assignment matches detections "
            "in frame *t* to detections in frame *t+1*.  The mean matched distance "
            "multiplied by fps yields an estimate of typical individual speed."
        ),
        formula_plain=(
            "For each (t, t+1) pair: "
            "greedily match each detection to nearest unmatched detection; "
            "matched_speed[t] = mean(matched_distances) * fps; "
            "metric = mean over frame pairs"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=[
            "Frame pairs where any animal has NaN position are skipped",
            "Greedy assignment; not globally optimal",
        ],
        warnings=[
            "Greedy assignment may be biased in crowded scenes",
            "The implementation is greedy nearest-neighbour matching, one "
            "pass, NOT a globally optimal (Hungarian/assignment-problem) "
            "solve -- the citation below is for CLEAR MOT's evaluation "
            "framework, matched to what this metric actually computes.",
        ],
        primary_reference=BERNARDIN_STIEFELHAGEN_2008,
    )

    @staticmethod
    def _greedy_nn_match(pts_a: np.ndarray, pts_b: np.ndarray) -> float:
        """Compute mean matched distance via greedy NN assignment.

        Parameters
        ----------
        pts_a, pts_b:
            Arrays of shape (n, 2) representing detections in frame *t* and
            frame *t+1* respectively.

        Returns
        -------
        float
            Mean matched Euclidean distance.
        """
        n = pts_a.shape[0]
        unmatched = list(range(n))
        total_dist = 0.0
        for i in range(n):
            a = pts_a[i]
            best_j = None
            best_d = np.inf
            for j in unmatched:
                d = float(np.sqrt(((a - pts_b[j]) ** 2).sum()))
                if d < best_d:
                    best_d = d
                    best_j = j
            if best_j is not None:
                total_dist += best_d
                unmatched.remove(best_j)
        return total_dist / n if n > 0 else 0.0

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute NN-matched speed for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused for this metric).

        Returns
        -------
        pd.DataFrame
            One row with mean (and optionally cm/s) matched speed.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        fps = session.fps
        n_frames = session.n_frames

        matched_speeds: list[float] = []

        for t in range(n_frames - 1):
            pts_a = xy[t]    # (n_animals, 2)
            pts_b = xy[t + 1]  # (n_animals, 2)

            # Skip if any animal has NaN in either frame
            if np.isnan(pts_a).any() or np.isnan(pts_b).any():
                continue

            mean_dist = self._greedy_nn_match(pts_a, pts_b)
            matched_speeds.append(mean_dist * fps)

        mean_speed_px_s = float(np.mean(matched_speeds)) if len(matched_speeds) > 0 else np.nan

        row: dict = {
            "session_id": session.session_id,
            "metric_id": self.id,
            "mean_matched_speed_px_s": mean_speed_px_s,
        }

        if session.px_per_cm is not None:
            row["mean_matched_speed_cm_s"] = (
                mean_speed_px_s / session.px_per_cm
                if not np.isnan(mean_speed_px_s)
                else np.nan
            )
        else:
            row["mean_matched_speed_cm_s"] = np.nan

        return pd.DataFrame([row])


# ── GL-2: InterIndividualDistance ─────────────────────────────────────────────


class InterIndividualDistance(Metric):
    """GL-2 — Mean inter-individual distance (IID) per session."""

    id = "GL-2"
    name = "inter_individual_distance"
    label = "Inter-Individual Distance"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_iid_px",
        "median_iid_px",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean of all pairwise Euclidean distances between individuals per frame, "
            "averaged over all frames.  Computed using scipy.spatial.distance.pdist."
        ),
        formula_plain=(
            "per-frame: iid[t] = mean(pdist(xy[t, :])); "
            "metric = mean/median over frames"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["Frames where any animal has NaN position are skipped"],
        warnings=["Skipped NaN frames may bias the metric"],
        primary_reference=KRAUSE_RUXTON_2002,
        supporting_references=[MILLER_GERLAI_2007, DELCOURT_PONCIN_2012],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute IID statistics for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused).

        Returns
        -------
        pd.DataFrame
            One row with mean and median IID.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames, n_animals = xy.shape[0], xy.shape[1]

        if n_animals < 2:
            return pd.DataFrame(
                [
                    {
                        "session_id": session.session_id,
                        "metric_id": self.id,
                        "mean_iid_px": np.nan,
                        "median_iid_px": np.nan,
                    }
                ]
            )

        frame_iids: list[float] = []
        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            if np.isnan(positions).any():
                continue
            dists = pdist(positions)
            if len(dists) > 0:
                frame_iids.append(float(dists.mean()))

        if len(frame_iids) == 0:
            mean_iid = np.nan
            median_iid = np.nan
        else:
            arr = np.array(frame_iids)
            mean_iid = float(arr.mean())
            median_iid = float(np.median(arr))

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_iid_px": mean_iid,
                    "median_iid_px": median_iid,
                }
            ]
        )


# ── GL-4: ConvexHullArea ──────────────────────────────────────────────────────


class ConvexHullArea(Metric):
    """GL-4 — Mean convex hull area of group positions per frame."""

    id = "GL-4"
    name = "convex_hull_area"
    label = "Convex Hull Area"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_hull_area_px2",
        "median_hull_area_px2",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean convex hull area of all animal positions per frame, averaged over "
            "all valid frames.  Requires N≥3 animals."
        ),
        formula_plain=(
            "per-frame: hull_area[t] = ConvexHull(xy[t, :]).volume; "
            "metric = mean/median over frames"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=[
            "Frames where any animal has NaN position are skipped",
            "Requires ≥3 animals for a valid convex hull",
        ],
        warnings=["Returns NaN when fewer than 3 animals are present"],
        # An earlier draft of METRICS_SPEC.md attributed this to Buhl et
        # al. 2006 (marching locusts); that paper characterises order via
        # alignment and density, not convex-hull area, so the
        # attribution was dropped rather than carried into the code.
        # Not reference-less after all: the minimum convex polygon (of
        # which this per-frame hull is the 2-D case) originates with
        # Mohr 1947.
        primary_reference=MOHR_1947,
        supporting_references=[KRAUSE_RUXTON_2002],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute convex hull area statistics for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused).

        Returns
        -------
        pd.DataFrame
            One row with mean and median hull area.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames, n_animals = xy.shape[0], xy.shape[1]

        if n_animals < 3:
            return pd.DataFrame(
                [
                    {
                        "session_id": session.session_id,
                        "metric_id": self.id,
                        "mean_hull_area_px2": np.nan,
                        "median_hull_area_px2": np.nan,
                    }
                ]
            )

        frame_areas: list[float] = []
        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            if np.isnan(positions).any():
                continue
            try:
                hull = ConvexHull(positions)
                frame_areas.append(float(hull.volume))  # hull.volume is area in 2D
            except QhullError:
                # Degenerate (all collinear)
                continue

        if len(frame_areas) == 0:
            mean_area = np.nan
            median_area = np.nan
        else:
            arr = np.array(frame_areas)
            mean_area = float(arr.mean())
            median_area = float(np.median(arr))

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_hull_area_px2": mean_area,
                    "median_hull_area_px2": median_area,
                }
            ]
        )


# ── GL-6: GroupCohesion ───────────────────────────────────────────────────────


class GroupCohesion(Metric):
    """GL-6 — Group cohesion = 1 / mean_NND."""

    id = "GL-6"
    name = "group_cohesion"
    label = "Group Cohesion"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "cohesion_index",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Group cohesion defined as the reciprocal of the mean nearest-neighbour "
            "distance.  Higher values indicate a more cohesive (closer) group."
        ),
        formula_plain=(
            "cohesion_index = 1 / mean_NND (cohesion_source='nnd', default), "
            "or 1 / mean_IID (cohesion_source='iid') -- see METRICS_SPEC.md §8 "
            "open question 3"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=[
            "cohesion_source='nnd' (default) uses the same NND computation as GL-1; "
            "cohesion_source='iid' uses the same mean-pairwise-distance computation as GL-2"
        ],
        warnings=["Undefined (NaN) when the mean distance = 0 or when fewer than 2 animals"],
        primary_reference=KRAUSE_RUXTON_2002,
        supporting_references=[DELCOURT_PONCIN_2012],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="cohesion_source",
            label="Cohesion source",
            kind="choice",
            default="nnd",
            choices=list(_COHESION_SOURCES),
            help=(
                "Which pairwise-distance measure cohesion is derived from: "
                "nearest-neighbour distance (nnd) or mean inter-individual "
                "distance (iid)."
            ),
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute group cohesion for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict. ``cfg['cohesion_source']`` selects
            ``'nnd'`` (default, same computation as GL-1) or ``'iid'`` (same
            computation as GL-2).

        Returns
        -------
        pd.DataFrame
            One row with cohesion_index.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames, n_animals = xy.shape[0], xy.shape[1]

        cohesion_source = "nnd"
        if cfg is not None and "cohesion_source" in cfg:
            cohesion_source = cfg["cohesion_source"]
            # Validate rather than falling through to the nnd branch: a
            # typo ("IID", "iid ") would otherwise export NND numbers
            # while the project file records the user choosing IID --
            # a wrong result wearing the appearance of a correct one.
            if cohesion_source not in _COHESION_SOURCES:
                raise ValueError(
                    f"cohesion_source must be one of "
                    f"{', '.join(sorted(_COHESION_SOURCES))}; got {cohesion_source!r}"
                )

        if n_animals < 2:
            return pd.DataFrame(
                [
                    {
                        "session_id": session.session_id,
                        "metric_id": self.id,
                        "cohesion_index": np.nan,
                    }
                ]
            )

        frame_dists: list[float] = []
        for t in range(n_frames):
            positions = xy[t]
            if np.isnan(positions).any():
                continue
            if cohesion_source == "iid":
                frame_dists.append(float(pdist(positions).mean()))
            else:
                tree = cKDTree(positions)
                dists, _ = tree.query(positions, k=2)
                frame_dists.append(float(dists[:, 1].mean()))

        if len(frame_dists) == 0:
            cohesion = np.nan
        else:
            mean_dist = float(np.mean(frame_dists))
            cohesion = 1.0 / mean_dist if mean_dist != 0 else np.nan

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "cohesion_index": cohesion,
                }
            ]
        )


# ── GL-8: RotationalOrder ─────────────────────────────────────────────────────


class RotationalOrder(Metric):
    """GL-8 — Rotational order parameter (milling vs. polarised motion)."""

    id = "GL-8"
    name = "rotational_order"
    label = "Rotational Order"
    level = "group"
    priority = "optional"
    # Rotational order needs the same per-individual headings as GL-3, so
    # it inherits GL-3's identity dependence. Also listed as not
    # identity-free derivable in METRICS_SPEC.md section 4.5.
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_rotational_order",
        "median_rotational_order",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Rotational order (milling) measures how strongly the group circles "
            "its own centroid rather than translating in a common direction.  A "
            "value of 1 means every individual moves exactly tangentially around "
            "the group centroid in the same rotational sense (milling); 0 means "
            "no net rotation.  It complements polarisation (GL-3): milling shows "
            "high M and low polarisation, coordinated translation shows the "
            "opposite."
        ),
        formula_plain=(
            "M[t] = ||(1/N) Σ_k r̂_k(t) x ê_k(t)||, where r̂_k = (xy[t,k] - C[t]) "
            "/ ||xy[t,k] - C[t]|| is the unit vector from the group centroid to "
            "animal k, ê_k is animal k's unit heading vector, and x is the "
            "scalar 2-D cross product r̂_k.x·ê_k.y - r̂_k.y·ê_k.x; stationary "
            "animals (speed ≈ 0) and animals exactly at the centroid are "
            "excluded per frame"
        ),
        inputs=[
            "PreprocessedSession.xy",
            "PreprocessedSession.kinematics.heading_rad",
            "PreprocessedSession.kinematics.speed_px_s",
        ],
        assumptions=[
            "The group centroid C[t] is the mean position of all animals with a "
            "valid (non-NaN) position in frame t, regardless of speed",
            "Animals with speed ≈ 0 (below 1e-6 px/s) are excluded from each "
            "frame",
            "Animals exactly at the centroid (undefined radial direction) are "
            "excluded from each frame",
            "Frames with fewer than 2 included animals are skipped",
        ],
        warnings=[
            "Same heading-stability caveat as GL-3: results may be biased when "
            "many animals are stationary or headings are noisy"
        ],
        # Couzin 2002 defines this angular-momentum order parameter;
        # Tunstrøm 2013 supplies the empirical milling-state thresholds
        # needed to interpret the value, as a supporting reference rather
        # than folded into one compound citation string.
        primary_reference=COUZIN_2002,
        supporting_references=[TUNSTROM_2013],
    )

    _STATIONARY_THRESHOLD = 1e-6  # px/s — animals slower than this are excluded
    _ZERO_RADIUS_EPS = 1e-9  # px — animals this close to the centroid are excluded
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="stationary_threshold_px_s",
            label="Stationary threshold",
            kind="float",
            default=1e-6,
            minimum=0.0,
            unit="px/s",
            help="Animals slower than this are excluded from each frame's rotation term.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute group rotational order (milling) for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional dict.  ``cfg['stationary_threshold_px_s']`` overrides the
            default threshold of 1e-6 px/s for classifying animals as stationary.

        Returns
        -------
        pd.DataFrame
            One row with mean and median rotational order.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        heading = session.kinematics.heading_rad  # (n_frames, n_animals)
        speed = session.kinematics.speed_px_s  # (n_frames, n_animals)

        stationary_thr: float = self._STATIONARY_THRESHOLD
        if cfg is not None:
            stationary_thr = float(cfg.get("stationary_threshold_px_s", stationary_thr))

        n_frames = xy.shape[0]
        frame_rotational: list[float] = []

        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            h_t = heading[t]  # (n_animals,)
            s_t = speed[t]  # (n_animals,)

            valid_pos = ~np.isnan(positions[:, 0]) & ~np.isnan(positions[:, 1])
            if valid_pos.sum() == 0:
                continue  # no centroid possible this frame

            centroid = positions[valid_pos].mean(axis=0)

            # Exclude stationary animals and animals with NaN heading/speed/position
            moving = (
                valid_pos
                & (~np.isnan(h_t))
                & (~np.isnan(s_t))
                & (s_t > stationary_thr)
            )
            idx = np.where(moving)[0]
            if idx.size < 2:
                continue  # skip frame

            r = positions[idx] - centroid  # (k, 2)
            r_norm = np.sqrt((r**2).sum(axis=1))
            nonzero = r_norm > self._ZERO_RADIUS_EPS
            if nonzero.sum() < 2:
                continue  # skip frame

            idx = idx[nonzero]
            r_hat = r[nonzero] / r_norm[nonzero, None]
            e_hat = np.column_stack((np.cos(h_t[idx]), np.sin(h_t[idx])))

            cross = r_hat[:, 0] * e_hat[:, 1] - r_hat[:, 1] * e_hat[:, 0]
            m_t = abs(float(cross.mean()))
            frame_rotational.append(m_t)

        if len(frame_rotational) == 0:
            mean_rot = np.nan
            median_rot = np.nan
        else:
            arr = np.array(frame_rotational)
            mean_rot = float(arr.mean())
            median_rot = float(np.median(arr))

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_rotational_order": mean_rot,
                    "median_rotational_order": median_rot,
                }
            ]
        )


# ── GL-9: GroupCentroidPosition ───────────────────────────────────────────────


class GroupCentroidPosition(Metric):
    """GL-9 — Mean group centroid position (x, y) over the session."""

    id = "GL-9"
    name = "group_centroid_position"
    label = "Group Centroid Position"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_centroid_x_px",
        "mean_centroid_y_px",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Time-averaged group centroid position.  The centroid per frame is the "
            "mean (x, y) of all animals with valid positions; the metric reports the "
            "mean across frames."
        ),
        formula_plain=(
            "C[t] = mean(xy[t, valid, :]); "
            "metric = mean over frames of C[t]"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["NaN animal positions are excluded per frame"],
        warnings=["Frames where all animals are NaN are skipped"],
        citation=(
            "Standard kinematics (arithmetic mean position); no single "
            "originating work"
        ),
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute mean group centroid position for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused).

        Returns
        -------
        pd.DataFrame
            One row with mean centroid coordinates.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames = xy.shape[0]

        centroids: list[np.ndarray] = []
        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            valid = ~np.isnan(positions[:, 0])
            if valid.sum() > 0:
                centroids.append(positions[valid].mean(axis=0))

        if len(centroids) == 0:
            mean_x = np.nan
            mean_y = np.nan
        else:
            arr = np.array(centroids)  # (n_valid_frames, 2)
            mean_x = float(arr[:, 0].mean())
            mean_y = float(arr[:, 1].mean())

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_centroid_x_px": mean_x,
                    "mean_centroid_y_px": mean_y,
                }
            ]
        )


# ── GL-10: GroupSpread ────────────────────────────────────────────────────────


class GroupSpread(Metric):
    """GL-10 — Group spread: mean RMS distance from centroid per frame."""

    id = "GL-10"
    name = "group_spread"
    label = "Group Spread"
    level = "group"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_group_spread_px",
    ]
    documentation = MetricDocumentation(
        definition=(
            "RMS distance of all animals from the group centroid per frame, averaged "
            "over all valid frames."
        ),
        formula_plain=(
            "spread[t] = sqrt(mean_k(||xy[t,k] - C[t]||^2)); "
            "metric = mean over frames"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["Frames where any animal has NaN position are skipped"],
        warnings=[
            "Skipped frames may bias the metric",
            "This is RMS distance to the centroid specifically -- neither SD "
            "of positions nor mean pairwise distance, which are different "
            "'spread' statistics with different values",
        ],
        citation=(
            "Standard spatial-dispersion measure; complements GL-4 "
            "(convex-hull area). No single originating work"
        ),
        supporting_references=[CLARK_EVANS_1954],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute group spread for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused).

        Returns
        -------
        pd.DataFrame
            One row with mean group spread.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames = xy.shape[0]

        frame_spreads: list[float] = []
        for t in range(n_frames):
            positions = xy[t]  # (n_animals, 2)
            if np.isnan(positions).any():
                continue
            centroid = positions.mean(axis=0)
            diffs = positions - centroid
            dist_sq = (diffs**2).sum(axis=1)
            rms_dist = float(np.sqrt(dist_sq.mean()))
            frame_spreads.append(rms_dist)

        mean_spread = np.nan if len(frame_spreads) == 0 else float(np.mean(frame_spreads))

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_group_spread_px": mean_spread,
                }
            ]
        )


# ── GL-11: Order-state classification ─────────────────────────────────────────


class OrderStateClassification(Metric):
    """GL-11 — Classifies each frame into polarised/milling/swarm using
    the polarisation (GL-3) x rotational-order (GL-8) plane.

    Both order parameters are already computed by GL-3 and GL-8, but
    reported there as independent time series. The 2-D state space is
    the established way to read them together and turns two continuous
    traces into an interpretable behavioural budget.
    """

    id = "GL-11"
    name = "order_state_classification"
    label = "Order-State Classification"
    level = "group"
    priority = "primary"
    # Order-state classification thresholds GL-3's polarisation against
    # GL-8's rotational order, so it is identity-dependent for both of
    # their reasons.
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "polarised_time_pct",
        "milling_time_pct",
        "swarm_time_pct",
        "n_classified_frames",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Joint classification of each frame into one of three collective "
            "states from the GL-3 (polarisation, Φ) x GL-8 (rotational order, "
            "M) plane: 'polarised' (Φ >= polarised_threshold), 'milling' "
            "(Φ < polarised_threshold and M >= milling_threshold), or 'swarm' "
            "(neither -- low order in both). Reports the time fraction spent "
            "in each state."
        ),
        formula_plain=(
            "Per frame: compute Φ[t] and M[t] exactly as GL-3/GL-8 do "
            "(same stationary_threshold_px_s); "
            "state[t] = 'polarised' if Φ[t] >= polarised_threshold, "
            "else 'milling' if M[t] >= milling_threshold, else 'swarm'; "
            "*_time_pct = fraction of classified frames in that state"
        ),
        inputs=[
            "PreprocessedSession.xy",
            "PreprocessedSession.kinematics.heading_rad",
            "PreprocessedSession.kinematics.speed_px_s",
        ],
        assumptions=[
            "A frame is classified only when both Φ[t] and M[t] are defined "
            "(same per-frame skip rules as GL-3 and GL-8: >=2 moving animals, "
            "and for M, >=2 of them off the centroid)",
        ],
        warnings=[
            "Threshold choice is a modelling decision, not a physical "
            "constant -- the defaults follow Tunstrøm 2013's empirical "
            "milling-state boundaries for fish schools and may not transfer "
            "to other species or group sizes without re-checking",
        ],
        primary_reference=TUNSTROM_2013,
        supporting_references=[COUZIN_2002, VICSEK_1995],
    )
    _STATIONARY_THRESHOLD = 1e-6
    _ZERO_RADIUS_EPS = 1e-9
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="polarised_threshold",
            label="Polarised-state threshold (Φ)",
            kind="float",
            default=0.65,
            minimum=0.0,
            maximum=1.0,
            help="Φ at or above this counts a frame as 'polarised'.",
        ),
        MetricParameter(
            name="milling_threshold",
            label="Milling-state threshold (M)",
            kind="float",
            default=0.65,
            minimum=0.0,
            maximum=1.0,
            help="M at or above this (when not already polarised) counts a frame as 'milling'.",
        ),
        MetricParameter(
            name="stationary_threshold_px_s",
            label="Stationary threshold",
            kind="float",
            default=1e-6,
            minimum=0.0,
            unit="px/s",
            help="Same threshold GL-3/GL-8 use to exclude stationary animals per frame.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        xy = session.xy
        heading = session.kinematics.heading_rad
        speed = session.kinematics.speed_px_s

        polarised_thr = 0.65
        milling_thr = 0.65
        stationary_thr = self._STATIONARY_THRESHOLD
        if cfg is not None:
            polarised_thr = float(cfg.get("polarised_threshold", polarised_thr))
            milling_thr = float(cfg.get("milling_threshold", milling_thr))
            stationary_thr = float(cfg.get("stationary_threshold_px_s", stationary_thr))

        n_frames = xy.shape[0]
        counts = {"polarised": 0, "milling": 0, "swarm": 0}
        n_classified = 0

        for t in range(n_frames):
            positions = xy[t]
            h_t = heading[t]
            s_t = speed[t]

            moving = (~np.isnan(h_t)) & (~np.isnan(s_t)) & (s_t > stationary_thr)
            if moving.sum() < 2:
                continue

            cos_h = np.cos(h_t[moving])
            sin_h = np.sin(h_t[moving])
            phi = float(np.sqrt(cos_h.mean() ** 2 + sin_h.mean() ** 2))

            valid_pos = ~np.isnan(positions[:, 0]) & ~np.isnan(positions[:, 1])
            if valid_pos.sum() == 0:
                continue
            centroid = positions[valid_pos].mean(axis=0)

            rot_moving = valid_pos & (~np.isnan(h_t)) & (~np.isnan(s_t)) & (s_t > stationary_thr)
            idx = np.where(rot_moving)[0]
            if idx.size < 2:
                continue

            r = positions[idx] - centroid
            r_norm = np.sqrt((r**2).sum(axis=1))
            nonzero = r_norm > self._ZERO_RADIUS_EPS
            if nonzero.sum() < 2:
                continue

            idx2 = idx[nonzero]
            r_hat = r[nonzero] / r_norm[nonzero, None]
            e_hat = np.column_stack((np.cos(h_t[idx2]), np.sin(h_t[idx2])))
            cross = r_hat[:, 0] * e_hat[:, 1] - r_hat[:, 1] * e_hat[:, 0]
            m_val = float(abs(cross.mean()))

            n_classified += 1
            if phi >= polarised_thr:
                counts["polarised"] += 1
            elif m_val >= milling_thr:
                counts["milling"] += 1
            else:
                counts["swarm"] += 1

        if n_classified == 0:
            polarised_pct = milling_pct = swarm_pct = np.nan
        else:
            polarised_pct = counts["polarised"] / n_classified
            milling_pct = counts["milling"] / n_classified
            swarm_pct = counts["swarm"] / n_classified

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "polarised_time_pct": polarised_pct,
                    "milling_time_pct": milling_pct,
                    "swarm_time_pct": swarm_pct,
                    "n_classified_frames": n_classified,
                }
            ]
        )


# ── GL-13: Topological k-NN counts ────────────────────────────────────────────


class TopologicalNeighbourCounts(Metric):
    """GL-13 — Distances to the 1st..k-th nearest neighbours, and the
    count of neighbours within a metric radius.

    Whether interaction range is metric or topological is a live
    question in the collective-behaviour literature, and the two give
    different answers about density effects. Cheap once GL-1's
    per-frame ``cKDTree`` exists -- this queries the same tree for more
    than one neighbour.
    """

    id = "GL-13"
    name = "topological_neighbour_counts"
    label = "Topological k-NN Counts"
    level = "group"
    priority = "optional"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "k",
        "mean_kth_nn_distance_px",
        "mean_neighbours_within_radius",
    ]
    documentation = MetricDocumentation(
        definition=(
            "For k = 1..k_max: the mean distance to each animal's k-th "
            "nearest neighbour, averaged over animals and frames. Also the "
            "mean count of neighbours within a fixed metric radius, for "
            "comparison against the topological (rank-based) k-NN counts."
        ),
        formula_plain=(
            "Per frame, per animal: query cKDTree for the k_max nearest "
            "other animals; kth_nn_distance[k] = distance to the k-th; "
            "neighbours_within_radius = count of other animals within "
            "radius_px; both averaged over all animals and valid frames"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=["Frames where any animal has NaN position are skipped"],
        warnings=[
            "Requires at least k_max + 1 animals with valid positions in a "
            "frame for that frame to contribute to the k=k_max distance",
        ],
        primary_reference=BALLERINI_2008,
        supporting_references=[CLARK_EVANS_1954],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="k_max",
            label="Maximum neighbour rank (k)",
            kind="int",
            default=3,
            minimum=1,
            help="Report distances for every rank 1..k_max.",
        ),
        MetricParameter(
            name="radius_px",
            label="Metric radius",
            kind="float",
            default=50.0,
            minimum=0.0,
            unit="px",
            help="Radius for the topological-vs-metric neighbour-count comparison.",
        ),
    ]

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        xy = session.xy
        n_frames = xy.shape[0]

        k_max = 3
        radius_px = 50.0
        if cfg is not None:
            k_max = int(cfg.get("k_max", k_max))
            radius_px = float(cfg.get("radius_px", radius_px))

        kth_distances: dict[int, list[float]] = {k: [] for k in range(1, k_max + 1)}
        radius_counts: list[float] = []

        for t in range(n_frames):
            positions = xy[t]
            valid = ~np.isnan(positions[:, 0]) & ~np.isnan(positions[:, 1])
            pts = positions[valid]
            if pts.shape[0] < 2:
                continue

            tree = cKDTree(pts)
            n_query = min(k_max, pts.shape[0] - 1)
            # k=0 is each point itself (distance 0); ranks 1..n_query are
            # the actual neighbours.
            dists, _idx = tree.query(pts, k=n_query + 1)
            if n_query == 0:
                continue
            for k in range(1, n_query + 1):
                kth_distances[k].extend(dists[:, k].tolist())

            pair_counts = tree.query_ball_point(pts, r=radius_px)
            # Exclude the point itself from its own neighbour count.
            radius_counts.extend(len(neighbours) - 1 for neighbours in pair_counts)

        rows = []
        mean_radius_count = float(np.mean(radius_counts)) if radius_counts else np.nan
        for k in range(1, k_max + 1):
            values = kth_distances[k]
            mean_kth = float(np.mean(values)) if values else np.nan
            rows.append(
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "k": k,
                    "mean_kth_nn_distance_px": mean_kth,
                    "mean_neighbours_within_radius": mean_radius_count,
                }
            )

        return pd.DataFrame(rows)


# ── GL-15: Group elongation / shape anisotropy ────────────────────────────────


class GroupElongation(Metric):
    """GL-15 — Aspect ratio and orientation of the group's shape, from
    the eigenvalues of the per-frame position covariance matrix.

    GL-4 (convex hull area) and GL-10 (RMS spread) are both size-only;
    a school moving fast elongates along its direction of travel at
    roughly constant area or spread. This is the two extra numbers that
    say so.
    """

    id = "GL-15"
    name = "group_elongation"
    label = "Group Elongation / Anisotropy"
    level = "group"
    priority = "optional"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "metric_id",
        "mean_elongation_ratio",
        "mean_major_axis_orientation_rad",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Per-frame shape anisotropy of the group: the ratio of the major "
            "to minor eigenvalue of the position covariance matrix (1.0 = "
            "circular, higher = more elongated), and the orientation of the "
            "major axis, averaged over frames."
        ),
        formula_plain=(
            "Per frame: Σ = cov(xy[t, valid, :]) (2x2); "
            "λ1 >= λ2 = eigenvalues(Σ); "
            "elongation_ratio[t] = sqrt(λ1 / λ2) (NaN if λ2 <= 0); "
            "major_axis_orientation[t] = angle of the eigenvector for λ1; "
            "metric = mean over frames with >=3 valid animals"
        ),
        inputs=["PreprocessedSession.xy"],
        assumptions=[
            "Requires >=3 valid animal positions in a frame to define a covariance matrix"
        ],
        warnings=[
            "Orientation is averaged as a circular quantity mod π (an axis "
            "has no head/tail), not as a plain arithmetic mean of angles",
        ],
        primary_reference=TUNSTROM_2013,
        supporting_references=[MOHR_1947],
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        xy = session.xy
        n_frames = xy.shape[0]

        ratios: list[float] = []
        orientations: list[complex] = []

        for t in range(n_frames):
            positions = xy[t]
            valid = ~np.isnan(positions[:, 0]) & ~np.isnan(positions[:, 1])
            pts = positions[valid]
            if pts.shape[0] < 3:
                continue

            cov = np.cov(pts.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            # eigh returns ascending order; take the larger as major axis.
            lam_minor, lam_major = eigvals[0], eigvals[1]
            if lam_minor <= 0 or lam_major <= 0:
                continue

            ratios.append(float(np.sqrt(lam_major / lam_minor)))

            major_vec = eigvecs[:, 1]
            angle = float(np.arctan2(major_vec[1], major_vec[0]))
            # Average orientation as a mod-pi circular quantity (an axis has
            # no head/tail) via doubled-angle unit vectors.
            orientations.append(np.exp(1j * 2 * angle))

        mean_ratio = np.nan if not ratios else float(np.mean(ratios))

        if not orientations:
            mean_orientation = np.nan
        else:
            mean_doubled = np.mean(orientations)
            mean_orientation = float(np.angle(mean_doubled) / 2.0)

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "metric_id": self.id,
                    "mean_elongation_ratio": mean_ratio,
                    "mean_major_axis_orientation_rad": mean_orientation,
                }
            ]
        )


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(NearestNeighbourDistance)
_register(InterIndividualDistance)
_register(Polarisation)
_register(ConvexHullArea)
_register(CentroidSpeed)
_register(GroupCohesion)
_register(NNMatchedSpeed)
_register(RotationalOrder)
_register(GroupCentroidPosition)
_register(GroupSpread)
_register(OrderStateClassification)
_register(TopologicalNeighbourCounts)
_register(GroupElongation)
