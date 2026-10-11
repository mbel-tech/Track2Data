"""A native 3-D project in the GUI: the add path, the Metrics screen and the stage status."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from tests.test_native3d.test_project_rules import SESSION_CM, _manifest, _native, _ref
from track2data.core.models import CalibrationConfig, ProjectManifest, SessionRef
from track2data.metrics.availability import NEEDS_WATER_COLUMN_REASON


def _store_with(manifest: ProjectManifest):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store._manifest = manifest
    return store


def _native_ref(session_id: str, target: str | None = None) -> SessionRef:
    options: dict = {"fps": 25.0, "unit": "mm"}
    if target is not None:
        options["target_unit"] = target
    return SessionRef(
        session_id=session_id,
        folder=Path("/tmp") / f"{session_id}.csv",
        sha256="",
        reader="anipose",
        reader_options=options,
    )


def _no_probes(store, monkeypatch) -> list[str]:
    """Record the probes a store would submit, without running any."""
    submitted: list[str] = []
    monkeypatch.setattr(store, "_submit_probe", lambda sid, folder: submitted.append(sid))
    return submitted


def _finish_probe(store, session_id: str, session) -> None:
    task = f"task-{session_id}"
    store._identity_probes[task] = session_id
    store._on_identity_probe_finished(task, session)


def _cal(store):
    cal = store.manifest.calibration
    return cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user


# ── the add path ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("unit", ["cm", "mm"])
def test_adding_two_native_files_at_once_sets_the_calibration(
    qtbot, monkeypatch, unit: str
) -> None:
    store = _store_with(_manifest([]))
    _no_probes(store, monkeypatch)
    added = store.add_confirmed([_native_ref("a", unit), _native_ref("b", unit)])
    assert [r.session_id for r in added] == ["a", "b"]
    _finish_probe(store, "a", _native("a", unit=unit))
    assert store.manifest.calibration.mode == "bodylength"  # waits for the whole batch
    _finish_probe(store, "b", _native("b", unit=unit))
    assert _cal(store) == ("session", unit, True)
    assert [r.session_id for r in store.manifest.sessions] == ["a", "b"]


def _refused(store) -> list[tuple[str, str]]:
    refused: list[tuple[str, str]] = []
    store.sessionRefused.connect(lambda sid, msg: refused.append((sid, msg)))
    return refused


def test_a_mixed_batch_is_refused_before_anything_is_listed(qtbot, monkeypatch) -> None:
    store = _store_with(_manifest([]))
    submitted = _no_probes(store, monkeypatch)
    refused = _refused(store)
    pixel = SessionRef(session_id="p1", folder=Path("/tmp/p1"), sha256="", reader="idtrackerai")
    assert store.add_confirmed([_native_ref("a"), pixel]) == []
    assert store.manifest.sessions == [] and submitted == []
    assert refused and "NATIVE_3D_MIXED" in refused[0][1]


def test_a_batch_with_two_targets_is_refused_before_anything_is_listed(
    qtbot, monkeypatch
) -> None:
    store = _store_with(_manifest([]))
    _no_probes(store, monkeypatch)
    refused = _refused(store)
    assert store.add_confirmed([_native_ref("a", "cm"), _native_ref("b", "mm")]) == []
    assert store.manifest.sessions == []
    assert refused and "NATIVE_3D_UNIT_MISMATCH" in refused[0][1]


def test_native_files_into_a_pixel_project_are_refused_before_listing(
    qtbot, monkeypatch
) -> None:
    store = _store_with(_manifest([_ref("p1", "idtrackerai")]))
    _no_probes(store, monkeypatch)
    refused = _refused(store)
    assert store.add_confirmed([_native_ref("a")]) == []
    assert [r.session_id for r in store.manifest.sessions] == ["p1"]
    assert refused and "NATIVE_3D_MIXED" in refused[0][1]


def test_another_target_into_a_calibrated_native_project_is_refused(
    qtbot, monkeypatch
) -> None:
    store = _store_with(_manifest([_ref("n1")], calibration=SESSION_CM))
    _no_probes(store, monkeypatch)
    refused = _refused(store)
    assert store.add_confirmed([_native_ref("a", "mm"), _native_ref("b", "mm")]) == []
    assert [r.session_id for r in store.manifest.sessions] == ["n1"]
    assert refused and "NATIVE_3D_UNIT_MISMATCH" in refused[0][1]
    assert store.manifest.calibration == SESSION_CM


def test_the_probe_recheck_removes_the_batch_when_the_files_disagree(
    qtbot, monkeypatch
) -> None:
    """Defence: the saved options passed, but the files read into another unit."""
    store = _store_with(_manifest([]))
    _no_probes(store, monkeypatch)
    refused = _refused(store)
    logged: list[str] = []
    store.runLogAppended.connect(logged.append)
    store.add_confirmed([_native_ref("a", "cm"), _native_ref("b", "cm")])
    _finish_probe(store, "a", _native("a", unit="cm"))
    _finish_probe(store, "b", _native("b", unit="mm"))
    assert store.manifest.sessions == []
    assert store.manifest.calibration.mode == "bodylength"
    assert refused and "NATIVE_3D_UNIT_MISMATCH" in refused[0][1]
    assert any("NATIVE_3D_UNIT_MISMATCH" in line for line in logged)


def test_a_batch_whose_probe_fails_still_sets_up_the_rest(qtbot, monkeypatch) -> None:
    store = _store_with(_manifest([]))
    _no_probes(store, monkeypatch)
    store.add_confirmed([_native_ref("a", "mm"), _native_ref("b", "mm")])
    _finish_probe(store, "a", RuntimeError("unreadable"))
    _finish_probe(store, "b", _native("b", unit="mm"))
    assert _cal(store) == ("session", "mm", True)


def test_reopening_a_project_does_not_set_it_up_again(qtbot) -> None:
    """A probe of a session already in the project (open_project) changes nothing."""
    store = _store_with(_manifest([_ref("n1")], calibration=CalibrationConfig(mode="scalar")))
    _finish_probe(store, "n1", _native("n1"))
    assert store.manifest.calibration.mode == "scalar"
    assert [ref.session_id for ref in store.manifest.sessions] == ["n1"]


# ── the Metrics screen ───────────────────────────────────────────────────────


def test_metrics_screen_gives_il15_the_water_column_reason(qtbot) -> None:
    from PySide6.QtCore import Qt

    from ui.metrics_screen import MetricsScreen

    store = _store_with(_manifest([_ref("n1")], calibration=SESSION_CM, individual=("IL-15",)))
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)
    table = screen._ind_table
    role = Qt.ItemDataRole.UserRole
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).data(role) == "IL-15")
    tip = table.item(row, 0).toolTip()
    assert tip == NEEDS_WATER_COLUMN_REASON[0].upper() + NEEDS_WATER_COLUMN_REASON[1:] + "."


# ── the stage status ─────────────────────────────────────────────────────────


def _calibration_stage(manifest: ProjectManifest):
    from ui.store.stage_status import PAGE_NAMES, compute_stage_statuses

    return compute_stage_statuses(manifest, has_run_results=False)[
        PAGE_NAMES.index("Calibration")
    ]


@pytest.mark.parametrize(
    "calibration",
    [CalibrationConfig(mode="bodylength"), CalibrationConfig(mode="scalar", px_per_cm=10.0)],
)
def test_stage_status_blocks_a_native_project_outside_session_mode(calibration) -> None:
    from track2data.api import NATIVE_3D_NEEDS_SESSION_CALIBRATION

    info = _calibration_stage(_manifest([_native_ref("n1")], calibration=calibration))
    assert info.status == "blocked"
    assert info.message == NATIVE_3D_NEEDS_SESSION_CALIBRATION


def test_stage_status_of_a_native_project_in_session_mode() -> None:
    from track2data.api import NATIVE_3D_UNIT_NOT_CONFIRMED, native_unit_issue

    ok = _calibration_stage(_manifest([_native_ref("n1")], calibration=SESSION_CM))
    assert ok.status == "valid"
    unconfirmed = SESSION_CM.model_copy(update={"length_unit_confirmed_by_user": False})
    info = _calibration_stage(_manifest([_native_ref("n1")], calibration=unconfirmed))
    assert (info.status, info.message) == ("blocked", NATIVE_3D_UNIT_NOT_CONFIRMED)
    info = _calibration_stage(_manifest([_native_ref("n1", "mm")], calibration=SESSION_CM))
    assert (info.status, info.message) == ("blocked", native_unit_issue("cm", "mm", "n1"))


def test_stage_status_of_pixel_projects_unchanged() -> None:
    info = _calibration_stage(_manifest([_ref("p1", None)]))
    assert (info.status, info.message) == ("valid", "Mode: bodylength.")
