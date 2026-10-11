"""Which metrics a project's camera view rules out, and why."""

from __future__ import annotations

import pytest

from track2data.metrics.availability import (
    depth_scale_reason,
    view_skipped_metrics,
    view_unavailable_reason,
)


class _AnyView:
    id = "IL-ANY"


class _SideOnly:
    id = "IL-SIDE"
    valid_camera_views = frozenset({"side"})


class _TopOrUnknown:
    id = "IL-TOP"
    valid_camera_views = frozenset({"top", "unknown"})


@pytest.mark.parametrize("view", ["unknown", "top", "side"])
def test_a_metric_that_declares_no_views_is_never_ruled_out(view: str) -> None:
    """The default is 'any view': a metric (or a test double) with no attribute is unaffected."""
    assert view_unavailable_reason(_AnyView, view) is None


@pytest.mark.parametrize(
    ("cls", "view", "available"),
    [
        (_SideOnly, "side", True),
        (_SideOnly, "top", False),
        (_SideOnly, "unknown", False),
        (_TopOrUnknown, "top", True),
        (_TopOrUnknown, "unknown", True),
        (_TopOrUnknown, "side", False),
    ],
)
def test_truth_table(cls: type, view: str, available: bool) -> None:
    assert (view_unavailable_reason(cls, view) is None) is available


def test_the_reason_names_the_needed_view_the_actual_view_and_the_fix() -> None:
    reason = view_unavailable_reason(_SideOnly, "unknown")
    assert reason is not None
    assert reason.startswith("needs a side view recording")
    assert "not set" in reason
    assert "Calibration" in reason

    top_reason = view_unavailable_reason(_SideOnly, "top")
    assert top_reason is not None
    assert "top-down" in top_reason


def test_view_skipped_metrics_maps_only_the_ruled_out_ids() -> None:
    registry = {"IL-ANY": _AnyView, "IL-SIDE": _SideOnly}
    skipped = view_skipped_metrics(["IL-ANY", "IL-SIDE", "IL-GONE"], "unknown", registry.get)
    assert set(skipped) == {"IL-SIDE"}
    assert view_skipped_metrics(["IL-ANY", "IL-SIDE"], "side", registry.get) == {}


def test_required_views_text_names_the_views_or_nothing() -> None:
    from track2data.metrics.availability import required_views_text

    assert required_views_text(_AnyView) is None
    assert required_views_text(_SideOnly) == "side view"
    assert required_views_text(_TopOrUnknown) == "not set or top-down"


def test_the_reason_uses_the_same_wording_as_required_views_text() -> None:
    from track2data.metrics.availability import required_views_text

    reason = view_unavailable_reason(_TopOrUnknown, "side")
    assert reason is not None
    assert required_views_text(_TopOrUnknown) in reason


class _DepthMetric:
    id = "IL-DEPTH"
    valid_camera_views = frozenset({"side"})
    uses_depth = True


@pytest.mark.parametrize("view", ["unknown", "top", "side"])
def test_a_depth_metric_is_available_for_a_session_with_depth(view: str) -> None:
    assert view_unavailable_reason(_DepthMetric, view, has_depth=True) is None


def test_a_depth_metric_without_depth_keeps_its_view_reason() -> None:
    assert view_unavailable_reason(_DepthMetric, "top") == view_unavailable_reason(
        _SideOnly, "top"
    )
    assert view_unavailable_reason(_DepthMetric, "side") is None


def test_has_depth_does_not_widen_other_metrics() -> None:
    assert view_unavailable_reason(_SideOnly, "top", has_depth=True) is not None
    registry = {"IL-SIDE": _SideOnly, "IL-DEPTH": _DepthMetric}
    skipped = view_skipped_metrics(["IL-SIDE", "IL-DEPTH"], "top", registry.get, has_depth=True)
    assert set(skipped) == {"IL-SIDE"}


def test_view_skipped_metrics_adds_the_depth_scale_reason() -> None:
    class _Flagged:
        id = "IL-FLAG"
        requires_depth_scale = True

    scale = {
        "dimension": "2d",
        "calibration_mode": "scalar",
        "has_depth": False,
        "px_per_cm": 1.0,
        "depth_height_cm": 1.0,
    }
    lookup = {"IL-FLAG": _Flagged, "IL-ANY": _AnyView}.get
    ids = ["IL-FLAG", "IL-ANY"]
    assert view_skipped_metrics(ids, "top", lookup, depth_scale=scale) == {
        "IL-FLAG": "needs a fused 3-D session"
    }
    # without the depth-scale arguments the answer is the camera-view one only
    assert view_skipped_metrics(ids, "top", lookup) == {}


def test_manifest_depth_scale_uses_the_scalar_value_when_set() -> None:
    from tests.test_api import _make_manifest
    from track2data.core.models import CalibrationConfig, ProjectMode
    from track2data.metrics.availability import manifest_depth_scale

    three_d = ProjectMode(dimension="3d", layout="two_videos")
    unset = _make_manifest(calibration=CalibrationConfig(mode="scalar")).model_copy(
        update={"mode": three_d}
    )
    assert manifest_depth_scale(unset)["px_per_cm"] is None
    from track2data.metrics import get

    assert (
        depth_scale_reason(get("IL-16"), **manifest_depth_scale(unset))
        == "needs a cm scale for the top view"
    )
    calibration = CalibrationConfig(mode="scalar", px_per_cm=9.0)
    given = unset.model_copy(update={"calibration": calibration})
    assert manifest_depth_scale(given)["px_per_cm"] == 9.0
    assert depth_scale_reason(get("IL-16"), **manifest_depth_scale(given)) is None
    session = unset.model_copy(update={"calibration": CalibrationConfig(mode="session")})
    assert depth_scale_reason(get("IL-16"), **manifest_depth_scale(session)) is None


def test_a_native_project_has_3d_data_and_asks_for_the_water_column() -> None:
    from pathlib import Path

    from tests.test_api import _make_manifest
    from track2data.core.models import CalibrationConfig, SceneConfig, SessionRef, WaterColumn
    from track2data.metrics import get
    from track2data.metrics.availability import (
        DEPTH_SCALE_REASONS,
        NEEDS_WATER_COLUMN_REASON,
        manifest_depth_scale,
        manifest_view,
        unavailable_reason,
    )

    assert NEEDS_WATER_COLUMN_REASON == (
        "needs the water column (surface and floor z) on the Calibration page"
    )
    assert NEEDS_WATER_COLUMN_REASON in DEPTH_SCALE_REASONS
    ref = SessionRef(session_id="n", folder=Path("n"), sha256="", reader="deeplabcut_3d")
    native = _make_manifest(
        sessions=[ref], calibration=CalibrationConfig(mode="session")
    ).model_copy(update={"scene": SceneConfig(camera_view="side")})
    view, has_depth = manifest_view(native)
    assert (view, has_depth) == ("top", False)  # the declared view is irrelevant
    scale = manifest_depth_scale(native)
    assert scale["dimension"] == "3d" and scale["has_depth"] is True
    for mid in ("IL-16", "IL-17", "GL-16", "IL-1"):
        assert unavailable_reason(get(mid), view, has_depth=has_depth, depth_scale=scale) is None
    assert (
        unavailable_reason(get("IL-15"), view, has_depth=has_depth, depth_scale=scale)
        == NEEDS_WATER_COLUMN_REASON
    )
    # a native unit has no depth_height_cm without a water column: z is enough
    unit = {**scale, "px_per_cm": 1.0, "depth_height_cm": None}
    assert unavailable_reason(get("IL-16"), "top", depth_scale=unit) is None

    calibration = CalibrationConfig(
        mode="session", water_column=WaterColumn(surface_z=0.0, floor_z=5.0)
    )
    with_column = native.model_copy(update={"calibration": calibration})
    view, has_depth = manifest_view(with_column)
    assert (view, has_depth) == ("top", True)
    assert (
        unavailable_reason(
            get("IL-15"), view, has_depth=has_depth, depth_scale=manifest_depth_scale(with_column)
        )
        is None
    )
