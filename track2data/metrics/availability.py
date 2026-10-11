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


def _is_native_3d(manifest: Any) -> bool:
    """Whether *manifest* is a native 3-D project (a 2-D-mode project of native 3-D sessions)."""
    from track2data.readers.native3d import manifest_native_3d

    return manifest.mode.dimension != "3d" and manifest_native_3d(manifest)


def manifest_view(manifest: Any) -> tuple[str, bool]:
    """``(camera_view, has_depth)`` for availability decided from the manifest alone.

    A 3-D project runs fused sessions only, and a fused session is top-view with a depth. A
    native 3-D project's declared view is irrelevant: it is top-view (the 2-D metrics run on the
    horizontal plane), with a depth once the Calibration page has its water column. Otherwise
    the project's declared view and no depth.
    """
    if manifest.mode.dimension == "3d":
        return "top", True
    if _is_native_3d(manifest):
        return "top", manifest.calibration.water_column is not None
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
#: A depth metric (IL-15) in a native 3-D project, until the water column is given.
NEEDS_WATER_COLUMN_REASON = (
    "needs the water column (surface and floor z) on the Calibration page"
)
#: The same reason as the command line says it (there is no Calibration page there).
_WATER_COLUMN_CLI_REASON = NEEDS_WATER_COLUMN_REASON.replace(
    "Calibration page", "calibration settings (`calibration.water_column` in the project)"
)


def reason_for_cli(reason: str) -> str:
    """*reason* as the command line prints it: the water-column reason names the project setting.

    Works on a line that quotes the reason too; every other text comes back unchanged.
    """
    return reason.replace(NEEDS_WATER_COLUMN_REASON, _WATER_COLUMN_CLI_REASON)


#: Metrics whose default threshold, bin or arena is sized in video pixels (IL-3 arena, IL-9 and
#: IL-10 occupancy bins, IL-14 wall distance). A native 3-D file has no pixels, so the same number
#: would silently mean the project unit and change with ``target_unit``.
PIXEL_FRAME_METRIC_IDS = frozenset({"IL-3", "IL-9", "IL-10", "IL-14"})
#: Why those four are unavailable in a native 3-D project.
NEEDS_PIXEL_FRAME_REASON = (
    "uses a pixel-sized default and the project's native 3-D files have no pixel frame"
)
#: Why every group-level metric is unavailable in a native 3-D project.
NEEDS_SEVERAL_ANIMALS_REASON = (
    "needs several animals in one session; a native 3-D file holds one animal"
)
#: The reasons that are 3-D requirements rather than the camera view.
DEPTH_SCALE_REASONS = frozenset(
    {
        NEEDS_FUSED_REASON,
        NEEDS_CM_MODE_REASON,
        NEEDS_CM_SCALE_REASON,
        NEEDS_WATER_COLUMN_REASON,
        NEEDS_PIXEL_FRAME_REASON,
        NEEDS_SEVERAL_ANIMALS_REASON,
    }
)

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
    native_3d: bool = False,
) -> str | None:
    """Why a ``requires_depth_scale`` metric cannot run, or None (also for any other metric).

    Checked in order: not a fused 3-D session, then a manifest calibration mode that gives no
    cm scale (``bodylength``), then a unit without ``px_per_cm`` / ``depth_height_cm``.

    *native_3d* marks native 3-D data (its ``z`` is absolute, in the project unit), which needs
    no ``depth_height_cm``.
    """
    if not getattr(metric_cls, "requires_depth_scale", False):
        return None
    if dimension != "3d" or not has_depth:
        return NEEDS_FUSED_REASON
    if calibration_mode == "bodylength":
        return NEEDS_CM_MODE_REASON
    if px_per_cm is None or (depth_height_cm is None and not native_3d):
        return NEEDS_CM_SCALE_REASON
    return None


def manifest_depth_scale(manifest: Any) -> dict[str, Any]:
    """Keyword arguments of :func:`depth_scale_reason` decided from the manifest alone.

    Optimistic about the scale: ``depth_height_cm`` is a placeholder (1.0) and so is
    ``px_per_cm`` except in scalar mode, where the manifest's own value is used (None when unset).
    Session calibration is only known per unit. Replace both from the run unit before asking
    about a unit.

    A native 3-D project (2-D mode, sessions from a native reader) reports ``dimension "3d"``
    and ``has_depth True``: for these arguments the names mean "3-D data present", which its
    absolute ``z`` is, water column or not. ``native_3d`` says which kind of 3-D data it is
    (only a native project carries it as True).
    """
    native = _is_native_3d(manifest)
    is_3d = manifest.mode.dimension == "3d" or native
    px_per_cm: float | None = _SCALE_ASSUMED
    if manifest.calibration.mode == "scalar":
        px_per_cm = manifest.calibration.px_per_cm
    scale: dict[str, Any] = {
        "dimension": "3d" if is_3d else manifest.mode.dimension,
        "calibration_mode": manifest.calibration.mode,
        "has_depth": is_3d,
        "px_per_cm": px_per_cm,
        "depth_height_cm": _SCALE_ASSUMED,
    }
    if native:
        scale["native_3d"] = True
    return scale


def unavailable_reason(
    metric_cls: Any,
    camera_view: str,
    *,
    has_depth: bool = False,
    depth_scale: dict[str, Any] | None = None,
) -> str | None:
    """The one answer: the camera-view reason, else the depth-scale reason, else None.

    In a native 3-D project (``depth_scale["native_3d"]``) a depth metric without a depth is
    waiting for the water column, never for a camera view: :data:`NEEDS_WATER_COLUMN_REASON`.
    A native project also rules out the metrics sized in pixels (:data:`NEEDS_PIXEL_FRAME_REASON`)
    and every group-level metric (:data:`NEEDS_SEVERAL_ANIMALS_REASON`: one animal per file). The
    data-extent arena fallback of ``metrics/derived.py`` is therefore not reachable in a run.
    """
    if depth_scale is not None and depth_scale.get("native_3d", False):
        if getattr(metric_cls, "id", None) in PIXEL_FRAME_METRIC_IDS:
            return NEEDS_PIXEL_FRAME_REASON
        if getattr(metric_cls, "level", None) == "group":
            return NEEDS_SEVERAL_ANIMALS_REASON
        if getattr(metric_cls, "uses_depth", False) and not has_depth:
            return NEEDS_WATER_COLUMN_REASON
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
