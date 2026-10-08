"""Coordinate units: what a session's numbers are expressed in, and what its columns are called.

Most trackers give pixels. Some give no pixel frame at all (a 3-D triangulation in board units, a
tracker that reports millimetres only). For those the pipeline's arithmetic is unchanged (it is
unit-agnostic), but the *names* matter: a distance in millimetres must never be exported under a
``_px`` header, and a tool's unit label must not be believed unless someone confirmed it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from track2data.core.units import (
    PIXELS,
    RESERVED_LABELS,
    TOOL_UNITS,
    effective_unit,
    native_unit_for_column,
    relabel_column,
    relabel_frame,
    unit_symbol,
    units_per_cm,
)


class TestRelabellingAColumn:
    @pytest.mark.parametrize(
        ("column", "unit", "expected"),
        [
            ("distance_px", "mm", "distance_mm"),
            ("speed_px_s", "mm", "speed_mm_s"),
            ("max_accel_px_s2", "mm", "max_accel_mm_s2"),
            ("area_px2", "mm", "area_mm2"),
            ("x_px", "tu", "x_tu"),
            ("speed_px_s", "tu", "speed_tu_s"),
            ("area_px2", "tu", "area_tu2"),
        ],
    )
    def test_the_pixel_family_takes_the_unit(self, column: str, unit: str, expected: str) -> None:
        assert relabel_column(column, unit) == expected

    @pytest.mark.parametrize(
        "column",
        ["distance_cm", "speed_cm_s", "time_s", "heading_rad", "distance_bl", "n_frames_used",
         "session_id", "px_per_cm", "spx", "x_pxx"],
    )  # fmt: skip
    def test_everything_else_is_left_alone(self, column: str) -> None:
        assert relabel_column(column, "mm") == column

    def test_pixels_relabel_to_themselves(self) -> None:
        assert relabel_column("speed_px_s", PIXELS) == "speed_px_s"

    def test_each_family_is_read_whole(self) -> None:
        # "_px_s2" must not be read as "_px" + "_s2".
        assert relabel_column("a_px_s2", "mm") == "a_mm_s2"


class TestRelabellingATable:
    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"session_id": ["s"], "x_px": [1.0], "speed_px_s": [2.0], "x_cm": [0.1]}
        )

    def test_pixel_tables_come_back_untouched_and_uncopied(self) -> None:
        df = self.frame()
        assert relabel_frame(df, PIXELS) is df

    def test_other_units_rename_only_the_pixel_family(self) -> None:
        out = relabel_frame(self.frame(), "mm")
        assert list(out.columns) == ["session_id", "x_mm", "speed_mm_s", "x_cm"]

    def test_the_input_is_not_modified(self) -> None:
        df = self.frame()
        relabel_frame(df, "mm")
        assert "x_px" in df.columns

    def test_the_values_are_not_touched(self) -> None:
        out = relabel_frame(self.frame(), "mm")
        assert out["x_mm"].tolist() == [1.0] and out["speed_mm_s"].tolist() == [2.0]

    def test_an_empty_or_missing_table_is_fine(self) -> None:
        assert relabel_frame(pd.DataFrame(), "mm").empty
        assert relabel_frame(None, "mm") is None  # type: ignore[arg-type]


class TestWhatTheNumbersAreCalled:
    def test_pixels_when_there_is_a_pixel_frame(self) -> None:
        assert effective_unit(has_pixel_frame=True, confirmed_label=None) == PIXELS
        assert effective_unit(has_pixel_frame=True, confirmed_label="mm") == PIXELS

    def test_tool_units_until_somebody_confirms_what_they_are(self) -> None:
        assert effective_unit(has_pixel_frame=False, confirmed_label=None) == TOOL_UNITS

    def test_the_confirmed_label_once_someone_has(self) -> None:
        assert effective_unit(has_pixel_frame=False, confirmed_label="mm") == "mm"

    def test_a_label_that_would_collide_with_another_column_family_is_not_believed(self) -> None:
        for label in ("s", "bl", "rad", "px"):
            assert effective_unit(has_pixel_frame=False, confirmed_label=label) == TOOL_UNITS

    def test_the_reserved_labels_are_the_other_families_suffixes(self) -> None:
        assert {"px", "bl", "s", "rad"} <= RESERVED_LABELS


class TestSymbols:
    def test_tool_units_are_spelled_out(self) -> None:
        assert unit_symbol(TOOL_UNITS) == "tool units"

    def test_others_are_themselves(self) -> None:
        assert unit_symbol("mm") == "mm" and unit_symbol(PIXELS) == "px"


class TestUnitsPerCentimetre:
    @pytest.mark.parametrize(
        ("unit", "per_cm"), [("mm", 10.0), ("cm", 1.0), ("m", 0.01), ("um", 10000.0)]
    )
    def test_known_lengths(self, unit: str, per_cm: float) -> None:
        assert units_per_cm(unit) == pytest.approx(per_cm)

    @pytest.mark.parametrize("unit", ["px", "tu", "furlong", ""])
    def test_anything_else_is_unknown_never_guessed(self, unit: str) -> None:
        assert units_per_cm(unit) is None


class TestTheUnitOfARelabelledColumn:
    @pytest.mark.parametrize(
        ("column", "expected"),
        [
            ("distance_mm", "mm"),
            ("speed_mm_s", "mm/s"),
            ("max_accel_mm_s2", "mm/s^2"),
            ("area_mm2", "mm^2"),
        ],
    )
    def test_physical_units(self, column: str, expected: str) -> None:
        assert native_unit_for_column(column, "mm") == expected

    def test_tool_units(self) -> None:
        assert native_unit_for_column("speed_tu_s", TOOL_UNITS) == "tool units/s"
        assert native_unit_for_column("area_tu2", TOOL_UNITS) == "tool units^2"

    def test_a_column_that_is_not_in_that_unit_is_not_claimed(self) -> None:
        assert native_unit_for_column("distance_cm", "mm") is None
        assert native_unit_for_column("distance_px", "mm") is None
        assert native_unit_for_column("distance_mm", "tu") is None

    def test_pixels_have_no_native_family(self) -> None:
        assert native_unit_for_column("distance_px", PIXELS) is None
