"""
Diagnostic metrics D-1 through D-5.

These are always-on metrics computed for every session regardless of user
selection. They read directly from the Session object (no preprocessing
required).
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd

from track2data.core.models import Session
from track2data.metrics.base import Metric, MetricDocumentation

# ── D-1: Tracking Coverage ─────────────────────────────────────────────────────


class TrackingCoverage(Metric):
    """D-1: Fraction of non-NaN frames per tracked animal."""

    id = "D-1"
    name = "tracking_coverage"
    label = "Tracking Coverage"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "coverage_fraction",
        "nan_frames_count",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Fraction of frames in which each animal's position is non-NaN. "
            "A value of 1.0 means the animal was detected in every frame."
        ),
        formula_plain="coverage[k] = count(~nan(xy[:,k,0])) / n_frames",
        formula_latex=(
            r"\text{coverage}_k = "
            r"\frac{\sum_{t} \mathbf{1}[\text{xy}_{t,k} \neq \text{NaN}]}{T}"
        ),
        inputs=["Session.raw_xy"],
        assumptions=["NaN in xy[:,k,0] indicates a missing detection for animal k."],
        warnings=[
            "Low coverage may indicate segmentation failure or animal leaving the arena."
        ],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        n_frames = session.n_frames
        n_animals = session.n_animals
        # NaN check on the x-coordinate channel; shape (n_frames, n_animals)
        is_nan = np.isnan(session.raw_xy[:, :, 0])
        nan_counts = is_nan.sum(axis=0)  # (n_animals,)
        coverage = 1.0 - nan_counts / n_frames

        rows = []
        for k in range(n_animals):
            rows.append(
                {
                    "session_id": session.session_id,
                    "individual_id": k,
                    "coverage_fraction": float(coverage[k]),
                    "nan_frames_count": int(nan_counts[k]),
                }
            )
        return pd.DataFrame(rows, columns=self.output_columns)


# ── D-2: Tracking Accuracy ─────────────────────────────────────────────────────


class TrackingAccuracy(Metric):
    """D-2: Session-level accuracy estimates from the tracker quality dict."""

    id = "D-2"
    name = "tracking_accuracy"
    label = "Tracking Accuracy"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "estimated_accuracy",
        "fraction_identified",
        "note",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Session-level accuracy estimates reported by idtracker.ai. "
            "estimated_accuracy is the model's self-reported accuracy; "
            "fraction_identified is the fraction of frames with a confident identity."
        ),
        formula_plain=(
            "Reads Session.quality['estimated_accuracy'] "
            "and Session.quality['fraction_identified']"
        ),
        inputs=["Session.quality"],
        assumptions=["quality dict is populated by the reader from the tracker output."],
        warnings=[
            "Returns NaN values when Session.quality is None.",
            "These are tracker self-reports and may not reflect ground-truth accuracy.",
        ],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        note = ""
        if session.quality is None:
            estimated_accuracy = float("nan")
            fraction_identified = float("nan")
            note = "quality is None; no accuracy data available"
        else:
            estimated_accuracy_raw = session.quality.get("estimated_accuracy")
            fraction_identified_raw = session.quality.get("fraction_identified")
            estimated_accuracy = (
                float(estimated_accuracy_raw)
                if estimated_accuracy_raw is not None
                else float("nan")
            )
            fraction_identified = (
                float(fraction_identified_raw)
                if fraction_identified_raw is not None
                else float("nan")
            )

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "estimated_accuracy": estimated_accuracy,
                    "fraction_identified": fraction_identified,
                    "note": note,
                }
            ],
            columns=self.output_columns,
        )


# ── D-3: ID-Probability Distribution ──────────────────────────────────────────


class IdProbabilityStats(Metric):
    """D-3: Per-animal summary statistics of the identity-probability array."""

    id = "D-3"
    name = "id_probability_stats"
    label = "ID-Probability Distribution"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "id_prob_median",
        "id_prob_p10",
        "id_prob_p90",
        "id_prob_frac_above_0p9",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Per-animal summary of the per-frame identity-probability values "
            "reported by idtracker.ai. High median and high fraction-above-0.9 "
            "indicate confident identities. NaN entries (frames where the "
            "animal was not detected -- output_structure_idtrackerai.md:69) "
            "are excluded from the percentile/median/fraction calculations, "
            "not treated as zero-confidence or propagated to NaN."
        ),
        formula_plain=(
            "median/p10/p90 = nanpercentile(id_probabilities[:,k], 50/10/90); "
            "frac_above_0p9 = mean(id_probabilities[:,k] > 0.9) over non-NaN entries"
        ),
        inputs=["Session.id_probabilities"],
        assumptions=["id_probabilities has shape (n_frames, n_animals)."],
        warnings=[
            "Returns NaN values when Session.id_probabilities is None, or "
            "when an animal has zero non-NaN entries (never detected)."
        ],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        rows = []
        for k in range(session.n_animals):
            if session.id_probabilities is None:
                rows.append(
                    {
                        "session_id": session.session_id,
                        "individual_id": k,
                        "id_prob_median": float("nan"),
                        "id_prob_p10": float("nan"),
                        "id_prob_p90": float("nan"),
                        "id_prob_frac_above_0p9": float("nan"),
                    }
                )
            else:
                col = session.id_probabilities[:, k]
                valid = col[~np.isnan(col)]
                # NaN in id_probabilities means "animal not detected in this
                # frame" (output_structure_idtrackerai.md:69), not a
                # confidence value of zero. np.median/np.percentile propagate
                # any NaN to the whole result -- on the real corpus 44.5% of
                # id_probabilities entries are NaN, so the plain-numpy
                # version returned NaN for every animal in every session,
                # violating this metric's own "NaN only when Session.id_
                # probabilities is None" contract. nanmedian/nanpercentile
                # compute over the valid (detected) frames only.
                if valid.size == 0:
                    median = p10 = p90 = frac_above = float("nan")
                else:
                    median = float(np.nanmedian(col))
                    p10 = float(np.nanpercentile(col, 10))
                    p90 = float(np.nanpercentile(col, 90))
                    frac_above = float(np.mean(valid > 0.9))
                rows.append(
                    {
                        "session_id": session.session_id,
                        "individual_id": k,
                        "id_prob_median": median,
                        "id_prob_p10": p10,
                        "id_prob_p90": p90,
                        "id_prob_frac_above_0p9": frac_above,
                    }
                )
        return pd.DataFrame(rows, columns=self.output_columns)


# ── D-4: Inconsistent Frame Count ─────────────────────────────────────────────


class InconsistentFrameCount(Metric):
    """D-4: Count and fraction of frames flagged as inconsistent."""

    id = "D-4"
    name = "inconsistent_frame_count"
    label = "Inconsistent-Frame Count"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "inconsistent_frame_count",
        "inconsistent_frame_fraction",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Number and fraction of frames flagged as inconsistent by "
            "idtracker.ai's post-processing validator."
        ),
        formula_plain=(
            "n_inconsistent = len(inconsistent_frames) "
            "if inconsistent_frames is not None else 0; "
            "frac_inconsistent = n_inconsistent / n_frames"
        ),
        inputs=["Session.inconsistent_frames", "Session.n_frames"],
        assumptions=["inconsistent_frames is a set of frame indices or None."],
        warnings=[
            "A high fraction may indicate tracking or segmentation failures.",
        ],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        n_inconsistent = (
            len(session.inconsistent_frames)
            if session.inconsistent_frames is not None
            else 0
        )
        frac = n_inconsistent / session.n_frames if session.n_frames > 0 else 0.0

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "inconsistent_frame_count": n_inconsistent,
                    "inconsistent_frame_fraction": frac,
                }
            ],
            columns=self.output_columns,
        )


# ── D-5: Identity Stability ────────────────────────────────────────────────────


class IdentityStability(Metric):
    """D-5: Categorical identity-stability classification for the session."""

    id = "D-5"
    name = "identity_stability"
    label = "Identity Stability Flag"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = ["session_id", "identity_stability_status"]
    documentation = MetricDocumentation(
        definition=(
            "Categorical classification of identity stability: "
            "'stable' when identities are well-maintained, "
            "'weak' when identities exist but are unreliable, "
            "'identity_free' when the session has no stable identities."
        ),
        formula_plain=(
            "stable        if has_stable_identities=True  and fraction_identified >= 0.5; "
            "weak          if has_stable_identities=True  and fraction_identified < 0.5"
            " (or missing); "
            "identity_free if has_stable_identities=False"
        ),
        inputs=["Session.has_stable_identities", "Session.quality"],
        assumptions=["fraction_identified defaults to 0.0 when not available."],
        warnings=["'weak' status may indicate frequent identity swaps."],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        if not session.has_stable_identities:
            status = "identity_free"
        else:
            fraction_identified: float = 0.0
            if session.quality is not None:
                raw = session.quality.get("fraction_identified")
                if raw is not None:
                    fraction_identified = float(raw)
            status = "stable" if fraction_identified >= 0.5 else "weak"

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "identity_stability_status": status,
                }
            ],
            columns=self.output_columns,
        )


# ── D-6: Segmentation Error Frames ──────────────────────────────────────────


class SegmentationErrorFrames(Metric):
    """D-6: idtracker.ai's own count of frames with more blobs than animals."""

    id = "D-6"
    name = "segmentation_error_frames"
    label = "Segmentation Error Frames"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "number_of_error_frames",
        "error_frame_fraction",
    ]
    documentation = MetricDocumentation(
        definition=(
            "idtracker.ai's own authoritative count of frames where more "
            "blobs than animals were detected -- segmentation contamination "
            "from shadows, reflections, dust, etc. (idtracker.ai_usage.md: "
            "'indicate a bad segmentation'). Independent of any user-side "
            "inconsistent_frames.csv (see D-4), and the only place this "
            "surfaces when the tracking run had check_segmentation "
            "disabled, which silences it in idtracker.ai's own log."
        ),
        formula_plain=(
            "number_of_error_frames = Session.number_of_error_frames; "
            "error_frame_fraction = number_of_error_frames / n_frames"
        ),
        inputs=["Session.number_of_error_frames", "Session.n_frames"],
        assumptions=["Returns NaN when Session.number_of_error_frames is None."],
        warnings=[
            "A high fraction indicates segmentation contamination that can "
            "degrade identification accuracy, independent of D-4's post-hoc "
            "inconsistency flags."
        ],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        n_error = session.number_of_error_frames
        if n_error is None:
            n_error_val = float("nan")
            fraction = float("nan")
        else:
            n_error_val = float(n_error)
            fraction = n_error / session.n_frames if session.n_frames > 0 else float("nan")

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "number_of_error_frames": n_error_val,
                    "error_frame_fraction": fraction,
                }
            ],
            columns=self.output_columns,
        )


# ── D-7: Fragment Length Distribution ───────────────────────────────────────


class FragmentLengthDistribution(Metric):
    """D-7: Distribution of individual-fragment lengths -- how often
    identity had to be re-established.

    Reads Session.fragments (preprocessing/list_of_fragments.json, see
    readers/idtrackerai/fragments.py). Measured on a real session: median
    fragment length 3 frames (p90 118, max 3409) -- identity is
    reconstructed constantly, a fact invisible without this metric.
    """

    id = "D-7"
    name = "fragment_length_distribution"
    label = "Fragment Length Distribution"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "n_individual_fragments",
        "fragment_length_median",
        "fragment_length_p10",
        "fragment_length_p90",
        "fragment_length_max",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Median/p10/p90/max length (in frames) of individual fragments "
            "-- maximal runs of frames idtracker.ai believes belong to the "
            "same animal. A short median means identity is being "
            "re-established constantly, which bounds how much any "
            "per-individual metric can be trusted between fragment breaks."
        ),
        formula_plain=(
            "length[i] = end_frame[i] - start_frame[i] for each individual "
            "fragment; median/p10/p90/max computed over that distribution"
        ),
        inputs=["Session.fragments"],
        assumptions=["Returns NaN values when Session.fragments is None."],
        warnings=["A very short median fragment length indicates frequent "
                   "crossings or occlusions relative to the tracked area."],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        from track2data.readers.idtrackerai.fragments import individual_fragments

        if session.fragments is None:
            return pd.DataFrame(
                [{
                    "session_id": session.session_id,
                    "n_individual_fragments": float("nan"),
                    "fragment_length_median": float("nan"),
                    "fragment_length_p10": float("nan"),
                    "fragment_length_p90": float("nan"),
                    "fragment_length_max": float("nan"),
                }],
                columns=self.output_columns,
            )

        lengths = np.array([
            f["end_frame"] - f["start_frame"]
            for f in individual_fragments(session.fragments)
            if "end_frame" in f and "start_frame" in f
        ], dtype=np.float64)

        if lengths.size == 0:
            median = p10 = p90 = mx = float("nan")
        else:
            median = float(np.median(lengths))
            p10 = float(np.percentile(lengths, 10))
            p90 = float(np.percentile(lengths, 90))
            mx = float(lengths.max())

        return pd.DataFrame(
            [{
                "session_id": session.session_id,
                "n_individual_fragments": float(lengths.size),
                "fragment_length_median": median,
                "fragment_length_p10": p10,
                "fragment_length_p90": p90,
                "fragment_length_max": mx,
            }],
            columns=self.output_columns,
        )


# ── D-8: Crossing Rate ───────────────────────────────────────────────────────


class CrossingRate(Metric):
    """D-8: Fraction of fragments (and of frames) that are crossings.

    Direct confound quantifier for every group/social metric (GL-*):
    animals inside a crossing fragment are, by definition, touching or
    overlapping another animal for that entire span.
    """

    id = "D-8"
    name = "crossing_rate"
    label = "Crossing Rate"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "crossing_fragment_fraction",
        "crossing_frame_fraction",
    ]
    documentation = MetricDocumentation(
        definition=(
            "crossing_fragment_fraction: fraction of all fragments (individual "
            "+ crossing) where is_an_individual is False. "
            "crossing_frame_fraction: fraction of total fragment-frames "
            "(sum of fragment lengths) covered by crossing fragments -- "
            "weights by duration rather than fragment count, since crossing "
            "fragments and individual fragments have very different typical "
            "lengths."
        ),
        formula_plain=(
            "crossing_fragment_fraction = n_crossing_fragments / n_fragments; "
            "crossing_frame_fraction = sum(length of crossing fragments) / "
            "sum(length of all fragments)"
        ),
        inputs=["Session.fragments"],
        assumptions=["Returns NaN values when Session.fragments is None."],
        warnings=["A high crossing_frame_fraction means a large share of "
                   "the recording has animals in physical contact or "
                   "overlap, confounding distance/orientation-based group "
                   "metrics for that span."],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        if session.fragments is None:
            return pd.DataFrame(
                [{
                    "session_id": session.session_id,
                    "crossing_fragment_fraction": float("nan"),
                    "crossing_frame_fraction": float("nan"),
                }],
                columns=self.output_columns,
            )

        all_frags = session.fragments["fragments"]
        if not all_frags:
            frag_frac = frame_frac = float("nan")
        else:
            n_crossing = sum(1 for f in all_frags if f.get("is_an_individual") is False)
            frag_frac = n_crossing / len(all_frags)

            def _length(f: dict[str, Any]) -> int:
                return max(0, f.get("end_frame", 0) - f.get("start_frame", 0))

            total_len = sum(_length(f) for f in all_frags)
            crossing_len = sum(
                _length(f) for f in all_frags if f.get("is_an_individual") is False
            )
            frame_frac = crossing_len / total_len if total_len > 0 else float("nan")

        return pd.DataFrame(
            [{
                "session_id": session.session_id,
                "crossing_fragment_fraction": frag_frac,
                "crossing_frame_fraction": frame_frac,
            }],
            columns=self.output_columns,
        )


# ── D-9: Identity Swap Opportunity Count ────────────────────────────────────


class SwapOpportunityCount(Metric):
    """D-9: Exact, decidable count of frames where an identity swap is
    physically possible -- fragment boundaries, per
    readers/idtrackerai/fragments.py's fragment_swap_boundaries().

    Deliberately not a corrector: this reports where and how often a swap
    *could* have happened, and leaves the decision to the researcher,
    rather than silently re-permuting the trajectory (see
    preprocess/identity_switch.py, disabled by default -- this metric is
    the "declassare invece di riparare" alternative the format-alignment
    plan settled on for that risk).
    """

    id = "D-9"
    name = "swap_opportunity_count"
    label = "Identity Swap Opportunity Count"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "swap_opportunity_count",
        "swap_opportunity_fraction",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Number and fraction of frames that are the end_frame of some "
            "individual fragment without identity_is_fixed=True -- the "
            "exact, bounded set of frames where idtracker.ai's own "
            "segmentation leaves open the possibility of an identity swap. "
            "Every other frame is inside a fragment idtracker.ai considers "
            "a single continuous identity."
        ),
        formula_plain=(
            "boundaries = {f['end_frame'] for f in individual_fragments "
            "if not f.get('identity_is_fixed')}; "
            "swap_opportunity_count = len(boundaries); "
            "swap_opportunity_fraction = swap_opportunity_count / n_frames"
        ),
        inputs=["Session.fragments", "Session.n_frames"],
        assumptions=["Returns NaN values when Session.fragments is None."],
        warnings=["A high count relative to n_frames indicates a session "
                   "with frequent crossings/occlusions where per-individual "
                   "trajectories should be reviewed rather than trusted "
                   "outright between boundaries."],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        from track2data.readers.idtrackerai.fragments import fragment_swap_boundaries

        if session.fragments is None:
            count = float("nan")
            fraction = float("nan")
        else:
            boundaries = fragment_swap_boundaries(session.fragments)
            count = float(len(boundaries))
            fraction = count / session.n_frames if session.n_frames > 0 else float("nan")

        return pd.DataFrame(
            [{
                "session_id": session.session_id,
                "swap_opportunity_count": count,
                "swap_opportunity_fraction": fraction,
            }],
            columns=self.output_columns,
        )


# ── Convenience function ───────────────────────────────────────────────────────


def compute_all_diagnostics(session: Session) -> dict[str, pd.DataFrame]:
    """Run all 9 diagnostic metrics and return {metric_id: DataFrame}."""
    metrics: list[Metric] = [
        TrackingCoverage(),
        TrackingAccuracy(),
        IdProbabilityStats(),
        InconsistentFrameCount(),
        IdentityStability(),
        SegmentationErrorFrames(),
        FragmentLengthDistribution(),
        CrossingRate(),
        SwapOpportunityCount(),
    ]
    return {m.id: m.compute(session) for m in metrics}


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(TrackingCoverage)
_register(TrackingAccuracy)
_register(IdProbabilityStats)
_register(InconsistentFrameCount)
_register(IdentityStability)
_register(SegmentationErrorFrames)
_register(FragmentLengthDistribution)
_register(CrossingRate)
_register(SwapOpportunityCount)
