"""The consent gate on trajectory formats that execute code when loaded.

``np.load(..., allow_pickle=True)`` runs arbitrary code from the file, and
``npy`` is one of idtracker.ai's default trajectory output formats -- so that
path is reached by importing an ordinary session folder. Before this gate
existed, any shared, downloaded or collaborator-supplied folder was an
execution vector, while the loader's own docstring claimed a consent check
that was implemented nowhere.

What these tests pin:

* refusal is the default, everywhere -- loader, reader, dispatcher, Engine;
* refusal is *not* a hard failure when the folder carries an inert format
  too: the reader falls through to h5/csv, which is what keeps the gate from
  being a usability wall. A real idtracker.ai folder normally ships both;
* opting in restores the pickled format's real priority;
* external readers written before the gate keep working.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from track2data.core.errors import ImportError_
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SecurityConfig,
    SessionRef,
)
from track2data.readers import read_session
from track2data.readers.base import SessionReader
from track2data.readers.idtrackerai.formats.npy import load_npy


def _pickle_only(session_folder: Path, dest: Path) -> Path:
    """Copy *session_folder*, leaving only the pickled trajectory.

    The tiny_real fixture ships a ``trajectories_csv`` bundle alongside the
    npy -- which is the *good* case, since the reader falls through to it.
    This strips that, so a refusal has nowhere to go.
    """
    shutil.copytree(session_folder, dest)
    shutil.rmtree(dest / "trajectories" / "trajectories_csv")
    return dest


# ── the loader ────────────────────────────────────────────────────────────────


def test_loader_refuses_by_default(tiny_real_session: Path) -> None:
    """Default-off, so nothing unpickles by accident."""
    path = tiny_real_session / "trajectories" / "trajectories.npy"

    with pytest.raises(ImportError_) as exc:
        load_npy(path)

    assert exc.value.code == "IDT_PICKLE_REFUSED"


def test_refusal_says_how_to_proceed(tiny_real_session: Path) -> None:
    """A refusal the user cannot act on is just a broken import."""
    path = tiny_real_session / "trajectories" / "trajectories.npy"

    with pytest.raises(ImportError_) as exc:
        load_npy(path)

    remediation = exc.value.remediation or ""
    assert "allow_pickle_trajectories" in remediation
    assert "h5" in remediation


def test_loader_loads_when_permitted(tiny_real_session: Path) -> None:
    path = tiny_real_session / "trajectories" / "trajectories.npy"
    assert isinstance(load_npy(path, allow_pickle=True), dict)


def test_refusal_precedes_touching_the_file(tmp_path: Path) -> None:
    """The gate closes before np.load runs, not after: a hostile file is
    never opened at all."""
    hostile = tmp_path / "trajectories.npy"
    hostile.write_bytes(b"not even a numpy file")

    with pytest.raises(ImportError_) as exc:
        load_npy(hostile)

    # IDT_PICKLE_REFUSED rather than a parse error -- nothing read the bytes.
    assert exc.value.code == "IDT_PICKLE_REFUSED"


# ── the reader ────────────────────────────────────────────────────────────────


def test_reader_falls_through_to_an_inert_format(tiny_real_session: Path) -> None:
    """Refusing the pickle must not fail an import that had a safe option.

    npy outranks csv in detect()'s priority order, so reading csv here is
    proof that the refusal happened and the existing format-fallback walk
    absorbed it. An ordinary import keeps working untouched.
    """
    session = read_session(tiny_real_session)

    assert session.trajectory_format == "csv"
    assert session.trajectory_source is not None
    assert session.trajectory_source.name == "trajectories_csv"


def test_reader_prefers_the_pickled_format_once_permitted(
    tiny_real_session: Path,
) -> None:
    """Opting in restores detect()'s real priority order."""
    session = read_session(tiny_real_session, allow_pickle=True)

    assert session.trajectory_format == "npy"
    assert session.trajectory_source is not None
    assert session.trajectory_source.name == "trajectories.npy"


def test_reader_refuses_a_pickle_only_folder(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    """With nothing inert to fall back to, the import fails rather than
    quietly executing the file."""
    folder = _pickle_only(tiny_real_session, tmp_path / "npy_only")

    with pytest.raises(ImportError_) as exc:
        read_session(folder)

    assert exc.value.code == "IDT_FORMAT_AMBIGUOUS"
    # The message has to name consent as the cause, or the user is left
    # thinking their file is corrupt.
    assert "IDT_PICKLE_REFUSED" in str(exc.value)
    assert "allow_pickle_trajectories" in (exc.value.remediation or "")


def test_pickle_only_folder_reads_once_permitted(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    folder = _pickle_only(tiny_real_session, tmp_path / "npy_only_ok")

    assert read_session(folder, allow_pickle=True).trajectory_format == "npy"


# ── the Engine ────────────────────────────────────────────────────────────────


def _manifest(folder: Path, *, allow: bool) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=folder.name, folder=folder, sha256="")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"]),
        security=SecurityConfig(allow_pickle_trajectories=allow),
    )


def test_engine_defaults_to_refusing(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    from track2data.api import Engine

    folder = _pickle_only(tiny_real_session, tmp_path / "engine_npy_only")

    with pytest.raises(ImportError_):
        Engine(_manifest(folder, allow=False)).import_session(folder)


def test_engine_honours_the_project_opt_in(tiny_real_session: Path) -> None:
    from track2data.api import Engine

    session = Engine(_manifest(tiny_real_session, allow=True)).import_session(
        tiny_real_session
    )
    assert session.trajectory_format == "npy"


def test_manifest_defaults_to_refusing() -> None:
    """The safe default has to be the *default*, not a thing to remember."""
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now)
    assert manifest.security.allow_pickle_trajectories is False


def test_security_choice_is_persisted_in_the_manifest(tmp_path: Path) -> None:
    """Consent is per project and must survive save/reopen, or the user is
    asked again on every launch and stops reading the question."""
    from track2data.core.manifest import read, write

    path = tmp_path / "p.t2d.json"
    write(_manifest(tmp_path, allow=True), path)

    assert read(path).security.allow_pickle_trajectories is True


# ── plug-in compatibility ─────────────────────────────────────────────────────


def test_external_readers_without_the_flag_still_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A third-party reader written against ``read(folder)`` predates this
    gate and must not break -- ``read_session`` passes the keyword only to
    readers that declare they understand it."""
    import track2data.readers as readers_module
    from track2data.core.models import Session, VideoInfo

    class LegacyReader(SessionReader):
        name = "legacy_external"
        priority = 999

        @classmethod
        def detect(cls, folder: Path) -> bool:
            return True

        def read(self, folder: Path) -> Session:
            return Session(
                session_id="legacy",
                folder=folder,
                reader=self.name,
                video=VideoInfo(fps=25.0, n_frames=2, width_px=10, height_px=10),
                n_animals=1,
                trajectory_variant="wo_gaps",
                has_stable_identities=True,
                raw_xy=np.zeros((2, 1, 2), dtype=np.float64),
            )

    assert LegacyReader.accepts_allow_pickle is False
    monkeypatch.setattr(readers_module, "_REGISTRY", [LegacyReader])

    session = read_session(tmp_path, allow_pickle=True)
    assert session.reader == "legacy_external"


# ── the legacy v5 reader ──────────────────────────────────────────────────────


def test_v5_reader_declines_to_unpickle_video_object_by_default(
    tmp_path: Path,
) -> None:
    """The audit named only the unified reader's npy loader; ``video_object.npy``
    in the legacy v5 reader is a second, separately-reachable pickle load.

    Unlike the trajectory, refusing it degrades rather than fails the import:
    it carries metadata only (fps, resolution, frame count), all of which
    session.json can also supply.
    """
    from track2data.readers.idtrackerai_v5 import IDTrackerAiV5Reader

    assert IDTrackerAiV5Reader.accepts_allow_pickle is True
    # No file needs to exist: the gate closes before the path is touched.
    assert IDTrackerAiV5Reader._load_video_object(tmp_path) is None
    assert IDTrackerAiV5Reader._load_video_object(tmp_path, allow_pickle=False) is None
