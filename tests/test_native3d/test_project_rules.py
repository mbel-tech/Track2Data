"""A native 3-D project: who may join it, its calibration, and which metrics it offers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.test_api import _make_psess, _make_session
from tests.test_readers.native3d_files import write_anipose_csv
from track2data.api import NATIVE_3D_NEEDS_SESSION_CALIBRATION, Engine
from track2data.core.errors import ImportError_
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    SceneConfig,
    Session,
    SessionRef,
    VideoInfo,
    WaterColumn,
)
from track2data.metrics import get
from track2data.metrics.availability import (
    NEEDS_FUSED_REASON,
    NEEDS_WATER_COLUMN_REASON,
    manifest_depth_scale,
    manifest_view,
    unavailable_reason,
)
from track2data.readers.native3d import manifest_native_3d

THREE_D_IDS = ("IL-16", "IL-17", "GL-16")
SESSION_CM = CalibrationConfig(
    mode="session", length_unit_label="cm", length_unit_confirmed_by_user=True
)


def _native(session_id: str = "n1", unit: str = "cm", reader: str = "anipose") -> Session:
    n = 20
    xy = np.zeros((n, 1, 2))
    xy[:, 0, 0] = np.arange(n, dtype=float)
    return Session(
        session_id=session_id,
        folder=Path("/tmp") / session_id,
        reader=reader,
        video=VideoInfo(fps=25.0, n_frames=n, width_px=0, height_px=0),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        raw_z=np.linspace(0.0, 10.0, n).reshape(n, 1),
        length_unit=1.0,
        has_pixel_frame=False,
        coordinate_unit=unit,
    )


def _ref(session_id: str, reader: str | None = "anipose", folder: Path | None = None):
    return SessionRef(
        session_id=session_id,
        folder=folder or Path("/tmp") / session_id,
        sha256="",
        reader=reader,
        reader_options={"fps": 25.0, "unit": "mm"} if reader == "anipose" else {},
    )


def _manifest(
    refs: list[SessionRef],
    *,
    calibration: CalibrationConfig | None = None,
    individual: tuple[str, ...] = (),
    group: tuple[str, ...] = (),
    dimension: str = "2d",
    camera_view: str = "unknown",
) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    mode = (
        ProjectMode(dimension="3d", layout="two_videos") if dimension == "3d" else ProjectMode()
    )
    return ProjectManifest(
        project_name="native",
        created_at=now,
        updated_at=now,
        sessions=refs,
        calibration=calibration or CalibrationConfig(),
        metrics=MetricSelection(individual=list(individual), group=list(group)),
        mode=mode,
        scene=SceneConfig(camera_view=camera_view),
    )


# ── project rules ────────────────────────────────────────────────────────────


def test_manifest_native_3d() -> None:
    assert manifest_native_3d(_manifest([_ref("n1"), _ref("n2", "deeplabcut_3d")]))
    assert not manifest_native_3d(_manifest([_ref("p1", "idtrackerai"), _ref("p2", None)]))
    assert not manifest_native_3d(_manifest([]))


def test_first_native_import_sets_calibration() -> None:
    engine = Engine(_manifest([_ref("n1")]))
    assert engine.manifest.calibration.mode == "bodylength"
    engine.register_native_import(_native("n1", unit="mm"))
    cal = engine.manifest.calibration
    assert cal.mode == "session"
    assert cal.length_unit_label == "mm"
    assert cal.length_unit_confirmed_by_user is True


def test_first_native_import_through_import_ref(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "pose.csv", ["head"], 5)
    ref = SessionRef(
        session_id="n1",
        folder=path,
        sha256="",
        reader="anipose",
        reader_options={"fps": 50.0, "unit": "mm", "target_unit": "m"},
    )
    engine = Engine(_manifest([ref]))
    session = engine.import_ref(ref)
    assert session.coordinate_unit == "m"
    cal = engine.manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        "m",
        True,
    )


def test_registering_an_already_set_native_project_changes_nothing() -> None:
    manifest = _manifest([_ref("n1"), _ref("n2")], calibration=SESSION_CM)
    engine = Engine(manifest)
    engine.register_native_import(_native("n2"))
    assert engine.manifest is manifest


def test_second_import_with_other_target_is_refused() -> None:
    engine = Engine(_manifest([_ref("n1"), _ref("n2")], calibration=SESSION_CM))
    with pytest.raises(ImportError_) as info:
        engine.register_native_import(_native("n2", unit="mm"))
    assert info.value.code == "NATIVE_3D_UNIT_MISMATCH"
    message = str(info.value)
    assert "'mm'" in message and "'cm'" in message
    assert engine.manifest.calibration == SESSION_CM


def test_native_into_pixel_project_and_back_are_refused() -> None:
    pixel_project = Engine(_manifest([_ref("p1", "idtrackerai"), _ref("n1")]))
    with pytest.raises(ImportError_) as info:
        pixel_project.register_native_import(_native("n1"))
    assert info.value.code == "NATIVE_3D_MIXED"
    message = str(info.value)
    assert "'n1'" in message and "native 3-D" in message and "pixel" in message
    assert pixel_project.manifest.calibration.mode == "bodylength"

    native_project = Engine(_manifest([_ref("n1"), _ref("p1", None)], calibration=SESSION_CM))
    with pytest.raises(ImportError_) as info:
        native_project.register_native_import(_make_session("p1"))
    assert info.value.code == "NATIVE_3D_MIXED"
    message = str(info.value)
    assert "'p1'" in message and "native 3-D" in message and "pixel" in message


def test_native_refused_in_a_fused_3d_project() -> None:
    engine = Engine(_manifest([_ref("n1")], dimension="3d"))
    with pytest.raises(ImportError_) as info:
        engine.register_native_import(_native("n1"))
    assert info.value.code == "NATIVE_3D_MIXED"
    assert "'n1'" in str(info.value) and "fused" in str(info.value)


def test_pixel_sessions_register_as_a_no_op() -> None:
    manifest = _manifest([_ref("p1", None), _ref("p2", "idtrackerai")])
    engine = Engine(manifest)
    engine.register_native_import(_make_session("p1"))
    assert engine.manifest is manifest
    fused = _manifest([_ref("p1", None)], dimension="3d")
    engine = Engine(fused)
    engine.register_native_import(_make_session("p1"))
    assert engine.manifest is fused


def test_validate_requires_session_mode() -> None:
    scalar = CalibrationConfig(mode="scalar", px_per_cm=10.0)
    issues = Engine(_manifest([_ref("n1")], calibration=scalar, individual=("IL-1",))).validate()
    assert NATIVE_3D_NEEDS_SESSION_CALIBRATION in issues
    issues = Engine(
        _manifest([_ref("n1")], calibration=SESSION_CM, individual=("IL-1",))
    ).validate()
    assert NATIVE_3D_NEEDS_SESSION_CALIBRATION not in issues
    # a pixel project in scalar mode is not asked for it
    issues = Engine(
        _manifest([_ref("p1", None)], calibration=scalar, individual=("IL-1",))
    ).validate()
    assert NATIVE_3D_NEEDS_SESSION_CALIBRATION not in issues


def test_a_native_session_is_calibrated_by_its_own_unit_whatever_the_mode() -> None:
    scalar = CalibrationConfig(mode="scalar", px_per_cm=10.0)
    engine = Engine(_manifest([_ref("n1")], calibration=scalar))
    psess = engine.preprocess(_native("n1"))
    assert psess.px_per_cm == 1.0
    assert engine._resolve_px_per_cm(_native("n1")) == 1.0
    # a pixel session in a scalar project keeps the scalar scale
    pixel = Engine(_manifest([_ref("p1", None)], calibration=scalar))
    assert pixel._resolve_px_per_cm(_make_session("p1")) == 10.0


# ── availability ─────────────────────────────────────────────────────────────


def _native_psess(engine: Engine, session: Session | None = None):
    return engine.preprocess(session or _native("n1"))


def test_native_project_offers_the_three_3d_metrics() -> None:
    manifest = _manifest(
        [_ref("n1")], calibration=SESSION_CM, individual=("IL-16", "IL-17"), group=("GL-16",)
    )
    view, has_depth = manifest_view(manifest)
    assert (view, has_depth) == ("top", False)
    scale = manifest_depth_scale(manifest)
    assert scale["dimension"] == "3d" and scale["has_depth"] is True
    for mid in THREE_D_IDS:
        assert unavailable_reason(get(mid), view, has_depth=has_depth, depth_scale=scale) is None
    engine = Engine(manifest)
    assert engine.skipped_metrics(False) == {}
    psess = _native_psess(engine)
    assert psess.depth is None and psess.z is not None
    assert engine.skipped_metrics(False, psess.session, psess=psess) == {}
    assert engine.skipped_metrics(False, psess.session) == {}
    results = engine.compute_metrics(psess)
    assert set(THREE_D_IDS) <= set(results)


def test_il15_needs_the_water_column_in_a_native_project(qtbot) -> None:
    pytest.importorskip("PySide6")
    manifest = _manifest([_ref("n1")], calibration=SESSION_CM, individual=("IL-15",))
    engine = Engine(manifest)
    assert engine.skipped_metrics(False) == {"IL-15": NEEDS_WATER_COLUMN_REASON}
    psess = _native_psess(engine)
    assert engine.skipped_metrics(False, psess.session, psess=psess) == {
        "IL-15": NEEDS_WATER_COLUMN_REASON
    }
    assert engine.skipped_metrics(False, psess.session) == {"IL-15": NEEDS_WATER_COLUMN_REASON}
    issues = engine.validate()
    assert any(f"IL-15: {NEEDS_WATER_COLUMN_REASON}." in issue for issue in issues)
    assert not any("camera view" in issue for issue in issues)

    # with another metric selected, the note (not a block) carries the same reason
    both = Engine(manifest.model_copy(update={"metrics": MetricSelection(
        individual=["IL-1", "IL-15"]
    )}))
    assert both._view_selection_notes() == [f"IL-15 will be skipped: {NEEDS_WATER_COLUMN_REASON}."]

    from ui.metrics_screen import MetricsScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store._manifest = manifest
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)
    table = screen._ind_table
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).data(256) == "IL-15")
    tip = table.item(row, 0).toolTip()
    assert tip == NEEDS_WATER_COLUMN_REASON[0].upper() + NEEDS_WATER_COLUMN_REASON[1:] + "."


def test_il15_available_with_the_water_column() -> None:
    calibration = SESSION_CM.model_copy(
        update={"water_column": WaterColumn(surface_z=0.0, floor_z=10.0)}
    )
    manifest = _manifest([_ref("n1")], calibration=calibration, individual=("IL-15", "IL-16"))
    assert manifest_view(manifest) == ("top", True)
    engine = Engine(manifest)
    assert engine.skipped_metrics(False) == {}
    psess = _native_psess(engine)
    assert psess.depth is not None
    assert engine.skipped_metrics(False, psess.session, psess=psess) == {}
    assert engine.skipped_metrics(False, psess.session) == {}
    assert "IL-15" in engine.compute_metrics(psess)


def test_2d_and_fused_projects_unchanged() -> None:
    pixel = _manifest([_ref("p1", None)], camera_view="top", individual=("IL-15", "IL-16"))
    assert manifest_view(pixel) == ("top", False)
    skipped = Engine(pixel).skipped_metrics(False)
    assert skipped["IL-16"] == NEEDS_FUSED_REASON
    assert "camera view is top-down" in skipped["IL-15"]
    assert "native_3d" not in manifest_depth_scale(pixel) or not manifest_depth_scale(pixel)[
        "native_3d"
    ]
    psess = _make_psess(_make_session("p1"))
    unit = Engine(pixel).skipped_metrics(False, psess.session, psess=psess)
    assert unit["IL-16"] == NEEDS_FUSED_REASON and "camera view" in unit["IL-15"]

    fused = _manifest(
        [_ref("p1", None)],
        dimension="3d",
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        individual=("IL-15", "IL-16"),
    )
    assert manifest_view(fused) == ("top", True)
    assert Engine(fused).skipped_metrics(False) == {}
    fused_unit = _make_psess(_make_session("p1"))
    fused_unit.px_per_cm = 10.0
    no_scale = Engine(fused).skipped_metrics(False, fused_unit.session, psess=fused_unit)
    assert no_scale["IL-16"] == NEEDS_FUSED_REASON


# ── the GUI's add path goes through the same Engine function ─────────────────


def _store_with(manifest: ProjectManifest):
    pytest.importorskip("PySide6")
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store._manifest = manifest
    return store


def test_the_store_registers_a_probed_native_session(qtbot) -> None:
    store = _store_with(_manifest([_ref("n1")]))
    store._identity_probes["task-1"] = "n1"
    store._new_session_ids.add("n1")
    changed: list[bool] = []
    store.calibrationChanged.connect(lambda: changed.append(True))
    store._on_identity_probe_finished("task-1", _native("pose", unit="mm"))
    cal = store.manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        "mm",
        True,
    )
    assert changed and store.session_facts("n1") is not None


def test_the_store_removes_a_refused_session_and_says_why(qtbot) -> None:
    store = _store_with(_manifest([_ref("p1", "idtrackerai"), _ref("n1")]))
    store._identity_probes["task-1"] = "n1"
    store._new_session_ids.add("n1")
    logged: list[str] = []
    refused: list[tuple[str, str]] = []
    store.runLogAppended.connect(logged.append)
    store.sessionRefused.connect(lambda sid, msg: refused.append((sid, msg)))
    store._on_identity_probe_finished("task-1", _native("pose"))
    assert [ref.session_id for ref in store.manifest.sessions] == ["p1"]
    assert store.session_facts("n1") is None
    assert refused and refused[0][0] == "n1" and "NATIVE_3D_MIXED" in refused[0][1]
    assert any("NATIVE_3D_MIXED" in line for line in logged)
    assert store.manifest.calibration.mode == "bodylength"


def test_reopening_a_project_does_not_register_again(qtbot) -> None:
    """A probe of a session already in the project (open_project) changes nothing."""
    manifest = _manifest([_ref("n1")], calibration=CalibrationConfig(mode="scalar"))
    store = _store_with(manifest)
    store._identity_probes["task-1"] = "n1"
    store._on_identity_probe_finished("task-1", _native("pose"))
    assert store.manifest.calibration.mode == "scalar"
    assert [ref.session_id for ref in store.manifest.sessions] == ["n1"]


# ── the CLI's add path ───────────────────────────────────────────────────────


def _cli_add(project: Path, root: Path, *extra: str):
    from click.testing import CliRunner

    from track2data.cli import cli

    args = ["add", str(project), str(root), "--yes", "--option", "fps=50", "--option", "unit=mm"]
    return CliRunner().invoke(cli, [*args, *extra])


def test_cli_add_sets_the_calibration_of_a_native_project(tmp_path: Path) -> None:
    from track2data.core.manifest import read as read_manifest
    from track2data.core.manifest import write as write_manifest

    root = tmp_path / "pose"
    root.mkdir()
    write_anipose_csv(root / "fish1.csv", ["head"], 5)
    project = tmp_path / "p.t2d.json"
    write_manifest(_manifest([]), project)
    out = _cli_add(project, root, "--option", "target_unit=mm")
    assert out.exit_code == 0, out.output
    cal = read_manifest(project).calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        "mm",
        True,
    )


def test_cli_add_refuses_native_files_in_a_pixel_project(tmp_path: Path) -> None:
    from track2data.core.manifest import write as write_manifest

    root = tmp_path / "pose"
    root.mkdir()
    write_anipose_csv(root / "fish1.csv", ["head"], 5)
    project = tmp_path / "p.t2d.json"
    write_manifest(_manifest([_ref("p1", "idtrackerai")]), project)
    before = project.read_bytes()
    out = _cli_add(project, root)
    assert out.exit_code != 0
    assert "NATIVE_3D_MIXED" in out.output
    assert project.read_bytes() == before
