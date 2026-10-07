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
    assert row == ["session_a", "—", "—", "—", "—", "—", "", "—"]


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
    assert row == ["session_a", "idtrackerai", "30.0", "1000", "4", "Stable", "", "Not found"]


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


def test_add_folders_scans_what_was_picked_and_adds_nothing_yet(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from ui.import_screen import ImportScreen

    f1, f2 = tmp_path / "s1", tmp_path / "s2"
    f1.mkdir()
    f2.mkdir()
    monkeypatch.setattr("ui.import_screen.QFileDialog", _FakeMultiSelectDialog([f1, f2]))

    store = _make_store(tmp_path)
    asked: list[list[Path]] = []
    monkeypatch.setattr(store, "scan_folders", lambda paths: asked.append(list(paths)) or "t1")
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    screen._add_folders()

    assert asked == [[f1, f2]]
    assert store.manifest.sessions == []


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


def test_drag_enter_accepts_a_tracking_file_too(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    one_file = tmp_path / "tracks.csv"
    one_file.write_text("x")

    assert _fire_drag_enter(screen, [one_file])


def test_drag_enter_rejects_something_that_is_not_on_disk(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    assert not _fire_drag_enter(screen, [tmp_path / "does_not_exist"])


def test_drop_scans_everything_dropped(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.import_screen import ImportScreen

    f1 = tmp_path / "s1"
    f1.mkdir()
    plain_file = tmp_path / "tracks.csv"
    plain_file.write_text("x")

    store = _make_store(tmp_path)
    asked: list[list[Path]] = []
    monkeypatch.setattr(store, "scan_folders", lambda paths: asked.append(list(paths)) or "t1")
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    screen.dropEvent(_urls_event_drop([f1, plain_file]))

    assert asked == [[f1, plain_file]]
    assert store.manifest.sessions == []


# ── scan -> confirm -> add ──────────────────────────────────────────────────


def _idtracker_root(tiny_real_session: Path, tmp_path: Path, names=("s1", "s2")) -> Path:
    import shutil

    root = tmp_path / "root"
    for name in names:
        shutil.copytree(tiny_real_session, root / name)
    return root


def _scan_to_dialog(qtbot, screen, root: Path):
    screen._import_paths([root])
    qtbot.waitUntil(lambda: screen._dialog is not None, timeout=8000)
    return screen._dialog


def test_a_scanned_folder_opens_the_confirm_dialog_and_adds_nothing_yet(
    qtbot, tiny_real_session: Path, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    dialog = _scan_to_dialog(qtbot, screen, _idtracker_root(tiny_real_session, tmp_path))

    assert dialog.isVisible()
    assert dialog.draft.reader == "idtrackerai"
    assert [row.session_id for row in dialog.draft.rows] == ["s1", "s2"]
    assert store.manifest.sessions == []


def test_confirming_adds_the_sessions_with_the_reader_that_was_confirmed(
    qtbot, tiny_real_session: Path, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    dialog = _scan_to_dialog(qtbot, screen, _idtracker_root(tiny_real_session, tmp_path))

    dialog.ok_button.click()

    refs = store.manifest.sessions
    assert {r.session_id for r in refs} == {"s1", "s2"}
    assert {r.reader for r in refs} == {"idtrackerai"}
    assert {r.reader_chosen_by for r in refs} == {"detected"}
    assert screen._dialog is None


def test_cancelling_the_dialog_adds_nothing(qtbot, tiny_real_session: Path, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    dialog = _scan_to_dialog(qtbot, screen, _idtracker_root(tiny_real_session, tmp_path))

    dialog.cancel_button.click()

    assert store.manifest.sessions == []
    assert screen._dialog is None


def test_leaving_a_session_out_in_the_dialog_leaves_it_out_of_the_project(
    qtbot, tiny_real_session: Path, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    dialog = _scan_to_dialog(qtbot, screen, _idtracker_root(tiny_real_session, tmp_path))

    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    dialog.ok_button.click()

    assert [r.session_id for r in store.manifest.sessions] == ["s1"]


def test_a_session_already_in_the_project_is_marked_when_the_folder_is_scanned_again(
    qtbot, tiny_real_session: Path, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    root = _idtracker_root(tiny_real_session, tmp_path)
    _scan_to_dialog(qtbot, screen, root).ok_button.click()

    second = _scan_to_dialog(qtbot, screen, root)

    assert all(row.already_added for row in second.draft.rows)
    assert not second.ok_button.isEnabled()


def test_a_folder_with_nothing_recognisable_opens_the_dialog_in_its_empty_state(
    qtbot, tmp_path: Path
) -> None:
    from ui.import_screen import ImportScreen

    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hello")
    store = _make_store(tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    dialog = _scan_to_dialog(qtbot, screen, junk)

    assert dialog.draft.is_empty
    assert dialog.ok_button.isHidden()


def test_a_scan_in_progress_is_shown_with_a_way_to_stop_it(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    monkeypatch.setattr(store, "scan_folders", lambda paths: "t1")
    stopped: list[str] = []
    monkeypatch.setattr(store, "cancel_scan", stopped.append)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    assert screen._scan_row.isHidden()

    screen._import_paths([tmp_path])
    assert not screen._scan_row.isHidden()

    screen._scan_cancel_btn.click()
    assert stopped == ["t1"]

    store.scanCancelled.emit("t1")
    assert screen._scan_row.isHidden()
    assert screen._dialog is None


def test_scan_progress_is_written_next_to_the_bar(qtbot, tmp_path: Path, monkeypatch) -> None:
    from track2data.core.progress import ProgressEvent
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    monkeypatch.setattr(store, "scan_folders", lambda paths: "t1")
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    screen._import_paths([tmp_path])

    store.scanProgress.emit("t1", ProgressEvent("scan", 40, 100, message="40 entries"))

    assert "40 entries" in screen._scan_label.text()
    assert screen._scan_bar.value() == 40


def test_a_failed_scan_says_so_inline_without_a_modal(qtbot, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    monkeypatch.setattr(store, "scan_folders", lambda paths: "t1")
    modals: list[object] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: modals.append(a))
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    screen._import_paths([tmp_path])

    store.scanFinished.emit("t1", RuntimeError("the disk went away"))

    assert not screen._scan_message.isHidden()
    assert "the disk went away" in screen._scan_message.text()
    assert screen._scan_row.isHidden() and screen._dialog is None
    assert modals == []


def test_a_new_scan_replaces_one_still_running(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    ids = iter(["t1", "t2"])
    monkeypatch.setattr(store, "scan_folders", lambda paths: next(ids))
    stopped: list[str] = []
    monkeypatch.setattr(store, "cancel_scan", stopped.append)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    screen._import_paths([tmp_path])
    screen._import_paths([tmp_path])

    assert stopped == ["t1"]


def test_an_old_scans_result_is_ignored(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    monkeypatch.setattr(store, "scan_folders", lambda paths: "t2")
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    screen._import_paths([tmp_path])

    store.scanFinished.emit("t1", RuntimeError("stale"))

    assert not screen._scan_row.isHidden()  # still waiting for t2
    assert screen._scan_message.isHidden()


# ── the Reader column comes from the project, not only from the probe ───────


def test_the_reader_column_names_the_saved_reader_before_the_probe_lands(
    qtbot, tmp_path: Path
) -> None:
    from track2data.core.models import SessionRef
    from track2data.readers import get_reader
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    ref = SessionRef(session_id="a", folder=tmp_path / "a", sha256="", reader="idtrackerai")
    store.update_sessions([ref])
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    shown = screen._table.item(0, 1).text()

    assert shown == get_reader("idtrackerai").display_name
    assert shown != "—"


# ── identity-free override checkbox ────────────────────────────────────────


def _free_cell(screen):
    from ui.import_screen import _COL_IDENTITY_FREE

    return screen._table.item(0, _COL_IDENTITY_FREE)


def test_identity_free_checkbox_is_disabled_until_the_probe_lands(qtbot, tmp_path: Path) -> None:
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
                session_id="session_a",
                folder=folder,
                sha256="",
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


def test_ticking_the_checkbox_writes_an_override_to_the_store(qtbot, tmp_path: Path) -> None:
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


def test_unticking_records_an_explicit_override_not_a_reset_to_auto(qtbot, tmp_path: Path) -> None:
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
                session_id="session_a",
                folder=folder,
                sha256="",
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


def test_refreshing_the_table_does_not_clobber_the_override(qtbot, tmp_path: Path) -> None:
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


def test_a_later_probe_result_does_not_undo_the_override(qtbot, tmp_path: Path) -> None:
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


# ── Locate video ─────────────────────────────────────────────────────────────


class _FakeOpenFile:
    """Stands in for QFileDialog's static getOpenFileName."""

    def __init__(self, chosen: Path | None) -> None:
        self._chosen = chosen

    def getOpenFileName(self, *_a, **_k):  # noqa: N802 -- mirrors Qt's QFileDialog API
        return (str(self._chosen) if self._chosen else "", "")


def _video_cell(screen) -> tuple[str, str]:
    from ui.import_screen import _COL_VIDEO

    item = screen._table.item(0, _COL_VIDEO)
    return item.text(), item.toolTip()


def test_video_column_reports_missing_found_and_located(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "s1", tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    _cache_facts(store, "s1", video_path=None)
    store.sessionFactsChanged.emit()
    text, tip = _video_cell(screen)
    assert text == "Not found" and "Locate Video" in tip

    video = tmp_path / "real.mp4"
    video.write_bytes(b"x")
    _cache_facts(store, "s1", video_path=video)
    store.sessionFactsChanged.emit()
    assert _video_cell(screen) == ("Found", str(video))


def test_locate_button_needs_exactly_one_selected_session(qtbot, tmp_path: Path) -> None:
    from ui.import_screen import ImportScreen

    store = _make_store(tmp_path)
    _add_ref(store, "s1", tmp_path)
    _add_ref(store, "s2", tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)

    assert not screen._locate_btn.isEnabled()
    screen._table.selectRow(0)
    assert screen._locate_btn.isEnabled()
    screen._table.selectAll()
    assert not screen._locate_btn.isEnabled()


def test_locate_video_stores_the_choice_and_updates_the_row(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from ui.import_screen import ImportScreen

    video = tmp_path / "real.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr("ui.import_screen.QFileDialog", _FakeOpenFile(video))

    store = _make_store(tmp_path)
    _add_ref(store, "s1", tmp_path)
    _cache_facts(store, "s1", video_path=None)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    screen._table.selectRow(0)

    screen._locate_video()

    assert store.manifest.video_overrides == {"s1": video}
    assert _video_cell(screen) == ("Located", str(video))


def test_locate_video_cancelled_changes_nothing(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.import_screen import ImportScreen

    monkeypatch.setattr("ui.import_screen.QFileDialog", _FakeOpenFile(None))
    store = _make_store(tmp_path)
    _add_ref(store, "s1", tmp_path)
    screen = ImportScreen(store)
    qtbot.addWidget(screen)
    screen._table.selectRow(0)

    screen._locate_video()

    assert store.manifest.video_overrides == {}


def test_store_rejects_a_missing_file_or_unknown_session(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _add_ref(store, "s1", tmp_path)
    with pytest.raises(FileNotFoundError):
        store.set_video_path("s1", tmp_path / "nope.mp4")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with pytest.raises(KeyError):
        store.set_video_path("ghost", video)
    assert store.manifest.video_overrides == {}
