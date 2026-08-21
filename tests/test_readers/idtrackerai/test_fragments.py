"""Tests for readers.idtrackerai.fragments."""

from __future__ import annotations

import json
from pathlib import Path

from track2data.readers.idtrackerai.fragments import (
    fragment_swap_boundaries,
    individual_fragments,
    load_fragments,
)


def _write_fragments_json(folder: Path, data: dict) -> None:
    preproc = folder / "preprocessing"
    preproc.mkdir(parents=True, exist_ok=True)
    (preproc / "list_of_fragments.json").write_text(json.dumps(data), encoding="utf-8")


def _minimal_fragment(**overrides) -> dict:
    frag = {
        "identifier": 0,
        "start_frame": 0,
        "end_frame": 7,
        "images": [0, 1, 2, 3, 4, 5, 6],
        "episodes": [[0], [7]],
        "is_an_individual": True,
        "frame_by_frame_velocity": [1.0] * 6,
        "start_position": [0.0, 0.0],
        "end_position": [10.0, 10.0],
        "P1_vector": [0.0, 0.0],
    }
    frag.update(overrides)
    return frag


class TestLoadFragments:
    def test_missing_preprocessing_dir_returns_none(self, tmp_path: Path) -> None:
        assert load_fragments(tmp_path) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "preprocessing").mkdir()
        assert load_fragments(tmp_path) is None

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        preproc = tmp_path / "preprocessing"
        preproc.mkdir()
        (preproc / "list_of_fragments.json").write_text("{not valid json", encoding="utf-8")
        assert load_fragments(tmp_path) is None

    def test_missing_fragments_key_returns_none(self, tmp_path: Path) -> None:
        _write_fragments_json(tmp_path, {"n_animals": 4})
        assert load_fragments(tmp_path) is None

    def test_loads_valid_file(self, tmp_path: Path) -> None:
        _write_fragments_json(tmp_path, {
            "n_animals": 4,
            "fragments": [_minimal_fragment()],
            "id_to_exclusive_roi": [-1, -1, -1, -1],
            "accumulable_individual_fragments": [0],
            "not_accumulable_individual_fragments": [],
        })
        data = load_fragments(tmp_path)
        assert data is not None
        assert data["n_animals"] == 4
        assert len(data["fragments"]) == 1
        assert data["id_to_exclusive_roi"] == [-1, -1, -1, -1]

    def test_sparse_fragment_missing_optional_keys_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """Only the FRAGMENT_ALWAYS_PRESENT keys are guaranteed -- a
        fragment lacking 'identity'/'certainty'/etc. (34%/12% of real
        fragments respectively) must load without error."""
        _write_fragments_json(tmp_path, {
            "n_animals": 2,
            "fragments": [_minimal_fragment()],  # no identity, no certainty
        })
        data = load_fragments(tmp_path)
        assert data is not None
        assert data["fragments"][0].get("identity") is None

    def test_unknown_keys_preserved_verbatim(self, tmp_path: Path) -> None:
        """Real fragments carry keys absent from all four official docs
        (e.g. 'zero_identity_assigned_by_P2') -- must survive, not be
        stripped."""
        frag = _minimal_fragment(zero_identity_assigned_by_P2=True, P1_below_random=False)
        _write_fragments_json(tmp_path, {"n_animals": 1, "fragments": [frag]})
        data = load_fragments(tmp_path)
        assert data["fragments"][0]["zero_identity_assigned_by_P2"] is True
        assert data["fragments"][0]["P1_below_random"] is False

    def test_negative_certainty_not_rejected(self, tmp_path: Path) -> None:
        """certainty is not a probability -- a real observed value is
        -0.0069. Must not be clamped, rejected, or asserted into [0,1]."""
        frag = _minimal_fragment(certainty=-0.0069)
        _write_fragments_json(tmp_path, {"n_animals": 1, "fragments": [frag]})
        data = load_fragments(tmp_path)
        assert data["fragments"][0]["certainty"] == -0.0069


class TestIndividualFragments:
    def test_filters_to_is_an_individual_true(self, tmp_path: Path) -> None:
        data = {
            "fragments": [
                _minimal_fragment(identifier=0, is_an_individual=True),
                _minimal_fragment(identifier=1, is_an_individual=False),
            ]
        }
        result = individual_fragments(data)
        assert len(result) == 1
        assert result[0]["identifier"] == 0

    def test_missing_is_an_individual_treated_as_not_individual(self) -> None:
        """Conservative: an ambiguous fragment (missing key) must not be
        trusted for identity-switch boundaries or body-length sampling."""
        frag = _minimal_fragment()
        del frag["is_an_individual"]
        result = individual_fragments({"fragments": [frag]})
        assert result == []


class TestFragmentSwapBoundaries:
    def test_returns_end_frames_of_individual_fragments(self) -> None:
        data = {
            "fragments": [
                _minimal_fragment(identifier=0, end_frame=7, is_an_individual=True),
                _minimal_fragment(identifier=1, end_frame=20, is_an_individual=True),
            ]
        }
        assert fragment_swap_boundaries(data) == {7, 20}

    def test_excludes_identity_is_fixed_fragments(self) -> None:
        """identity_is_fixed fragments 'cannot be modified during the
        postprocessing' (fragment_idtrackerai.md) -- must not be offered
        as a swap site."""
        data = {
            "fragments": [
                _minimal_fragment(identifier=0, end_frame=7, identity_is_fixed=True),
                _minimal_fragment(identifier=1, end_frame=20, identity_is_fixed=False),
            ]
        }
        assert fragment_swap_boundaries(data) == {20}

    def test_excludes_crossing_fragments(self) -> None:
        data = {
            "fragments": [
                _minimal_fragment(identifier=0, end_frame=7, is_an_individual=False),
            ]
        }
        assert fragment_swap_boundaries(data) == set()

    def test_empty_fragments_returns_empty_set(self) -> None:
        assert fragment_swap_boundaries({"fragments": []}) == set()
