"""Tests for diagnostic metrics D-1 through D-6 (TDD)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from track2data import readers
from track2data.core.models import Session, VideoInfo
from track2data.metrics.diagnostic import (
    CrossingRate,
    FragmentLengthDistribution,
    IdentityStability,
    IdProbabilityStats,
    InconsistentFrameCount,
    MetricInputProvenance,
    PhysicalPlausibilityViolations,
    SegmentationErrorFrames,
    SwapOpportunityCount,
    TrackingAccuracy,
    TrackingCoverage,
    compute_all_diagnostics,
)
from track2data.readers.base import SessionReader


def make_session(**kwargs):  # type: ignore[no-untyped-def]
    """Make a minimal Session for testing."""
    defaults = dict(
        session_id="test",
        folder=Path("/tmp/test"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=100, width_px=100, height_px=100),
        n_animals=2,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.zeros((100, 2, 2), dtype=np.float64),
    )
    defaults.update(kwargs)
    return Session(**defaults)


def make_psess(**kwargs):  # type: ignore[no-untyped-def]
    """Wrap make_session() in a minimal PreprocessedSession.

    D-11 reads the preprocessed arrays rather than Session.raw_xy, so the
    aggregate runner takes the PreprocessedSession; D-1..D-10 read
    ``psess.session`` and are unaffected.
    """
    from track2data.core.models import KinematicsArrays, PreprocessedSession

    session = make_session(**kwargs)
    n_frames, n_animals = session.n_frames, session.n_animals
    empty = np.full((n_frames, n_animals), np.nan)
    return PreprocessedSession(
        session=session,
        xy=session.raw_xy.copy(),
        kinematics=KinematicsArrays(
            speed_px_s=empty.copy(),
            accel_px_s2=empty.copy(),
            heading_rad=empty.copy(),
        ),
    )


# ── D-1: Tracking Coverage ─────────────────────────────────────────────────────


class TestTrackingCoverage:
    def test_d1_columns_present(self) -> None:
        sess = make_session()
        df = TrackingCoverage().compute(sess)
        for col in ["session_id", "individual_id", "coverage_fraction", "nan_frames_count"]:
            assert col in df.columns

    def test_d1_one_row_per_animal(self) -> None:
        sess = make_session()
        df = TrackingCoverage().compute(sess)
        assert len(df) == 2

    def test_d1_coverage_all_valid(self) -> None:
        sess = make_session()
        df = TrackingCoverage().compute(sess)
        assert all(v == pytest.approx(1.0) for v in df["coverage_fraction"])

    def test_d1_nan_count_zero_when_all_valid(self) -> None:
        sess = make_session()
        df = TrackingCoverage().compute(sess)
        assert (df["nan_frames_count"] == 0).all()

    def test_d1_coverage_with_nans(self) -> None:
        xy = np.ones((100, 2, 2))
        xy[0:10, 0, :] = np.nan  # 10% NaN for animal 0
        sess = make_session(raw_xy=xy)
        df = TrackingCoverage().compute(sess)
        assert df.loc[df["individual_id"] == 0, "coverage_fraction"].values[0] == pytest.approx(0.9)

    def test_d1_nan_count_with_nans(self) -> None:
        xy = np.ones((100, 2, 2))
        xy[0:10, 0, :] = np.nan
        sess = make_session(raw_xy=xy)
        df = TrackingCoverage().compute(sess)
        assert df.loc[df["individual_id"] == 0, "nan_frames_count"].values[0] == 10

    def test_d1_session_id_column(self) -> None:
        sess = make_session(session_id="my_session")
        df = TrackingCoverage().compute(sess)
        assert (df["session_id"] == "my_session").all()

    def test_d1_individual_ids_present(self) -> None:
        sess = make_session()
        df = TrackingCoverage().compute(sess)
        assert set(df["individual_id"]) == {0, 1}

    def test_d1_metric_attributes(self) -> None:
        m = TrackingCoverage()
        assert m.id == "D-1"
        assert m.level == "diagnostic"
        assert m.priority == "diagnostic"
        assert m.requires_identity is False


# ── D-2: Tracking Accuracy ─────────────────────────────────────────────────────


class TestTrackingAccuracy:
    def test_d2_columns_present(self) -> None:
        sess = make_session()
        df = TrackingAccuracy().compute(sess)
        for col in ["session_id", "estimated_accuracy", "fraction_identified"]:
            assert col in df.columns

    def test_d2_one_row(self) -> None:
        sess = make_session()
        df = TrackingAccuracy().compute(sess)
        assert len(df) == 1

    def test_d2_quality_none_returns_nan(self) -> None:
        sess = make_session(quality=None)
        df = TrackingAccuracy().compute(sess)
        assert np.isnan(df["estimated_accuracy"].values[0])
        assert np.isnan(df["fraction_identified"].values[0])

    def test_d2_quality_none_has_note(self) -> None:
        sess = make_session(quality=None)
        df = TrackingAccuracy().compute(sess)
        assert "note" in df.columns

    def test_d2_quality_present_accuracy(self) -> None:
        sess = make_session(quality={"estimated_accuracy": 0.95, "fraction_identified": 0.88})
        df = TrackingAccuracy().compute(sess)
        assert df["estimated_accuracy"].values[0] == pytest.approx(0.95)

    def test_d2_quality_present_fraction(self) -> None:
        sess = make_session(quality={"estimated_accuracy": 0.95, "fraction_identified": 0.88})
        df = TrackingAccuracy().compute(sess)
        assert df["fraction_identified"].values[0] == pytest.approx(0.88)

    def test_d2_quality_missing_keys_nan(self) -> None:
        sess = make_session(quality={"silhouette_score": 0.7})
        df = TrackingAccuracy().compute(sess)
        assert np.isnan(df["estimated_accuracy"].values[0])
        assert np.isnan(df["fraction_identified"].values[0])

    def test_d2_session_id_column(self) -> None:
        sess = make_session(session_id="sess42")
        df = TrackingAccuracy().compute(sess)
        assert df["session_id"].values[0] == "sess42"

    def test_d2_metric_attributes(self) -> None:
        m = TrackingAccuracy()
        assert m.id == "D-2"
        assert m.level == "diagnostic"


# ── D-3: ID-Probability Distribution ──────────────────────────────────────────


class TestIdProbabilityStats:
    def test_d3_columns_present(self) -> None:
        sess = make_session()
        df = IdProbabilityStats().compute(sess)
        for col in [
            "session_id",
            "individual_id",
            "id_prob_median",
            "id_prob_p10",
            "id_prob_p90",
            "id_prob_frac_above_0p9",
        ]:
            assert col in df.columns

    def test_d3_id_probs_none_returns_nan(self) -> None:
        sess = make_session(id_probabilities=None)
        df = IdProbabilityStats().compute(sess)
        assert np.isnan(df["id_prob_median"].values[0])

    def test_d3_id_probs_none_one_row_per_animal(self) -> None:
        sess = make_session(id_probabilities=None)
        df = IdProbabilityStats().compute(sess)
        assert len(df) == 2

    def test_d3_id_probs_computed(self) -> None:
        probs = np.ones((100, 2), dtype=np.float64) * 0.95
        sess = make_session(id_probabilities=probs)
        df = IdProbabilityStats().compute(sess)
        assert df["id_prob_median"].values[0] == pytest.approx(0.95)
        assert df["id_prob_frac_above_0p9"].values[0] == pytest.approx(1.0)

    def test_d3_id_probs_p10_p90(self) -> None:
        rng = np.random.default_rng(0)
        probs = rng.uniform(0.0, 1.0, (100, 2))
        sess = make_session(id_probabilities=probs)
        df = IdProbabilityStats().compute(sess)
        for i in range(2):
            row = df.loc[df["individual_id"] == i]
            expected_p10 = np.percentile(probs[:, i], 10)
            expected_p90 = np.percentile(probs[:, i], 90)
            assert row["id_prob_p10"].values[0] == pytest.approx(expected_p10)
            assert row["id_prob_p90"].values[0] == pytest.approx(expected_p90)

    def test_d3_frac_above_0p9(self) -> None:
        probs = np.zeros((100, 2))
        probs[:50, 0] = 1.0  # 50% above 0.9 for animal 0
        probs[50:, 0] = 0.5
        probs[:, 1] = 0.95   # 100% above 0.9 for animal 1
        sess = make_session(id_probabilities=probs)
        df = IdProbabilityStats().compute(sess)
        col = "id_prob_frac_above_0p9"
        assert df.loc[df["individual_id"] == 0, col].values[0] == pytest.approx(0.5)
        assert df.loc[df["individual_id"] == 1, col].values[0] == pytest.approx(1.0)

    def test_d3_nan_frames_excluded_not_propagated(self) -> None:
        """Regression: NaN in id_probabilities means 'animal not detected in
        this frame' (output_structure_idtrackerai.md:69), not zero
        confidence. np.median/np.percentile propagate any NaN to the whole
        result -- on the real corpus 44.5% of entries are NaN, so this used
        to return NaN for every animal in every real session."""
        probs = np.full((100, 2), 0.9)
        probs[:44, 0] = np.nan  # 44% NaN for animal 0, none for animal 1
        sess = make_session(id_probabilities=probs)
        df = IdProbabilityStats().compute(sess)
        row0 = df.loc[df["individual_id"] == 0].iloc[0]
        assert not np.isnan(row0["id_prob_median"])
        assert row0["id_prob_median"] == pytest.approx(0.9)
        assert row0["id_prob_frac_above_0p9"] == pytest.approx(0.0)  # 0.9 is not > 0.9

    def test_d3_all_nan_for_animal_returns_nan(self) -> None:
        """An animal never detected at all (100% NaN) still returns NaN --
        distinct from the None-array case, but the same output contract."""
        probs = np.full((100, 2), 0.9)
        probs[:, 0] = np.nan
        sess = make_session(id_probabilities=probs)
        df = IdProbabilityStats().compute(sess)
        row0 = df.loc[df["individual_id"] == 0].iloc[0]
        assert np.isnan(row0["id_prob_median"])

    def test_d3_metric_attributes(self) -> None:
        m = IdProbabilityStats()
        assert m.id == "D-3"
        assert m.level == "diagnostic"


# ── D-4: Inconsistent Frame Count ─────────────────────────────────────────────


class TestInconsistentFrameCount:
    def test_d4_columns_present(self) -> None:
        sess = make_session()
        df = InconsistentFrameCount().compute(sess)
        for col in ["session_id", "inconsistent_frame_count", "inconsistent_frame_fraction"]:
            assert col in df.columns

    def test_d4_one_row(self) -> None:
        sess = make_session()
        df = InconsistentFrameCount().compute(sess)
        assert len(df) == 1

    def test_d4_inconsistent_frames_none_count_zero(self) -> None:
        sess = make_session(inconsistent_frames=None)
        df = InconsistentFrameCount().compute(sess)
        assert df["inconsistent_frame_count"].values[0] == 0

    def test_d4_inconsistent_frames_none_fraction_zero(self) -> None:
        sess = make_session(inconsistent_frames=None)
        df = InconsistentFrameCount().compute(sess)
        assert df["inconsistent_frame_fraction"].values[0] == pytest.approx(0.0)

    def test_d4_inconsistent_frames_count(self) -> None:
        sess = make_session(inconsistent_frames={5, 10, 15})
        df = InconsistentFrameCount().compute(sess)
        assert df["inconsistent_frame_count"].values[0] == 3

    def test_d4_inconsistent_frames_fraction(self) -> None:
        sess = make_session(inconsistent_frames={5, 10, 15})  # 3/100 = 0.03
        df = InconsistentFrameCount().compute(sess)
        assert df["inconsistent_frame_fraction"].values[0] == pytest.approx(0.03)

    def test_d4_empty_set_count_zero(self) -> None:
        sess = make_session(inconsistent_frames=set())
        df = InconsistentFrameCount().compute(sess)
        assert df["inconsistent_frame_count"].values[0] == 0

    def test_d4_session_id_column(self) -> None:
        sess = make_session(session_id="s1")
        df = InconsistentFrameCount().compute(sess)
        assert df["session_id"].values[0] == "s1"

    def test_d4_metric_attributes(self) -> None:
        m = InconsistentFrameCount()
        assert m.id == "D-4"
        assert m.level == "diagnostic"


# ── D-6: Segmentation Error Frames ──────────────────────────────────────────
#
# Regression coverage: number_of_error_frames is idtracker.ai's own
# authoritative count of frames with more blobs than animals -- it was read
# from session.json and had zero consumers. Distinct from D-4's
# inconsistent_frames.csv, which is a user-side post-processing artefact.


class TestSegmentationErrorFrames:
    def test_d6_columns_present(self) -> None:
        sess = make_session()
        df = SegmentationErrorFrames().compute(sess)
        for col in ["session_id", "number_of_error_frames", "error_frame_fraction"]:
            assert col in df.columns

    def test_d6_one_row(self) -> None:
        sess = make_session()
        df = SegmentationErrorFrames().compute(sess)
        assert len(df) == 1

    def test_d6_none_returns_nan(self) -> None:
        sess = make_session(number_of_error_frames=None)
        df = SegmentationErrorFrames().compute(sess)
        assert np.isnan(df["number_of_error_frames"].values[0])
        assert np.isnan(df["error_frame_fraction"].values[0])

    def test_d6_count_and_fraction(self) -> None:
        sess = make_session(number_of_error_frames=75)  # n_frames=100 default
        df = SegmentationErrorFrames().compute(sess)
        assert df["number_of_error_frames"].values[0] == 75
        assert df["error_frame_fraction"].values[0] == pytest.approx(0.75)

    def test_d6_zero_error_frames(self) -> None:
        sess = make_session(number_of_error_frames=0)
        df = SegmentationErrorFrames().compute(sess)
        assert df["number_of_error_frames"].values[0] == 0
        assert df["error_frame_fraction"].values[0] == pytest.approx(0.0)

    def test_d6_metric_attributes(self) -> None:
        m = SegmentationErrorFrames()
        assert m.id == "D-6"
        assert m.level == "diagnostic"


# ── D-7/D-8/D-9: fragment-derived diagnostics ───────────────────────────────
#
# Regression coverage: preprocessing/list_of_fragments.json had zero
# consumers -- the entire fragment layer (identity-swap boundaries,
# crossing detection, fragment-length distribution) was unused.


def _frag(**overrides):  # type: ignore[no-untyped-def]
    frag = {
        "identifier": 0, "start_frame": 0, "end_frame": 5,
        "is_an_individual": True,
    }
    frag.update(overrides)
    return frag


class TestFragmentLengthDistribution:
    def test_d7_none_when_no_fragments(self) -> None:
        sess = make_session(fragments=None)
        df = FragmentLengthDistribution().compute(sess)
        assert np.isnan(df["fragment_length_median"].values[0])

    def test_d7_computes_distribution(self) -> None:
        fragments = {"fragments": [
            _frag(start_frame=0, end_frame=5),    # length 5
            _frag(start_frame=10, end_frame=30),  # length 20
            _frag(start_frame=0, end_frame=1, is_an_individual=False),  # crossing, excluded
        ]}
        sess = make_session(fragments=fragments)
        df = FragmentLengthDistribution().compute(sess)
        assert df["n_individual_fragments"].values[0] == 2
        assert df["fragment_length_median"].values[0] == pytest.approx(12.5)
        assert df["fragment_length_max"].values[0] == 20.0

    def test_d7_metric_attributes(self) -> None:
        m = FragmentLengthDistribution()
        assert m.id == "D-7"
        assert m.level == "diagnostic"


class TestCrossingRate:
    def test_d8_none_when_no_fragments(self) -> None:
        sess = make_session(fragments=None)
        df = CrossingRate().compute(sess)
        assert np.isnan(df["crossing_fragment_fraction"].values[0])

    def test_d8_computes_rates(self) -> None:
        fragments = {"fragments": [
            _frag(start_frame=0, end_frame=10, is_an_individual=True),   # 10 frames
            _frag(start_frame=0, end_frame=10, is_an_individual=False),  # 10 frames, crossing
        ]}
        sess = make_session(fragments=fragments)
        df = CrossingRate().compute(sess)
        assert df["crossing_fragment_fraction"].values[0] == pytest.approx(0.5)
        assert df["crossing_frame_fraction"].values[0] == pytest.approx(0.5)

    def test_d8_metric_attributes(self) -> None:
        m = CrossingRate()
        assert m.id == "D-8"
        assert m.level == "diagnostic"


class TestSwapOpportunityCount:
    def test_d9_none_when_no_fragments(self) -> None:
        sess = make_session(fragments=None)
        df = SwapOpportunityCount().compute(sess)
        assert np.isnan(df["swap_opportunity_count"].values[0])

    def test_d9_counts_boundaries_excluding_fixed(self) -> None:
        fragments = {"fragments": [
            _frag(identifier=0, end_frame=7, identity_is_fixed=False),
            _frag(identifier=1, end_frame=20, identity_is_fixed=True),  # excluded
        ]}
        sess = make_session(fragments=fragments, video=VideoInfo(
            fps=25.0, n_frames=100, width_px=100, height_px=100,
        ))
        df = SwapOpportunityCount().compute(sess)
        assert df["swap_opportunity_count"].values[0] == 1.0
        assert df["swap_opportunity_fraction"].values[0] == pytest.approx(0.01)

    def test_d9_metric_attributes(self) -> None:
        m = SwapOpportunityCount()
        assert m.id == "D-9"
        assert m.level == "diagnostic"


# ── D-5: Identity Stability ────────────────────────────────────────────────────


class TestIdentityStability:
    def test_d5_columns_present(self) -> None:
        sess = make_session()
        df = IdentityStability().compute(sess)
        for col in ["session_id", "identity_stability_status"]:
            assert col in df.columns

    def test_d5_one_row(self) -> None:
        sess = make_session()
        df = IdentityStability().compute(sess)
        assert len(df) == 1

    def test_d5_stable(self) -> None:
        sess = make_session(
            has_stable_identities=True,
            quality={"fraction_identified": 0.9, "estimated_accuracy": 0.95},
        )
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "stable"

    def test_d5_stable_at_boundary(self) -> None:
        sess = make_session(
            has_stable_identities=True,
            quality={"fraction_identified": 0.5, "estimated_accuracy": 0.8},
        )
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "stable"

    def test_d5_weak(self) -> None:
        sess = make_session(
            has_stable_identities=True,
            quality={"fraction_identified": 0.3, "estimated_accuracy": 0.5},
        )
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "weak"

    def test_d5_identity_free(self) -> None:
        sess = make_session(has_stable_identities=False)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "identity_free"

    def test_d5_stable_quality_none_no_fraction(self) -> None:
        """stable+identities but no quality dict -> treat fraction as missing -> weak."""
        sess = make_session(has_stable_identities=True, quality=None)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "weak"

    def test_d5_stable_quality_missing_key(self) -> None:
        """stable+identities but quality dict has no fraction_identified -> weak."""
        sess = make_session(has_stable_identities=True, quality={"estimated_accuracy": 0.9})
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "weak"

    def test_d5_session_id_column(self) -> None:
        sess = make_session(session_id="abc", has_stable_identities=False)
        df = IdentityStability().compute(sess)
        assert df["session_id"].values[0] == "abc"

    def test_d5_metric_attributes(self) -> None:
        m = IdentityStability()
        assert m.id == "D-5"
        assert m.level == "diagnostic"


class _NoQualityReader(SessionReader):
    """A registered reader whose software has no identification-quality metric."""

    name = "d5_no_quality"

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    def read(self, folder: Path) -> Session:  # pragma: no cover - never read
        raise NotImplementedError


class _QualityReader(_NoQualityReader):
    name = "d5_quality"
    provides_identification_quality = True


@pytest.fixture
def d5_readers() -> Iterator[None]:
    for cls in (_NoQualityReader, _QualityReader):
        readers.register(cls)
    yield
    for cls in (_NoQualityReader, _QualityReader):
        readers._REGISTRY.remove(cls)


class TestIdentityStabilityForOtherReaders:
    """D-5 rests on idtracker.ai's own fraction_identified. A tracker with no such metric cannot
    be rated 'weak' for lacking it: before this, every non-idtracker.ai session read 'weak'."""

    def test_no_quality_metric_means_not_assessed_not_weak(self, d5_readers: None) -> None:
        sess = make_session(reader="d5_no_quality", has_stable_identities=True, quality=None)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "not_assessed"

    def test_a_missing_key_is_also_not_assessed(self, d5_readers: None) -> None:
        sess = make_session(
            reader="d5_no_quality", has_stable_identities=True, quality={"other": 1.0}
        )
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "not_assessed"

    @pytest.mark.parametrize(("fraction", "expected"), [(0.9, "stable"), (0.2, "weak")])
    def test_a_value_the_reader_does_supply_is_still_used(
        self, d5_readers: None, fraction: float, expected: str
    ) -> None:
        sess = make_session(
            reader="d5_no_quality",
            has_stable_identities=True,
            quality={"fraction_identified": fraction},
        )
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == expected

    def test_a_reader_that_provides_quality_keeps_the_old_reading_of_missing(
        self, d5_readers: None
    ) -> None:
        sess = make_session(reader="d5_quality", has_stable_identities=True, quality=None)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "weak"

    def test_an_unregistered_reader_keeps_the_old_reading_of_missing(self) -> None:
        sess = make_session(reader="not_registered", has_stable_identities=True, quality=None)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "weak"

    def test_the_idtracker_readers_declare_that_they_provide_it(self) -> None:
        for name in ("idtrackerai", "idtrackerai_v5"):
            assert readers.get_reader(name).provides_identification_quality

    def test_identity_free_is_unaffected(self, d5_readers: None) -> None:
        sess = make_session(reader="d5_no_quality", has_stable_identities=False, quality=None)
        df = IdentityStability().compute(sess)
        assert df["identity_stability_status"].values[0] == "identity_free"


# ── D-10: Physical-Plausibility Violation Rate ──────────────────────────────


class TestPhysicalPlausibilityViolations:
    def test_metric_id(self) -> None:
        assert PhysicalPlausibilityViolations.id == "D-10"

    def test_smooth_trajectory_has_no_violations_with_explicit_limit(self) -> None:
        n_frames = 50
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, 0] = np.arange(n_frames) * 1.0  # constant 1 px/frame = 25 px/s at fps 25
        sess = make_session(n_animals=1, raw_xy=xy)
        df = PhysicalPlausibilityViolations().compute(sess, cfg={"speed_limit_px_s": 1000.0})
        assert df.iloc[0]["violation_fraction"] == pytest.approx(0.0)
        assert df.iloc[0]["teleport_jump_count"] == 0

    def test_injected_teleport_jump_is_detected(self) -> None:
        n_frames = 50
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, 0] = np.arange(n_frames) * 1.0
        xy[25, 0, 0] += 10_000.0  # one enormous single-frame jump
        sess = make_session(n_animals=1, raw_xy=xy)
        df = PhysicalPlausibilityViolations().compute(sess, cfg={"speed_limit_px_s": 1000.0})
        assert df.iloc[0]["teleport_jump_count"] >= 1

    def test_auto_speed_limit_is_data_driven_when_unset(self) -> None:
        rng = np.random.default_rng(4)
        n_frames = 200
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, :] = np.cumsum(rng.normal(0, 1, size=(n_frames, 2)), axis=0)
        sess = make_session(n_animals=1, raw_xy=xy)
        df = PhysicalPlausibilityViolations().compute(sess)
        assert not np.isnan(df.iloc[0]["speed_limit_px_s"])
        assert df.iloc[0]["speed_limit_px_s"] > 0

    def test_speed_limit_percentile_is_configurable(self) -> None:
        rng = np.random.default_rng(5)
        n_frames = 200
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, :] = np.cumsum(rng.normal(0, 1, size=(n_frames, 2)), axis=0)
        sess = make_session(n_animals=1, raw_xy=xy)
        low = PhysicalPlausibilityViolations().compute(
            sess, cfg={"speed_limit_percentile": 50.0}
        ).iloc[0]["speed_limit_px_s"]
        high = PhysicalPlausibilityViolations().compute(
            sess, cfg={"speed_limit_percentile": 99.9}
        ).iloc[0]["speed_limit_px_s"]
        assert high > low

    def test_teleport_multiplier_is_configurable(self) -> None:
        n_frames = 50
        xy = np.zeros((n_frames, 1, 2))
        xy[:, 0, 0] = np.arange(n_frames) * 1.0
        xy[25, 0, 0] += 500.0
        sess = make_session(n_animals=1, raw_xy=xy)
        loose = PhysicalPlausibilityViolations().compute(
            sess, cfg={"speed_limit_px_s": 100.0, "teleport_multiplier": 2.0}
        ).iloc[0]["teleport_jump_count"]
        strict = PhysicalPlausibilityViolations().compute(
            sess, cfg={"speed_limit_px_s": 100.0, "teleport_multiplier": 50.0}
        ).iloc[0]["teleport_jump_count"]
        assert loose >= strict


# ── compute_all_diagnostics ────────────────────────────────────────────────────


class TestComputeAllDiagnostics:
    def test_returns_every_registered_diagnostic(self) -> None:
        result = compute_all_diagnostics(make_psess())
        assert set(result.keys()) == {
            "D-1", "D-2", "D-3", "D-4", "D-5", "D-6", "D-7", "D-8", "D-9",
            "D-10", "D-11",
        }

    def test_values_are_dataframes(self) -> None:
        import pandas as pd

        result = compute_all_diagnostics(make_psess())
        for key, df in result.items():
            assert isinstance(df, pd.DataFrame), f"{key} is not a DataFrame"

    def test_all_contain_session_id(self) -> None:
        result = compute_all_diagnostics(make_psess(session_id="full_test"))
        for key, df in result.items():
            assert "session_id" in df.columns, f"{key} missing session_id"


# ── D-11: Metric Input Provenance ─────────────────────────────────────────────


def _psess_with(raw: np.ndarray, final: np.ndarray, jumps: np.ndarray | None = None):  # type: ignore[no-untyped-def]
    """PreprocessedSession with explicit raw/final arrays and a jump mask."""
    from track2data.core.models import KinematicsArrays, PreprocessedSession

    session = make_session(
        raw_xy=raw,
        n_animals=raw.shape[1],
        video=VideoInfo(
            fps=25.0, n_frames=raw.shape[0], width_px=100, height_px=100
        ),
    )
    empty = np.full(final.shape[:2], np.nan)
    return PreprocessedSession(
        session=session,
        xy=final,
        kinematics=KinematicsArrays(
            speed_px_s=empty.copy(),
            accel_px_s2=empty.copy(),
            heading_rad=empty.copy(),
        ),
        jump_replaced=jumps,
    )


class TestMetricInputProvenance:
    def test_metric_id(self) -> None:
        assert MetricInputProvenance.id == "D-11"

    def test_fully_measured_session_reports_no_reconstruction(self) -> None:
        xy = np.ones((10, 2, 2), dtype=np.float64)
        df = MetricInputProvenance().compute(_psess_with(xy, xy.copy()))

        assert list(df["n_frames_used"]) == [10, 10]
        assert (df["frac_interpolated"] == 0.0).all()
        assert (df["frac_measured"] == 1.0).all()

    def test_interpolated_frames_are_counted_against_the_used_frames(self) -> None:
        """The denominator is what the metrics saw, not the session length."""
        raw = np.ones((10, 1, 2), dtype=np.float64)
        raw[2:4] = np.nan            # a gap the pipeline filled
        final = np.ones((10, 1, 2), dtype=np.float64)

        row = MetricInputProvenance().compute(_psess_with(raw, final)).iloc[0]

        assert row["n_frames_used"] == 10
        assert row["n_interpolated"] == 2
        assert row["frac_interpolated"] == pytest.approx(0.2)
        assert row["frac_measured"] == pytest.approx(0.8)

    def test_frames_still_missing_are_excluded_from_the_denominator(self) -> None:
        """A gap too long to fill is not a frame any metric could have used."""
        raw = np.ones((10, 1, 2), dtype=np.float64)
        raw[2:6] = np.nan
        final = np.ones((10, 1, 2), dtype=np.float64)
        final[2:6] = np.nan          # gap_fill declined it (max_gap_frames)

        row = MetricInputProvenance().compute(_psess_with(raw, final)).iloc[0]

        assert row["n_frames_total"] == 10
        assert row["n_frames_used"] == 6
        assert row["frac_frames_used"] == pytest.approx(0.6)
        assert row["n_interpolated"] == 0
        assert row["frac_measured"] == pytest.approx(1.0)

    def test_jump_replaced_frames_are_reported_separately(self) -> None:
        """A jump-replaced position started as a real measurement, so it is
        not interpolation -- but it is not observation either."""
        xy = np.ones((10, 1, 2), dtype=np.float64)
        jumps = np.zeros((10, 1), dtype=bool)
        jumps[5:8] = True

        row = MetricInputProvenance().compute(_psess_with(xy, xy.copy(), jumps)).iloc[0]

        assert row["n_jump_replaced"] == 3
        assert row["frac_jump_replaced"] == pytest.approx(0.3)
        assert row["frac_interpolated"] == 0.0
        assert row["frac_measured"] == pytest.approx(0.7)

    def test_absent_jump_mask_reports_zero_not_nan(self) -> None:
        """Jump detection that never ran replaced nothing."""
        xy = np.ones((10, 1, 2), dtype=np.float64)
        row = MetricInputProvenance().compute(_psess_with(xy, xy.copy(), None)).iloc[0]
        assert row["n_jump_replaced"] == 0
        assert row["frac_jump_replaced"] == 0.0

    def test_animal_with_no_usable_frames_reports_nan_not_a_number(self) -> None:
        """0/0 must read as "nothing to report", never as a fraction."""
        raw = np.full((10, 1, 2), np.nan)
        final = np.full((10, 1, 2), np.nan)

        row = MetricInputProvenance().compute(_psess_with(raw, final)).iloc[0]

        assert row["n_frames_used"] == 0
        assert np.isnan(row["frac_interpolated"])
        assert np.isnan(row["frac_measured"])

    def test_distinguishes_two_sessions_d1_would_report_identically(self) -> None:
        """The whole point: 92% and 41% real coverage must not look the same."""
        good_raw = np.ones((100, 1, 2), dtype=np.float64)
        good_raw[:8] = np.nan
        poor_raw = np.ones((100, 1, 2), dtype=np.float64)
        poor_raw[:59] = np.nan
        final = np.ones((100, 1, 2), dtype=np.float64)

        good = MetricInputProvenance().compute(_psess_with(good_raw, final)).iloc[0]
        poor = MetricInputProvenance().compute(
            _psess_with(poor_raw, final.copy())
        ).iloc[0]

        assert good["n_frames_used"] == poor["n_frames_used"] == 100
        assert good["frac_measured"] == pytest.approx(0.92)
        assert poor["frac_measured"] == pytest.approx(0.41)

    def test_output_columns_match_the_declaration(self) -> None:
        xy = np.ones((10, 2, 2), dtype=np.float64)
        df = MetricInputProvenance().compute(_psess_with(xy, xy.copy()))
        assert list(df.columns) == MetricInputProvenance.output_columns
