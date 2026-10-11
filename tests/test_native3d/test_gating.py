"""Metrics a native 3-D project cannot offer: the pixel-sized ones and every group metric."""

from __future__ import annotations

import pytest

from tests.test_native3d.test_project_rules import SESSION_CM, _manifest, _ref
from track2data.api import Engine
from track2data.metrics import get
from track2data.metrics.availability import (
    NEEDS_PIXEL_FRAME_REASON,
    NEEDS_SEVERAL_ANIMALS_REASON,
    manifest_depth_scale,
    manifest_view,
    unavailable_reason,
)

PIXEL_SIZED = ("IL-3", "IL-9", "IL-10", "IL-14")
GROUP = ("GL-1", "GL-3", "GL-5", "GL-7", "GL-16")
STILL_OFFERED = ("IL-1", "IL-2", "IL-16", "IL-17")


def _native():
    return _manifest(
        [_ref("n1")],
        calibration=SESSION_CM,
        individual=(*PIXEL_SIZED, *STILL_OFFERED),
        group=GROUP,
    )


def test_pixel_sized_and_group_metrics_are_unavailable_in_a_native_project() -> None:
    skipped = Engine(_native()).skipped_metrics(False)
    for mid in PIXEL_SIZED:
        assert skipped[mid] == NEEDS_PIXEL_FRAME_REASON
    for mid in GROUP:
        assert skipped[mid] == NEEDS_SEVERAL_ANIMALS_REASON
    for mid in STILL_OFFERED:
        assert mid not in skipped


def test_validate_names_the_same_reasons() -> None:
    manifest = _manifest([_ref("n1")], calibration=SESSION_CM, individual=("IL-14",))
    blocking, notes = Engine(manifest).validation_issues()
    text = " ".join([*blocking, *notes])
    assert NEEDS_PIXEL_FRAME_REASON in text


@pytest.mark.parametrize("mid", [*PIXEL_SIZED, *GROUP])
def test_the_one_function_agrees(mid: str) -> None:
    manifest = _native()
    view, has_depth = manifest_view(manifest)
    reason = unavailable_reason(
        get(mid), view, has_depth=has_depth, depth_scale=manifest_depth_scale(manifest)
    )
    assert reason in {NEEDS_PIXEL_FRAME_REASON, NEEDS_SEVERAL_ANIMALS_REASON}


def test_pixel_and_fused_projects_still_offer_them() -> None:
    pixel = _manifest(
        [_ref("p1", "idtrackerai")], individual=PIXEL_SIZED, group=GROUP[:2], camera_view="top"
    )
    skipped = Engine(pixel).skipped_metrics(False)
    assert not set(skipped) & {*PIXEL_SIZED, "GL-1", "GL-3"}
    fused = _manifest(
        [_ref("t1", "idtrackerai")],
        individual=PIXEL_SIZED,
        group=("GL-1", "GL-16"),
        dimension="3d",
    )
    skipped = Engine(fused).skipped_metrics(False)
    reasons = {NEEDS_PIXEL_FRAME_REASON, NEEDS_SEVERAL_ANIMALS_REASON}
    assert not reasons & set(skipped.values())
