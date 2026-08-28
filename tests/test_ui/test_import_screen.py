"""
Tests for ui/import_screen.py (Part 1 of the post-v0.1.0 GUI fixes
plan): multi-folder selection, drag-and-drop, and a SessionFacts-driven
table replacing the old single-select QListWidget.

No prior coverage existed for this screen (only the blanket
instantiate-all check in test_app_smoke.py) -- these are the first
real tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog as RealQFileDialog


def _make_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


def _add_ref(store, session_id: str, tmp_path: Path):
    from track2data.core.models import SessionRef

    folder = tmp_path / session_id
    folder.mkdir()
    ref = SessionRef(session_id=session_id, folder=folder, sha256="")
    sessions = [*list(store.manifest.sessions), ref]
    store.update_sessions(sessions)
    return folder


def _cache_facts(store, session_id: str, **overrides):
    """Cache a SessionFacts for *session_id*, as the background probe would."""
    from ui.store.session_facts import SessionFacts

    fields = dict(
        session_id=session_id,
        reader="idtrackerai",
        fps=30.0,
        n_frames=1000,
        n_animals=4,
        width_px=640,
        height_px=480,
        has_stable_identities=True,
        track_wo_identities=False,
        idtrackerai_version=None,
        length_unit=None,
        setup_points=None,
        roi_list=None,
        has_body_length=False,
        background_image_path=None,
    )
    fields.update(overrides)
    store._session_facts[session_id] = SessionFacts(**fields)



# ── table population ────────────────────────────────────────────────────────


def test_refresh_populates_from_a_store_that_already_has_sessions(qtbot, tmp_path: Path) -> None:
    """Regression: the screen used to only refresh via signals, so
    constructing it against an already-populated store showed an empty
    table until something changed."""
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    assert screen._table.rowCount() == 1
    assert screen._table.item(0, 0).text() == "session_a"


def test_table_shows_dash_placeholders_before_facts_are_cached(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    row = [screen._table.item(0, c).text() for c in range(screen._table.columnCount())]
    # Trailing "" is the Identity-free checkbox cell, which carries a
    # check state rather than text.
    assert row == ["session_a", "—", "—", "—", "—", "—", ""]


def test_table_shows_session_facts_once_cached(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen
    from ui.store.session_facts import SessionFacts

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)
    store._session_facts["session_a"] = SessionFacts(
        session_id="session_a",
        reader="idtrackerai",
        fps=30.0,
        n_frames=1000,
        n_animals=4,
        width_px=640,
        height_px=480,
        has_stable_identities=True,
        track_wo_identities=False,
        idtrackerai_version="6.0.15a0",
        length_unit=None,
        setup_points=None,
        roi_list=None,
        has_body_length=False,
        background_image_path=None,
    )

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    row = [screen._table.item(0, c).text() for c in range(screen._table.columnCount())]
    assert row == ["session_a", "idtrackerai", "30.0", "1000", "4", "Stable", ""]


def test_table_refreshes_when_facts_arrive_after_construction(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen
    from ui.store.session_facts import SessionFacts

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    assert screen._table.item(0, 5).text() == "—"

    store._session_facts["session_a"] = SessionFacts(
        session_id="session_a",
        reader="idtrackerai",
        fps=30.0,
        n_frames=1000,
        n_animals=1,
        width_px=640,
        height_px=480,
        has_stable_identities=False,
        track_wo_identities=False,
        idtrackerai_version=None,
        length_unit=None,
        setup_points=None,
        roi_list=None,
        has_body_length=False,
        background_image_path=None,
    )
    store.sessionFactsChanged.emit()

    assert screen._table.item(0, 5).text() == "Unstable"


# ── multi-row removal ────────────────────────────────────────────────────────


def test_remove_selected_removes_every_selected_row(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    for sid in ("s0", "s1", "s2"):
        _add_ref(store, sid, tmp_path)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    # QTableWidget.selectRow() always clears the prior selection before
    # selecting, so it can't build up a multi-row selection on its own
    # -- go through the selection model directly with the Select flag
    # (what an actual ctrl/shift-click emulates) to select rows 0 and 2
    # without row 1. This is the actual regression under test:
    # _remove_selected was already written to handle a multi-row
    # selection, but the widget was SingleSelection so it could never
    # receive one.
    from PySide6.QtCore import QItemSelectionModel

    selection_model = screen._table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    selection_model.select(screen._table.model().index(0, 0), flags)
    selection_model.select(screen._table.model().index(2, 0), flags)

    screen._remove_selected()

    assert [s.session_id for s in store.manifest.sessions] == ["s1"]


# ── multi-folder dialog ──────────────────────────────────────────────────────


class _FakeMultiSelectDialog:
    """Stands in for the non-native QFileDialog _add_folders() drives."""

    def __init__(self, selected: list[Path]) -> None:
        self._selected = selected

    def __call__(self, *_args, **_kwargs):
        return self

    def setFileMode(self, *_a) -> None:  # noqa: N802 -- mirrors Qt's QFileDialog API
        pass

    def setOption(self, *_a) -> None:  # noqa: N802 -- mirrors Qt's QFileDialog API
        pass

    def findChildren(self, *_a, **_k):  # noqa: N802 -- mirrors Qt's QFileDialog API
        return []

    def exec(self):
        return RealQFileDialog.DialogCode.Accepted

    def selectedFiles(self):  # noqa: N802 -- mirrors Qt's QFileDialog API
        return [str(p) for p in self._selected]


def test_add_folders_imports_every_selected_folder(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.import_screen import ImportScreen

    f1, f2 = tmp_path / "s1", tmp_path / "s2"
    f1.mkdir()
    f2.mkdir()
    monkeypatch.setattr("ui.import_screen.QFileDialog", _FakeMultiSelectDialog([f1, f2]))

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    screen._add_folders()

    assert {s.session_id for s in store.manifest.sessions} == {"s1", "s2"}


# ── drag and drop ────────────────────────────────────────────────────────────


def _urls_event_enter(paths: list[Path]) -> QDragEnterEvent:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDragEnterEvent(
        QPoint(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    # QDragEnterEvent stores a raw (non-owning) QMimeData pointer -- Qt's
    # own drag machinery keeps the real QMimeData alive for the event's
    # lifetime, but a hand-built event has nothing else holding a
    # reference to `mime`, so Python's GC can free it before the event
    # is used, leaving mimeData() returning a dangling generic QObject.
    # Pin it to the event explicitly.
    event._mime_keepalive = mime
    return event


def _urls_event_drop(paths: list[Path]) -> QDropEvent:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(
        QPointF(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event._mime_keepalive = mime  # see _urls_event_enter's comment
    return event


def _fire_drag_enter(screen, paths: list[Path]) -> bool:
    """Fire dragEnterEvent and return a plain bool, never the raw Qt
    event -- pytest's assertion-rewrite repr() of a PySide6 event
    object segfaults on this stack (a dangling C++ pointer once the
    short-lived event is out of scope), so the event must never appear
    inside an `assert` expression itself."""
    event = _urls_event_enter(paths)
    screen.dragEnterEvent(event)
    return bool(event.isAccepted())


def test_drag_enter_accepts_an_existing_directory(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    folder = tmp_path / "s1"
    folder.mkdir()
    accepted = _fire_drag_enter(screen, [folder])

    assert accepted


def test_drag_enter_rejects_a_plain_file(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    plain_file = tmp_path / "not_a_folder.csv"
    plain_file.write_text("x")
    accepted = _fire_drag_enter(screen, [plain_file])

    assert not accepted


def test_drop_imports_every_dropped_directory(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    f1, f2 = tmp_path / "s1", tmp_path / "s2"
    f1.mkdir()
    f2.mkdir()

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    event = _urls_event_drop([f1, f2])
    screen.dropEvent(event)

    assert {s.session_id for s in store.manifest.sessions} == {"s1", "s2"}


def test_drop_ignores_files_mixed_in_with_directories(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    folder = tmp_path / "s1"
    folder.mkdir()
    plain_file = tmp_path / "not_a_folder.csv"
    plain_file.write_text("x")

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    event = _urls_event_drop([folder, plain_file])
    screen.dropEvent(event)

    assert [s.session_id for s in store.manifest.sessions] == ["s1"]


# ── duplicate-folder guard (project_store.add_session) ──────────────────────


def test_dropping_the_same_folder_twice_does_not_duplicate_the_session(
    qtbot, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    folder = tmp_path / "s1"
    folder.mkdir()

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    screen.dropEvent(_urls_event_drop([folder]))
    screen.dropEvent(_urls_event_drop([folder]))

    assert [s.session_id for s in store.manifest.sessions] == ["s1"]


# ── identity-free override checkbox ────────────────────────────────────────


def _free_cell(screen):
    from ui.import_screen import _COL_IDENTITY_FREE

    return screen._table.item(0, _COL_IDENTITY_FREE)


def test_identity_free_checkbox_is_disabled_until_the_probe_lands(
    qtbot, tmp_path: Path
) -> None:
    """Before the probe there is nothing to show: an unchecked box would
    assert the session preserves identity, which is not yet known."""
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    cell = _free_cell(screen)
    assert not (cell.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert not (cell.flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_identity_free_checkbox_starts_unchecked_for_an_identified_session(
    qtbot, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)
    _cache_facts(store, "session_a", track_wo_identities=False)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    cell = _free_cell(screen)
    assert cell.checkState() == Qt.CheckState.Unchecked
    assert bool(cell.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert "with identification" in cell.toolTip()


def test_identity_free_checkbox_starts_checked_when_the_tracker_says_so(
    qtbot, tmp_path: Path
) -> None:
    from track2data.core.models import SessionRef
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    folder = tmp_path / "session_a"
    folder.mkdir()
    store.update_sessions(
        [
            SessionRef(
                session_id="session_a", folder=folder, sha256="",
                track_wo_identities=True,
            )
        ]
    )
    _cache_facts(store, "session_a", track_wo_identities=True)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    cell = _free_cell(screen)
    assert cell.checkState() == Qt.CheckState.Checked
    assert "without identification" in cell.toolTip()


def test_ticking_the_checkbox_writes_an_override_to_the_store(
    qtbot, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)
    _cache_facts(store, "session_a", track_wo_identities=False)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    _free_cell(screen).setCheckState(Qt.CheckState.Checked)

    ref = store.manifest.sessions[0]
    assert ref.identity_free_override is True
    assert ref.is_identity_free() is True


def test_unticking_records_an_explicit_override_not_a_reset_to_auto(
    qtbot, tmp_path: Path
) -> None:
    """Unticking a session the tracker called identity-free must persist as
    a deliberate "no, identities are fine here", or the next refresh would
    re-check the box from the tracker's value."""
    from track2data.core.models import SessionRef
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    folder = tmp_path / "session_a"
    folder.mkdir()
    store.update_sessions(
        [
            SessionRef(
                session_id="session_a", folder=folder, sha256="",
                track_wo_identities=True,
            )
        ]
    )
    _cache_facts(store, "session_a", track_wo_identities=True)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    _free_cell(screen).setCheckState(Qt.CheckState.Unchecked)

    ref = store.manifest.sessions[0]
    assert ref.identity_free_override is False
    assert ref.is_identity_free() is False
    assert _free_cell(screen).checkState() == Qt.CheckState.Unchecked


def test_refreshing_the_table_does_not_clobber_the_override(
    qtbot, tmp_path: Path
) -> None:
    """_refresh_table sets check states, which emits itemChanged -- without
    the re-entrancy guard that write-back would fire on every refresh."""
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)
    _cache_facts(store, "session_a", track_wo_identities=False)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    _free_cell(screen).setCheckState(Qt.CheckState.Checked)

    _cache_facts(store, "session_a", track_wo_identities=False, n_animals=7)
    store.sessionFactsChanged.emit()

    assert store.manifest.sessions[0].identity_free_override is True
    assert _free_cell(screen).checkState() == Qt.CheckState.Checked


def test_a_later_probe_result_does_not_undo_the_override(
    qtbot, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "session_a", tmp_path)
    _cache_facts(store, "session_a", track_wo_identities=False)

    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    _free_cell(screen).setCheckState(Qt.CheckState.Checked)

    store._set_session_identity("session_a", True, False)

    assert store.manifest.sessions[0].identity_free_override is True
    assert _free_cell(screen).checkState() == Qt.CheckState.Checked
