"""
Diagnostic metrics D-1 through D-10.

These are always-on metrics computed for every session regardless of user
selection. They read directly from the Session object (no preprocessing
required).
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd

from track2data.core.models import PreprocessedSession, Session
from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter
from track2data.metrics.references import (
    BERNARDIN_STIEFELHAGEN_2008,
    BJORNERAAS_2010,
    ROMERO_FERRERO_2019,
)

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
        formula_plain=(
            "coverage[k] = count(~nan(xy[:,k,0])) / n_frames; "
            "session_coverage = mean(coverage) over k, equivalently "
            "total non-NaN detections / (n_frames * n_animals)"
        ),
        formula_latex=(
            r"\text{coverage}_k = "
            r"\frac{\sum_{t} \mathbf{1}[\text{xy}_{t,k} \neq \text{NaN}]}{T}"
        ),
        inputs=["Session.raw_xy"],
        assumptions=["NaN in xy[:,k,0] indicates a missing detection for animal k."],
        warnings=[
            "Low coverage may indicate segmentation failure or animal leaving the arena."
        ],
        citation=(
            "Tracking-pipeline convention (fraction of frames with a "
            "successfully assigned position); no single originating work"
        ),
        supporting_references=[ROMERO_FERRERO_2019],
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
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[BERNARDIN_STIEFELHAGEN_2008],
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
        primary_reference=ROMERO_FERRERO_2019,
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
        citation=(
            "Track2Data's own bounding-box post-processing pipeline; no "
            "external work defines this counter"
        ),
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


def _reader_has_no_identification_quality(reader_name: str) -> bool:
    """True for a *registered* reader whose tracker reports no identification quality.

    An unregistered name (a hand-built Session, a plug-in that is not installed) keeps D-5's
    original reading of a missing value, so nothing that worked before changes.
    """
    from track2data import readers
    from track2data.core.errors import ImportError_

    try:
        return not readers.get_reader(reader_name).provides_identification_quality
    except ImportError_:
        return False


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
            "'identity_free' when the session has no stable identities, "
            "'not_assessed' when the tracker reports no identification quality to judge by."
        ),
        formula_plain=(
            "stable        if has_stable_identities=True  and fraction_identified >= 0.5; "
            "weak          if has_stable_identities=True  and fraction_identified < 0.5"
            " (or missing); "
            "not_assessed  if has_stable_identities=True  and fraction_identified is missing"
            " and the session's reader has no identification-quality metric; "
            "identity_free if has_stable_identities=False"
        ),
        inputs=["Session.has_stable_identities", "Session.quality"],
        assumptions=[
            "fraction_identified defaults to 0.0 when not available, for readers whose "
            "tracker does report it (idtracker.ai) or whose reader is unknown.",
            "Readers whose tracker has no such metric (provides_identification_quality is "
            "False) are 'not_assessed' rather than 'weak': the metric does not exist for them.",
        ],
        warnings=["'weak' status may indicate frequent identity swaps."],
        citation=(
            "Track2Data engineering threshold on idtracker.ai's own "
            "fraction_identified (PRD §5.2, FR-IMP-3); not an external "
            "scientific result"
        ),
        supporting_references=[ROMERO_FERRERO_2019],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        if not session.has_stable_identities:
            status = "identity_free"
        else:
            fraction_identified: float | None = None
            if session.quality is not None:
                raw = session.quality.get("fraction_identified")
                if raw is not None:
                    fraction_identified = float(raw)
            if fraction_identified is None and _reader_has_no_identification_quality(
                session.reader
            ):
                status = "not_assessed"
            else:
                status = "stable" if (fraction_identified or 0.0) >= 0.5 else "weak"

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
            "inconsistency flags.",
            "number_of_error_frames is idtracker.ai's own internal counter, "
            "documented in its usage guide rather than singled out as a "
            "named metric in Romero-Ferrero et al. 2019 -- the citation "
            "supports the underlying software and its segmentation "
            "pipeline, not this specific field by name.",
        ],
        primary_reference=ROMERO_FERRERO_2019,
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
        primary_reference=ROMERO_FERRERO_2019,
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
        primary_reference=ROMERO_FERRERO_2019,
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
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[BERNARDIN_STIEFELHAGEN_2008],
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


# ── D-10: Physical-Plausibility Violation Rate ──────────────────────────────


class PhysicalPlausibilityViolations(Metric):
    """D-10: Fraction of raw-data steps exceeding a plausible speed
    limit, and a count of single-frame 'teleport' jumps.

    D-1..D-9 all inherit idtracker.ai's own self-report -- this is the
    only diagnostic INDEPENDENT of it, run on ``Session.raw_xy`` before
    any smoothing or gap-filling, which is exactly the failure mode
    that silently corrupts IL-2's max speed and IL-6's acceleration
    downstream.
    """

    id = "D-10"
    name = "physical_plausibility_violations"
    label = "Physical-Plausibility Violation Rate"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "violation_fraction",
        "teleport_jump_count",
        "speed_limit_px_s",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Screens the RAW (pre-preprocessing) trajectory for frame-to-frame "
            "steps faster than a plausible speed limit, using the "
            "movement-characteristic screening approach used for GPS "
            "telemetry data. Reports what fraction of an animal's steps "
            "violate the limit, and how many are severe enough ('teleport "
            "jumps') to be near-certainly a tracking error rather than real "
            "movement."
        ),
        formula_plain=(
            "step_speed[t,k] = ||raw_xy[t+1,k] - raw_xy[t,k]|| * fps (NaN pairs "
            "skipped); speed_limit_px_s = cfg['speed_limit_px_s'] if given, else "
            "the speed_limit_percentile-th percentile of this session's own "
            "pooled step_speed distribution (default 99.5th, default "
            "multiplier 3.0 applied on top); violation_fraction = fraction of "
            "an animal's steps with step_speed > speed_limit_px_s; "
            "teleport_jump_count = count with step_speed > speed_limit_px_s * "
            "teleport_multiplier (default 5.0)"
        ),
        inputs=["Session.raw_xy", "Session.video.fps"],
        assumptions=[
            "Uses raw_xy, not the preprocessed trajectory -- this is "
            "deliberately independent of gap-fill/jump-detect/smoothing, "
            "which this diagnostic exists to help evaluate",
        ],
        warnings=[
            "No calibration-derived default: Session.body_length_reliable "
            "is always False (METRICS_SPEC.md §2.1), so the default limit "
            "is data-driven (a percentile of this session's own step "
            "distribution) rather than body-length-based. A "
            "cfg['speed_limit_bl_per_s'] override is available when the "
            "user has explicitly acknowledged that caveat, but is not the "
            "default.",
            "A data-driven percentile default is circular on a session that "
            "is mostly bad data -- it screens outliers relative to the "
            "session's own distribution, not an absolute biological limit",
        ],
        primary_reference=BJORNERAAS_2010,
        supporting_references=[ROMERO_FERRERO_2019],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="speed_limit_px_s",
            label="Speed limit",
            kind="float",
            unit="px/s",
            help=(
                "Explicit plausible-speed ceiling. Auto-computed from this "
                "session's data when unset."
            ),
        ),
        MetricParameter(
            name="speed_limit_percentile",
            label="Auto speed-limit percentile",
            kind="float",
            default=99.5,
            minimum=0.0,
            maximum=100.0,
            help=(
                "Percentile of this session's own step-speed distribution "
                "used when speed_limit_px_s is unset."
            ),
        ),
        MetricParameter(
            name="teleport_multiplier",
            label="Teleport-jump multiplier",
            kind="float",
            default=5.0,
            minimum=1.0,
            help="A step this many times the speed limit counts as a teleport jump.",
        ),
    ]

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        fps = session.video.fps
        xy = session.raw_xy
        n_animals = session.n_animals

        percentile = 99.5
        teleport_multiplier = 5.0
        explicit_limit: float | None = None
        if cfg is not None:
            percentile = float(cfg.get("speed_limit_percentile", percentile))
            teleport_multiplier = float(cfg.get("teleport_multiplier", teleport_multiplier))
            if cfg.get("speed_limit_px_s") is not None:
                explicit_limit = float(cfg["speed_limit_px_s"])

        per_animal_speeds: list[np.ndarray] = []
        for k in range(n_animals):
            traj = xy[:, k, :]
            diff = traj[1:] - traj[:-1]
            valid = ~(np.isnan(diff[:, 0]) | np.isnan(diff[:, 1]))
            step_speed = np.sqrt((diff[valid] ** 2).sum(axis=1)) * fps
            per_animal_speeds.append(step_speed)

        if explicit_limit is not None:
            speed_limit = explicit_limit
        else:
            pooled = np.concatenate(per_animal_speeds) if per_animal_speeds else np.array([])
            speed_limit = float(np.percentile(pooled, percentile)) if pooled.size else float("nan")

        teleport_threshold = (
            speed_limit * teleport_multiplier if not np.isnan(speed_limit) else float("nan")
        )

        rows = []
        for k in range(n_animals):
            step_speed = per_animal_speeds[k]
            if step_speed.size == 0 or np.isnan(speed_limit):
                violation_fraction = float("nan")
                teleport_count = 0
            else:
                violation_fraction = float((step_speed > speed_limit).mean())
                teleport_count = int((step_speed > teleport_threshold).sum())

            rows.append(
                {
                    "session_id": session.session_id,
                    "individual_id": k,
                    "violation_fraction": violation_fraction,
                    "teleport_jump_count": teleport_count,
                    "speed_limit_px_s": speed_limit,
                }
            )

        return pd.DataFrame(rows, columns=self.output_columns)


# ── D-11: Metric Input Provenance ─────────────────────────────────────────────


class MetricInputProvenance(Metric):
    """D-11: How much of each animal's metric input was actually measured.

    D-1 reports coverage of ``Session.raw_xy`` -- the tracker's own output.
    This reports what the *metrics* consumed, after gap-filling and jump
    replacement, and how much of that was reconstructed rather than measured.

    The distinction matters because without it a session with 92% real
    coverage and one with 41% produce indistinguishable ``path_length_px``
    rows. Keyed on (session_id, individual_id) -- the same key the exporters
    merge summary metrics on -- so every metric row can be joined to the
    quality of the data behind it.
    """

    id = "D-11"
    name = "metric_input_provenance"
    label = "Metric Input Provenance"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "n_frames_total",
        "n_frames_used",
        "frac_frames_used",
        "n_interpolated",
        "frac_interpolated",
        "n_jump_replaced",
        "frac_jump_replaced",
        "frac_measured",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Per individual: how many frames the metrics were computed from, "
            "and what fraction of those were gap-filled or jump-replaced "
            "rather than measured directly."
        ),
        formula_plain=(
            "n_frames_used = count(~nan(preprocessed xy[:,k,0])); "
            "frac_interpolated = count(was_interpolated[:,k]) / n_frames_used; "
            "frac_jump_replaced = count(jump_replaced[:,k]) / n_frames_used; "
            "frac_measured = 1 - frac_interpolated - frac_jump_replaced"
        ),
        inputs=[
            "PreprocessedSession.xy",
            "PreprocessedSession.was_interpolated",
            "PreprocessedSession.jump_replaced",
        ],
        assumptions=[
            "The denominator is the frames the metrics actually used (non-NaN "
            "after preprocessing), not the session length -- a metric cannot "
            "be affected by a frame it never saw.",
            "A frame counts in at most one of interpolated/jump_replaced: "
            "gap-fill acts on frames that were NaN, jump replacement on "
            "frames that were not.",
        ],
        warnings=[
            "A high frac_interpolated means the corresponding metric values "
            "rest largely on interpolation rather than observation. Path "
            "length and speed are the most affected: interpolating across a "
            "gap draws a straight line, understating both.",
            "frac_jump_replaced is zero whenever jump detection did not run, "
            "which is not the same as no jumps being present.",
        ],
        citation=(
            "Data-provenance convention for derived measures; no single "
            "originating work"
        ),
    )

    def compute(
        self, session: PreprocessedSession, cfg: dict[str, Any] | None = None
    ) -> pd.DataFrame:
        n_frames = session.n_frames
        n_animals = session.n_animals

        used = ~np.isnan(session.xy[:, :, 0])       # (n_frames, n_animals)
        interpolated = session.was_interpolated
        replaced = (
            session.jump_replaced
            if session.jump_replaced is not None
            else np.zeros_like(used)
        )

        rows = []
        for k in range(n_animals):
            n_used = int(used[:, k].sum())
            n_interp = int((interpolated[:, k] & used[:, k]).sum())
            n_replaced = int((replaced[:, k] & used[:, k]).sum())
            # NaN rather than inf or 0 when nothing was usable: an animal with
            # no frames is a real and important case, and 0/0 should read as
            # "nothing to report" rather than as a number.
            denom = float(n_used) if n_used else float("nan")
            rows.append(
                {
                    "session_id": session.session_id,
                    "individual_id": k,
                    "n_frames_total": n_frames,
                    "n_frames_used": n_used,
                    "frac_frames_used": n_used / n_frames if n_frames else float("nan"),
                    "n_interpolated": n_interp,
                    "frac_interpolated": n_interp / denom,
                    "n_jump_replaced": n_replaced,
                    "frac_jump_replaced": n_replaced / denom,
                    "frac_measured": (n_used - n_interp - n_replaced) / denom,
                }
            )
        return pd.DataFrame(rows, columns=self.output_columns)


class FragmentQualityScores(Metric):
    """D-12: idtracker.ai's own fragment-clustering quality scores.

    ``fragment_connectivity`` and ``silhouette_score`` are already read into
    ``Session.quality`` and recorded in the export's provenance; this makes
    them selectable and tabulable like the rest of D-1..D-11, so they can be
    filtered on across a batch.
    """

    id = "D-12"
    name = "fragment_quality_scores"
    label = "Fragment Quality Scores"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "fragment_connectivity",
        "silhouette_score",
        "note",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Quality scores idtracker.ai reports for its identification of "
            "fragments. fragment_connectivity summarises how well fragments "
            "are linked into global fragments; silhouette_score is the "
            "silhouette of the identity clustering of fragment embeddings "
            "(higher is better separated)."
        ),
        formula_plain=(
            "Reads Session.quality['fragment_connectivity'] "
            "and Session.quality['silhouette_score']"
        ),
        inputs=["Session.quality"],
        assumptions=["quality dict is populated by the reader from the tracker output."],
        warnings=[
            "Returns NaN values when Session.quality is None or the key is absent.",
            "These are tracker self-reports and may not reflect ground-truth accuracy.",
        ],
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        quality = session.quality or {}

        def _get(key: str) -> float:
            raw = quality.get(key)
            try:
                return float(raw) if raw is not None else float("nan")
            except (TypeError, ValueError):
                return float("nan")

        return pd.DataFrame(
            [
                {
                    "session_id": session.session_id,
                    "fragment_connectivity": _get("fragment_connectivity"),
                    "silhouette_score": _get("silhouette_score"),
                    "note": "" if quality else "quality is None; no scores available",
                }
            ],
            columns=self.output_columns,
        )


class FragmentIdentityCertainty(Metric):
    """D-13: idtracker.ai's own identification certainty, per identity.

    Distinct from D-3, which summarises the raw ``id_probabilities`` array:
    this reads the per-fragment ``certainty`` idtracker.ai stores in
    ``list_of_fragments.json`` and aggregates it per identity, weighted by
    fragment length, so one long confident fragment outweighs many short
    doubtful ones.
    """

    id = "D-13"
    name = "fragment_identity_certainty"
    label = "Per-Identity Fragment Certainty"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = True
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "n_fragments",
        "n_frames_attributed",
        "certainty_mean",
        "certainty_min",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Frame-weighted mean and minimum of idtracker.ai's per-fragment "
            "identification certainty, for each identity."
        ),
        formula_plain=(
            "certainty_mean[k] = sum(len_i * certainty_i) / sum(len_i) over "
            "individual fragments i with identity k+1 and a recorded "
            "certainty; len_i = end_frame - start_frame"
        ),
        inputs=["Session.fragments"],
        assumptions=[
            "Fragment identity is 1-based and is mapped to the 0-based "
            "individual_id used everywhere else.",
        ],
        warnings=[
            "certainty is not a probability: negative values occur "
            "(observed -0.0069) and no upper bound is guaranteed.",
            "Fragments without an identity or certainty (about a third of "
            "fragments in the corpus used to build the reader) are skipped; "
            "n_frames_attributed shows how much of the identity that covers.",
            "NaN when Session.fragments is None.",
        ],
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        from track2data.readers.idtrackerai.fragments import individual_fragments

        n_animals = session.n_animals
        weights: dict[int, list[tuple[float, float]]] = {k: [] for k in range(n_animals)}
        if session.fragments is not None:
            for frag in individual_fragments(session.fragments):
                identity, certainty = frag.get("identity"), frag.get("certainty")
                start, end = frag.get("start_frame"), frag.get("end_frame")
                if (
                    not isinstance(identity, int)
                    or isinstance(identity, bool)
                    or certainty is None
                    or not isinstance(start, int)
                    or not isinstance(end, int)
                    or not 1 <= identity <= n_animals
                    or end <= start
                ):
                    continue
                try:
                    weights[identity - 1].append((float(end - start), float(certainty)))
                except (TypeError, ValueError):
                    continue

        rows = []
        for k in range(n_animals):
            pairs = weights[k]
            if pairs:
                total = sum(w for w, _ in pairs)
                mean = sum(w * c for w, c in pairs) / total
                lowest = min(c for _, c in pairs)
            else:
                total, mean, lowest = 0.0, float("nan"), float("nan")
            rows.append({
                "session_id": session.session_id,
                "individual_id": k,
                "n_fragments": len(pairs),
                "n_frames_attributed": int(total),
                "certainty_mean": mean,
                "certainty_min": lowest,
            })
        return pd.DataFrame(rows, columns=self.output_columns)


class CertainFragmentFrameFraction(Metric):
    """D-14: what share of frames sit in fragments whose identity is secure.

    A cleaner signal than D-1's raw coverage: a frame can have coordinates and
    still belong to a fragment idtracker.ai itself was unsure about.
    """

    id = "D-14"
    name = "certain_fragment_frame_fraction"
    label = "Certain-Fragment Frame Fraction"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "certainty_threshold_used",
        "frac_frames_certain",
        "frac_frames_identity_fixed",
        "frac_frames_individual",
    ]
    #: Track2Data threshold (not an idtracker.ai constant); see warnings.
    MIN_CERTAINTY: ClassVar[float] = 0.5
    documentation = MetricDocumentation(
        definition=(
            "Fraction of session frames covered by individual fragments "
            "whose certainty meets a threshold, and by fragments idtracker.ai "
            "marked identity_is_fixed."
        ),
        formula_plain=(
            "frac_frames_certain = sum(len_i for individual fragments with "
            "certainty_i >= min_certainty) / n_frames; "
            "frac_frames_identity_fixed uses identity_is_fixed; "
            "frac_frames_individual counts every individual fragment"
        ),
        inputs=["Session.fragments", "Session.n_frames"],
        assumptions=[
            "Fragments are disjoint per animal, so their lengths are summed "
            "over all animals and divided by n_frames * n_animals.",
        ],
        warnings=[
            "The 0.5 certainty cut (the same value the body-length blob "
            "reader uses) is a Track2Data threshold, not one idtracker.ai "
            "defines, and is not configurable; certainty is not a probability.",
            "Fragments lacking a certainty count as not certain.",
            "NaN when Session.fragments is None.",
        ],
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        from track2data.readers.idtrackerai.fragments import individual_fragments

        threshold = self.MIN_CERTAINTY
        nan = float("nan")
        certain = fixed = individual = nan
        denom = session.n_frames * session.n_animals
        if session.fragments is not None and denom > 0:
            certain = fixed = individual = 0.0
            for frag in individual_fragments(session.fragments):
                start, end = frag.get("start_frame"), frag.get("end_frame")
                if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                    continue
                length = float(end - start)
                individual += length
                c = frag.get("certainty")
                if isinstance(c, (int, float)) and not isinstance(c, bool) and c >= threshold:
                    certain += length
                if frag.get("identity_is_fixed") is True:
                    fixed += length
            certain, fixed, individual = (
                min(v / denom, 1.0) for v in (certain, fixed, individual)
            )
        return pd.DataFrame(
            [{
                "session_id": session.session_id,
                "certainty_threshold_used": threshold,
                "frac_frames_certain": certain,
                "frac_frames_identity_fixed": fixed,
                "frac_frames_individual": individual,
            }],
            columns=self.output_columns,
        )


class TrackerCorrectionCensus(Metric):
    """D-15: frames where idtracker.ai's own tracker re-assigned an identity.

    Independent of D-9, which counts opportunities for a swap in *this*
    project's preprocessing; this counts what the tracker itself changed.
    """

    id = "D-15"
    name = "tracker_correction_census"
    label = "Tracker Correction Census"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "n_corrected_frames",
        "frac_corrected_frames",
        "note",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Number and fraction of frames in which at least one blob's "
            "identity was re-assigned by idtracker.ai while solving jumps."
        ),
        formula_plain=(
            "n_corrected_frames = count(frames with any blob where "
            "identity_corrected_solving_jumps is not None)"
        ),
        inputs=["Session.tracker_corrected_frames"],
        assumptions=[
            "Read from preprocessing/list_of_blobs.pickle, only when the "
            "project sets blob_diagnostics and allows pickle loading.",
        ],
        warnings=[
            "NaN means the blob layer was not read -- not that there were no "
            "corrections.",
            "The attribute's semantics come from idtracker.ai's source and "
            "have not been checked against a real-session corpus.",
        ],
        primary_reference=ROMERO_FERRERO_2019,
        supporting_references=[],
    )

    def compute(self, session: Session, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        frames = session.tracker_corrected_frames
        if frames is None:
            n, frac, note = float("nan"), float("nan"), "blob layer not read"
        else:
            n = float(len(frames))
            frac = n / session.n_frames if session.n_frames else float("nan")
            note = ""
        return pd.DataFrame(
            [{
                "session_id": session.session_id,
                "n_corrected_frames": n,
                "frac_corrected_frames": frac,
                "note": note,
            }],
            columns=self.output_columns,
        )


class PreprocessingDistortion(Metric):
    """D-16: how far preprocessing moved each animal from its raw track.

    Takes the PreprocessedSession (like D-11). One scale-free number --
    ``distortion_index`` -- says at a glance whether gap-fill, jump
    replacement and smoothing changed the trajectory by more than the animal
    actually moves per frame.
    """

    id = "D-16"
    name = "preprocessing_distortion"
    label = "Preprocessing Distortion Index"
    level = "diagnostic"
    priority = "diagnostic"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "rms_displacement_px",
        "frac_frames_altered",
        "path_length_ratio",
        "distortion_index",
    ]
    documentation = MetricDocumentation(
        definition=(
            "RMS distance between the raw and preprocessed position, the "
            "fraction of frames that differ, the ratio of preprocessed to "
            "raw path length, and the RMS displacement divided by the raw "
            "median per-frame step."
        ),
        formula_plain=(
            "d_t = |xy_t - raw_t| over frames finite in both; "
            "rms = sqrt(mean(d_t^2)); distortion_index = rms / "
            "median(|raw_t - raw_{t-1}|); path_length_ratio = "
            "sum|xy_t - xy_{t-1}| / sum|raw_t - raw_{t-1}|"
        ),
        inputs=["PreprocessedSession.xy", "Session.raw_xy"],
        assumptions=[
            "Frames filled by gap-fill have no raw position, so they count "
            "as altered but are excluded from the RMS (nothing to compare).",
        ],
        warnings=[
            "distortion_index is NaN for an animal whose median raw step is "
            "zero (a stationary track); read path_length_ratio instead -- "
            "a large ratio there is exactly the spurious-teleport failure.",
            "Smoothing alone lowers path_length_ratio below 1 by design.",
        ],
        citation=(
            "Data-provenance convention for derived measures; no single "
            "originating work"
        ),
    )

    def compute(
        self, session: PreprocessedSession, cfg: dict[str, Any] | None = None
    ) -> pd.DataFrame:
        raw = np.asarray(session.session.raw_xy, dtype=np.float64)
        proc = np.asarray(session.xy, dtype=np.float64)
        nan = float("nan")
        rows = []
        for k in range(session.n_animals):
            r, p = raw[:, k, :], proc[:, k, :]
            both = ~(np.isnan(r).any(axis=1) | np.isnan(p).any(axis=1))
            if both.any():
                d = np.hypot(*(p[both] - r[both]).T)
                rms = float(np.sqrt(np.mean(d**2)))
            else:
                rms = nan

            p_ok = ~np.isnan(p).any(axis=1)
            differs = ~both & p_ok | (both & (np.hypot(*(p - r).T) > 1e-9))
            n_used = int(p_ok.sum())
            altered = float(differs.sum() / n_used) if n_used else nan

            def _steps(a: np.ndarray) -> np.ndarray:
                ok = ~np.isnan(a).any(axis=1)
                pair = ok[1:] & ok[:-1]
                return np.hypot(*(a[1:] - a[:-1]).T)[pair]

            raw_steps, proc_steps = _steps(r), _steps(p)
            raw_len = float(raw_steps.sum())
            ratio = float(proc_steps.sum()) / raw_len if raw_len > 0 else nan
            med = float(np.median(raw_steps)) if raw_steps.size else nan
            index = rms / med if med and not np.isnan(rms) and med > 0 else nan
            rows.append({
                "session_id": session.session_id,
                "individual_id": k,
                "rms_displacement_px": rms,
                "frac_frames_altered": altered,
                "path_length_ratio": ratio,
                "distortion_index": index,
            })
        return pd.DataFrame(rows, columns=self.output_columns)


# ── Convenience function ───────────────────────────────────────────────────────



def compute_all_diagnostics(psess: PreprocessedSession) -> dict[str, pd.DataFrame]:
    """Run every diagnostic metric and return {metric_id: DataFrame}.

    Takes the PreprocessedSession, not the Session: D-1..D-10 all describe
    the tracker's own output and read ``psess.session``, but D-11 describes
    what the metrics consumed and needs the preprocessed arrays.
    """
    session = psess.session
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
        PhysicalPlausibilityViolations(),
        FragmentQualityScores(),
        FragmentIdentityCertainty(),
        CertainFragmentFrameFraction(),
        TrackerCorrectionCensus(),
    ]
    results = {m.id: m.compute(session) for m in metrics}
    results[MetricInputProvenance.id] = MetricInputProvenance().compute(psess)
    results[PreprocessingDistortion.id] = PreprocessingDistortion().compute(psess)
    return results


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
_register(PhysicalPlausibilityViolations)
_register(MetricInputProvenance)
_register(FragmentQualityScores)
_register(FragmentIdentityCertainty)
_register(CertainFragmentFrameFraction)
_register(TrackerCorrectionCensus)
_register(PreprocessingDistortion)
