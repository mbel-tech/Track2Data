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
from track2data.metrics.base import Metric, MetricDocumentation

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
        citation="Couzin et al. 2002, J. Theor. Biol.",
        citation_doi="10.1006/jtbi.2002.3065",
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
    requires_identity = False
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
        citation="Couzin et al. 2002, J. Theor. Biol.",
        citation_doi="10.1006/jtbi.2002.3065",
    )

    _STATIONARY_THRESHOLD = 1e-6  # px/s — animals slower than this are excluded

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
        warnings=["Highly variable valid-animal counts across frames may bias the metric"],
        citation="Standard collective motion",
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
        warnings=["Greedy assignment may be biased in crowded scenes"],
        citation="Identity-free tracking analysis — standard method",
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
        citation="Standard collective behaviour",
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
        citation="Standard spatial analysis",
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
        formula_plain="cohesion_index = 1 / mean_NND",
        inputs=["PreprocessedSession.xy"],
        assumptions=["Uses the same NND computation as GL-1"],
        warnings=["Undefined (NaN) when mean_NND = 0 or when fewer than 2 animals"],
        citation="Standard collective behaviour",
    )

    def compute(self, session: PreprocessedSession, cfg: dict | None = None) -> pd.DataFrame:
        """Compute group cohesion for *session*.

        Parameters
        ----------
        session:
            A fully preprocessed session.
        cfg:
            Optional configuration dict (unused).

        Returns
        -------
        pd.DataFrame
            One row with cohesion_index.
        """
        xy = session.xy  # (n_frames, n_animals, 2)
        n_frames, n_animals = xy.shape[0], xy.shape[1]

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

        frame_nnds: list[float] = []
        for t in range(n_frames):
            positions = xy[t]
            if np.isnan(positions).any():
                continue
            tree = cKDTree(positions)
            dists, _ = tree.query(positions, k=2)
            frame_nnds.append(float(dists[:, 1].mean()))

        if len(frame_nnds) == 0:
            cohesion = np.nan
        else:
            mean_nnd = float(np.mean(frame_nnds))
            cohesion = 1.0 / mean_nnd if mean_nnd != 0 else np.nan

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
    requires_identity = False
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
        citation="Couzin et al. 2002, J. Theor. Biol.; Tunstrøm et al. 2013, PLoS Comp Bio",
        citation_doi="10.1006/jtbi.2002.3065",
    )

    _STATIONARY_THRESHOLD = 1e-6  # px/s — animals slower than this are excluded
    _ZERO_RADIUS_EPS = 1e-9  # px — animals this close to the centroid are excluded

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
        citation="Standard collective motion",
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
        warnings=["Skipped frames may bias the metric"],
        citation="Standard collective motion",
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
