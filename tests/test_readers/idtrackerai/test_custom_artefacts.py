"""Tests for custom-artefact loaders — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

from track2data.readers.idtrackerai.custom_artefacts import (
    load_bbox_summary,
    load_bbox_table,
    load_inconsistent_frames,
    load_matching_results,
)


class TestInconsistentFrames:
    def test_loads_from_tiny_real(self, tiny_real_session: Path) -> None:
        from tests.conftest import TINY_REAL_INCONSISTENT_FRAMES
        result = load_inconsistent_frames(tiny_real_session)
        assert result == TINY_REAL_INCONSISTENT_FRAMES

    def test_returns_set_of_ints(self, tiny_real_session: Path) -> None:
        result = load_inconsistent_frames(tiny_real_session)
        assert isinstance(result, set)
        assert all(isinstance(f, int) for f in result)

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = load_inconsistent_frames(tmp_path)
        assert result is None

    def test_custom_csv(self, tmp_path: Path) -> None:
        (tmp_path / "inconsistent_frames.csv").write_text("3\n7\n15\n", encoding="utf-8")
        result = load_inconsistent_frames(tmp_path)
        assert result == {3, 7, 15}


class TestBboxTable:
    def test_loads_from_tiny_real(self, tiny_real_session: Path) -> None:
        result = load_bbox_table(tiny_real_session)
        assert result is not None

    def test_has_expected_columns(self, tiny_real_session: Path) -> None:
        result = load_bbox_table(tiny_real_session)
        assert result is not None
        assert "body_length_px" in result.columns
        assert "frame" in result.columns
        assert "identity" in result.columns

    def test_n_rows_equals_frames_times_animals(self, tiny_real_session: Path) -> None:
        result = load_bbox_table(tiny_real_session)
        assert result is not None
        # 10 frames x 2 animals = 20 rows
        assert len(result) == 20

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = load_bbox_table(tmp_path)
        assert result is None


class TestBboxSummary:
    def test_loads_from_tiny_real(self, tiny_real_session: Path) -> None:
        result = load_bbox_summary(tiny_real_session)
        assert result is not None

    def test_has_status_key(self, tiny_real_session: Path) -> None:
        result = load_bbox_summary(tiny_real_session)
        assert result is not None
        assert "status" in result

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = load_bbox_summary(tmp_path)
        assert result is None


class TestMatchingResults:
    def test_no_matching_results_dir_returns_empty(self, tiny_real_session: Path) -> None:
        result = load_matching_results(tiny_real_session)
        assert result == []

    def test_returns_list_of_session_names(self, tmp_path: Path) -> None:
        mr_dir = tmp_path / "matching_results"
        (mr_dir / "session_other_Segment1").mkdir(parents=True)
        result = load_matching_results(tmp_path)
        assert "session_other_Segment1" in result

    def test_missing_matching_results_returns_empty(self, tmp_path: Path) -> None:
        result = load_matching_results(tmp_path)
        assert result == []
