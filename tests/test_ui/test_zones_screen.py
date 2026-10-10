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
        track_wo_identities=False,
        idtrackerai_version=None,
        length_unit=None,
        setup_points=None,
        roi_list=None,
        has_body_length=False,
        background_image_path=None,
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


# ── canvas: loading a session's background + setup_points ───────────────────


def test_selecting_a_session_loads_its_points_into_the_canvas(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, setup_points={"BP1": [[303, 477]], "BP2": [[1037, 497]]}
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    assert screen._canvas.selected_points() == []
    # Points are loaded (clickable), even though nothing is selected yet.
    screen._canvas.click_at(303.0, 477.0)
    assert screen._canvas.selected_points() == [(303.0, 477.0)]


def test_custom_point_button_toggles_canvas_custom_mode(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(store, "session_a", tmp_path)

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    screen._custom_point_btn.setChecked(True)
    screen._canvas.click_at(15.0, 15.0)  # empty space -- only works in custom mode

    assert screen._canvas.selected_points() == [(15.0, 15.0)]


# ── canvas: saving a selection as a zone ─────────────────────────────────────


def test_save_zone_button_disabled_until_three_points_selected(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store,
        "session_a",
        tmp_path,
        setup_points={"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]},
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    assert not screen._save_zone_btn.isEnabled()

    screen._canvas.click_at(0.0, 0.0)
    screen._canvas.click_at(10.0, 0.0)
    assert not screen._save_zone_btn.isEnabled()

    screen._canvas.click_at(10.0, 10.0)
    assert screen._save_zone_btn.isEnabled()


def test_save_zone_appends_an_roi_built_from_the_selection_in_click_order(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store,
        "session_a",
        tmp_path,
        setup_points={"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]},
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    screen._canvas.click_at(10.0, 10.0)
    screen._canvas.click_at(0.0, 0.0)
    screen._canvas.click_at(10.0, 0.0)
    screen._zone_name_edit.setText("arena")
    screen._zone_level_combo.setCurrentText("main")

    screen._save_zone()

    rois = store.manifest.zones.rois
    assert len(rois) == 1
    assert rois[0].name == "arena"
    assert rois[0].level == "main"
    assert rois[0].vertices == [(10.0, 10.0), (0.0, 0.0), (10.0, 0.0)]


def test_save_zone_requires_a_name(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ui.zones_screen import ZonesScreen

    monkeypatch.setattr(
        "ui.zones_screen.QMessageBox.warning", staticmethod(lambda *a, **k: None)
    )

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store,
        "session_a",
        tmp_path,
        setup_points={"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]},
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")
    screen._canvas.click_at(0.0, 0.0)
    screen._canvas.click_at(10.0, 0.0)
    screen._canvas.click_at(10.0, 10.0)
    screen._zone_name_edit.setText("")  # blank

    screen._save_zone()

    assert store.manifest.zones.rois == []


def test_save_zone_clears_canvas_selection_and_name_field(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store,
        "session_a",
        tmp_path,
        setup_points={"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]},
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")
    screen._canvas.click_at(0.0, 0.0)
    screen._canvas.click_at(10.0, 0.0)
    screen._canvas.click_at(10.0, 10.0)
    screen._zone_name_edit.setText("arena")

    screen._save_zone()

    assert screen._canvas.selected_points() == []
    assert screen._zone_name_edit.text() == ""


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


def test_saved_zones_appear_on_the_canvas(qtbot, tmp_path: Path) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    assert screen._canvas.saved_zone_names() == []

    store.update_zones(
        ZoneSet(rois=[ROI(name="arena", vertices=[(0, 0), (10, 0), (10, 10)])])
    )
    assert screen._canvas.saved_zone_names() == ["arena"]


def test_rectangle_tool_button_drives_the_canvas_and_enables_save(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._tool_buttons["rect"].click()
    screen._canvas.drag_shape((10, 10), (60, 50))
    assert screen._save_zone_btn.isEnabled()
    assert len(screen._canvas.selected_points()) == 4

    screen._undo_btn.click()
    assert len(screen._canvas.selected_points()) == 3


# ── select, reshape and delete a saved zone ──────────────────────────────────


def _two_zone_store(tmp_path: Path):
    from track2data.core.models import ROI, ZoneSet

    store = _make_store(tmp_path)
    store.update_zones(
        ZoneSet(
            rois=[
                ROI(name="a", level="main", vertices=[(0, 0), (100, 0), (100, 100), (0, 100)]),
                ROI(name="b", level="main", vertices=[(200, 200), (300, 200), (250, 300)]),
            ]
        )
    )
    return store


def test_polygon_area_is_the_shoelace_area() -> None:
    from ui.widgets.zone_canvas import polygon_area

    assert polygon_area([(0, 0), (4, 0), (4, 3), (0, 3)]) == 12.0
    assert polygon_area([(0, 0), (4, 0), (0, 3)]) == 6.0
    assert polygon_area([(0, 0), (1, 1)]) == 0.0


def test_selecting_a_zone_row_highlights_it_and_reports_its_size(qtbot, tmp_path) -> None:
    from ui.zones_screen import ZonesScreen

    screen = ZonesScreen(_two_zone_store(tmp_path))
    qtbot.addWidget(screen)
    screen._zone_list.setCurrentRow(0)

    assert screen._canvas.selected_zone() == 0
    assert screen._zone_info.text() == "4 vertices · 10000 px²"
    assert screen._delete_zone_btn.isEnabled() is True
    assert len(screen._canvas._handle_items) == 4


def test_dragging_a_handle_reshapes_the_stored_zone(qtbot, tmp_path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _two_zone_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._zone_list.setCurrentRow(0)

    assert screen._canvas.edit_vertex(2, 150.0, 150.0) is True

    assert tuple(store.manifest.zones.rois[0].vertices[2]) == (150.0, 150.0)
    assert store.manifest.zones.rois[1].name == "b"  # the other zone is untouched
    assert screen._zone_list.currentRow() == 0  # still selected after the refresh


def test_deleting_the_selected_zone_removes_only_that_zone(qtbot, tmp_path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _two_zone_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._zone_list.setCurrentRow(1)
    screen._delete_zone_btn.click()

    assert [r.name for r in store.manifest.zones.rois] == ["a"]
    assert screen._delete_zone_btn.isEnabled() is False


def test_edit_vertex_without_a_selected_zone_does_nothing(qtbot, tmp_path) -> None:
    from ui.zones_screen import ZonesScreen

    screen = ZonesScreen(_two_zone_store(tmp_path))
    qtbot.addWidget(screen)
    assert screen._canvas.edit_vertex(0, 1.0, 1.0) is False


# ── an edit that would ruin a zone is refused ────────────────────────────────


def _warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda _p, title, text: shown.append(text))
    )
    return shown


def _triangle_screen(qtbot, tmp_path):
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    store.update_zones(
        ZoneSet(
            rois=[
                ROI(name="tri", level="main", vertices=[(0, 0), (100, 0), (0, 100)]),
                ROI(name="other", level="main", vertices=[(200, 200), (300, 200), (250, 300)]),
            ]
        )
    )
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._zone_list.setCurrentRow(0)
    return store, screen


def test_a_collinear_edit_is_refused_and_the_zone_is_kept(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, screen = _triangle_screen(qtbot, tmp_path)
    shown = _warnings(monkeypatch)
    before = [r.model_copy() for r in store.manifest.zones.rois]

    screen._canvas.edit_vertex(2, 50.0, 0.0)  # all three vertices on the x axis

    assert store.manifest.zones.rois == before
    assert len(shown) == 1 and "area" in shown[0]
    assert screen._zone_list.currentRow() == 0  # still selected
    assert screen._zone_info.text() == "3 vertices · 5000 px²"  # reports the kept shape


def test_a_refused_edit_puts_the_handle_back(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, screen = _triangle_screen(qtbot, tmp_path)
    _warnings(monkeypatch)
    screen._canvas.edit_vertex(2, 50.0, 0.0)
    handle = screen._canvas._handle_items[2].rect().center()
    assert (handle.x(), handle.y()) == (0.0, 100.0)


def test_a_self_intersecting_edit_is_refused(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.core.models import ROI, ZoneSet

    store, screen = _triangle_screen(qtbot, tmp_path)
    store.update_zones(
        ZoneSet(
            rois=[
                ROI(name="sq", level="main", vertices=[(0, 0), (100, 0), (100, 100), (0, 100)])
            ]
        )
    )
    screen._zone_list.setCurrentRow(0)
    shown = _warnings(monkeypatch)
    screen._canvas.edit_vertex(1, 0.0, 100.0)  # swaps two corners into a bowtie
    assert len(shown) == 1 and "cross" in shown[0]
    assert tuple(store.manifest.zones.rois[0].vertices[1]) == (100, 0)


def test_a_valid_move_is_saved_and_changes_the_area(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, screen = _triangle_screen(qtbot, tmp_path)
    shown = _warnings(monkeypatch)
    screen._canvas.edit_vertex(2, 0.0, 200.0)
    assert shown == []
    assert tuple(store.manifest.zones.rois[0].vertices[2]) == (0.0, 200.0)
    assert screen._zone_info.text() == "3 vertices · 10000 px²"


def test_an_edit_keeps_the_zones_name_level_sign_and_the_other_zones(
    qtbot, tmp_path
) -> None:
    store, screen = _triangle_screen(qtbot, tmp_path)
    screen._canvas.edit_vertex(1, 120.0, 0.0)
    tri, other = store.manifest.zones.rois
    assert (tri.name, tri.level, tri.sign) == ("tri", "main", "+")
    assert other.name == "other" and len(other.vertices) == 3


def test_the_store_refuses_a_bad_shape_directly(tmp_path) -> None:
    from track2data.core.errors import ZoneValidationError
    from track2data.core.models import ROI, ZoneSet

    store = _make_store(tmp_path)
    store.update_zones(ZoneSet(rois=[ROI(name="t", vertices=[(0, 0), (10, 0), (0, 10)])]))
    with pytest.raises(ZoneValidationError):
        store.update_zone_vertices(0, [(0, 0), (10, 0), (5, 0)])
    assert store.manifest.zones.rois[0].vertices == [(0, 0), (10, 0), (0, 10)]


def test_importing_a_tracker_polygon_is_not_subject_to_the_edit_rule(tmp_path) -> None:
    """update_zones still accepts what a tracker's roi_list contains (the engine repairs it)."""
    from track2data.core.models import ROI, ZoneSet

    store = _make_store(tmp_path)
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    store.update_zones(ZoneSet(rois=[ROI(name="imported", vertices=bowtie)]))
    assert len(store.manifest.zones.rois) == 1


def test_a_real_mouse_drag_onto_a_degenerate_shape_is_refused(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    store, screen = _triangle_screen(qtbot, tmp_path)
    screen.resize(1100, 800)
    screen.show()
    qtbot.waitExposed(screen)
    shown = _warnings(monkeypatch)
    canvas = screen._canvas
    view = canvas.viewport()

    def at(x: float, y: float) -> QPoint:
        return canvas.mapFromScene(QPointF(x, y))

    # Press on the third vertex (0, 100), drag it onto the x axis, release.
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(0, 100))
    QTest.mouseMove(view, at(50, 0))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(50, 0))

    assert len(shown) == 1
    assert tuple(store.manifest.zones.rois[0].vertices[2]) == (0, 100)
    handle = canvas._handle_items[2].rect().center()
    assert (round(handle.x()), round(handle.y())) == (0, 100)


# ── zones are drawn in the video's own pixels ────────────────────────────────

_THREE_POINTS = {"BP1": [[0, 0]], "BP2": [[10, 0]], "BP3": [[10, 10]]}


def _draw_zone(screen, name: str = "tank") -> None:
    screen._canvas.click_at(0.0, 0.0)
    screen._canvas.click_at(10.0, 0.0)
    screen._canvas.click_at(10.0, 10.0)
    screen._zone_name_edit.setText(name)
    screen._save_zone()


def test_a_session_without_a_background_gets_a_canvas_the_size_of_its_frame(
    qtbot, tmp_path: Path
) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, width_px=1920, height_px=1080, setup_points=_THREE_POINTS
    )

    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    rect = screen._canvas.scene().sceneRect()
    assert (rect.width(), rect.height()) == (1920, 1080)


def test_the_first_zone_saved_records_the_frame_it_was_drawn_on(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, width_px=1920, height_px=1080, setup_points=_THREE_POINTS
    )
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    _draw_zone(screen)

    zones = store.manifest.zones
    assert (zones.source_width_px, zones.source_height_px) == (1920, 1080)


def test_a_zone_added_to_existing_unstamped_zones_does_not_stamp_them(
    qtbot, tmp_path: Path
) -> None:
    """Zones drawn on the old blank 640x480 canvas carry no size. Stamping them now would
    relabel coordinates that are not video pixels as video pixels, and hide the mismatch."""
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, width_px=1920, height_px=1080, setup_points=_THREE_POINTS
    )
    store.update_zones(ZoneSet(rois=[ROI(name="old", vertices=[(0, 0), (5, 0), (5, 5)])]))
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    _draw_zone(screen, "new")

    zones = store.manifest.zones
    assert [r.name for r in zones.rois] == ["old", "new"]
    assert zones.source_width_px is None and zones.source_height_px is None


def test_a_recorded_frame_size_is_never_overwritten(qtbot, tmp_path: Path) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, width_px=1920, height_px=1080, setup_points=_THREE_POINTS
    )
    store.update_zones(
        ZoneSet(
            rois=[ROI(name="old", vertices=[(0, 0), (5, 0), (5, 5)])],
            source_width_px=640,
            source_height_px=480,
        )
    )
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    _draw_zone(screen, "new")

    zones = store.manifest.zones
    assert (zones.source_width_px, zones.source_height_px) == (640, 480)


def test_a_session_with_an_unknown_frame_leaves_the_size_unrecorded(qtbot, tmp_path: Path) -> None:
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(
        store, "session_a", tmp_path, width_px=0, height_px=0, setup_points=_THREE_POINTS
    )
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")

    _draw_zone(screen)

    zones = store.manifest.zones
    assert zones.source_width_px is None and zones.source_height_px is None


def test_zones_screen_passes_the_sessions_panel_to_the_canvas(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from track2data.core.models import PanelRect
    from ui.widgets.zone_canvas import ZoneCanvas
    from ui.zones_screen import ZonesScreen

    store = _make_store(tmp_path)
    _add_session_with_facts(store, "session_a", tmp_path)
    panel = PanelRect(x=1, y=2, width=30, height=40)
    store.manifest.sessions[0] = store.manifest.sessions[0].model_copy(update={"panel": panel})
    calls = []
    monkeypatch.setattr(
        ZoneCanvas, "load_session", lambda self, *a, **k: calls.append(k.get("crop"))
    )
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    screen._session_combo.setCurrentText("session_a")
    screen._refresh_canvas()
    assert calls[-1] == panel
