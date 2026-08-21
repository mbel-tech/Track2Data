"""Tests for diagnostic metrics D-1 through D-5 (TDD)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import Session, VideoInfo
from track2data.metrics.diagnostic import (
    IdentityStability,
    IdProbabilityStats,
    InconsistentFrameCount,
    TrackingAccuracy,
    TrackingCoverage,
    compute_all_diagnostics,
)


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


# ── compute_all_diagnostics ────────────────────────────────────────────────────


class TestComputeAllDiagnostics:
    def test_returns_five_keys(self) -> None:
        sess = make_session()
        result = compute_all_diagnostics(sess)
        assert set(result.keys()) == {"D-1", "D-2", "D-3", "D-4", "D-5"}

    def test_values_are_dataframes(self) -> None:
        import pandas as pd

        sess = make_session()
        result = compute_all_diagnostics(sess)
        for key, df in result.items():
            assert isinstance(df, pd.DataFrame), f"{key} is not a DataFrame"

    def test_all_contain_session_id(self) -> None:
        sess = make_session(session_id="full_test")
        result = compute_all_diagnostics(sess)
        for key, df in result.items():
            assert "session_id" in df.columns, f"{key} missing session_id"
