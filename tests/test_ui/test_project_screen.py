"""Tests for the 2D/3D mode controls on ui/project_screen.py."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import ProjectMode, SessionRef

THREE_D = ProjectMode(dimension="3d", layout="two_videos")


def _make(qtbot, tmp_path: Path, with_project: bool = True):
    from ui.project_screen import ProjectScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = ProjectScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    if with_project:
        store.new_project("p", tmp_path)
    return store, screen


def _session(tmp_path: Path) -> SessionRef:
    return SessionRef(session_id="s1", folder=tmp_path, sha256="0" * 64)


def test_layout_group_visible_only_for_3d(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path)
    assert not screen._layout_box.isVisible()
    screen._dim_3d.click()
    assert screen._layout_box.isVisible()
    screen._dim_2d.click()
    assert not screen._layout_box.isVisible()


def test_choosing_3d_with_layout_updates_store(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._dim_3d.click()
    assert store.manifest.mode == ProjectMode()
    screen._layout_two.click()
    assert store.manifest.mode == THREE_D


def test_switching_back_to_2d_clears_layout(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._dim_3d.click()
    screen._layout_single.click()
    assert store.manifest.mode.dimension == "3d"
    screen._dim_2d.click()
    assert store.manifest.mode == ProjectMode()


def test_locked_with_sessions(qtbot, tmp_path) -> None:
    from ui.store.project_store import MODE_LOCK_REASON

    store, screen = _make(qtbot, tmp_path)
    store.update_sessions([_session(tmp_path)])
    for w in (screen._dim_2d, screen._dim_3d, screen._layout_single, screen._layout_two):
        assert not w.isEnabled()
    assert screen._lock_label.text() == MODE_LOCK_REASON
    store.update_sessions([])
    for w in (screen._dim_2d, screen._dim_3d, screen._layout_single, screen._layout_two):
        assert w.isEnabled()
    assert screen._lock_label.text() == ""


def test_opening_project_syncs_radios_without_writing(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path, with_project=False)
    store.new_project("q", tmp_path, mode=THREE_D)
    path = store.save_project()
    store.new_project("r", tmp_path)
    screen._dim_3d.click()
    screen._layout_single.click()
    assert store.manifest.mode.layout == "single_video_two_panels"
    store.save_project()
    emitted: list[int] = []
    store.modeChanged.connect(lambda: emitted.append(1))
    handler_calls: list[int] = []
    real_write = screen._write_mode
    screen._write_mode = lambda: (handler_calls.append(1), real_write())[1]
    store.open_project(path)
    assert handler_calls == []
    assert screen._dim_3d.isChecked()
    assert screen._layout_two.isChecked()
    assert not screen._layout_single.isChecked()
    assert screen._layout_box.isVisible()
    assert emitted == []
    assert store.manifest.mode == THREE_D


def test_locked_project_sync_does_not_write(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path, with_project=False)
    store.new_project("q", tmp_path, mode=THREE_D)
    store.update_sessions([_session(tmp_path)])
    path = store.save_project()
    store.new_project("r", tmp_path)
    screen._dim_3d.click()
    screen._layout_single.click()
    emitted: list[int] = []
    store.modeChanged.connect(lambda: emitted.append(1))
    handler_calls: list[int] = []
    real_write = screen._write_mode
    screen._write_mode = lambda: (handler_calls.append(1), real_write())[1]
    store.open_project(path)
    assert handler_calls == []
    assert screen._layout_two.isChecked()
    assert not screen._dim_3d.isEnabled()
    assert emitted == []
    assert store.manifest.mode == THREE_D


def test_clicking_checked_layout_keeps_it_checked(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._dim_3d.click()
    screen._layout_two.click()
    screen._layout_two.click()
    assert screen._layout_two.isChecked()
    assert store.manifest.mode == THREE_D


def test_create_project_uses_chosen_mode(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path, with_project=False)
    screen._name_edit.setText("proj")
    screen._selected_dir = str(tmp_path)
    screen._dim_3d.click()
    screen._layout_single.click()
    screen._create_project()
    assert store.manifest.mode == ProjectMode(dimension="3d", layout="single_video_two_panels")


def test_create_3d_without_layout_warns_and_creates_nothing(qtbot, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    calls: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: calls.append(a))
    store, screen = _make(qtbot, tmp_path, with_project=False)
    screen._name_edit.setText("proj")
    screen._selected_dir = str(tmp_path)
    screen._dim_3d.click()
    screen._create_project()
    assert len(calls) == 1
    assert store.manifest is None
