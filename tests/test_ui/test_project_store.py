"""
Tests for the identity-probe extension to
ui/store/project_store.py's add_session(): a background reader read
(via TaskRunner) that fills in SessionRef.has_stable_identities once
it completes. See
docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md
§5.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from track2data.core.models import ProjectManifest, Session, VideoInfo


@pytest.fixture
def store(qtbot, tmp_path: Path):
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    s = ProjectStore()
    s._manifest = ProjectManifest(project_name="test_project", created_at=now, updated_at=now)
    s._project_dir = tmp_path
    yield s
    s.tasks.shutdown(3000)


def test_add_session_registers_ref_immediately(qtbot, store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    assert [s.session_id for s in store.manifest.sessions] == ["session_a"]
    assert store.manifest.sessions[0].has_stable_identities is None


def test_add_session_fills_in_has_stable_identities_on_probe_success(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        return Session(
            session_id=folder.name,
            folder=folder,
            reader="fake",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 1, 2)),
        )

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)  # first emission: immediate registration

    with qtbot.waitSignal(store.sessionsChanged, timeout=2000):
        pass  # second emission: probe completion

    assert store.manifest.sessions[0].has_stable_identities is True


def test_add_session_leaves_has_stable_identities_none_on_probe_failure(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    logged: list[str] = []
    store.runLogAppended.connect(logged.append)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    with qtbot.waitSignal(store.runLogAppended, timeout=2000):
        pass

    assert store.manifest.sessions[0].has_stable_identities is None
    assert any("Identity probe failed" in line for line in logged)


def test_identity_probes_cleared_on_new_project(store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    # Add a session, which submits a probe task
    store.add_session(folder)

    # Verify the probe is tracked
    assert len(store._identity_probes) == 1

    # Create a new project
    store.new_project("new_project", tmp_path)

    # Verify probes are cleared
    assert store._identity_probes == {}


def test_identity_probes_cleared_on_open_project(store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    # Add a session, which submits a probe task
    store.add_session(folder)

    # Verify the probe is tracked
    assert len(store._identity_probes) == 1

    # Create a dummy project file to open
    from track2data.core.models import ProjectManifest
    import json

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="existing_project", created_at=now, updated_at=now
    )
    project_file = tmp_path / "existing_project.t2d.json"
    project_file.write_text(manifest.model_dump_json())

    # Open the project
    store.open_project(project_file)

    # Verify probes are cleared
    assert store._identity_probes == {}
