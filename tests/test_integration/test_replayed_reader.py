"""A saved reader replays to exactly what detection produced.

``Engine.import_ref`` takes a different road for an entry that names its reader (the class is
looked up and its saved options are passed) than for one that does not (detection). Whichever
road is taken, a run must write the same bytes: otherwise saving the reader would quietly change
a project's numbers.

The comparison covers every CSV a run writes -- all metrics, diagnostics included -- for both
idtracker.ai layouts and both calibration modes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SecurityConfig,
    SessionRef,
)
from track2data.metrics import _load_builtins, _registry

READER_OF = {"tiny_real": "idtrackerai", "tiny_v5": "idtrackerai_v5"}


def _engine(folders: dict[str, Path], *, saved: bool, calibration: CalibrationConfig) -> Engine:
    _load_builtins()
    every = {
        level: sorted(k for k, m in _registry.items() if m.level == level)
        for level in ("individual", "group", "zone", "diagnostic")
    }
    refs = [
        SessionRef(
            session_id=name,
            folder=folder,
            sha256="",
            **({"reader": READER_OF[name]} if saved else {}),
        )
        for name, folder in folders.items()
    ]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Engine(
        ProjectManifest(
            project_name="replay",
            created_at=now,
            updated_at=now,
            sessions=refs,
            calibration=calibration,
            security=SecurityConfig(allow_pickle_trajectories=True),
            metrics=MetricSelection(**every),
        )
    )


def _csv_files(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*.csv"))}


@pytest.mark.parametrize(
    "calibration",
    [CalibrationConfig(mode="bodylength"), CalibrationConfig(mode="scalar", px_per_cm=10.0)],
    ids=["bodylength", "scalar"],
)
def test_replaying_the_saved_reader_writes_the_same_files_as_detecting_it(
    tiny_real_session: Path, tiny_v5_session: Path, tmp_path: Path, calibration: CalibrationConfig
) -> None:
    folders = {"tiny_real": tiny_real_session, "tiny_v5": tiny_v5_session}
    outputs = {}
    for label, saved in (("detected", False), ("saved", True)):
        out = tmp_path / label
        result = _engine(folders, saved=saved, calibration=calibration).run(
            out, exporters=["csv_long"]
        )
        assert [r.error for r in result.sessions] == [None, None], label
        outputs[label] = _csv_files(out)

    detected, saved_files = outputs["detected"], outputs["saved"]
    assert detected, "the run wrote no CSV at all, so there is nothing to compare"
    assert sorted(saved_files) == sorted(detected)
    different = [name for name in detected if saved_files[name] != detected[name]]
    assert different == []
