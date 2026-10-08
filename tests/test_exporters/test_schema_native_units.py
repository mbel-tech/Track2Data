"""The codebook and the long table in a project whose lengths are not pixels."""

from __future__ import annotations

import pandas as pd

from track2data.exporters.schema import build_codebook, long_table, unit_for_column


class TestUnitForColumn:
    def test_pixel_projects_are_unchanged(self) -> None:
        assert unit_for_column("speed_px_s") == "px/s"
        assert unit_for_column("speed_px_s", "px") == "px/s"
        assert unit_for_column("distance_cm") == "cm"

    def test_a_confirmed_unit_names_its_columns(self) -> None:
        assert unit_for_column("speed_mm_s", "mm") == "mm/s"
        assert unit_for_column("area_mm2", "mm") == "mm^2"
        assert unit_for_column("distance_mm", "mm") == "mm"

    def test_tool_units_are_spelled_out(self) -> None:
        assert unit_for_column("speed_tu_s", "tu") == "tool units/s"

    def test_other_families_keep_their_units(self) -> None:
        for column, unit in (("time_s", "s"), ("heading_rad", "rad"), ("distance_cm", "cm")):
            assert unit_for_column(column, "mm") == unit

    def test_a_pixel_name_in_a_native_project_is_not_silently_called_pixels(self) -> None:
        # It should not exist; if one slips through, "px" would be a believable lie.
        assert unit_for_column("speed_px_s", "mm") == "unknown"

    def test_identifiers_and_explicit_units_are_unaffected(self) -> None:
        assert unit_for_column("session_id", "mm") == "identifier"
        assert unit_for_column("time_pct", "mm") == "fraction (0-1)"


class TestCodebook:
    def test_pixel_columns_are_named_for_the_project_unit(self) -> None:
        book = build_codebook(coordinate_unit="mm")
        columns = set(book["column"])
        assert "distance_mm" in columns or any(c.endswith("_mm") for c in columns)
        assert not any(c.endswith(("_px", "_px_s", "_px_s2", "_px2")) for c in columns)

    def test_every_relabelled_column_has_a_unit(self) -> None:
        book = build_codebook(coordinate_unit="mm")
        mm = book[book["column"].str.contains(r"_mm(?:_s2?|2)?$", regex=True)]
        assert not mm.empty and (mm["unit"] != "unknown").all()
        assert set(mm["unit"]) <= {"mm", "mm/s", "mm/s^2", "mm^2"}

    def test_tool_units_read_as_tool_units(self) -> None:
        book = build_codebook(coordinate_unit="tu")
        tu = book[book["column"].str.contains(r"_tu(?:_s2?|2)?$", regex=True)]
        assert not tu.empty and all("tool units" in u for u in tu["unit"])

    def test_pixel_codebook_is_exactly_what_it_was(self) -> None:
        pd.testing.assert_frame_equal(build_codebook(), build_codebook(coordinate_unit="px"))
        assert any(c.endswith("_px") for c in build_codebook()["column"])


class TestLongTable:
    def frames(self) -> dict[str, pd.DataFrame]:
        return {
            "IL-1": pd.DataFrame(
                {
                    "session_id": ["s"],
                    "individual_id": ["a"],
                    "distance_mm": [3.0],
                    "mean_speed_mm_s": [1.0],
                }
            )
        }

    def test_units_follow_the_project_unit(self) -> None:
        out = long_table(self.frames(), coordinate_unit="mm")
        assert dict(zip(out["column"], out["unit"], strict=True)) == {
            "distance_mm": "mm",
            "mean_speed_mm_s": "mm/s",
        }

    def test_the_default_is_still_pixels(self) -> None:
        frames = {
            "IL-1": pd.DataFrame(
                {"session_id": ["s"], "individual_id": ["a"], "distance_px": [3.0]}
            )
        }
        assert long_table(frames)["unit"].tolist() == ["px"]
