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

from track2data.core.models import ProjectManifest, Session, SessionRef, VideoInfo
from ui.store.session_facts import SessionFacts


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


# ── SessionFacts cache (Foundation for Sessions/Calibration/Zones) ─────────


def test_session_facts_is_none_before_probe_completes(store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    store.add_session(folder)

    assert store.session_facts("session_a") is None


def test_session_facts_unknown_id_returns_none(store) -> None:
    assert store.session_facts("no_such_session") is None


def test_session_facts_populated_on_probe_success(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        return Session(
            session_id=folder.name,
            folder=folder,
            reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=200),
            n_animals=3,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 3, 2)),
            idtrackerai_version="6.0.15a0",
            length_unit=12.5,
            setup_points={"feeder": [10, 20]},
            roi_list=[{"name": "arena", "level": "main", "points": [[0, 0]]}],
            background_image_path=folder / "preprocessing" / "background.png",
        )

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionFactsChanged, timeout=2000):
        store.add_session(folder)

    facts = store.session_facts("session_a")
    assert facts is not None
    assert facts.session_id == "session_a"
    assert facts.reader == "idtrackerai"
    assert facts.fps == 25.0
    assert facts.n_frames == 10
    assert facts.n_animals == 3
    assert facts.width_px == 100
    assert facts.height_px == 200
    assert facts.has_stable_identities is True
    assert facts.background_image_path == folder / "preprocessing" / "background.png"
    assert facts.idtrackerai_version == "6.0.15a0"
    assert facts.length_unit == 12.5
    assert facts.setup_points == {"feeder": [10, 20]}
    assert facts.roi_list == [{"name": "arena", "level": "main", "points": [[0, 0]]}]
    assert facts.has_body_length is False


def test_session_facts_stays_none_on_probe_failure(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    with qtbot.waitSignal(store.runLogAppended, timeout=2000):
        pass  # probe-failure log line, same completion signal as the has_stable_identities test

    assert store.session_facts("session_a") is None


def test_session_facts_cleared_on_new_project(store, tmp_path: Path) -> None:
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

    store._session_facts["session_a"] = SessionFacts.from_session(
        fake_read_session(tmp_path / "session_a")
    )

    store.new_project("new_project", tmp_path)

    assert store.session_facts("session_a") is None


def test_session_facts_pruned_when_session_removed_via_update_sessions(
    store, tmp_path: Path
) -> None:
    def fake_session(session_id: str) -> Session:
        return Session(
            session_id=session_id,
            folder=tmp_path / session_id,
            reader="fake",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 1, 2)),
        )

    store._session_facts["session_a"] = SessionFacts.from_session(fake_session("session_a"))
    store._session_facts["session_b"] = SessionFacts.from_session(fake_session("session_b"))
    store.update_sessions(
        [SessionRef(session_id="session_b", folder=tmp_path / "session_b", sha256="")]
    )

    assert store.session_facts("session_a") is None
    assert store.session_facts("session_b") is not None


def test_identity_probes_cleared_on_open_project(store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    # Add a session, which submits a probe task
    store.add_session(folder)

    # Verify the probe is tracked
    assert len(store._identity_probes) == 1

    # Create a dummy project file to open
    from track2data.core.models import ProjectManifest

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
