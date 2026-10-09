"""screen_flow seam: every mode uses the standard screen flow for now."""

from __future__ import annotations

import pytest

from track2data.core.models import ProjectMode
from ui.store.screen_flow import screen_flow


@pytest.mark.parametrize(
    "mode",
    [
        ProjectMode(),
        ProjectMode(dimension="3d", layout="single_video_two_panels"),
        ProjectMode(dimension="3d", layout="two_videos"),
    ],
)
def test_screen_flow_is_standard(mode: ProjectMode) -> None:
    assert screen_flow(mode) == "standard"
