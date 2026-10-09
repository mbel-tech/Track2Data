"""Tests for the Views page roles and pairing patterns (ui/views_screen.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import PairingPatterns, ProjectMode, SessionRef

TOP = "(?P<key>.+)_top$"
SIDE = "(?P<key>.+)_side$"


def _refs(tmp_path: Path, names) -> list[SessionRef]:
    return [SessionRef(session_id=n, folder=tmp_path / n, sha256="0" * 64) for n in names]


def _make(qtbot, tmp_path: Path, names=("t1_top", "t1_side", "t2_top", "t2_side")):
    from ui.store.project_store import ProjectStore
    from ui.views_screen import ViewsScreen

    store = ProjectStore()
    screen = ViewsScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    store.new_project("p", tmp_path, mode=ProjectMode(dimension="3d", layout="two_videos"))
    store.update_sessions(_refs(tmp_path, names))
    return store, screen


def _combo(screen, row):
    return screen._role_table.cellWidget(row, 1)


def test_role_combos_reflect_and_set_roles(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    assert [_combo(screen, 0).itemText(i) for i in range(3)] == ["(not set)", "Top", "Side"]
    assert _combo(screen, 0).currentText() == "(not set)"
    _combo(screen, 0).setCurrentIndex(1)
    assert store.manifest.sessions[0].view_role == "top"
    store.update_view_role("t1_side", "side")
    assert _combo(screen, 1).currentText() == "Side"


def test_typing_patterns_updates_match_label_live(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._top_regex_edit.setText(TOP)
    screen._side_regex_edit.setText(SIDE)
    assert screen._match_label.text() == (
        "Top pattern catches 2 sessions · side pattern catches 2 sessions"
    )
    assert screen._commit.pending
    screen._commit.flush()
    assert store.manifest.mode.pairing == PairingPatterns(top_regex=TOP, side_regex=SIDE)


def test_invalid_pattern_shows_error(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path)
    screen._top_regex_edit.setText("(")
    assert screen._error_label.text().startswith("top regex")
    screen._top_regex_edit.setText(".+_top$")
    assert "key" in screen._error_label.text()
    screen._top_regex_edit.setText(TOP)
    assert screen._error_label.text() == ""


def test_apply_creates_pairs_and_roles(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._top_regex_edit.setText(TOP)
    screen._side_regex_edit.setText(SIDE)
    screen._apply_btn.click()
    assert len(store.manifest.view_pairs) == 2
    assert [s.view_role for s in store.manifest.sessions] == ["top", "side", "top", "side"]
    assert _combo(screen, 0).currentText() == "Top"
    assert screen._unpaired_label.text() == ""


def test_unpaired_label_lists_lone_session(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path, names=("t1_top", "t1_side", "t3_top"))
    screen._top_regex_edit.setText(TOP)
    screen._side_regex_edit.setText(SIDE)
    assert "t3_top" in screen._unpaired_label.text()


def test_help_buttons_show_popover(qtbot, tmp_path) -> None:
    from ui.widgets.regex_help import REGEX_HELP_TEXT

    _, screen = _make(qtbot, tmp_path)
    assert screen._top_help_btn.text() == "ⓘ"
    assert not screen._popover.isVisible()
    screen._top_help_btn.click()
    assert screen._popover.isVisible()
    for part in ("(?P<key>", "(?P<key>.+)_top$", "trial01_top", "same key are paired"):
        assert part in REGEX_HELP_TEXT


def test_refresh_does_not_write_back(qtbot, tmp_path, monkeypatch) -> None:
    store, screen = _make(qtbot, tmp_path)
    store.update_pairing(PairingPatterns(top_regex=TOP, side_regex=SIDE))
    calls = []
    monkeypatch.setattr(store, "update_view_role", lambda *a: calls.append(a))
    monkeypatch.setattr(store, "update_pairing", lambda *a: calls.append(a))
    store.viewsChanged.emit()
    store.sessionsChanged.emit()
    store.modeChanged.emit()
    store.projectChanged.emit()
    screen._commit.flush()
    assert calls == []
    assert screen._top_regex_edit.text() == TOP


def test_empty_states(qtbot, tmp_path) -> None:
    from ui.store.project_store import ProjectStore
    from ui.views_screen import ViewsScreen

    bare = ViewsScreen(None)
    qtbot.addWidget(bare)
    assert not bare._empty_label.isHidden()

    store = ProjectStore()
    screen = ViewsScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    assert screen._empty_label.isVisible()
    store.new_project("p2", tmp_path)
    assert screen._empty_label.isVisible()
    store.new_project("p3", tmp_path, mode=ProjectMode(dimension="3d", layout="two_videos"))
    assert screen._empty_label.isVisible()
    assert screen._role_table.rowCount() == 0
