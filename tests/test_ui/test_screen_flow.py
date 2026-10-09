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


TWO_D = ProjectMode()
THREE_D = ProjectMode(dimension="3d", layout="two_videos")


def test_page_route() -> None:
    from ui.store.screen_flow import page_route

    assert page_route(TWO_D) == list(range(10))
    assert page_route(THREE_D) == [0, 1, 10, 2, 3, 4, 5, 6, 7, 8, 9]


def test_next_and_prev_page() -> None:
    from ui.store.screen_flow import next_page, prev_page

    assert next_page(TWO_D, 1) == 2
    assert next_page(THREE_D, 1) == 10
    assert next_page(THREE_D, 10) == 2
    assert next_page(THREE_D, 9) is None
    assert next_page(TWO_D, 9) is None
    assert next_page(TWO_D, 10) is None
    assert prev_page(THREE_D, 2) == 10
    assert prev_page(THREE_D, 10) == 1
    assert prev_page(THREE_D, 1) == 0
    assert prev_page(THREE_D, 0) is None
    assert prev_page(TWO_D, 2) == 1
    assert prev_page(TWO_D, 10) is None
