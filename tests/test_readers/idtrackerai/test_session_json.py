"""Tests for session.json parser — written before implementation (TDD RED)."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.readers.idtrackerai.session_json import load_session_json


class TestSessionJsonInfinity:
    def test_infinity_literal_parsed(self, tmp_path: Path) -> None:
        """stdlib json.loads rejects 'Infinity'; our loader must handle it."""
        (tmp_path / "session.json").write_text(
            '{"area_ths": [100.0, Infinity]}', encoding="utf-8"
        )
        result = load_session_json(tmp_path)
        assert result is not None
        assert result["area_ths"][1] == float("inf")

    def test_negative_infinity_literal_parsed(self, tmp_path: Path) -> None:
        (tmp_path / "session.json").write_text(
            '{"val": -Infinity}', encoding="utf-8"
        )
        result = load_session_json(tmp_path)
        assert result is not None
        assert result["val"] == float("-inf")

    def test_nan_literal_parsed(self, tmp_path: Path) -> None:
        import math
        (tmp_path / "session.json").write_text(
            '{"val": NaN}', encoding="utf-8"
        )
        result = load_session_json(tmp_path)
        assert result is not None
        assert math.isnan(result["val"])

    def test_strict_json_still_works(self, tmp_path: Path) -> None:
        (tmp_path / "session.json").write_text(
            '{"fps": 25.0, "n_animals": 2}', encoding="utf-8"
        )
        result = load_session_json(tmp_path)
        assert result is not None
        assert result["fps"] == pytest.approx(25.0)


class TestSessionJsonFields:
    def test_loads_tiny_real_session_json(self, tiny_real_session: Path) -> None:
        result = load_session_json(tiny_real_session)
        assert result is not None

    def test_tracking_intervals_present(self, tiny_real_session: Path) -> None:
        result = load_session_json(tiny_real_session)
        assert result is not None
        assert "tracking_intervals" in result
        assert result["tracking_intervals"] == [[0, 9]]

    def test_roi_list_present(self, tiny_real_session: Path) -> None:
        result = load_session_json(tiny_real_session)
        assert result is not None
        assert "roi_list" in result
        assert len(result["roi_list"]) == 1
        assert result["roi_list"][0].startswith("+ Polygon")

    def test_area_ths_infinity_in_tiny_real(self, tiny_real_session: Path) -> None:
        result = load_session_json(tiny_real_session)
        assert result is not None
        assert result["area_ths"][1] == float("inf")

    def test_missing_session_json_returns_none(self, tmp_path: Path) -> None:
        result = load_session_json(tmp_path)
        assert result is None

    def test_corrupt_session_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "session.json").write_text("{{not valid json", encoding="utf-8")
        result = load_session_json(tmp_path)
        assert result is None


class TestSessionJsonLogDigest:
    def test_loads_log_digest(self, tiny_real_session: Path) -> None:
        from track2data.readers.idtrackerai.log import load_log_digest
        digest = load_log_digest(tiny_real_session)
        assert digest is not None
        assert digest["status"] == "Success"

    def test_missing_log_returns_none(self, tmp_path: Path) -> None:
        from track2data.readers.idtrackerai.log import load_log_digest
        digest = load_log_digest(tmp_path)
        assert digest is None
