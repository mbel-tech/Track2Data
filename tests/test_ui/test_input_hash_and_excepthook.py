"""
Review findings B8 and B9 (12 Nov 2026).

B8  Re-probing a session (every project open) overwrote SessionRef.sha256, so the
    stored "these bytes produced these numbers" claim silently followed whatever
    file was on disk. Only an empty hash is filled; a different one is kept and
    the user is warned.
B9  A windowed build had no sys.excepthook, so an exception in a Qt slot vanished.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import ProjectManifest, SessionRef


@pytest.fixture
def store(qtbot, tmp_path: Path):
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    s = ProjectStore()
    s._manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now)
    s._project_dir = tmp_path
    yield s
    s.tasks.shutdown(3000)


def _with_ref(store, tmp_path: Path, sha: str) -> Path:
    traj = tmp_path / "trajectories.npy"
    traj.write_bytes(b"new bytes")
    store._manifest = store._manifest.model_copy(
        update={"sessions": [SessionRef(session_id="s", folder=tmp_path, sha256=sha)]}
    )
    return traj


def test_an_empty_hash_is_filled(store, tmp_path: Path) -> None:
    traj = _with_ref(store, tmp_path, "")
    store._set_session_input_hash("s", SimpleNamespace(trajectory_source=traj))
    assert store.manifest.sessions[0].sha256 == hashlib.sha256(b"new bytes").hexdigest()


def test_a_changed_input_keeps_the_stored_hash_and_warns(qtbot, store, tmp_path: Path) -> None:
    old = "0" * 64
    traj = _with_ref(store, tmp_path, old)
    logged: list[str] = []
    store.runLogAppended.connect(logged.append)
    with qtbot.waitSignal(store.sessionInputChanged, timeout=1000) as blocker:
        store._set_session_input_hash("s", SimpleNamespace(trajectory_source=traj))
    assert store.manifest.sessions[0].sha256 == old
    assert blocker.args[0] == "s"
    assert "changed" in blocker.args[1]
    assert any("changed" in line for line in logged)


def test_the_same_hash_is_silent(qtbot, store, tmp_path: Path) -> None:
    traj = _with_ref(store, tmp_path, hashlib.sha256(b"new bytes").hexdigest())
    with qtbot.assertNotEmitted(store.sessionInputChanged):
        store._set_session_input_hash("s", SimpleNamespace(trajectory_source=traj))


def test_the_excepthook_logs_and_shows_a_dialog(monkeypatch, caplog) -> None:
    from app import main as app_main

    shown: list[str] = []
    monkeypatch.setattr(app_main, "_show_error_dialog", lambda text: shown.append(text))
    previous = sys.excepthook
    try:
        app_main.install_excepthook()
        try:
            raise RuntimeError("slot blew up")
        except RuntimeError:
            exc_type, exc, tb = sys.exc_info()
        with caplog.at_level(logging.ERROR):
            sys.excepthook(exc_type, exc, tb)
    finally:
        sys.excepthook = previous
    assert any("slot blew up" in (r.exc_text or r.getMessage()) for r in caplog.records)
    assert shown and "slot blew up" in shown[0]


def test_the_excepthook_lets_keyboard_interrupt_through(monkeypatch) -> None:
    from app import main as app_main

    called: list[object] = []
    monkeypatch.setattr(app_main, "_show_error_dialog", lambda text: called.append(text))
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: called.append("default"))
    previous = sys.excepthook
    try:
        app_main.install_excepthook()
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        sys.excepthook = previous
    assert called == ["default"]
