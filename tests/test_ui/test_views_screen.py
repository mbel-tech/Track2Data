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
    store.update_view_role("t1_top", "top")
    store.update_pairing(PairingPatterns(top_regex=TOP, side_regex=SIDE))
    assert screen._top_regex_edit.text() == TOP
    assert _combo(screen, 0).currentText() == "Top"
    # Change the store behind the page's back, then let the page rebuild.
    with qtbot.assertNotEmitted(store.viewsChanged):
        store.blockSignals(True)
        store.update_view_role("t1_top", None)
        store.update_pairing(PairingPatterns(top_regex="(?P<key>a)", side_regex="(?P<key>b)"))
        store.blockSignals(False)
    calls = []
    monkeypatch.setattr(store, "update_view_role", lambda *a: calls.append(a))
    monkeypatch.setattr(store, "update_pairing", lambda *a: calls.append(a))
    store.sessionsChanged.emit()
    store.projectChanged.emit()
    assert screen._top_regex_edit.text() == "(?P<key>a)"
    assert screen._side_regex_edit.text() == "(?P<key>b)"
    assert _combo(screen, 0).currentText() == "(not set)"
    screen._commit.flush()
    assert calls == []
    assert not screen._commit.pending


def test_apply_right_after_typing_uses_typed_patterns(qtbot, tmp_path) -> None:
    store, screen = _make(qtbot, tmp_path)
    screen._top_regex_edit.setText(TOP)
    screen._side_regex_edit.setText(SIDE)
    assert screen._commit.pending
    screen._apply_btn.click()
    assert store.manifest.mode.pairing == PairingPatterns(top_regex=TOP, side_regex=SIDE)
    assert len(store.manifest.view_pairs) == 2


def test_side_help_button_shows_popover(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path)
    screen._side_help_btn.click()
    assert screen._popover.isVisible()


def test_ambiguous_key_listed(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path, names=("a_top", "a2_top", "a_side"))
    screen._top_regex_edit.setText(r"(?P<key>a)\d*_top$")
    screen._side_regex_edit.setText(SIDE)
    assert "Ambiguous" in screen._unpaired_label.text()
    assert "a" in screen._unpaired_label.text()


def test_session_matching_both_patterns_listed(qtbot, tmp_path) -> None:
    _, screen = _make(qtbot, tmp_path, names=("x_top_side", "t1_top"))
    screen._top_regex_edit.setText(r"(?P<key>.+)_top")
    screen._side_regex_edit.setText(r"(?P<key>.+)_side$")
    assert "Match both patterns: x_top_side" in screen._unpaired_label.text()


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


# ── pair list ──────────────────────────────────────────────────────────────


def _facts(sid, labels=None, n=0, stable=True):
    from ui.store.session_facts import SessionFacts

    return SessionFacts(
        session_id=sid, reader="idtrackerai", fps=30.0, n_frames=10, n_animals=n,
        width_px=10, height_px=10, has_stable_identities=stable, track_wo_identities=None,
        idtrackerai_version=None, length_unit=None, setup_points=None, roi_list=None,
        has_body_length=False, identities_labels=labels, background_image_path=None,
    )


def _paired(qtbot, tmp_path, top_labels=None, side_labels=None, names=("t1_top", "t1_side")):
    from track2data.core.models import ViewPair

    store, screen = _make(qtbot, tmp_path, names=names)
    store.update_view_role("t1_top", "top")
    store.update_view_role("t1_side", "side")
    store.update_view_pair(ViewPair(top_session_id="t1_top", side_session_id="t1_side"))
    if top_labels is not None:
        store._session_facts["t1_top"] = _facts("t1_top", top_labels, len(top_labels))
        store._session_facts["t1_side"] = _facts("t1_side", side_labels, len(side_labels))
        store.sessionFactsChanged.emit()
    return store, screen


def _tick(screen, row=0):
    return screen._pairs_table.cellWidget(row, 2)


def _status(screen, row=0):
    return screen._pairs_table.item(row, 3)


def test_pair_row_needs_matching_without_facts(qtbot, tmp_path) -> None:
    _, screen = _paired(qtbot, tmp_path)
    assert screen._pairs_table.rowCount() == 1
    assert screen._pairs_table.item(0, 0).text() == "t1_top"
    assert screen._pairs_table.item(0, 1).text() == "t1_side"
    assert _status(screen).text() == "Needs matching"


def test_same_ids_tick_fills_identity_map(qtbot, tmp_path) -> None:
    store, screen = _paired(qtbot, tmp_path, ["a", "b"], ["a", "b"])
    assert _status(screen).text() == "Needs matching"
    _tick(screen).setChecked(True)
    pair = store.manifest.view_pairs[0]
    assert pair.same_ids and pair.fish_map == {"a": "a", "b": "b"}
    assert _status(screen).text() == "Matched"
    _tick(screen).setChecked(False)
    pair = store.manifest.view_pairs[0]
    assert not pair.same_ids and pair.fish_map == {"a": "a", "b": "b"}


def test_partial_overlap_maps_shared_and_lists_unmatched(qtbot, tmp_path) -> None:
    store, screen = _paired(qtbot, tmp_path, ["a", "b"], ["b", "c"])
    _tick(screen).setChecked(True)
    assert store.manifest.view_pairs[0].fish_map == {"b": "b"}
    assert _status(screen).text() == "Matched"
    tip = _status(screen).toolTip()
    assert tip == "Not matched: top a; side c"


def test_identity_free_session_cannot_match(qtbot, tmp_path) -> None:
    store, screen = _paired(qtbot, tmp_path, ["a"], ["a"])
    refs = [
        s.model_copy(update={"identity_free_override": True}) if s.session_id == "t1_side" else s
        for s in store.manifest.sessions
    ]
    store.update_sessions(refs)
    assert _status(screen).text() == "cannot match fish: this session has no stable identities"
    assert not _tick(screen).isEnabled()
    _tick(screen).setChecked(True)
    assert store.manifest.view_pairs[0].fish_map == {}


def test_remove_button_deletes_pair(qtbot, tmp_path) -> None:
    store, screen = _paired(qtbot, tmp_path)
    screen._pairs_table.cellWidget(0, 4).click()
    assert store.manifest.view_pairs == []
    assert screen._pairs_table.rowCount() == 0


def test_manual_add_excludes_paired_sessions(qtbot, tmp_path) -> None:
    store, screen = _paired(
        qtbot, tmp_path, names=("t1_top", "t1_side", "t2_top", "t2_side")
    )
    store.update_view_role("t2_top", "top")
    assert not screen._manual_add_btn.isEnabled()
    top_combo = screen._manual_top_combo
    assert [top_combo.itemText(i) for i in range(top_combo.count())] == ["t2_top"]
    assert screen._manual_side_combo.count() == 0
    store.update_view_role("t2_side", "side")
    assert screen._manual_add_btn.isEnabled()
    screen._manual_add_btn.click()
    assert [(p.top_session_id, p.side_session_id) for p in store.manifest.view_pairs] == [
        ("t1_top", "t1_side"),
        ("t2_top", "t2_side"),
    ]
    assert screen._manual_top_combo.count() == 0
    assert not screen._manual_add_btn.isEnabled()


def test_selection_emits_and_survives_rebuild(qtbot, tmp_path) -> None:
    store, screen = _paired(
        qtbot, tmp_path, names=("t1_top", "t1_side", "t2_top", "t2_side")
    )
    store.update_view_role("t2_top", "top")
    store.update_view_role("t2_side", "side")
    screen._manual_add_btn.click()
    assert screen._current_pair is None
    with qtbot.waitSignal(screen.pairSelected) as sig:
        screen._pairs_table.selectRow(1)
    assert sig.args == [("t2_top", "t2_side")]
    with qtbot.assertNotEmitted(screen.pairSelected):
        store.sessionFactsChanged.emit()
        store.update_view_pair(store.manifest.view_pairs[1].model_copy(update={"same_ids": True}))
    assert screen._current_pair == ("t2_top", "t2_side")
    with qtbot.waitSignal(screen.pairSelected) as sig:
        store.remove_view_pair("t2_top", "t2_side")
    assert sig.args == [None]


def test_pair_rebuild_does_not_write_back(qtbot, tmp_path, monkeypatch) -> None:
    from track2data.core.models import ViewPair

    store, _screen = _paired(qtbot, tmp_path, ["a"], ["a"])
    store.update_view_pair(
        ViewPair(top_session_id="t1_top", side_session_id="t1_side", same_ids=True)
    )
    calls = []
    monkeypatch.setattr(store, "update_view_pair", lambda *a: calls.append(a))
    monkeypatch.setattr(store, "remove_view_pair", lambda *a: calls.append(a))
    store.sessionsChanged.emit()
    store.viewsChanged.emit()
    store.sessionFactsChanged.emit()
    assert calls == []


def test_rejected_tick_resyncs_checkbox(qtbot, tmp_path, monkeypatch) -> None:
    store, screen = _paired(qtbot, tmp_path, ["a"], ["a"])

    def boom(_pair):
        raise ValueError("nope")

    monkeypatch.setattr(store, "update_view_pair", boom)
    _tick(screen).setChecked(True)
    assert not _tick(screen).isChecked()
    assert screen._error_label.text() == "nope"


# ── manual matching ────────────────────────────────────────────────────────


def _fake_loader(monkeypatch, fail=()):
    import numpy as np

    from ui import views_screen
    from ui.preview_screen import TrajectoryData

    def fake(_manifest, session_id, _cache):
        if session_id in fail:
            raise RuntimeError("boom")
        xy = np.zeros((5, 3, 2))
        xy[:, :, 0] = np.arange(3) + np.arange(5)[:, None]
        return TrajectoryData(raw_xy=xy, xy=xy, fps=30.0, background=None, size=(50.0, 50.0))

    monkeypatch.setattr(views_screen, "load_trajectory_data", fake)


def _select(qtbot, screen):
    screen._pairs_table.selectRow(0)
    qtbot.waitUntil(lambda: screen._top_plot.n_frames == 5 and screen._side_plot.n_frames == 5)


def _match_combo(screen, row):
    return screen._match_table.cellWidget(row, 1)


def _matched(qtbot, tmp_path, monkeypatch, fish_map=None, **kw):
    from track2data.core.models import ViewPair

    _fake_loader(monkeypatch, **kw)
    store, screen = _paired(qtbot, tmp_path, ["a", "b", "c"], ["x", "y", "z"])
    if fish_map is not None:
        store.update_view_pair(
            ViewPair(top_session_id="t1_top", side_session_id="t1_side", fish_map=fish_map)
        )
    _select(qtbot, screen)
    return store, screen


def test_selecting_pair_fills_match_table(qtbot, tmp_path, monkeypatch) -> None:
    _, screen = _matched(qtbot, tmp_path, monkeypatch, {"a": "y", "c": "x"})
    t = screen._match_table
    assert [t.item(r, 0).text() for r in range(3)] == ["a", "b", "c"]
    assert [_match_combo(screen, r).itemData(0) for r in range(3)] == [None] * 3
    assert _match_combo(screen, 0).itemText(0) == "(no match)"
    assert [_match_combo(screen, 0).itemData(i) for i in range(1, 4)] == ["x", "y", "z"]
    assert [_match_combo(screen, r).currentData() for r in range(3)] == ["y", None, "x"]
    assert screen._match_issues.text() == ""


def test_combo_choice_writes_and_clears_map(qtbot, tmp_path, monkeypatch) -> None:
    store, screen = _matched(qtbot, tmp_path, monkeypatch)
    _match_combo(screen, 1).setCurrentIndex(3)
    assert store.manifest.view_pairs[0].fish_map == {"b": "z"}
    assert _match_combo(screen, 1).currentData() == "z"
    _match_combo(screen, 1).setCurrentIndex(0)
    assert store.manifest.view_pairs[0].fish_map == {}


def test_choosing_used_item_writes_bare_label_and_keeps_selection(
    qtbot, tmp_path, monkeypatch
) -> None:
    store, screen = _matched(qtbot, tmp_path, monkeypatch, {"a": "x"})
    screen._match_table.selectRow(2)
    combo = _match_combo(screen, 2)
    assert combo.itemText(1) == "x (used)"
    calls = []
    real = store.update_view_pair
    monkeypatch.setattr(store, "update_view_pair", lambda p: (calls.append(p), real(p))[1])
    combo.setCurrentIndex(1)
    assert len(calls) == 1 and calls[0].fish_map == {"a": "x", "c": "x"}
    assert store.manifest.view_pairs[0].fish_map["c"] == "x"
    assert screen._match_table.selectionModel().selectedRows()[0].row() == 2
    assert screen._top_plot.highlighted_animal == 2
    assert screen._side_plot.highlighted_animal == 0


def test_duplicate_side_fish_reported_and_marked(qtbot, tmp_path, monkeypatch) -> None:
    _, screen = _matched(qtbot, tmp_path, monkeypatch, {"a": "x", "b": "x"})
    assert "duplicate side fish: x" in screen._match_issues.text()
    combo = _match_combo(screen, 2)
    assert combo.itemData(1) == "x" and combo.itemText(1) != "x"
    assert _match_combo(screen, 0).itemText(1) == "x (used)"


def test_row_selection_highlights_both_plots(qtbot, tmp_path, monkeypatch) -> None:
    _, screen = _matched(qtbot, tmp_path, monkeypatch, {"a": "y"})
    assert screen._top_plot.highlighted_animal is None
    screen._match_table.selectRow(0)
    assert screen._top_plot.highlighted_animal == 0
    assert screen._side_plot.highlighted_animal == 1
    screen._match_table.selectRow(1)
    assert screen._top_plot.highlighted_animal == 1
    assert screen._side_plot.highlighted_animal is None


def test_identity_free_pair_disables_table(qtbot, tmp_path, monkeypatch) -> None:
    _fake_loader(monkeypatch)
    store, screen = _paired(qtbot, tmp_path, ["a"], ["a"])
    refs = [
        s.model_copy(update={"identity_free_override": True}) if s.session_id == "t1_side" else s
        for s in store.manifest.sessions
    ]
    store.update_sessions(refs)
    screen._pairs_table.selectRow(0)
    msg = "cannot match fish: this session has no stable identities"
    assert screen._match_issues.text() == msg
    assert not screen._match_table.isEnabled()
    screen._match_table.selectRow(0)
    store.sessionFactsChanged.emit()
    assert screen._match_table.selectionModel().selectedRows() == []


def test_pair_without_facts_has_empty_table(qtbot, tmp_path, monkeypatch) -> None:
    _fake_loader(monkeypatch)
    _, screen = _paired(qtbot, tmp_path)
    screen._pairs_table.selectRow(0)
    assert screen._match_table.rowCount() == 0


def test_failed_load_shows_error(qtbot, tmp_path, monkeypatch) -> None:
    _fake_loader(monkeypatch, fail=("t1_side",))
    _, screen = _paired(qtbot, tmp_path, ["a"], ["a"])
    screen._pairs_table.selectRow(0)
    qtbot.waitUntil(lambda: "boom" in screen._match_status.text())
    screen._pairs_table.clearSelection()
    assert screen._match_table.rowCount() == 0


class _ManualTasks:
    """Records submitted loads; the test delivers results itself."""

    def __init__(self, store, monkeypatch):
        self.submitted: list[str] = []
        self.store = store
        monkeypatch.setattr(store.tasks, "submit", self._submit)

    def _submit(self, fn):
        tid = f"task{len(self.submitted)}"
        self.submitted.append(tid)
        return tid

    def finish(self, tid):
        import numpy as np

        from ui.preview_screen import TrajectoryData

        xy = np.zeros((5, 3, 2))
        xy[:, :, 0] = np.arange(3) + np.arange(5)[:, None]
        data = TrajectoryData(raw_xy=xy, xy=xy, fps=30.0, background=None, size=(50.0, 50.0))
        self.store.taskFinished.emit(tid, data)


def _two_pairs(qtbot, tmp_path, monkeypatch):
    from track2data.core.models import ViewPair

    store, screen = _paired(
        qtbot, tmp_path, ["a"], ["a"], names=("t1_top", "t1_side", "t2_top", "t2_side")
    )
    store.update_view_role("t2_top", "top")
    store.update_view_role("t2_side", "side")
    store.update_view_pair(ViewPair(top_session_id="t2_top", side_session_id="t2_side"))
    store._session_facts["t2_top"] = _facts("t2_top", ["a"], 1)
    store._session_facts["t2_side"] = _facts("t2_side", ["a"], 1)
    return store, screen, _ManualTasks(store, monkeypatch)


def test_stale_result_for_previous_pair_is_ignored(qtbot, tmp_path, monkeypatch) -> None:
    _store, screen, tasks = _two_pairs(qtbot, tmp_path, monkeypatch)
    screen._pairs_table.selectRow(0)
    old = list(tasks.submitted)
    assert len(old) == 2
    screen._pairs_table.selectRow(1)
    tasks.finish(old[0])
    tasks.finish(old[1])
    assert screen._top_plot.n_frames == 0 and screen._side_plot.n_frames == 0
    tasks.finish(tasks.submitted[2])
    assert screen._top_plot.n_frames == 5 and screen._side_plot.n_frames == 0
    assert screen._match_table.item(0, 0).text() == "a"


def test_plots_cleared_when_selecting_or_clearing_pair(qtbot, tmp_path, monkeypatch) -> None:
    _store, screen, tasks = _two_pairs(qtbot, tmp_path, monkeypatch)
    screen._pairs_table.selectRow(0)
    for tid in tasks.submitted:
        tasks.finish(tid)
    assert screen._top_plot.n_frames == 5
    screen._pairs_table.selectRow(1)
    assert screen._top_plot.n_frames == 0 and screen._side_plot.n_frames == 0
    for tid in tasks.submitted[2:]:
        tasks.finish(tid)
    screen._pairs_table.clearSelection()
    assert screen._top_plot.n_frames == 0 and screen._side_plot.n_frames == 0


def test_whole_track_is_drawn_after_load(qtbot, tmp_path, monkeypatch) -> None:
    _, screen = _matched(qtbot, tmp_path, monkeypatch)
    for plot in (screen._top_plot, screen._side_plot):
        assert plot.current_frame == 4
        assert plot.trail_point_count() > 3


def test_project_change_with_same_ids_drops_old_loads_and_reloads(
    qtbot, tmp_path, monkeypatch
) -> None:
    store, screen, tasks = _two_pairs(qtbot, tmp_path, monkeypatch)
    screen._pairs_table.selectRow(0)
    old = list(tasks.submitted)
    store.projectChanged.emit()
    assert screen._current_pair == ("t1_top", "t1_side")
    assert len(tasks.submitted) == 4
    tasks.finish(old[0])
    assert screen._top_plot.n_frames == 0
    tasks.finish(tasks.submitted[2])
    assert screen._top_plot.n_frames == 5


def test_facts_change_reloads_selected_pair(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, tasks = _two_pairs(qtbot, tmp_path, monkeypatch)
    screen._pairs_table.selectRow(0)
    store.sessionFactsChanged.emit()
    assert len(tasks.submitted) == 2  # unchanged facts: no reload
    store._session_facts["t1_top"] = _facts("t1_top", ["a", "b"], 2)
    store.sessionFactsChanged.emit()
    assert len(tasks.submitted) == 4
    assert screen._match_table.rowCount() == 2


def test_cleared_selection_never_writes(qtbot, tmp_path, monkeypatch) -> None:
    store, screen = _matched(qtbot, tmp_path, monkeypatch, {"a": "x"})
    calls = []
    monkeypatch.setattr(store, "update_view_pair", lambda *a: calls.append(a))
    screen._pairs_table.clearSelection()
    screen._on_pair_selected(None)
    store.sessionFactsChanged.emit()
    assert calls == [] and screen._match_table.rowCount() == 0
