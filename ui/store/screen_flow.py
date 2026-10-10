"""Which screen flow a project mode uses.

This is the seam the later 3-D screens (layouts F and G) replace: each layout
will return its own flow here. Until then every mode uses the standard flow.
"""

from __future__ import annotations

from typing import Literal

from track2data.core.models import ProjectMode


def screen_flow(mode: ProjectMode) -> Literal["standard"]:
    """The screen flow for *mode*; always ``"standard"`` for now."""
    return "standard"


#: The Views page index in the stacked widget (3-D only). Defined here once:
#: ``app.navigation`` and ``ui.store.stage_status`` import it.
VIEWS_PAGE = 10


def page_route(mode: ProjectMode) -> list[int]:
    """The wizard pages in order for *mode*; 3-D inserts Views after Sessions."""
    if mode.dimension == "3d":
        return [0, 1, VIEWS_PAGE, *range(2, 10)]
    return list(range(10))


def next_page(mode: ProjectMode, page: int) -> int | None:
    """The page after *page* in the route, or None at the end / off the route."""
    route = page_route(mode)
    if page not in route or page == route[-1]:
        return None
    return route[route.index(page) + 1]


def prev_page(mode: ProjectMode, page: int) -> int | None:
    """The page before *page* in the route, or None at the start / off the route."""
    route = page_route(mode)
    if page not in route or page == route[0]:
        return None
    return route[route.index(page) - 1]
