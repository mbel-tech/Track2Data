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


class TestParseRoiString:
    """Session.roi_list docstring claims "Parsed signed polygons" -- before
    this, reader.py just stored the raw string verbatim ({"raw": r}).
    parse_roi_string is what makes that claim true."""

    def test_additive_polygon(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        result = parse_roi_string("+ Polygon [[10.0, 20.0], [30.0, 20.0], [30.0, 40.0]]")
        assert result is not None
        assert result["sign"] == "+"
        assert result["vertices"] == [(10.0, 20.0), (30.0, 20.0), (30.0, 40.0)]

    def test_subtractive_polygon(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        result = parse_roi_string("- Polygon [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]")
        assert result is not None
        assert result["sign"] == "-"

    def test_raw_preserved(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        raw = "+ Polygon [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]"
        result = parse_roi_string(raw)
        assert result is not None
        assert result["raw"] == raw

    def test_negative_coordinates(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        result = parse_roi_string("+ Polygon [[-5.0, -10.0], [5.0, -10.0], [5.0, 10.0]]")
        assert result is not None
        assert result["vertices"][0] == (-5.0, -10.0)

    def test_unrecognised_format_returns_none(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        assert parse_roi_string("not a polygon at all") is None

    def test_malformed_vertex_list_returns_none(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        assert parse_roi_string("+ Polygon [not valid python]") is None

    def test_fewer_than_three_vertices_returns_none(self) -> None:
        from track2data.readers.idtrackerai.session_json import parse_roi_string

        assert parse_roi_string("+ Polygon [[0.0, 0.0], [1.0, 1.0]]") is None
