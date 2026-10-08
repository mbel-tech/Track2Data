"""A raw Ctrax file through the real pipeline: saved reader, run, export, cache.

Ctrax identities are track fragments, so the session is identity-free by construction. The pipeline
must run it, say so in the export, and honour the option that keeps only the longest tracks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.support.ctrax import walkers, write_ctrax_mat
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

OPTIONS = {"width_px": 640, "height_px": 480}


def _engine(path: Path, cache_dir: Path | None = None, **options) -> Engine:
    now = datetime.now(tz=UTC)
    return Engine(
        ProjectManifest(
            project_name="ctrax",
            created_at=now,
            updated_at=now,
            sessions=[
                SessionRef(
                    session_id="trial1",
                    folder=path,
                    sha256="",
                    reader="ctrax_mat",
                    reader_options={**OPTIONS, **options},
                    reader_chosen_by="detected",
                    reader_confidence="HIGH",
                )
            ],
            calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
            metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
        ),
        cache_dir=cache_dir,
    )


@pytest.fixture
def ctrax_file(tmp_path: Path) -> Path:
    return write_ctrax_mat(tmp_path / "in" / "trial1.mat", walkers(120, (0, 1, 2, 3)))


def test_the_project_runs_end_to_end(ctrax_file: Path, tmp_path: Path) -> None:
    engine = _engine(ctrax_file)
    assert engine.validate() == []
    result = engine.run(tmp_path / "out", exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]


def test_the_export_says_the_session_is_identity_free_and_names_the_file(
    ctrax_file: Path, tmp_path: Path
) -> None:
    _engine(ctrax_file).run(tmp_path / "out", exporters=["csv_long", "readme"])
    text = (tmp_path / "out" / "trial1" / "README.md").read_text("utf-8")
    assert "| Software | Ctrax (raw .mat)" in text
    assert "Treated as identity-free | True" in text
    assert "`trial1.mat`" in text and "height_px=480" in text
    assert "Animal position" not in text  # one point per animal: no skeleton to describe


def test_the_longest_tracks_option_reaches_the_pipeline(ctrax_file: Path) -> None:
    engine = _engine(ctrax_file, top_n=2)
    assert engine.import_ref(engine.manifest.sessions[0]).n_animals == 2


def test_an_edited_file_is_not_served_from_the_cache(ctrax_file: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    ref = _engine(ctrax_file, cache).manifest.sessions[0]
    first = _engine(ctrax_file, cache).preprocess_ref(ref).session
    write_ctrax_mat(ctrax_file, walkers(120, (0, 1, 2, 3), seed=9))
    edited = _engine(ctrax_file, cache).preprocess_ref(ref).session
    assert not np.allclose(first.raw_xy, edited.raw_xy, equal_nan=True)
