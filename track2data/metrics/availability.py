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


def view_label(camera_view: str) -> str:
    """A camera view in words ("side view"), for sentences and tables."""
    return _VIEW_WORDS.get(camera_view, camera_view)


def view_unavailable_reason(metric_cls: Any, camera_view: str) -> str | None:
    """Why *metric_cls* cannot run for a project with *camera_view*, or None when it can.

    Read with ``getattr`` so a class (or a test double) that predates the attribute counts as
    "any view".
    """
    valid = getattr(metric_cls, "valid_camera_views", None)
    if valid is None or camera_view in valid:
        return None
    return (
        f"needs a {required_views_text(metric_cls)} recording; the project's camera view is "
        f"{_VIEW_WORDS.get(camera_view, camera_view)} (set it on the Calibration screen)"
    )


def required_views_text(metric_cls: Any) -> str | None:
    """The views *metric_cls* is meaningful for, in words ("side view"), or None for any view."""
    valid = getattr(metric_cls, "valid_camera_views", None)
    if valid is None:
        return None
    ordered = [view for view in _VIEW_WORDS if view in valid]
    ordered += sorted(v for v in valid if v not in _VIEW_WORDS)
    return " or ".join(_VIEW_WORDS.get(v, v) for v in ordered)


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


def view_dependent_metrics(
    metric_ids: Iterable[str],
    camera_view: str,
    lookup: Callable[[str], Any],
) -> list[str]:
    """The ids in *metric_ids* that only run for views that include *camera_view*.

    These are the metrics a project gets *because* it declared that view, so the screens use it
    to ask for what such a view needs (a side view needs a water column) only when something
    selected will use it.
    """
    needing: list[str] = []
    for mid in metric_ids:
        valid = getattr(lookup(mid), "valid_camera_views", None)
        if valid is not None and camera_view in valid:
            needing.append(mid)
    return needing
