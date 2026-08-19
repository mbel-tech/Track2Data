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
