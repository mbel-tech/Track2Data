"""A native 3-D project: who may join it, its calibration, and which metrics it offers.

The Qt halves (store, screens, stage status) are in test_project_rules_ui.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.test_api import _make_psess, _make_session
from tests.test_readers.native3d_files import write_anipose_csv
from track2data.api import (
    NATIVE_3D_NEEDS_SESSION_CALIBRATION,
    NATIVE_3D_UNIT_NOT_CONFIRMED,
    Engine,
    native_unit_issue,
)
from track2data.core.errors import CalibrationError, ImportError_
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
    NEEDS_SEVERAL_ANIMALS_REASON,
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


def _file_ref(tmp_path: Path, session_id: str, target: str | None = "cm") -> SessionRef:
    path = write_anipose_csv(tmp_path / f"{session_id}.csv", ["head"], 5)
    options: dict = {"fps": 50.0, "unit": "mm"}
    if target is not None:
        options["target_unit"] = target
    return SessionRef(
        session_id=session_id, folder=path, sha256="", reader="anipose", reader_options=options
    )


def test_import_ref_is_read_only_on_the_manifest(tmp_path: Path) -> None:
    ref = _file_ref(tmp_path, "n1", "m")
    manifest = _manifest([ref])
    engine = Engine(manifest)
    session = engine.import_ref(ref)
    assert session.coordinate_unit == "m"
    assert engine.manifest is manifest


@pytest.mark.parametrize(
    ("calibration", "expected"),
    [
        (CalibrationConfig(mode="bodylength"), NATIVE_3D_NEEDS_SESSION_CALIBRATION),
        (
            SESSION_CM.model_copy(update={"length_unit_confirmed_by_user": False}),
            NATIVE_3D_UNIT_NOT_CONFIRMED,
        ),
        (
            SESSION_CM.model_copy(update={"length_unit_label": "mm"}),
            native_unit_issue("mm", "cm", "a, b"),
        ),
    ],
    ids=["bodylength", "unconfirmed", "label-mm"],
)
def test_import_sessions_never_rewrites_an_existing_project(
    tmp_path: Path, calibration: CalibrationConfig, expected: str
) -> None:
    """import_sessions reads the project's own entries: none is new, so nothing is set up; a
    project that is not set up stays so and validate keeps saying why."""
    refs = [_file_ref(tmp_path, "a"), _file_ref(tmp_path, "b")]
    manifest = _manifest(refs, calibration=calibration, individual=("IL-1",))
    before = manifest.project_hash()
    engine = Engine(manifest)
    try:
        engine.import_sessions()
    except ImportError_ as exc:  # a confirmed label in another unit is refused, read-only
        assert exc.code == "NATIVE_3D_UNIT_MISMATCH"
    assert engine.manifest is manifest
    assert engine.manifest.project_hash() == before
    assert expected in engine.validate()


def test_a_fresh_project_is_set_up_by_its_add_not_by_import_sessions(tmp_path: Path) -> None:
    """The set-up belongs to the add: a batch whose entries were not in the project before."""
    refs = [_file_ref(tmp_path, "a", "mm"), _file_ref(tmp_path, "b", "mm")]
    engine = Engine(_manifest([]))
    engine.set_up_native_import([engine.read_ref(r) for r in refs])
    cal = engine.manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        "mm",
        True,
    )


@pytest.mark.parametrize("unit", ["cm", "mm"])
def test_a_batch_of_two_native_files_sets_the_calibration(unit: str) -> None:
    engine = Engine(_manifest([_ref("a"), _ref("b")]))
    engine.set_up_native_import([_native("a", unit=unit), _native("b", unit=unit)])
    cal = engine.manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        unit,
        True,
    )


def test_a_batch_with_two_targets_is_refused() -> None:
    engine = Engine(_manifest([_ref("a"), _ref("b")]))
    with pytest.raises(ImportError_) as info:
        engine.set_up_native_import([_native("a", unit="cm"), _native("b", unit="mm")])
    assert info.value.code == "NATIVE_3D_UNIT_MISMATCH"
    assert "'cm'" in str(info.value) and "'mm'" in str(info.value)
    assert engine.manifest.calibration.mode == "bodylength"


def test_a_mixed_batch_is_refused() -> None:
    engine = Engine(_manifest([]))
    with pytest.raises(ImportError_) as info:
        engine.set_up_native_import([_native("a"), _make_session("p1")])
    assert info.value.code == "NATIVE_3D_MIXED"
    assert "'a'" in str(info.value) and "p1" in str(info.value)
    assert engine.manifest.calibration.mode == "bodylength"


def test_a_batch_into_a_calibrated_native_project_with_another_target_is_refused() -> None:
    engine = Engine(_manifest([_ref("n1"), _ref("a"), _ref("b")], calibration=SESSION_CM))
    with pytest.raises(ImportError_) as info:
        engine.set_up_native_import([_native("a", unit="mm"), _native("b", unit="mm")])
    assert info.value.code == "NATIVE_3D_UNIT_MISMATCH"
    assert "'mm'" in str(info.value) and "'cm'" in str(info.value)
    assert engine.manifest.calibration == SESSION_CM


def test_a_batch_into_a_calibrated_native_project_with_its_target_changes_nothing() -> None:
    manifest = _manifest([_ref("n1"), _ref("a"), _ref("b")], calibration=SESSION_CM)
    engine = Engine(manifest)
    engine.set_up_native_import([_native("a"), _native("b")])
    assert engine.manifest is manifest


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


@pytest.mark.parametrize(
    "calibration",
    [CalibrationConfig(mode="scalar", px_per_cm=10.0), CalibrationConfig(mode="bodylength")],
)
def test_a_native_session_in_another_mode_is_refused(calibration: CalibrationConfig) -> None:
    engine = Engine(_manifest([_ref("n1")], calibration=calibration, individual=("IL-1",)))
    with pytest.raises(CalibrationError) as info:
        engine.preprocess(_native("n1"))
    assert info.value.code == "NATIVE_3D_NEEDS_SESSION_CALIBRATION"
    assert "Session" in info.value.remediation and "Calibration page" in info.value.remediation
    psess = Engine(_manifest([_ref("n1")], calibration=SESSION_CM)).preprocess(_native("n1"))
    with pytest.raises(CalibrationError) as info:
        engine.compute_metrics(psess)
    assert info.value.code == "NATIVE_3D_NEEDS_SESSION_CALIBRATION"
    # a pixel session in a scalar project keeps the scalar scale
    scalar = CalibrationConfig(mode="scalar", px_per_cm=10.0)
    pixel = Engine(_manifest([_ref("p1", None)], calibration=scalar))
    assert pixel._resolve_px_per_cm(_make_session("p1")) == 10.0


def test_t2d_run_refuses_a_native_session_in_another_mode(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from track2data.cli import cli
    from track2data.core.manifest import write as write_manifest

    project = tmp_path / "p.t2d.json"
    write_manifest(_manifest([_file_ref(tmp_path, "n1")], individual=("IL-1",)), project)
    out = CliRunner().invoke(cli, ["run", str(project), "-o", str(tmp_path / "out")])
    assert out.exit_code != 0
    assert "NATIVE_3D_NEEDS_SESSION_CALIBRATION" in out.output


# ── validate: each native set-up problem is its own readable error ───────────


@pytest.mark.parametrize("n_sessions", [1, 2])
def test_validate_reports_a_hand_edited_label_and_confirmation(
    tmp_path: Path, n_sessions: int
) -> None:
    refs = [_file_ref(tmp_path, f"n{i}") for i in range(n_sessions)]
    ids = ", ".join(r.session_id for r in refs)
    label_mm = SESSION_CM.model_copy(update={"length_unit_label": "mm"})
    manifest = _manifest(refs, calibration=label_mm, individual=("IL-1",))
    engine = Engine(manifest)
    before = manifest.project_hash()
    issues = engine.validate()
    assert native_unit_issue("mm", "cm", ids) in issues
    assert not any("could not be read" in issue for issue in issues)
    assert engine.manifest.project_hash() == before
    engine.run(tmp_path / "out")
    assert engine.manifest.project_hash() == before

    unconfirmed = SESSION_CM.model_copy(update={"length_unit_confirmed_by_user": False})
    manifest = _manifest(refs, calibration=unconfirmed, individual=("IL-1",))
    engine = Engine(manifest)
    issues = engine.validate()
    assert NATIVE_3D_UNIT_NOT_CONFIRMED in issues
    assert not any("could not be read" in issue for issue in issues)
    assert engine.manifest.project_hash() == manifest.project_hash()


def test_validate_reports_a_mixed_project(tmp_path: Path) -> None:
    refs = [_file_ref(tmp_path, "n1"), _ref("p1", "idtrackerai")]
    issues = Engine(_manifest(refs, calibration=SESSION_CM, individual=("IL-1",))).validate()
    assert any("NATIVE_3D_MIXED" in issue or "pixel-tracked" in issue for issue in issues)


def test_a_correct_native_project_validates(tmp_path: Path) -> None:
    refs = [_file_ref(tmp_path, "n1"), _file_ref(tmp_path, "n2", None)]
    assert Engine(_manifest(refs, calibration=SESSION_CM, individual=("IL-1",))).validate() == []


# ── availability ─────────────────────────────────────────────────────────────


def _native_psess(engine: Engine, session: Session | None = None):
    return engine.preprocess(session or _native("n1"))


def test_native_project_offers_the_three_3d_metrics() -> None:
    manifest = _manifest(
        [_ref("n1")], calibration=SESSION_CM, individual=("IL-16", "IL-17")
    )
    view, has_depth = manifest_view(manifest)
    assert (view, has_depth) == ("top", False)
    scale = manifest_depth_scale(manifest)
    assert scale["dimension"] == "3d" and scale["has_depth"] is True
    for mid in ("IL-16", "IL-17"):
        assert unavailable_reason(get(mid), view, has_depth=has_depth, depth_scale=scale) is None
    # GL-16 stays a fused-3-D metric: a native file holds one animal (see test_gating.py)
    assert unavailable_reason(
        get("GL-16"), view, has_depth=has_depth, depth_scale=scale
    ) == NEEDS_SEVERAL_ANIMALS_REASON
    engine = Engine(manifest)
    assert engine.skipped_metrics(False) == {}
    psess = _native_psess(engine)
    assert psess.depth is None and psess.z is not None
    assert engine.skipped_metrics(False, psess.session, psess=psess) == {}
    assert engine.skipped_metrics(False, psess.session) == {}
    results = engine.compute_metrics(psess)
    assert {"IL-16", "IL-17"} <= set(results)


def test_il15_needs_the_water_column_in_a_native_project() -> None:
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


# ── the CLI's add path ───────────────────────────────────────────────────────


def _cli_add(project: Path, root: Path, *extra: str):
    from click.testing import CliRunner

    from track2data.cli import cli

    args = ["add", str(project), str(root), "--yes", "--option", "fps=50", "--option", "unit=mm"]
    return CliRunner().invoke(cli, [*args, *extra])


@pytest.mark.parametrize("n_files", [1, 2])
@pytest.mark.parametrize("unit", ["cm", "mm"])
def test_cli_add_sets_the_calibration_of_a_native_project(
    tmp_path: Path, unit: str, n_files: int
) -> None:
    from track2data.core.manifest import read as read_manifest
    from track2data.core.manifest import write as write_manifest

    root = tmp_path / "pose"
    root.mkdir()
    for i in range(n_files):
        write_anipose_csv(root / f"fish{i}.csv", ["head"], 5)
    project = tmp_path / "p.t2d.json"
    write_manifest(_manifest([]), project)
    out = _cli_add(project, root, "--option", f"target_unit={unit}")
    assert out.exit_code == 0, out.output
    manifest = read_manifest(project)
    assert len(manifest.sessions) == n_files
    cal = manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        unit,
        True,
    )


def test_cli_add_refuses_another_target_in_a_calibrated_native_project(tmp_path: Path) -> None:
    from track2data.core.manifest import write as write_manifest

    root = tmp_path / "pose"
    root.mkdir()
    write_anipose_csv(root / "fish1.csv", ["head"], 5)
    write_anipose_csv(root / "fish2.csv", ["head"], 5)
    project = tmp_path / "p.t2d.json"
    write_manifest(_manifest([_ref("n0")], calibration=SESSION_CM), project)
    before = project.read_bytes()
    out = _cli_add(project, root, "--option", "target_unit=mm")
    assert out.exit_code != 0 and "NATIVE_3D_UNIT_MISMATCH" in out.output
    assert project.read_bytes() == before


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
