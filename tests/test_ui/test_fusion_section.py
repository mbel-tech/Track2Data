"""Tests for the Fusion section of the Views page (ui/widgets/fusion_section.py)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

# Preloaded so the store's own background work (session-facts probes) does not import
# track2data.api on a worker thread during garbage collection, which can segfault on 3.13.
# Tests only; production does not preload.
import track2data.api  # noqa: F401
from track2data.core.models import FusionSettings, ProjectMode, SessionRef, ViewPair
from track2data.fusion.fuse import FusionError

SETTINGS = FusionSettings(surface_row=10, floor_row=110, tank_height_cm=20)
OTHER = FusionSettings(frame_offset=3, surface_row=10, floor_row=110, tank_height_cm=20)


def _refs(tmp_path: Path, names) -> list[SessionRef]:
    return [SessionRef(session_id=n, folder=tmp_path / n, sha256="0" * 64) for n in names]


def _report(**kw):
    base = dict(
        overlap_frames=120,
        fused_labels=["a", "b"],
        n_outside_column=4,
        agreement_rms_cm=1.234,
        agreement_skipped=None,
        agreement_warning=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _make(qtbot, tmp_path, monkeypatch, layout="two_videos", with_settings=True):
    from ui.store.project_store import ProjectStore
    from ui.views_screen import ViewsScreen
    from ui.widgets import fusion_section

    calls: dict = {"fuse": [], "load": [], "dialogs": [], "result": _report()}

    def fake_fuse(manifest, pair, cache_dir):
        calls["fuse"].append(pair.fusion)
        gate = calls.get("gate")
        if gate is not None:
            gate.wait(5)
        calls["calib"] = manifest.calibration.px_per_cm
        res = calls["result"]
        if isinstance(res, Exception):
            raise res
        return SimpleNamespace(report=res)

    def fake_load(manifest, pair, cache_dir):
        calls["load"].append(pair.top_session_id)
        if calls.get("fail"):
            raise RuntimeError("boom")
        bg = calls.get("bg")
        side = SimpleNamespace(session=SimpleNamespace(background_image_path=bg))
        return SimpleNamespace(), side

    class StubDialog:
        def __init__(
            self, top, side, pair, same_video, background_path=None, parent=None,
            background_crop=None,
        ):
            calls["dialogs"].append((same_video, background_path))
            calls.setdefault("crops", []).append(background_crop)
            hook = calls.get("during_dialog")
            if hook:
                hook()

        def exec(self):
            return calls.get("accept", True)

        def result_settings(self):
            return OTHER

    monkeypatch.setattr(fusion_section, "fuse_status", fake_fuse)
    monkeypatch.setattr(fusion_section, "load_pair_sessions", fake_load)
    monkeypatch.setattr(fusion_section, "FusionDialog", StubDialog)
    store = ProjectStore()
    screen = ViewsScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    store.new_project("p", tmp_path, mode=ProjectMode(dimension="3d", layout=layout))
    store.update_sessions(_refs(tmp_path, ("t_top", "t_side")))
    store.update_view_role("t_top", "top")
    store.update_view_role("t_side", "side")
    store.update_view_pair(ViewPair(top_session_id="t_top", side_session_id="t_side"))
    if with_settings:
        store.update_fusion("t_top", "t_side", SETTINGS)
    screen.refresh_now()
    return store, screen, calls


def _select(screen) -> None:
    screen._pairs_table.selectRow(0)


def test_hidden_in_2d_shown_in_3d(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, _ = _make(qtbot, tmp_path, monkeypatch)
    assert screen._fusion_box.isVisible()
    assert screen._fusion_box.title() == "Fusion"
    store.new_project("q", tmp_path, mode=ProjectMode())
    screen.refresh_now()
    assert not screen._fusion_box.isVisible()


def test_no_pair_and_no_settings_states(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch, with_settings=False)
    assert screen._fusion_status.text() == "Select a pair."
    assert not screen._fusion_btn.isEnabled()
    _select(screen)
    assert screen._fusion_status.text() == "Fusion setup needed."
    assert screen._fusion_btn.isEnabled()
    assert calls["fuse"] == []


def test_ready_status_after_selecting(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    assert screen._fusion_status.text() == (
        "Ready: 120 shared frames, 2 fish fused, 4 positions outside the water column, "
        "agreement 1.23 cm"
    )
    assert len(calls["fuse"]) == 1
    screen.refresh_now()  # unchanged pair, settings and sessions: no second task
    screen.refresh_now()
    assert len(calls["fuse"]) == 1
    assert screen._fusion_status.text().startswith("Ready")


def test_warning_and_skipped_texts(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["result"] = _report(agreement_rms_cm=None, agreement_skipped="top view not calibrated")
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    assert "top view not calibrated" in screen._fusion_status.text()
    from ui.widgets.fusion_section import ready_text

    assert "agreement warning" in ready_text(_report(agreement_warning=True))


def test_fusion_error_shown_verbatim(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["result"] = FusionError("session t_side could not be read: gone")
    _select(screen)
    qtbot.waitUntil(
        lambda: screen._fusion_status.text() == "session t_side could not be read: gone",
        timeout=3000,
    )


def test_stale_result_ignored(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    gate = calls["gate"] = threading.Event()
    _select(screen)
    qtbot.waitUntil(lambda: len(calls["fuse"]) == 1, timeout=3000)
    screen._pairs_table.clearSelection()
    assert screen._fusion_status.text() == "Select a pair."
    gate.set()
    qtbot.wait(200)
    assert screen._fusion_status.text() == "Select a pair."
    assert screen._fusion_box._result_text is None


def test_accept_updates_store_once_and_refreshes(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    writes = []
    orig = store.update_fusion
    store.update_fusion = lambda *a: (writes.append(a), orig(*a))[1]
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(writes) == 1, timeout=3000)
    assert writes == [("t_top", "t_side", OTHER)]
    assert calls["dialogs"] == [(False, None)]
    qtbot.waitUntil(lambda: OTHER in calls["fuse"], timeout=3000)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    qtbot.wait(100)
    assert len(writes) == 1
    assert calls["fuse"] == [SETTINGS, OTHER]


def test_same_video_flag(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch, layout="single_video_two_panels")
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 1, timeout=3000)
    assert calls["dialogs"][0][0] is True


def test_cancel_writes_nothing(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["accept"] = False
    before = store.manifest
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 1, timeout=3000)
    qtbot.wait(50)
    assert store.manifest is before


def test_load_failure_shows_error(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["fail"] = True
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: "boom" in screen._fusion_status.text(), timeout=3000)
    assert calls["dialogs"] == []


def test_removed_session_while_loading(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    _select(screen)
    screen._fusion_btn.click()
    store.update_sessions(_refs(tmp_path, ("t_top",)))
    qtbot.waitUntil(lambda: calls["load"] == ["t_top"], timeout=3000)
    qtbot.wait(150)
    assert calls["dialogs"] == []
    assert OTHER not in [p.fusion for p in store.manifest.view_pairs]
    assert screen._fusion_status.text() == "Select a pair."


def test_removed_during_dialog_writes_nothing(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["during_dialog"] = lambda: store.update_sessions(_refs(tmp_path, ("t_top",)))
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 1, timeout=3000)
    qtbot.wait(100)
    assert all(p.fusion != OTHER for p in store.manifest.view_pairs)
    assert store.manifest.view_pairs == []


def test_rebuild_never_writes(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, _ = _make(qtbot, tmp_path, monkeypatch)
    store.update_fusion = lambda *a: pytest.fail("rebuild wrote")
    _select(screen)
    for _ in range(3):
        screen._fusion_box.rebuild()
        screen.refresh_now()


def test_calibration_change_resubmits_status(qtbot, tmp_path, monkeypatch) -> None:
    from track2data.core.models import CalibrationConfig

    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    assert len(calls["fuse"]) == 1
    calls["result"] = _report(agreement_rms_cm=None, agreement_skipped="top view not calibrated")
    store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=None))
    qtbot.waitUntil(lambda: len(calls["fuse"]) == 2, timeout=3000)
    qtbot.waitUntil(lambda: "not calibrated" in screen._fusion_status.text(), timeout=3000)
    store.update_calibration(CalibrationConfig(mode="scalar", px_per_cm=5.0))
    qtbot.waitUntil(lambda: len(calls["fuse"]) == 3, timeout=3000)
    qtbot.waitUntil(lambda: calls["calib"] == 5.0, timeout=3000)


def test_unrelated_change_does_not_resubmit(qtbot, tmp_path, monkeypatch) -> None:
    store, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text().startswith("Ready"), timeout=3000)
    store.metadataChanged.emit()
    store.exportChanged.emit()
    screen.refresh_now()
    qtbot.wait(150)
    assert len(calls["fuse"]) == 1


def test_dialog_gets_existing_background(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"x")
    calls["bg"] = bg
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 1, timeout=3000)
    assert calls["dialogs"][0][1] == bg
    calls["bg"] = tmp_path / "missing.png"
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 2, timeout=3000)
    assert calls["dialogs"][1][1] is None


def test_dialog_gets_side_panel_crop(qtbot, tmp_path, monkeypatch) -> None:
    from track2data.core.models import PanelRect

    store, screen, calls = _make(qtbot, tmp_path, monkeypatch, layout="single_video_two_panels")
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 1, timeout=3000)
    assert calls["crops"][0] is None
    store.set_session_panel("t_side", PanelRect(x=5, y=6, width=50, height=60))
    screen.refresh_now()
    _select(screen)
    screen._fusion_btn.click()
    qtbot.waitUntil(lambda: len(calls["dialogs"]) == 2, timeout=3000)
    assert calls["crops"][1] == PanelRect(x=5, y=6, width=50, height=60)


def test_fuse_status_names_unexpected_errors(monkeypatch) -> None:
    from track2data.api import Engine
    from ui.widgets import fusion_section

    def boom(self, pair):
        raise KeyError()

    monkeypatch.setattr(Engine, "fuse_pair", boom)
    with pytest.raises(FusionError, match=r"^KeyError$"):
        fusion_section.fuse_status(SimpleNamespace(), None, None)
    monkeypatch.setattr(Engine, "fuse_pair", lambda self, pair: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(FusionError, match=r"^OSError: x$"):
        fusion_section.fuse_status(SimpleNamespace(), None, None)


def test_blank_error_and_note_cleared(qtbot, tmp_path, monkeypatch) -> None:
    _, screen, calls = _make(qtbot, tmp_path, monkeypatch)
    calls["result"] = FusionError("")
    _select(screen)
    qtbot.waitUntil(lambda: screen._fusion_status.text() == "RuntimeError", timeout=3000)
    section = screen._fusion_box
    section._note = "old note"
    section._on_status_finished(section._key, SimpleNamespace(report=_report()))
    assert screen._fusion_status.text().startswith("Ready")
