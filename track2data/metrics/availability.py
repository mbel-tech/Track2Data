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


def manifest_view(manifest: Any) -> tuple[str, bool]:
    """``(camera_view, has_depth)`` for availability decided from the manifest alone.

    A 3-D project runs fused sessions only, and a fused session is top-view with a depth;
    otherwise the project's declared view and no depth.
    """
    if manifest.mode.dimension == "3d":
        return "top", True
    return manifest.scene.camera_view, False


def view_unavailable_reason(
    metric_cls: Any, camera_view: str, *, has_depth: bool = False
) -> str | None:
    """Why *metric_cls* cannot run for a project with *camera_view*, or None when it can.

    A metric with ``uses_depth`` is available whenever the session has depth (*has_depth*).

    Read with ``getattr`` so a class (or a test double) that predates the attribute counts as
    "any view".
    """
    valid = getattr(metric_cls, "valid_camera_views", None)
    if valid is None or camera_view in valid:
        return None
    if has_depth and getattr(metric_cls, "uses_depth", False):
        return None
    return (
        f"needs a {required_views_text(metric_cls)} recording; the project's camera view is "
        f"{_VIEW_WORDS.get(camera_view, camera_view)} (set it on the Calibration screen)"
    )


NEEDS_FUSED_REASON = "needs a fused 3-D session"
NEEDS_CM_MODE_REASON = "needs a cm scale for the top view (use scalar or session calibration)"
NEEDS_CM_SCALE_REASON = "needs a cm scale for the top view"
DEPTH_SCALE_REASONS = frozenset({NEEDS_FUSED_REASON, NEEDS_CM_MODE_REASON, NEEDS_CM_SCALE_REASON})

# Manifest-level answers cannot know a unit's scale yet; they pass these stand-ins and leave the
# per-unit check to the run. The manifest answer is therefore optimistic: it only catches a 2-D
# project, a bodylength calibration and a scalar project with no px_per_cm (a session
# calibration's scale is only known per unit). A caller deciding for a run unit must overwrite
# both values from the unit.
_SCALE_ASSUMED = 1.0


def depth_scale_reason(
    metric_cls: Any,
    *,
    dimension: str,
    calibration_mode: str,
    has_depth: bool,
    px_per_cm: float | None,
    depth_height_cm: float | None,
) -> str | None:
    """Why a ``requires_depth_scale`` metric cannot run, or None (also for any other metric).

    Checked in order: not a fused 3-D session, then a manifest calibration mode that gives no
    cm scale (``bodylength``), then a unit without ``px_per_cm`` / ``depth_height_cm``.
    """
    if not getattr(metric_cls, "requires_depth_scale", False):
        return None
    if dimension != "3d" or not has_depth:
        return NEEDS_FUSED_REASON
    if calibration_mode == "bodylength":
        return NEEDS_CM_MODE_REASON
    if px_per_cm is None or depth_height_cm is None:
        return NEEDS_CM_SCALE_REASON
    return None


def manifest_depth_scale(manifest: Any) -> dict[str, Any]:
    """Keyword arguments of :func:`depth_scale_reason` decided from the manifest alone.

    Optimistic about the scale: ``depth_height_cm`` is a placeholder (1.0) and so is
    ``px_per_cm`` except in scalar mode, where the manifest's own value is used (None when unset).
    Session calibration is only known per unit. Replace both from the run unit before asking
    about a unit.
    """
    is_3d = manifest.mode.dimension == "3d"
    px_per_cm: float | None = _SCALE_ASSUMED
    if manifest.calibration.mode == "scalar":
        px_per_cm = manifest.calibration.px_per_cm
    return {
        "dimension": manifest.mode.dimension,
        "calibration_mode": manifest.calibration.mode,
        "has_depth": is_3d,
        "px_per_cm": px_per_cm,
        "depth_height_cm": _SCALE_ASSUMED,
    }


def unavailable_reason(
    metric_cls: Any,
    camera_view: str,
    *,
    has_depth: bool = False,
    depth_scale: dict[str, Any] | None = None,
) -> str | None:
    """The one answer: the camera-view reason, else the depth-scale reason, else None."""
    reason = view_unavailable_reason(metric_cls, camera_view, has_depth=has_depth)
    if reason is None and depth_scale is not None:
        reason = depth_scale_reason(metric_cls, **depth_scale)
    return reason


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
    *,
    has_depth: bool = False,
    depth_scale: dict[str, Any] | None = None,
) -> dict[str, str]:
    """``{metric_id: reason}`` for the ids in *metric_ids* that *camera_view* rules out.

    With *depth_scale* (keyword arguments of :func:`depth_scale_reason`) a metric that needs
    the 3-D positions in cm is ruled out too when they are unavailable.

    *lookup* maps an id to its class (``metrics.get``); an id it does not know is left alone,
    because the engine already reports an unregistered metric on its own.
    """
    skipped: dict[str, str] = {}
    for mid in metric_ids:
        cls = lookup(mid)
        if cls is None:
            continue
        reason = unavailable_reason(
            cls, camera_view, has_depth=has_depth, depth_scale=depth_scale
        )
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
