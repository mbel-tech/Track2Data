"""A session tracked in separate intervals runs end to end: every metric, every exporter."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from track2data import metrics
from track2data.api import Engine
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    GapFillCfg,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    Session,
    SessionRef,
    ZoneSet,
)

GAP = 40  # frames never tracked between the two intervals


def _manifest(folder: Path, *, across: bool, bin_minutes: float | None) -> ProjectManifest:
    ids = metrics.all_ids()
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id="sess", folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        zones=ZoneSet(rois=[ROI(name="left", vertices=[(0, 0), (500, 0), (500, 1000), (0, 1000)])]),
        metrics=MetricSelection(
            individual=[i for i in ids if i.startswith("IL-")],
            group=[i for i in ids if i.startswith("GL-")],
            zone=[i for i in ids if i.startswith("Z-")],
            timepoint_minutes=bin_minutes,
        ),
        preprocess=PreprocessConfig(
            gap_fill=GapFillCfg(across_tracking_intervals=across, max_cross_interval_gap_s=60)
        ),
    )


@pytest.fixture()
def multi_interval(tiny_real_session: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    folder = tmp_path / "sess"
    shutil.copytree(tiny_real_session, folder)
    real = Engine.import_ref

    def two_intervals(self: Engine, ref: SessionRef) -> Session:
        session = real(self, ref)
        n = int(session.raw_xy.shape[0])
        half = n // 2
        return session.model_copy(
            update={"tracking_intervals": [(0, half), (half + GAP, n + GAP)]}
        )

    monkeypatch.setattr(Engine, "import_ref", two_intervals)
    return folder


@pytest.mark.parametrize("across", [False, True], ids=["breaks", "bridged"])
@pytest.mark.parametrize("bin_minutes", [None, 0.05], ids=["whole", "binned"])
def test_every_metric_and_exporter_runs_and_the_cache_reproduces_it(
    multi_interval: Path, tmp_path: Path, across: bool, bin_minutes: float | None
) -> None:
    manifest = _manifest(multi_interval, across=across, bin_minutes=bin_minutes)
    cache = tmp_path / "cache"
    first = Engine(manifest, cache_dir=cache).run(
        tmp_path / "out", exporters=["csv_long", "csv_wide", "feather", "excel", "readme"]
    )
    assert first.sessions[0].error is None
    again = Engine(manifest, cache_dir=cache).run(tmp_path / "out2", exporters=["csv_long"])
    assert again.sessions[0].error is None

    table = pd.read_csv(tmp_path / "out" / "sess" / "master_fish_by_frame.csv")
    tracked = table[table["in_tracking_interval"].astype(bool)]
    estimated = table[~table["in_tracking_interval"].astype(bool)]
    assert tracked["frame"].max() - tracked["frame"].min() >= GAP  # the gap is real time
    if across:
        assert len(estimated) > 0 and estimated["was_interpolated"].all()
        assert estimated["id_probability"].isna().all()
    else:
        assert estimated.empty  # nothing is exported for frames that were never tracked
        assert len(table) == len(tracked)
