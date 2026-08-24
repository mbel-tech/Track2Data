"""
Tests for ui/zones_screen.py.

No prior coverage existed for this screen (only the blanket
instantiate-all check in test_app_smoke.py). Added alongside Part 3 of
the post-v0.1.0 GUI fixes plan: wiring the already-built, already-tested
track2data.zones.io.zone_set_from_roi_list() into an "Import from
session" action, and surfacing Session.setup_points as informational
landmark guides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def _make_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


def _add_session_with_facts(store, session_id: str, tmp_path: Path, **facts_kwargs):
    from track2data.core.models import SessionRef
    from ui.store.session_facts import SessionFacts

    folder = tmp_path / session_id
    folder.mkdir(exist_ok=True)
    ref = SessionRef(session_id=session_id, folder=folder, sha256="")
    sessions = [*list(store.manifest.sessions), ref]
    store.update_sessions(sessions)
    defaults = dict(
        session_id=session_id,
        reader="idtrackerai",
        fps=30.0,
        n_frames=100,
        n_animals=2,
        width_px=1000,
        height_px=800,
        has_stable_identities=True,
        idtrackerai_version=None,
        length_unit=None,
        setup_points=None,
        roi_list=None,
        has_body_length=False,
    )
    defaults.update(facts_kwargs)
    store._session_facts[session_id] = SessionFacts(**defaults)
    return folder


_SAMPLE_ROI_LIST = [
    {"sign": "+", "vertices": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]},
]


# ── session combo population ─────────────────────────────────────────────────


def test_session_combo_lists_every_imported_session(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(store, "session_a", tmp_path)
    _add_session_with_facts(store, "session_b", tmp_path)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)

    items = [screen._session_combo.itemText(i) for i in range(screen._session_combo.count())]
    assert items == ["session_a", "session_b"]


# ── import ROIs from a session ───────────────────────────────────────────────


def test_import_from_session_populates_zones_from_roi_list(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, roi_list=_SAMPLE_ROI_LIST, width_px=1920, height_px=1080
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    screen._import_from_session()

    rois = store.manifest.zones.rois
    assert len(rois) == 1
    assert rois[0].name == "arena"
    assert rois[0].sign == "+"
    assert store.manifest.zones.source_width_px == 1920
    assert store.manifest.zones.source_height_px == 1080


def test_import_from_session_with_no_roi_list_does_not_crash_or_change_zones(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.zones_screen import ZonesScreen

    # No roi_list -> the "nothing to import" path shows a blocking
    # QMessageBox.information -- offscreen/headless has nothing to
    # click it, so it must be stubbed out or this test hangs forever.
    monkeypatch.setattr(
        "ui.zones_screen.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )

    store = _make_store(tmp_path)
    _add_session_with_facts(store, "session_a", tmp_path, roi_list=None)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    screen._import_from_session()  # must not raise

    assert store.manifest.zones.rois == []


def test_import_from_session_with_no_sessions_does_not_crash(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.zones_screen import ZonesScreen

    monkeypatch.setattr(
        "ui.zones_screen.QMessageBox.information", staticmethod(lambda *a, **k: None)
    )

    store = _make_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)

    screen._import_from_session()  # must not raise; nothing to import


# ── setup_points landmarks ───────────────────────────────────────────────────


def test_landmarks_list_shows_setup_points_for_the_selected_session(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, setup_points={"feeder": [12.0, 34.0], "corner": [0.0, 0.0]}
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    rows = [
        screen._landmarks_list.item(i).text() for i in range(screen._landmarks_list.count())
    ]
    assert any("feeder" in r for r in rows)
    assert any("corner" in r for r in rows)


def test_landmarks_list_empty_when_session_has_no_setup_points(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(store, "session_a", tmp_path, setup_points=None)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    assert screen._landmarks_list.count() == 0


# ── resolution-mismatch warning ──────────────────────────────────────────────


def test_resolution_mismatch_warning_shown_when_a_session_disagrees(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, roi_list=_SAMPLE_ROI_LIST, width_px=1920, height_px=1080
    )
    _add_session_with_facts(store, "session_b", tmp_path, width_px=640, height_px=480)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")
    screen._import_from_session()

    assert screen._mismatch_label.isVisible() or "session_b" in screen._mismatch_label.text()
    assert "session_b" in screen._mismatch_label.text()


def test_no_mismatch_warning_when_every_session_dimension_matches(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, roi_list=_SAMPLE_ROI_LIST, width_px=1920, height_px=1080
    )
    _add_session_with_facts(store, "session_b", tmp_path, width_px=1920, height_px=1080)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")
    screen._import_from_session()

    assert screen._mismatch_label.text() == ""


# ── pretty text on ROI level ─────────────────────────────────────────────────


def test_roi_level_shown_title_cased_not_raw(qtbot, tmp_path: Path) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    store.update_zones(ZoneSet(rois=[ROI(name="arena", level="secondary", vertices=[(0, 0)])]))

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)

    text = screen._zone_list.item(0).text()
    assert "secondary" not in text
    assert "Secondary" in text


# ── existing CSV load/clear behaviour (regression) ───────────────────────────


def test_clear_zones_empties_the_manifest(qtbot, tmp_path: Path) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    store.update_zones(ZoneSet(rois=[ROI(name="arena", level="main", vertices=[(0, 0)])]))

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._clear_zones()

    assert store.manifest.zones.rois == []
