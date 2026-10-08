"""Which metrics a project's camera view rules out.

A metric names the views it is meaningful for in ``Metric.valid_camera_views`` (``None`` = any
view). The engine, the validator, the CLI and the Metrics screen all ask this one module, so
they cannot disagree about whether a row is available or why it is not.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

# How each camera view reads in a sentence. "unknown" is the default of a project that never
# declared one.
_VIEW_WORDS = {"unknown": "not set", "top": "top-down", "side": "side view"}


def view_unavailable_reason(metric_cls: Any, camera_view: str) -> str | None:
    """Why *metric_cls* cannot run for a project with *camera_view*, or None when it can.

    Read with ``getattr`` so a class (or a test double) that predates the attribute counts as
    "any view".
    """
    valid = getattr(metric_cls, "valid_camera_views", None)
    if valid is None or camera_view in valid:
        return None
    needed = " or ".join(_VIEW_WORDS.get(v, v) for v in sorted(valid))
    return (
        f"needs a recording made from this view: {needed}; the project's camera view is "
        f"{_VIEW_WORDS.get(camera_view, camera_view)} (set it on the Calibration screen)"
    )


def view_skipped_metrics(
    metric_ids: Iterable[str],
    camera_view: str,
    lookup: Callable[[str], Any],
) -> dict[str, str]:
    """``{metric_id: reason}`` for the ids in *metric_ids* that *camera_view* rules out.

    *lookup* maps an id to its class (``metrics.get``); an id it does not know is left alone,
    because the engine already reports an unregistered metric on its own.
    """
    skipped: dict[str, str] = {}
    for mid in metric_ids:
        cls = lookup(mid)
        if cls is None:
            continue
        reason = view_unavailable_reason(cls, camera_view)
        if reason is not None:
            skipped[mid] = reason
    return skipped
