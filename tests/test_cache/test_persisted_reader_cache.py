"""The preprocessed-session cache must know which reader, with which options, made a session.

The key used to be: the reader detected from the folder, the folder's fingerprint and the
configs. A session whose reader was *chosen*, and given options its files do not record (the
frame rate), is a different input from the same folder read another way. Without both in the
key, a second run with another frame rate would be answered from the first run's numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.support.toy_reader import OPTIONS
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)


def _manifest(
    folder: Path, *, session_id: str = "trial1", **ref_fields: Any
) -> ProjectManifest:
    fields: dict[str, Any] = {"reader": "toy_csv", "reader_options": dict(OPTIONS)}
    fields.update(ref_fields)
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=session_id, folder=folder, sha256="", **fields)],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"]),
    )


@pytest.fixture
def pp_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    import track2data.preprocess.pipeline as pipeline

    calls: list[int] = []
    real = pipeline.run

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run", counting)
    return calls


def _run(manifest: ProjectManifest, cache: Path, out: Path) -> Path:
    result = Engine(manifest, cache_dir=cache).run(out, exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]
    return out


def test_the_same_reader_and_options_hit_the_cache(
    toy_reader: None, toy_folder: Path, tmp_path: Path, pp_calls: list[int]
) -> None:
    _run(_manifest(toy_folder), tmp_path / "cache", tmp_path / "o1")
    _run(_manifest(toy_folder), tmp_path / "cache", tmp_path / "o2")
    assert len(pp_calls) == 1


def test_a_different_frame_rate_is_a_different_input(
    toy_reader: None, toy_folder: Path, tmp_path: Path, pp_calls: list[int]
) -> None:
    cache = tmp_path / "cache"
    _run(_manifest(toy_folder), cache, tmp_path / "o1")
    faster = {**OPTIONS, "fps": 50.0}
    _run(_manifest(toy_folder, reader_options=faster), cache, tmp_path / "o2")
    assert len(pp_calls) == 2
    sessions = pd.read_csv(tmp_path / "o2" / "sessions.csv")
    assert sessions["fps"].tolist() == [50.0]


def test_a_renamed_session_gets_its_own_id_from_a_cache_hit(
    toy_reader: None, toy_folder: Path, tmp_path: Path, pp_calls: list[int]
) -> None:
    cache = tmp_path / "cache"
    _run(_manifest(toy_folder, session_id="first"), cache, tmp_path / "o1")
    out = _run(_manifest(toy_folder, session_id="second"), cache, tmp_path / "o2")
    assert len(pp_calls) == 1  # the second run really did come from the cache
    readme = (out / "second" / "README.md").read_text("utf-8")
    assert "| Session ID | second |" in readme
    assert "first" not in readme


def test_the_viewer_path_replays_the_saved_reader(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    manifest = _manifest(toy_folder)
    psess = Engine(manifest, cache_dir=tmp_path / "cache").preprocess_ref(manifest.sessions[0])
    assert psess.session.reader == "toy_csv"
    assert psess.session.video.fps == OPTIONS["fps"]
    assert psess.session.session_id == "trial1"


def test_the_viewer_path_and_a_run_share_one_cache_entry(
    toy_reader: None, toy_folder: Path, tmp_path: Path, pp_calls: list[int]
) -> None:
    cache = tmp_path / "cache"
    manifest = _manifest(toy_folder)
    Engine(manifest, cache_dir=cache).preprocess_ref(manifest.sessions[0])
    _run(manifest, cache, tmp_path / "o1")
    assert len(pp_calls) == 1


def test_the_folder_form_still_works_for_a_legacy_caller(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now)
    psess = Engine(manifest, cache_dir=tmp_path / "cache").preprocess_folder(tiny_real_session)
    assert psess.session.n_animals == 2
