"""MainWindow behaviour that depends on the project's 2D/3D mode."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import (
    ProjectMode,
    RunResult,
    SessionRef,
)
from ui.store.stage_status import SESSIONS_NEEDS_LAYOUT

THREE_D = ProjectMode(dimension="3d", layout="two_videos")


def _window(qtbot, tmp_path: Path):
    from app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._store.new_project("experiment", tmp_path)
    return win


def _ref(tmp_path: Path) -> SessionRef:
    return SessionRef(session_id="s1", folder=tmp_path, sha256="0" * 64)


def test_switching_to_3d_after_a_run_does_not_keep_2d_results(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_sessions([_ref(tmp_path)])
    store.set_run_results(RunResult(sessions=[]))
    store.update_sessions([])
    store.update_mode(THREE_D)
    assert store.run_results is None
    for stage in (7, 8):
        assert win._sidebar.status(stage) == "blocked"
    assert 8 in win._sidebar._locked


def test_3d_blocked_stages_ignore_any_stale_run_results(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_mode(THREE_D)
    store.set_run_results(RunResult(sessions=[]))
    for stage in (7, 8):
        assert win._sidebar.status(stage) == "blocked"
    assert 8 in win._sidebar._locked


def test_run_action_disabled_in_3d_and_back(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_sessions([_ref(tmp_path)])
    assert win._run_action.isEnabled()
    store.update_sessions([])
    store.update_mode(THREE_D)
    store.update_sessions([_ref(tmp_path)])
    assert not win._run_action.isEnabled()
    store.update_sessions([])
    store.update_mode(ProjectMode())
    store.update_sessions([_ref(tmp_path)])
    assert win._run_action.isEnabled()


def test_run_action_reevaluated_on_mode_change(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_mode(THREE_D)
    store.update_sessions([_ref(tmp_path)])
    store.update_sessions([])
    assert not win._run_action.isEnabled()


def test_pending_3d_layout_blocks_leaving_the_project_page(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    win._go_to_page(0)
    screen = win._stack.widget(0)
    screen._dim_3d.click()
    assert screen.pending_mode_message() == SESSIONS_NEEDS_LAYOUT
    assert not win._next_action.isEnabled()
    assert win._next_action.toolTip() == SESSIONS_NEEDS_LAYOUT
    win._go_to_page(1)  # sidebar navigation is refused too
    assert win._stack.currentIndex() == 0
    screen._layout_two.click()
    assert screen.pending_mode_message() is None
    assert win._next_action.isEnabled()
    win._go_to_page(1)
    assert win._stack.currentIndex() == 1


def test_2d_project_page_is_not_blocked(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    win._go_to_page(0)
    assert win._stack.widget(0).pending_mode_message() is None
    assert win._next_action.isEnabled()


# ── the Views page (page 10) in the route ──────────────────────────────────


def _routed_window(qtbot, tmp_path: Path, mode: ProjectMode):
    win = _window(qtbot, tmp_path)
    win._store.update_mode(mode)
    win._store.update_sessions([_ref(tmp_path)])
    win._go_to_page(1)
    return win


def test_3d_next_from_sessions_goes_through_views(qtbot, tmp_path) -> None:
    win = _routed_window(qtbot, tmp_path, THREE_D)
    win._go_next()
    assert win._stack.currentIndex() == 10
    win._go_next()
    assert win._stack.currentIndex() == 2
    win._go_back()
    assert win._stack.currentIndex() == 10
    win._go_back()
    assert win._stack.currentIndex() == 1


def test_2d_next_from_sessions_skips_views(qtbot, tmp_path) -> None:
    win = _routed_window(qtbot, tmp_path, ProjectMode())
    win._go_next()
    assert win._stack.currentIndex() == 2


def test_views_page_footer_and_sidebar(qtbot, tmp_path) -> None:
    win = _routed_window(qtbot, tmp_path, THREE_D)
    win._go_to_page(10)
    assert win._btn_next.text() == "Next: Calibration →"
    assert win._btn_back.text() == "← Sessions"
    assert not win._btn_run.isHidden()
    assert win._sidebar.currentRow() == 1


def test_footer_unchanged_on_late_pages(qtbot, tmp_path) -> None:
    win = _routed_window(qtbot, tmp_path, THREE_D)
    win._go_to_page(8)
    assert win._btn_next.text() == "Export dataset →"
    assert win._btn_run.isHidden()
    win._go_to_page(9)
    assert win._btn_next.text() == "Done"
    assert not win._next_action.isEnabled()
    assert win._btn_run.isHidden()


def test_mode_change_refreshes_footer(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    win._go_to_page(1)
    assert win._btn_next.text() == "Next: Calibration →"
    win._store.update_mode(THREE_D)
    assert win._btn_next.text() == "Next: Sessions →"  # the Views page, under Sessions
