"""A session whose positions have no pixel frame (a triangulation in board units, a tool that gives
only millimetres): what the model records about it, what ``assemble_session`` accepts, and that a
pixel session is unchanged."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.api import Engine
from track2data.core.errors import DataValidationError
from track2data.core.units import TOOL_UNITS
from track2data.readers.assemble import assemble_session


def build(**overrides):
    args = dict(
        session_id="s",
        folder=Path("somewhere"),
        reader="toy",
        fps=30.0,
        width_px=640,
        height_px=480,
        raw_xy=np.random.default_rng(0).uniform(0, 100, size=(20, 2, 2)),
        has_stable_identities=True,
    )
    args.update(overrides)
    return assemble_session(**args)


class TestAPixelSessionIsUnchanged:
    def test_pixels_are_the_default_and_there_is_a_pixel_frame(self) -> None:
        s = build()
        assert s.coordinate_unit == "px" and s.has_pixel_frame is True
        assert s.reported_unit is None

    @pytest.mark.parametrize("field", ["width_px", "height_px"])
    def test_a_pixel_session_still_needs_a_real_frame_size(self, field: str) -> None:
        with pytest.raises(DataValidationError) as caught:
            build(**{field: 0})
        assert caught.value.subject == field


class TestASessionWithNoPixelFrame:
    def test_it_is_recorded_as_tool_units_and_says_what_the_tool_called_them(self) -> None:
        s = build(coordinate_unit=TOOL_UNITS, reported_unit="mm", width_px=None, height_px=None)
        assert s.coordinate_unit == "tu" and s.has_pixel_frame is False
        assert s.reported_unit == "mm"

    def test_it_needs_no_frame_size(self) -> None:
        s = build(coordinate_unit=TOOL_UNITS, width_px=None, height_px=None)
        assert (s.video.width_px, s.video.height_px) == (0, 0)

    def test_a_frame_size_it_does_have_is_kept_but_is_not_a_pixel_frame_for_these_positions(
        self,
    ) -> None:
        s = build(coordinate_unit=TOOL_UNITS, width_px=1920, height_px=1080)
        assert (s.video.width_px, s.video.height_px) == (1920, 1080) and not s.has_pixel_frame

    def test_the_frame_rate_is_still_checked(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            build(coordinate_unit=TOOL_UNITS, width_px=None, height_px=None, fps=0.0)
        assert caught.value.subject == "fps"

    def test_a_nonsense_size_is_still_refused_when_one_is_given(self) -> None:
        with pytest.raises(DataValidationError):
            build(coordinate_unit=TOOL_UNITS, width_px=-5, height_px=480)

    def test_a_unit_name_that_is_empty_is_refused(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            build(coordinate_unit="")
        assert caught.value.subject == "coordinate_unit"


class TestTheCacheKnowsAboutTheNewFields:
    def test_the_cache_schema_was_bumped_for_them(self) -> None:
        # Entries written before Session had coordinate_unit unpickle without it.
        assert Engine._CACHE_SCHEMA >= 3
