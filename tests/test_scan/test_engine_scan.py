"""Engine.scan: the facade the shell uses to look at a folder before any project exists."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from track2data.api import Engine
from track2data.core.progress import CancellationToken, OperationCancelled, ProgressEvent
from track2data.readers.scan import ScanResult


def test_scanning_needs_no_project(tiny_real_session: Path, tmp_path: Path) -> None:
    for i in range(2):
        shutil.copytree(tiny_real_session, tmp_path / f"session_{i}")
    result = Engine.scan([tmp_path])
    assert isinstance(result, ScanResult)
    assert [g.best.reader for g in result.groups] == ["idtrackerai"]
    assert len(result.groups[0].best.sessions) == 2


def test_it_can_also_be_called_on_an_engine(tiny_real_session: Path) -> None:
    from datetime import UTC, datetime

    from track2data.core.models import ProjectManifest

    now = datetime.now(tz=UTC)
    engine = Engine(ProjectManifest(project_name="p", created_at=now, updated_at=now))
    assert engine.scan([tiny_real_session]).groups


def test_progress_is_forwarded(tiny_real_session: Path) -> None:
    events: list[ProgressEvent] = []
    Engine.scan([tiny_real_session], progress=events.append)
    assert events
    assert {e.stage for e in events} == {"scan"}


def test_cancellation_is_forwarded(tiny_real_session: Path) -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        Engine.scan([tiny_real_session], token=token)
