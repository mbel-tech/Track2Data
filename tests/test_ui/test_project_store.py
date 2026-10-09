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

from track2data.core.models import ProjectManifest, ProjectMode, Session, SessionRef, VideoInfo
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
    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
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

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)

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
    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)

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
    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
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

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)

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
    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    with qtbot.waitSignal(store.runLogAppended, timeout=2000):
        pass  # probe-failure log line, same completion signal as the has_stable_identities test

    assert store.session_facts("session_a") is None


def test_session_facts_cleared_on_new_project(store, tmp_path: Path) -> None:
    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
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
        fake_probe_session(tmp_path / "session_a")
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


# ── pickled-trajectory consent ────────────────────────────────────────────────


def test_probe_asks_for_consent_when_the_reader_refuses_to_unpickle(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    """A folder whose only trajectory format executes code is not a broken
    folder -- the user has to be asked, and told which folder."""
    from track2data.core.errors import ImportError_

    def refusing_probe_session(folder: Path, **kwargs: object) -> Session:
        raise ImportError_(
            "No readable trajectory format among: npy. Skipped: npy "
            "(unreadable: [IDT_PICKLE_REFUSED] ...).",
            code="IDT_FORMAT_AMBIGUOUS",
            subject=str(folder),
        )

    monkeypatch.setattr("track2data.readers.probe_session", refusing_probe_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    with qtbot.waitSignal(store.pickleConsentRequired, timeout=2000) as blocker:
        pass

    session_id, reported_folder = blocker.args
    assert session_id == "session_a"
    assert reported_folder == str(folder)


def test_an_ordinary_probe_failure_does_not_ask_about_pickles(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    """Only a refusal asks. A genuinely broken folder must not be turned into
    a security question the user cannot answer usefully."""

    def broken_probe_session(folder: Path, **kwargs: object) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.probe_session", broken_probe_session)

    asked: list[tuple[str, str]] = []
    store.pickleConsentRequired.connect(lambda sid, f: asked.append((sid, f)))

    folder = tmp_path / "session_a"
    folder.mkdir()

    logged: list[str] = []
    store.runLogAppended.connect(logged.append)

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)
    qtbot.waitUntil(lambda: any("Identity probe failed" in line for line in logged), timeout=3000)

    assert asked == []


def test_consent_is_recorded_in_the_manifest(qtbot, store) -> None:
    """Persisted, so the user is asked once per project rather than once per
    launch -- a question repeated every session stops being read."""
    assert store.manifest.security.allow_pickle_trajectories is False

    with qtbot.waitSignal(store.projectChanged, timeout=1000):
        store.set_allow_pickle_trajectories(True)

    assert store.manifest.security.allow_pickle_trajectories is True


def test_probe_passes_the_project_setting_to_the_reader(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    """The consent has to actually reach the reader, or it is decoration."""
    seen: list[object] = []

    def recording_probe_session(folder: Path, **kwargs: object) -> Session:
        seen.append(kwargs.get("allow_pickle"))
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

    monkeypatch.setattr("track2data.readers.probe_session", recording_probe_session)
    store.set_allow_pickle_trajectories(True)

    folder = tmp_path / "session_a"
    folder.mkdir()
    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)
    qtbot.waitUntil(lambda: store.session_facts("session_a") is not None, timeout=3000)

    assert seen == [True]


def test_open_project_reprobes_existing_session_folders(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    probed: list[str] = []

    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
        probed.append(folder.name)
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

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)
    folder = tmp_path / "session_a"
    folder.mkdir()
    store.add_session(folder)
    qtbot.waitUntil(lambda: store.session_facts("session_a") is not None, timeout=2000)
    path = store.save_project()

    probed.clear()
    store.open_project(path)
    assert store.session_facts("session_a") is None  # cleared until re-probed
    qtbot.waitUntil(lambda: store.session_facts("session_a") is not None, timeout=2000)
    assert probed == ["session_a"]


# ── probes run in their own lane (PERF-03) ──────────────────────────────────


def _fake_session(folder: Path, **_kwargs: object) -> Session:
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


def test_probe_is_not_queued_behind_a_running_task(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    import threading

    monkeypatch.setattr("track2data.readers.probe_session", _fake_session)
    release = threading.Event()
    store.tasks.submit(lambda: release.wait(5))  # a long run occupying the run lane

    folder = tmp_path / "session_a"
    folder.mkdir()
    store.add_session(folder)
    qtbot.waitUntil(lambda: store.session_facts("session_a") is not None, timeout=3000)
    assert not release.is_set()
    release.set()


def test_a_failed_probe_does_not_emit_task_finished(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def boom(folder: Path, **kwargs: object) -> Session:
        raise RuntimeError("not a session")

    monkeypatch.setattr("track2data.readers.probe_session", boom)
    generic: list[object] = []
    store.taskFinished.connect(lambda tid, res: generic.append(res))
    logged: list[str] = []
    store.runLogAppended.connect(logged.append)

    folder = tmp_path / "session_a"
    folder.mkdir()
    store.add_session(folder)
    qtbot.waitUntil(lambda: any("Identity probe failed" in line for line in logged), timeout=3000)
    assert generic == []  # MainWindow shows its failure dialog on this signal


def test_new_project_cancels_queued_probes(qtbot, monkeypatch, store, tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    ran: list[str] = []

    def slow_probe(folder: Path, **kwargs: object) -> Session:
        ran.append(folder.name)
        gate.wait(5)
        return _fake_session(folder)

    monkeypatch.setattr("track2data.readers.probe_session", slow_probe)
    folders = []
    for name in ("a", "b"):
        f = tmp_path / name
        f.mkdir()
        folders.append(f)
        store.add_session(f)
    qtbot.waitUntil(lambda: ran == ["a"], timeout=3000)  # first is running, second queued

    store.new_project("other", tmp_path)
    gate.set()
    qtbot.wait(300)
    assert ran == ["a"]  # the queued probe never started
    assert store.session_facts("b") is None


def test_open_project_reprobes_with_the_saved_reader_and_options(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    """A session added with a chosen reader must not be re-detected when the project is
    reopened: another reader could read the same files into different numbers, and a
    reader that needs the frame rate cannot be probed without it."""
    seen: list[dict[str, object]] = []

    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
        seen.append(kwargs)
        return Session(
            session_id=folder.name,
            folder=folder,
            reader="toy",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 1, 2)),
        )

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)
    folder = tmp_path / "session_a"
    folder.mkdir()
    ref = SessionRef(
        session_id="a",
        folder=folder,
        sha256="",
        reader="toy",
        reader_options={"fps": 25.0},
    )
    store.update_sessions([ref])
    path = store.save_project()

    seen.clear()
    store.open_project(path)
    qtbot.waitUntil(lambda: store.session_facts("a") is not None, timeout=2000)
    assert seen[-1]["reader"] == "toy"
    assert seen[-1]["options"] == {"fps": 25.0}


def test_a_session_added_without_a_reader_is_still_detected(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    seen: list[dict[str, object]] = []

    def fake_probe_session(folder: Path, **kwargs: object) -> Session:
        seen.append(kwargs)
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.probe_session", fake_probe_session)
    folder = tmp_path / "session_a"
    folder.mkdir()
    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)
    assert seen[-1].get("reader") is None


# ── scanning a folder before adding it ──────────────────────────────────────


def _idtracker_root(tiny_real_session: Path, tmp_path: Path, names=("s1", "s2")) -> Path:
    import shutil

    root = tmp_path / "root"
    for name in names:
        shutil.copytree(tiny_real_session, root / name)
    return root


def test_scan_folders_reports_what_it_found_on_scan_finished(
    qtbot, store, tiny_real_session: Path, tmp_path: Path
) -> None:
    root = _idtracker_root(tiny_real_session, tmp_path)
    with qtbot.waitSignal(store.scanFinished, timeout=5000) as blocker:
        task_id = store.scan_folders([root])
    finished_id, result = blocker.args
    assert finished_id == task_id
    assert [g.best.reader for g in result.groups] == ["idtrackerai"]
    assert len(result.groups[0].best.sessions) == 2


def test_a_scan_reports_progress_on_its_own_signal(
    qtbot, store, tiny_real_session: Path, tmp_path: Path
) -> None:
    root = _idtracker_root(tiny_real_session, tmp_path)
    stages: list[str] = []
    store.scanProgress.connect(lambda tid, event: stages.append(event.stage))
    with qtbot.waitSignal(store.scanFinished, timeout=5000):
        store.scan_folders([root])
    assert set(stages) <= {"scan"}


def test_a_scan_that_fails_says_so_quietly(qtbot, monkeypatch, store, tmp_path: Path) -> None:
    from track2data.api import Engine

    def broken(roots, **kwargs):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(Engine, "scan", staticmethod(broken))
    generic: list[object] = []
    store.taskFinished.connect(lambda tid, res: generic.append(res))

    with qtbot.waitSignal(store.scanFinished, timeout=3000) as blocker:
        store.scan_folders([tmp_path])
    result = blocker.args[1]
    assert isinstance(result, Exception) and "disk went away" in str(result)
    assert hasattr(result, "traceback")
    assert generic == []  # MainWindow shows its modal failure dialog on this signal


def test_a_scan_can_be_cancelled_quickly(qtbot, monkeypatch, store, tmp_path: Path) -> None:
    import threading
    import time

    from track2data.api import Engine

    started = threading.Event()

    def spinning(roots, *, progress=None, token=None, **kwargs):
        started.set()
        while True:
            token.raise_if_cancelled()
            time.sleep(0.01)

    monkeypatch.setattr(Engine, "scan", staticmethod(spinning))
    finished: list[object] = []
    store.scanFinished.connect(lambda tid, res: finished.append(res))
    task_id = store.scan_folders([tmp_path])
    assert started.wait(2)
    begin = time.monotonic()
    with qtbot.waitSignal(store.scanCancelled, timeout=2000) as blocker:
        store.cancel_scan(task_id)
    assert blocker.args == [task_id]
    assert time.monotonic() - begin < 1.0
    assert finished == []  # a cancelled scan has no result


def test_a_new_project_drops_a_scan_in_flight(qtbot, monkeypatch, store, tmp_path: Path) -> None:
    import threading

    from track2data.api import Engine

    gate, started = threading.Event(), threading.Event()

    def slow(roots, **kwargs):
        started.set()
        gate.wait(5)  # does not poll for cancellation, so it will "finish" after the switch
        return "late result"

    monkeypatch.setattr(Engine, "scan", staticmethod(slow))
    finished: list[object] = []
    store.scanFinished.connect(lambda tid, res: finished.append(res))
    store.scan_folders([tmp_path])
    assert started.wait(2)  # really running, not merely queued
    store.new_project("other", tmp_path)
    gate.set()
    qtbot.wait(300)
    assert finished == []


def test_a_running_scan_does_not_hold_up_a_probe(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    import threading

    from track2data.api import Engine

    gate = threading.Event()
    monkeypatch.setattr(Engine, "scan", staticmethod(lambda roots, **kw: gate.wait(5)))
    monkeypatch.setattr("track2data.readers.probe_session", _fake_session)
    store.scan_folders([tmp_path])

    folder = tmp_path / "session_a"
    folder.mkdir()
    store.add_session(folder)
    qtbot.waitUntil(lambda: store.session_facts("session_a") is not None, timeout=3000)
    assert not gate.is_set()
    gate.set()


# ── adding what the user confirmed ──────────────────────────────────────────


def _ref(tmp_path: Path, name: str, **fields) -> SessionRef:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return SessionRef(session_id=name, folder=folder, sha256="", **fields)


def test_add_confirmed_adds_every_session_and_probes_each_with_its_saved_reader(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    seen: list[dict[str, object]] = []

    def recording(folder: Path, **kwargs: object) -> Session:
        seen.append({"folder": folder.name, **kwargs})
        return _fake_session(folder)

    monkeypatch.setattr("track2data.readers.probe_session", recording)
    refs = [
        _ref(tmp_path, "a", reader="toy", reader_options={"fps": 25.0}),
        _ref(tmp_path, "b", reader="toy", reader_options={"fps": 25.0}),
    ]
    sizes: list[int] = []
    store.sessionsChanged.connect(lambda: sizes.append(len(store.manifest.sessions)))
    added = store.add_confirmed(refs)
    assert sizes == [2]  # announced as soon as they are added, not when the probes finish
    assert [r.session_id for r in added] == ["a", "b"]
    assert [s.session_id for s in store.manifest.sessions] == ["a", "b"]
    assert {s.reader for s in store.manifest.sessions} == {"toy"}

    qtbot.waitUntil(lambda: len(seen) == 2, timeout=3000)
    assert {(s["folder"], s["reader"]) for s in seen} == {("a", "toy"), ("b", "toy")}
    assert all(s["options"] == {"fps": 25.0} for s in seen)


def test_add_confirmed_does_not_add_the_same_folder_and_reader_twice(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    monkeypatch.setattr("track2data.readers.probe_session", _fake_session)
    store.add_confirmed([_ref(tmp_path, "a", reader="toy")])
    again = store.add_confirmed([_ref(tmp_path, "a", reader="toy")])
    assert again == []
    assert len(store.manifest.sessions) == 1


def test_the_same_folder_under_another_reader_is_another_session(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    monkeypatch.setattr("track2data.readers.probe_session", _fake_session)
    store.add_confirmed([_ref(tmp_path, "a", reader="toy")])
    other = _ref(tmp_path, "a", reader="other").model_copy(update={"session_id": "a_other"})
    assert [r.session_id for r in store.add_confirmed([other])] == ["a_other"]
    assert len(store.manifest.sessions) == 2


def test_an_id_that_clashes_is_made_unique_rather_than_replacing_a_session(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    monkeypatch.setattr("track2data.readers.probe_session", _fake_session)
    store.add_confirmed([_ref(tmp_path, "a", reader="toy")])
    (tmp_path / "elsewhere").mkdir()
    clash = SessionRef(session_id="a", folder=tmp_path / "elsewhere", sha256="", reader="toy")
    (added,) = store.add_confirmed([clash])
    assert added.session_id != "a"
    assert [s.session_id for s in store.manifest.sessions] == ["a", added.session_id]


def test_add_confirmed_without_a_project_does_nothing(qtbot, tmp_path: Path) -> None:
    from ui.store.project_store import ProjectStore

    empty = ProjectStore()
    assert empty.add_confirmed([_ref(tmp_path, "a", reader="toy")]) == []
    empty.tasks.shutdown(1000)


def test_update_mode_sets_mode_and_emits(qtbot, store) -> None:
    with qtbot.waitSignal(store.modeChanged, timeout=1000):
        store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    assert store.manifest.mode.layout == "two_videos"


def test_update_mode_rejected_with_sessions(store, tmp_path: Path) -> None:
    store.update_sessions([_ref(tmp_path, "a")])
    with pytest.raises(ValueError):
        store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    assert store.manifest.mode == ProjectMode()


def test_mode_locked_message_and_unlock(store, tmp_path: Path) -> None:
    store.update_sessions([_ref(tmp_path, "a")])
    assert store.mode_locked == "Remove all sessions to change the mode"
    store.update_sessions([])
    assert store.mode_locked is None


def test_switch_3d_to_2d_clears_layout(store) -> None:
    store.update_mode(ProjectMode(dimension="3d", layout="single_video_two_panels"))
    store.update_mode(ProjectMode())
    assert store.manifest.mode.layout is None


def test_new_project_accepts_mode(store, tmp_path: Path) -> None:
    mode = ProjectMode(dimension="3d", layout="two_videos")
    assert store.new_project("p", tmp_path, mode)
    assert store.manifest.mode == mode


def test_saved_3d_project_with_sessions_opens_locked(store, tmp_path: Path) -> None:
    store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    store.update_sessions([_ref(tmp_path, "a")])
    path = store.save_project()
    store.open_project(path)
    assert store.manifest.mode.dimension == "3d"
    assert store.mode_locked == "Remove all sessions to change the mode"


def _fake_results():
    from track2data.core.models import RunResult

    return RunResult(sessions=[])


def test_update_mode_marks_project_dirty_and_persists(qtbot, store) -> None:
    store.save_project()
    assert not store.dirty
    with qtbot.waitSignal(store.persistenceChanged, timeout=1000):
        store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    assert store.dirty


def test_dimension_change_clears_run_results(store) -> None:
    store.set_run_results(_fake_results())
    store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    assert store.run_results is None


def test_no_op_mode_update_keeps_run_results(store) -> None:
    store.set_run_results(_fake_results())
    store.update_mode(ProjectMode())
    assert store.run_results is not None


# ── views: roles, pairing, view pairs ──────────────────────────────────────


@pytest.fixture
def store3d(store, tmp_path: Path):
    store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    store.update_sessions([_ref(tmp_path, n) for n in ("a_top", "a_side", "b_top", "b_side")])
    return store


def _name_patterns():
    from track2data.core.models import PairingPatterns

    return PairingPatterns(top_regex=r"(?P<key>.*)_top", side_regex=r"(?P<key>.*)_side")


def _roles(store) -> dict[str, str | None]:
    return {s.session_id: s.view_role for s in store.manifest.sessions}


def _pair(top: str, side: str, **kw):
    from track2data.core.models import ViewPair

    return ViewPair(top_session_id=top, side_session_id=side, **kw)


def test_update_view_role_sets_role_emits_and_marks_dirty(qtbot, store3d) -> None:
    store3d.save_project()
    assert not store3d.dirty
    with qtbot.waitSignal(store3d.viewsChanged, timeout=1000):
        store3d.update_view_role("a_top", "top")
    assert _roles(store3d)["a_top"] == "top"
    assert store3d.dirty


def test_view_mutators_rejected_in_2d(store, tmp_path: Path) -> None:
    from track2data.core.models import VIEWS_3D_ONLY, PairingPatterns

    store.update_sessions([_ref(tmp_path, "a")])
    calls = [
        lambda: store.update_view_role("a", "top"),
        lambda: store.update_pairing(PairingPatterns(top_regex="x")),
        lambda: store.apply_regex_pairing(),
        lambda: store.update_view_pair(_pair("a", "b")),
        lambda: store.remove_view_pair("a", "b"),
    ]
    for call in calls:
        with pytest.raises(ValueError, match=VIEWS_3D_ONLY):
            call()
    assert VIEWS_3D_ONLY == "Views apply to 3-D projects only"


def test_view_mutators_are_no_ops_without_a_project(qtbot) -> None:
    from ui.store.project_store import ProjectStore

    empty = ProjectStore()
    empty.update_view_role("a", "top")
    empty.remove_view_pair("a", "b")
    empty.tasks.shutdown(1000)


def test_same_role_again_is_a_no_op(qtbot, store3d) -> None:
    store3d.update_view_role("a_top", "top")
    with qtbot.assertNotEmitted(store3d.viewsChanged):
        store3d.update_view_role("a_top", "top")


def test_changing_a_role_drops_pairs_containing_the_session(store3d) -> None:
    for sid, role in (("a_top", "top"), ("a_side", "side"), ("b_top", "top"), ("b_side", "side")):
        store3d.update_view_role(sid, role)
    store3d.update_view_pair(_pair("a_top", "a_side"))
    store3d.update_view_pair(_pair("b_top", "b_side"))
    store3d.update_view_role("a_side", "top")
    assert [(p.top_session_id, p.side_session_id) for p in store3d.manifest.view_pairs] == [
        ("b_top", "b_side")
    ]
    store3d.update_view_role("b_top", None)
    assert store3d.manifest.view_pairs == []
    assert _roles(store3d)["b_top"] is None


def test_update_view_pair_upserts_by_session_pair(qtbot, store3d) -> None:
    store3d.update_view_role("a_top", "top")
    store3d.update_view_role("a_side", "side")
    with qtbot.waitSignal(store3d.viewsChanged, timeout=1000):
        store3d.update_view_pair(_pair("a_top", "a_side"))
    store3d.update_view_pair(_pair("a_top", "a_side", same_ids=True))
    pairs = store3d.manifest.view_pairs
    assert len(pairs) == 1 and pairs[0].same_ids


def test_update_view_pair_rejects_unknown_wrong_role_and_second_pair(store3d) -> None:
    for sid, role in (("a_top", "top"), ("a_side", "side"), ("b_top", "top"), ("b_side", "side")):
        store3d.update_view_role(sid, role)
    with pytest.raises(ValueError):
        store3d.update_view_pair(_pair("a_top", "nope"))
    with pytest.raises(ValueError):
        store3d.update_view_pair(_pair("a_side", "a_top"))  # swapped roles
    store3d.update_view_pair(_pair("a_top", "a_side"))
    with pytest.raises(ValueError):
        store3d.update_view_pair(_pair("a_top", "b_side"))
    with pytest.raises(ValueError):
        store3d.update_view_pair(_pair("b_top", "a_side"))
    assert len(store3d.manifest.view_pairs) == 1


def test_remove_view_pair(qtbot, store3d) -> None:
    store3d.update_view_role("a_top", "top")
    store3d.update_view_role("a_side", "side")
    store3d.update_view_pair(_pair("a_top", "a_side"))
    with qtbot.waitSignal(store3d.viewsChanged, timeout=1000):
        store3d.remove_view_pair("a_top", "a_side")
    assert store3d.manifest.view_pairs == []
    with qtbot.assertNotEmitted(store3d.viewsChanged):
        store3d.remove_view_pair("a_top", "a_side")


def test_removing_a_session_drops_only_its_pairs(qtbot, store3d) -> None:
    for sid, role in (("a_top", "top"), ("a_side", "side"), ("b_top", "top"), ("b_side", "side")):
        store3d.update_view_role(sid, role)
    store3d.update_view_pair(_pair("a_top", "a_side"))
    store3d.update_view_pair(_pair("b_top", "b_side"))
    remaining = [s for s in store3d.manifest.sessions if s.session_id != "a_side"]
    with qtbot.waitSignals([store3d.sessionsChanged, store3d.viewsChanged], timeout=1000):
        store3d.update_sessions(remaining)
    assert [(p.top_session_id, p.side_session_id) for p in store3d.manifest.view_pairs] == [
        ("b_top", "b_side")
    ]
    assert _roles(store3d) == {"a_top": "top", "b_top": "top", "b_side": "side"}


def test_update_sessions_without_dropped_pairs_does_not_emit_views(qtbot, store3d) -> None:
    with qtbot.assertNotEmitted(store3d.viewsChanged):
        store3d.update_sessions(list(store3d.manifest.sessions))


def test_update_pairing_stores_patterns_without_applying(store3d) -> None:

    store3d.update_pairing(_name_patterns())
    assert store3d.manifest.mode.pairing.top_regex == r"(?P<key>.*)_top"
    assert store3d.manifest.mode.layout == "two_videos"
    assert store3d.manifest.view_pairs == []
    assert set(_roles(store3d).values()) == {None}


def test_apply_regex_pairing_sets_roles_and_adds_auto_pairs(store3d) -> None:

    store3d.update_pairing(_name_patterns())
    result = store3d.apply_regex_pairing()
    assert sorted(result.pairs) == [("a_top", "a_side"), ("b_top", "b_side")]
    assert _roles(store3d) == {
        "a_top": "top", "a_side": "side", "b_top": "top", "b_side": "side",
    }
    pairs = store3d.manifest.view_pairs
    assert len(pairs) == 2 and all(p.auto for p in pairs)


def test_apply_regex_pairing_keeps_existing_pair_details(store3d) -> None:

    store3d.update_pairing(_name_patterns())
    store3d.apply_regex_pairing()
    store3d.update_view_pair(_pair("a_top", "a_side", fish_map={"0": "1"}, auto=True))
    store3d.update_view_pair(_pair("b_top", "b_side", same_ids=True, auto=False))
    store3d.apply_regex_pairing()
    by_top = {p.top_session_id: p for p in store3d.manifest.view_pairs}
    assert by_top["a_top"].fish_map == {"0": "1"} and by_top["a_top"].auto
    assert by_top["b_top"].same_ids and not by_top["b_top"].auto


def test_apply_regex_pairing_removes_stale_auto_pairs_only(store3d) -> None:
    from track2data.core.models import PairingPatterns

    store3d.update_pairing(_name_patterns())
    store3d.apply_regex_pairing()
    # b becomes a hand-made pair; a stays auto and then stops matching.
    store3d.update_view_pair(_pair("b_top", "b_side", auto=False))
    store3d.update_pairing(
        PairingPatterns(top_regex=r"zzz(?P<key>.*)", side_regex=r"yyy(?P<key>.*)")
    )
    store3d.apply_regex_pairing()
    assert [(p.top_session_id, p.side_session_id, p.auto) for p in store3d.manifest.view_pairs] == [
        ("b_top", "b_side", False)
    ]


def test_apply_regex_pairing_does_not_repair_a_hand_made_session(store3d) -> None:

    for sid, role in (("a_top", "top"), ("b_side", "side")):
        store3d.update_view_role(sid, role)
    store3d.update_view_pair(_pair("a_top", "b_side"))
    store3d.update_pairing(_name_patterns())
    store3d.apply_regex_pairing()
    pairs = [(p.top_session_id, p.side_session_id, p.auto) for p in store3d.manifest.view_pairs]
    assert pairs == [("a_top", "b_side", False)]


def test_apply_regex_pairing_emits_views_changed_once(qtbot, store3d) -> None:

    store3d.update_pairing(_name_patterns())
    with qtbot.waitSignal(store3d.viewsChanged, timeout=1000):
        store3d.apply_regex_pairing()
