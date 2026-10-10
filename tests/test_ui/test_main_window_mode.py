"""MainWindow behaviour that depends on the project's 2D/3D mode."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.navigation import SUMMARY_ROLE
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
    assert win._btn_next.text() == "Next: Views →"


# ── the Sessions sidebar row carries the Views status in 3-D ───────────────


def _two_view_refs(tmp_path: Path) -> list[SessionRef]:
    return [
        SessionRef(session_id=sid, folder=tmp_path / sid, sha256="0" * 64)
        for sid in ("t1_top", "t1_side")
    ]


def test_3d_sessions_row_shows_worse_of_sessions_and_views(qtbot, tmp_path) -> None:
    from track2data.core.models import FusionSettings, ViewPair

    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_mode(THREE_D)
    store.update_sessions(_two_view_refs(tmp_path))
    # Sessions valid, Views empty (no roles yet) -> empty
    assert win._sidebar.status(1) == "empty"
    assert "Views: Choose a view" in win._sidebar.item(1).toolTip()
    assert win._sidebar.item(1).data(SUMMARY_ROLE) == "2 sessions · 0 pairs"
    # Only viewsChanged fires for a role change: the row must still refresh.
    store.update_view_role("t1_top", "top")
    store.update_view_role("t1_side", "side")
    assert win._sidebar.status(1) == "warning"
    assert "is not paired" in win._sidebar.item(1).toolTip()
    store.update_view_pair(
        ViewPair(top_session_id="t1_top", side_session_id="t1_side", fish_map={"0": "0"})
    )
    assert win._sidebar.status(1) == "warning"
    assert "Fusion setup needed" in win._sidebar.item(1).toolTip()
    store.update_fusion(
        "t1_top",
        "t1_side",
        FusionSettings(surface_row=10.0, floor_row=110.0, tank_height_cm=20.0),
    )
    assert win._sidebar.status(1) == "valid"
    assert win._sidebar.item(1).data(SUMMARY_ROLE) == "2 sessions · 1 pair"
    # Next from Sessions follows the Sessions page alone.
    win._go_to_page(1)
    assert win._next_action.isEnabled()


def test_2d_sessions_row_ignores_views(qtbot, tmp_path) -> None:
    win = _window(qtbot, tmp_path)
    win._store.update_sessions(_two_view_refs(tmp_path))
    assert win._sidebar.status(1) == "valid"
    assert win._sidebar.item(1).toolTip() == "2 session(s)."
    assert win._sidebar.item(1).data(SUMMARY_ROLE) == "2 sessions"


# ── 3-D with a pair set up for fusion ────────────────────────────────────────


def _fused_window(qtbot, tmp_path, monkeypatch, outcome=None):
    import track2data.api  # noqa: F401  (preloaded: see test_fusion_section.py)
    from tests.test_ui.plan3d import SETTINGS, install_planner

    fake = install_planner(monkeypatch)
    if outcome is not None:
        fake.outcome = outcome
    win = _window(qtbot, tmp_path)
    store = win._store
    store.update_mode(THREE_D)
    store.update_sessions(_two_view_refs(tmp_path))
    store.update_view_role("t1_top", "top")
    store.update_view_role("t1_side", "side")
    from track2data.core.models import ViewPair

    store.update_view_pair(ViewPair(top_session_id="t1_top", side_session_id="t1_side"))
    store.update_fusion("t1_top", "t1_side", SETTINGS)
    return win, fake


def test_3d_with_fusion_settings_unblocks_run_and_results(qtbot, tmp_path, monkeypatch) -> None:
    win, _ = _fused_window(qtbot, tmp_path, monkeypatch)
    store = win._store
    for stage in (7, 8):
        assert win._sidebar.status(stage) != "blocked"
    assert win._run_action.isEnabled()
    from track2data.core.models import SessionRunResult

    store.set_run_results(RunResult(sessions=[SessionRunResult(session_id="t1_top+t1_side")]))
    assert 8 not in win._sidebar._locked
    assert win._sidebar.status(7) == "valid"


def test_3d_validate_uses_the_plan_off_the_gui_thread(qtbot, tmp_path, monkeypatch) -> None:
    import threading

    from tests.test_ui.plan3d import make_plan
    from track2data.api import Engine
    from ui.store.run_plan import PlanOutcome

    outcome = PlanOutcome(make_plan(("t1_top+t1_side",), (("x", "not in a fusable pair"),)))
    win, _fake = _fused_window(qtbot, tmp_path, monkeypatch, outcome)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.information",
        staticmethod(lambda *a, **k: shown.append(("info", a[2]))),
    )
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        staticmethod(lambda *a, **k: shown.append(("warn", a[2]))),
    )
    gui_calls: list[str] = []
    for name in ("run_units", "validate", "fuse_pair", "require_computable"):
        orig = getattr(Engine, name)

        def spy(self, *a, _orig=orig, _name=name, **k):
            if threading.current_thread() is threading.main_thread():
                gui_calls.append(_name)
            return _orig(self, *a, **k)

        monkeypatch.setattr(Engine, name, spy)
    qtbot.waitUntil(lambda: win._store.run_plan.current_plan() is not None, timeout=3000)
    win._action_validate()
    assert gui_calls == []
    assert len(shown) == 1
    assert "Will run: t1_top+t1_side" in shown[0][1]
    assert "Skipped: x — not in a fusable pair" in shown[0][1]


def test_3d_validate_while_checking_says_so(qtbot, tmp_path, monkeypatch) -> None:
    import threading

    win, fake = _fused_window(qtbot, tmp_path, monkeypatch)
    fake.hold = threading.Event()
    from tests.test_ui.plan3d import OTHER

    win._store.update_fusion("t1_top", "t1_side", OTHER)
    shown: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(
            f"app.main_window.QMessageBox.{kind}",
            staticmethod(lambda *a, **k: shown.append(a[2])),
        )
    win._action_validate()
    fake.hold.set()
    assert len(shown) == 1 and "Checking" in shown[0]
