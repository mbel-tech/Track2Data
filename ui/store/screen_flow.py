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
