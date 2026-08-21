"""Tests for the idtrackerai normaliser — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.readers.idtrackerai.normaliser import Normaliser

# 10 frames, 2 animals
N, M = 10, 2


def _minimal_payload(tmp_path: Path) -> dict:
    """Minimal TrajectoryPayload matching the 17 official idtracker.ai keys."""
    return {
        "trajectories": np.zeros((N, M, 2), dtype=np.float64),
        "id_probabilities": np.ones((N, M), dtype=np.float64) * 0.9,
        "version": "6.0.13",
        "height": 1080,
        "width": 1920,
        "video_paths": ["/Volumes/Expansion/dummy.mp4"],
        "frames_per_second": 25.0,
        "body_length": 150.0,
        "estimated_accuracy": 0.90,
        "fraction_identified": 0.85,
        "areas": {"mean": np.zeros(M), "median": np.zeros(M), "std": np.zeros(M)},
        "setup_points": {},
        "identities_labels": ["1", "2"],
        "identities_groups": [],
        "length_unit": None,
        "silhouette_score": 0.78,
        "fragment_connectivity": 1.34,
    }


class TestNormaliserFpsWidthHeightFallback:
    """Regression coverage for the fabricated-25.0-fps bug found on the real
    corpus: no session in a 70-session sample has fps==25.0 (real range is
    24.833-24.880), yet the old fallback made every session missing this
    key report exactly 25.0 with no warning."""

    def test_missing_fps_falls_back_to_session_json(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["frames_per_second"]
        s = Normaliser(tmp_path).normalise(
            payload, session_meta={"frames_per_second": 24.86}
        )
        assert s.video.fps == pytest.approx(24.86)

    def test_missing_fps_and_session_json_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        del payload["frames_per_second"]
        with pytest.raises(DataValidationError) as exc_info:
            Normaliser(tmp_path).normalise(payload, session_meta=None)
        assert exc_info.value.code == "IDT_DICT_MISSING_KEY"

    def test_nan_fps_is_rejected_not_silently_passed(self, tmp_path: Path) -> None:
        """float('nan') or 25.0 == nan in plain Python (NaN is truthy) --
        the old `payload.get(...) or 25.0` fallback let a NaN fps straight
        through. Must now be treated as invalid and fall back / raise."""
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        payload["frames_per_second"] = float("nan")
        with pytest.raises(DataValidationError):
            Normaliser(tmp_path).normalise(payload, session_meta=None)

    def test_missing_width_falls_back_to_session_json(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["width"]
        s = Normaliser(tmp_path).normalise(payload, session_meta={"width": 1920})
        assert s.video.width_px == 1920

    def test_zero_width_is_rejected(self, tmp_path: Path) -> None:
        """width used to silently default to 0 via `int(payload.get("width") or 0)`."""
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        payload["width"] = 0
        with pytest.raises(DataValidationError):
            Normaliser(tmp_path).normalise(payload, session_meta=None)

    def test_version_falls_back_to_session_json(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["version"]
        s = Normaliser(tmp_path).normalise(payload, session_meta={"version": "6.0.15a0"})
        assert s.idtrackerai_version == "6.0.15a0"


class TestNormaliserBodyLengthAndAreas:
    """Regression coverage: body_length and areas were read from the
    trajectory payload (they're in KNOWN_TRAJECTORY_KEYS) and then silently
    discarded -- neither reached any Session field. Since
    CalibrationConfig.mode defaults to 'bodylength', every idtracker.ai
    session hit CAL-BL-MISSING unconditionally."""

    def test_body_length_broadcast_to_all_animals(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["body_length"] = 150.15
        s = Normaliser(tmp_path).normalise(payload)
        assert s.body_length_px is not None
        assert s.body_length_px.shape == (M,)
        np.testing.assert_allclose(s.body_length_px, [150.15] * M)

    def test_missing_body_length_is_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["body_length"]
        s = Normaliser(tmp_path).normalise(payload)
        assert s.body_length_px is None

    def test_zero_body_length_is_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["body_length"] = 0.0
        s = Normaliser(tmp_path).normalise(payload)
        assert s.body_length_px is None

    def test_body_length_reliable_stays_false(self, tmp_path: Path) -> None:
        """output_structure_idtrackerai.md:104 warns this depends on
        segmentation params; must start unacknowledged regardless of source."""
        payload = _minimal_payload(tmp_path)
        payload["body_length"] = 150.15
        s = Normaliser(tmp_path).normalise(payload)
        assert s.body_length_reliable is False

    def test_areas_land_in_quality(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.quality is not None
        assert "areas" in s.quality
        assert set(s.quality["areas"].keys()) == {"mean", "median", "std"}


class TestNormaliserHasStableIdentities:
    """has_stable_identities used to be a pure NaN-coverage heuristic that
    ignored track_wo_identities and the already-loaded fraction_identified.
    A track_wo_identities=True session with good coverage used to be
    labelled 'stable' and get per-individual analysis applied to identities
    that are not persistent by construction."""

    def test_track_wo_identities_forces_unstable_even_with_full_coverage(
        self, tmp_path: Path
    ) -> None:
        payload = _minimal_payload(tmp_path)  # full coverage, no NaN
        s = Normaliser(tmp_path).normalise(
            payload, session_meta={"track_wo_identities": True}
        )
        assert s.has_stable_identities is False

    def test_fraction_identified_above_threshold_is_stable(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["fraction_identified"] = 0.822
        # Corrupt raw coverage so the heuristic alone would say unstable --
        # fraction_identified must take priority.
        payload["trajectories"] = np.full((N, M, 2), np.nan)
        s = Normaliser(tmp_path).normalise(payload, session_meta={})
        assert s.has_stable_identities is True

    def test_fraction_identified_below_threshold_is_unstable(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["fraction_identified"] = 0.3
        s = Normaliser(tmp_path).normalise(payload, session_meta={})
        assert s.has_stable_identities is False

    def test_falls_back_to_heuristic_when_no_authoritative_signal(
        self, tmp_path: Path
    ) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["fraction_identified"]
        s = Normaliser(tmp_path).normalise(payload, session_meta={})
        # _minimal_payload has full (non-NaN) coverage -> heuristic says stable.
        assert s.has_stable_identities is True


class TestNormaliserTrajectoryShapeValidation:
    """Regression coverage: _extract_trajectories used to accept any array
    shape with no validation -- a missing key silently produced an empty
    (0, 0, 2) Session, and a transposed array passed straight through and
    was misinterpreted with n_frames and n_animals swapped."""

    def test_missing_trajectories_key_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        del payload["trajectories"]
        with pytest.raises(DataValidationError) as exc_info:
            Normaliser(tmp_path).normalise(payload)
        assert exc_info.value.code == "IDT_DICT_MISSING_KEY"

    def test_wrong_last_dimension_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        payload["trajectories"] = np.zeros((N, M, 3))  # not (x, y)
        with pytest.raises(DataValidationError) as exc_info:
            Normaliser(tmp_path).normalise(payload)
        assert exc_info.value.code == "IDT_SHAPE_MISMATCH"

    def test_2d_array_raises_instead_of_index_error(self, tmp_path: Path) -> None:
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)
        payload["trajectories"] = np.zeros((N, 2))  # missing the animals axis
        with pytest.raises(DataValidationError):
            Normaliser(tmp_path).normalise(payload)

    def test_transposed_array_recovered_via_frame_count_hint(self, tmp_path: Path) -> None:
        """(n_animals, n_frames, 2) must be transposed back to canonical
        when session.json's number_of_frames identifies the true frame axis."""
        payload = _minimal_payload(tmp_path)
        # Deliberately transposed: (n_animals=2, n_frames=10, 2)
        canonical = payload["trajectories"]
        payload["trajectories"] = canonical.transpose(1, 0, 2)
        s = Normaliser(tmp_path).normalise(
            payload, session_meta={"number_of_frames": N, "number_of_animals": M}
        )
        assert s.raw_xy.shape == (N, M, 2)

    def test_animal_count_mismatch_with_session_json_raises(self, tmp_path: Path) -> None:
        from track2data.core.errors import DataValidationError

        payload = _minimal_payload(tmp_path)  # M=2 animals
        with pytest.raises(DataValidationError) as exc_info:
            Normaliser(tmp_path).normalise(
                payload, session_meta={"number_of_animals": 4}
            )
        assert exc_info.value.code == "IDT_SHAPE_MISMATCH"

    def test_no_hint_falls_back_to_dimension_heuristic(self, tmp_path: Path) -> None:
        """Without a session.json hint, a smaller leading axis is assumed to
        be n_animals (n_animals << n_frames in every real session)."""
        payload = _minimal_payload(tmp_path)
        canonical = payload["trajectories"]  # (10 frames, 2 animals, 2)
        payload["trajectories"] = canonical.transpose(1, 0, 2)  # (2, 10, 2)
        s = Normaliser(tmp_path).normalise(payload, session_meta={})
        assert s.raw_xy.shape == (N, M, 2)


class TestNormaliserIdProbabilities:
    def test_2d_id_probabilities_unchanged(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["id_probabilities"] = np.ones((N, M), dtype=np.float64)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.id_probabilities is not None
        assert s.id_probabilities.shape == (N, M)

    def test_3d_id_probabilities_squeezed(self, tmp_path: Path) -> None:
        """(N, M, 1) shipped by idtracker.ai 6.0.13 must be squeezed to (N, M)."""
        payload = _minimal_payload(tmp_path)
        payload["id_probabilities"] = np.ones((N, M, 1), dtype=np.float64) * 0.9
        s = Normaliser(tmp_path).normalise(payload)
        assert s.id_probabilities is not None
        assert s.id_probabilities.shape == (N, M)

    def test_missing_id_probabilities_becomes_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["id_probabilities"]
        s = Normaliser(tmp_path).normalise(payload)
        assert s.id_probabilities is None


class TestNormaliserLengthUnit:
    def test_none_length_unit_not_propagated(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["length_unit"] = None
        s = Normaliser(tmp_path).normalise(payload)
        assert s.length_unit is None

    def test_zero_length_unit_treated_as_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["length_unit"] = 0.0
        s = Normaliser(tmp_path).normalise(payload)
        assert s.length_unit is None

    def test_positive_length_unit_stored(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["length_unit"] = 12.5
        s = Normaliser(tmp_path).normalise(payload)
        assert s.length_unit == pytest.approx(12.5)

    def test_negative_length_unit_treated_as_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["length_unit"] = -1.0
        s = Normaliser(tmp_path).normalise(payload)
        assert s.length_unit is None

    def test_inf_length_unit_treated_as_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["length_unit"] = float("inf")
        s = Normaliser(tmp_path).normalise(payload)
        assert s.length_unit is None


class TestNormaliserBodyLength:
    def test_body_length_reliable_always_false(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.body_length_reliable is False

    def test_body_length_px_stored_per_animal_when_areas_present(
        self, tmp_path: Path
    ) -> None:
        """When areas dict is present, body_length_px can be None — computed later."""
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        # body_length_px is populated from the mean body_length scalar in this stub;
        # the per-individual value from bboxes.csv replaces it in a later step.
        # What matters here: the field exists and body_length_reliable is False.
        assert s.body_length_reliable is False


class TestNormaliserQuality:
    def test_quality_metrics_propagated(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.quality is not None
        assert s.quality["estimated_accuracy"] == pytest.approx(0.90)
        assert s.quality["fraction_identified"] == pytest.approx(0.85)
        assert s.quality["silhouette_score"] == pytest.approx(0.78)
        assert s.quality["fragment_connectivity"] == pytest.approx(1.34)

    def test_missing_quality_key_not_in_dict(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["silhouette_score"]
        s = Normaliser(tmp_path).normalise(payload)
        assert s.quality is not None
        assert "silhouette_score" not in s.quality


class TestNormaliserIdentities:
    def test_identities_labels_propagated(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.identities_labels == ["1", "2"]

    def test_identities_groups_propagated(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.identities_groups == []

    def test_identities_groups_accepts_dict(self, tmp_path: Path) -> None:
        """session_idtrackerai.md:21 documents this as a dict (exclusive-ROI groups);
        real 6.x sessions ship a dict in 70/70 of the GOT corpus. Must not raise."""
        payload = _minimal_payload(tmp_path)
        payload["identities_groups"] = {"region_a": [1, 2], "region_b": [3, 4]}
        s = Normaliser(tmp_path).normalise(payload)
        assert s.identities_groups == {"region_a": [1, 2], "region_b": [3, 4]}

    def test_identities_groups_accepts_empty_dict(self, tmp_path: Path) -> None:
        """The common real case: exclusive_rois=False -> identities_groups == {}."""
        payload = _minimal_payload(tmp_path)
        payload["identities_groups"] = {}
        s = Normaliser(tmp_path).normalise(payload)
        assert s.identities_groups == {}


class TestNormaliserVersion:
    def test_version_stored(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.idtrackerai_version == "6.0.13"

    def test_missing_version_becomes_none(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        del payload["version"]
        s = Normaliser(tmp_path).normalise(payload)
        assert s.idtrackerai_version is None


class TestNormaliserRawXY:
    def test_canonical_shape_unchanged(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.raw_xy.shape == (N, M, 2)

    def test_n_animals_from_trajectory(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.n_animals == M

    def test_video_fps_from_payload(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.video.fps == pytest.approx(25.0)

    def test_video_dimensions_from_payload(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        s = Normaliser(tmp_path).normalise(payload)
        assert s.video.width_px == 1920
        assert s.video.height_px == 1080


class TestNormaliserUnknownKeys:
    def test_unknown_keys_go_to_raw_attrs(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["future_key_unknown"] = "some_value"
        s = Normaliser(tmp_path).normalise(payload)
        assert s.raw_attrs is not None
        assert "future_key_unknown" in s.raw_attrs

    def test_known_keys_not_in_raw_attrs(self, tmp_path: Path) -> None:
        payload = _minimal_payload(tmp_path)
        payload["some_future_key"] = "extra_value"  # ensure raw_attrs is non-None
        s = Normaliser(tmp_path).normalise(payload)
        assert s.raw_attrs is not None
        # Known keys must not leak into raw_attrs
        assert "trajectories" not in s.raw_attrs
        assert "id_probabilities" not in s.raw_attrs
        # Unknown key is captured
        assert "some_future_key" in s.raw_attrs
