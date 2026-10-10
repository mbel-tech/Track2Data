"""Depth columns in the per-frame tables and fusion provenance in the run files."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_fusion.scene import DEPTHS, TANK_CM, build_scene, pair
from track2data.api import Engine
from track2data.core.runplan import FusionRunInfo
from track2data.exporters.base import ExportPayload
from track2data.exporters.csv_long import CsvLongExporter
from track2data.exporters.excel import ExcelExporter
from track2data.exporters.feather import FeatherExporter
from track2data.exporters.readme import ReadmeExporter

EXPORTERS = ["csv_long", "csv_wide", "feather", "excel", "readme"]


def _fused_frame(tmp_path: Path, *, tank: float | None = TANK_CM) -> pd.DataFrame:
    engine = Engine(build_scene(tmp_path / "data"))
    fused = engine.fuse_pair(engine._manifest.view_pairs[0])
    psess = fused.psess
    # a NaN gap in the depth of fish 0, a NaN position for fish 1, a different gap in position
    psess.depth = psess.depth.copy()
    psess.depth[10:12, 0] = np.nan
    psess.xy = psess.xy.copy()
    psess.xy[20:22, 1] = np.nan
    psess.depth_height_cm = tank
    return engine.build_fish_by_frame(psess)


def _payload(df: pd.DataFrame) -> ExportPayload:
    return ExportPayload(
        session_id="t1+s1", project_name="P", project_hash="h", app_version="0",
        fish_by_frame=df,
    )


def test_fused_frame_has_aligned_depth_columns(tmp_path: Path) -> None:
    df = _fused_frame(tmp_path)
    assert {"depth_fraction", "depth_cm"} <= set(df.columns)
    assert list(df.columns).index("depth_fraction") > list(df.columns).index("y_px")
    for k, d in enumerate(DEPTHS):
        f = df[df.individual_id == k]
        ok = f.depth_fraction.notna()
        np.testing.assert_allclose(f.depth_fraction[ok], d)
        np.testing.assert_allclose(f.depth_cm[ok], d * TANK_CM)
        # NaN exactly where the position or the depth is NaN
        expect_nan = f.x_px.isna() | f.y_px.isna()
        if k == 0:
            expect_nan = expect_nan | f.frame.isin([10, 11])
        assert (f.depth_fraction.isna() == expect_nan).all()
        assert (f.depth_cm.isna() == f.depth_fraction.isna()).all()
    assert df.depth_fraction.isna().sum() == 4


def test_unknown_tank_height_gives_nan_cm(tmp_path: Path) -> None:
    df = _fused_frame(tmp_path, tank=None)
    assert df.depth_fraction.notna().any()
    assert df.depth_cm.isna().all()


def test_no_depth_means_no_columns(tmp_path: Path) -> None:
    engine = Engine(build_scene(tmp_path / "data"))
    fused = engine.fuse_pair(engine._manifest.view_pairs[0])
    psess = fused.psess
    psess.depth = None
    df = engine.build_fish_by_frame(psess)
    assert "depth_fraction" not in df.columns and "depth_cm" not in df.columns


def test_the_four_formats_carry_the_same_depth_columns(tmp_path: Path) -> None:
    df = _fused_frame(tmp_path)
    p = _payload(df)
    CsvLongExporter().write(p, tmp_path / "csv")
    FeatherExporter().write(p, tmp_path / "feather")
    ExcelExporter().write(p, tmp_path / "xlsx")
    csv = pd.read_csv(tmp_path / "csv" / "master_fish_by_frame.csv")
    fea = pd.read_feather(tmp_path / "feather" / "master_fish_by_frame.feather")
    xls = pd.read_excel(next((tmp_path / "xlsx").glob("*.xlsx")), sheet_name="Fish by Frame")
    for got in (csv, fea, xls):
        assert list(got.columns) == list(df.columns)
        for col in ("depth_fraction", "depth_cm"):
            np.testing.assert_allclose(got[col].to_numpy(float), df[col].to_numpy(float))


def test_2d_run_has_no_new_columns_rows_or_files(tmp_path: Path, tiny_real_session: Path) -> None:
    from datetime import UTC, datetime

    from track2data.core.models import (
        CalibrationConfig,
        MetricSelection,
        ProjectManifest,
        SessionRef,
    )

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p2d", created_at=now, updated_at=now,
        sessions=[
            SessionRef(session_id=tiny_real_session.name, folder=tiny_real_session, sha256="")
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
    )
    engine = Engine(manifest)
    out = tmp_path / "out"
    engine.run(out, exporters=["csv_long", "readme"])

    header = (out / "sessions.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == [
        "session_id", "reader", "fps", "n_frames", "duration_s", "n_animals", "width_px",
        "height_px", "calibration_mode", "length_unit", "px_per_cm", "is_calibrated",
        "is_identity_free", "trajectory_source", "trajectory_sha256", "error",
        "length_calibration_n", "length_calibration_rel_sd",
    ]
    assert not list(out.rglob("skipped.csv"))
    for readme in (out / "PROJECT_SUMMARY.md", out / tiny_real_session.name / "README.md"):
        text = readme.read_text(encoding="utf-8")
        assert "3-D fusion" not in text and "Skipped sessions" not in text
    frame = pd.read_csv(out / tiny_real_session.name / "master_fish_by_frame.csv")
    assert not [c for c in frame.columns if c.startswith("depth_")]
    meta = json.loads((out / tiny_real_session.name / "manifest.json").read_text())
    assert "fusion" not in meta["run_metadata"]


def test_quality_threshold_masks_the_depth_columns(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data")
    manifest.metrics.quality_threshold = 0.5
    engine = Engine(manifest)
    psess = engine.fuse_pair(manifest.view_pairs[0]).psess
    prob = np.ones((psess.n_frames, psess.n_animals))
    prob[30, 0] = 0.1
    psess.id_probabilities_rows = prob
    df = engine.build_fish_by_frame(psess)
    low = df[(df.individual_id == 0) & (df.frame == 30)].iloc[0]
    assert np.isnan(low.x_px) and np.isnan(low.depth_fraction) and np.isnan(low.depth_cm)
    assert df.depth_fraction.isna().sum() == 1


def _metadata_manifest(manifest, csv: Path, session_id: str):
    from track2data.core.models import MappingRule, MetadataSource

    pd.DataFrame({"session_id": [session_id], "depth_cm": [99.0]}).to_csv(csv, index=False)
    return manifest.model_copy(
        update={
            "metadata_source": MetadataSource(path=csv, sha256="unused"),
            "mapping": MappingRule(rules={}, extra_columns=["depth_cm"]),
        }
    )


def test_2d_metadata_column_named_depth_cm_is_kept(tmp_path: Path, tiny_real_session: Path) -> None:
    from datetime import UTC, datetime

    from track2data.core.models import (
        CalibrationConfig,
        MetricSelection,
        ProjectManifest,
        SessionRef,
    )

    now = datetime.now(tz=UTC)
    base = ProjectManifest(
        project_name="p2d", created_at=now, updated_at=now,
        sessions=[
            SessionRef(session_id=tiny_real_session.name, folder=tiny_real_session, sha256="")
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
    )
    manifest = _metadata_manifest(base, tmp_path / "meta.csv", tiny_real_session.name)
    engine = Engine(manifest)
    psess = engine.preprocess(engine.import_session(tiny_real_session))
    frame = engine.build_fish_by_frame(psess)
    assert (frame["depth_cm"] == 99.0).all()
    metrics = engine.compute_metrics(psess)
    assert (metrics["IL-1"]["depth_cm"] == 99.0).all()


def test_3d_metadata_depth_column_warns_and_the_fused_depth_wins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    base = build_scene(tmp_path / "data")
    manifest = _metadata_manifest(base, tmp_path / "meta.csv", "t1+s1")
    engine = Engine(manifest)
    psess = engine.fuse_pair(manifest.view_pairs[0]).psess
    with caplog.at_level(logging.WARNING):
        frame = engine.build_fish_by_frame(psess)
    assert "metadata column 'depth_cm' is ignored in the per-frame table" in caplog.text
    assert not (frame["depth_cm"] == 99.0).any()
    assert set(frame["depth_cm"].dropna().round(6)) == {d * TANK_CM for d in DEPTHS}


# ── provenance ───────────────────────────────────────────────────────────────


def test_pair_unit_provenance_in_sessions_csv_and_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = build_scene(tmp_path / "data")
    real_import = Engine.import_ref

    def with_source(self: Engine, ref: object) -> object:  # the v5 fixture records no source file
        session = real_import(self, ref)
        npy = Path(ref.folder) / "trajectories" / "trajectories.npy"  # type: ignore[attr-defined]
        return session.model_copy(update={"trajectory_source": npy})

    monkeypatch.setattr(Engine, "import_ref", with_source)
    out = tmp_path / "out"
    result = Engine(manifest).run(out, exporters=EXPORTERS)
    info = result.sessions[0].fusion
    assert isinstance(info, FusionRunInfo)
    assert len(info.side_trajectory_sha256) == 64
    assert info.side_trajectory_sha256 != result.sessions[0].summary.trajectory_sha256

    sessions = pd.read_csv(out / "sessions.csv", dtype=str, keep_default_na=False)
    row = sessions[sessions.session_id == "t1+s1"].iloc[0]
    for key in info.as_row():
        assert key in sessions.columns
    assert row.unit_kind == "pair"
    assert (row.top_session_id, row.side_session_id) == ("t1", "s1")
    assert row.side_trajectory_sha256 == info.side_trajectory_sha256
    assert row.trajectory_sha256 == result.sessions[0].summary.trajectory_sha256
    assert row.fusion_fused_fish == "3"
    assert row.fusion_flip == "False"

    readme = (out / "t1+s1" / "README.md").read_text(encoding="utf-8")
    assert "## 3-D fusion" in readme
    assert "| Unit | pair of top `t1` and side `s1` |" in readme
    assert f"`{info.side_trajectory_sha256}`" in readme
    assert "Agreement RMS" in readme
    meta = json.loads((out / "t1+s1" / "manifest.json").read_text())
    assert meta["run_metadata"]["fusion"]["side_session_id"] == "s1"


def test_readme_states_why_agreement_was_skipped() -> None:
    info = FusionRunInfo(
        unit_kind="pair", top_session_id="t", side_session_id="s", fusion_frame_offset=2,
        fusion_axis="x", fusion_flip=True, fusion_surface_row=1.0, fusion_floor_row=2.0,
        fusion_tank_height_cm=20.0, fusion_overlap_frames=5, fusion_fused_fish=2,
        fusion_unmatched_top="a", fusion_unmatched_side="", fusion_outside_column=3,
        fusion_agreement_rms_cm=None, fusion_agreement_warning=False,
        fusion_agreement_skipped="too few frames",
    )
    lines = ReadmeExporter._fusion_lines(info)
    text = "\n".join(lines)
    assert "too few frames" in text
    assert "| Positions outside the water column | 3 |" in text


def test_skipped_csv_and_readme_only_when_skipped(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = Engine(build_scene(tmp_path / "data")).run(out, exporters=["csv_long", "readme"])
    assert [(s.session_id, s.reason) for s in result.skipped] == [("lone", "not in a fusable pair")]
    skipped = pd.read_csv(out / "skipped.csv")
    assert list(skipped.columns) == ["session_id", "reason"]
    assert skipped.to_dict("records") == [{"session_id": "lone", "reason": "not in a fusable pair"}]
    summary = (out / "PROJECT_SUMMARY.md").read_text(encoding="utf-8")
    assert "## Skipped sessions" in summary
    assert "| lone | not in a fusable pair |" in summary

    clean = tmp_path / "clean"
    Engine(build_scene(tmp_path / "data2", with_lone=False)).run(clean, exporters=["csv_long"])
    assert not (clean / "skipped.csv").exists()
    assert "Skipped sessions" not in (clean / "PROJECT_SUMMARY.md").read_text(encoding="utf-8")


def test_a_pair_without_settings_is_listed_with_its_reason(tmp_path: Path) -> None:
    pairs = [pair("t1", "s1"), pair("t2", "s2", fusion=None)]
    pairs[1] = pairs[1].model_copy(update={"fusion": None})
    out = tmp_path / "out"
    Engine(build_scene(tmp_path / "data", pairs=pairs, with_lone=False)).run(
        out, exporters=["csv_long"]
    )
    skipped = pd.read_csv(out / "skipped.csv")
    assert set(skipped.reason) == {"pair t2+s2: no fusion settings for this pair"}
    assert list(skipped.session_id) == ["t2", "s2"]


def test_sessions_table_blanks_provenance_for_session_units() -> None:
    from track2data.core.session_consistency import SessionSummary, sessions_table

    def summary(sid: str) -> SessionSummary:
        return SessionSummary(
            session_id=sid, reader="r", fps=25.0, n_frames=10, n_animals=2, width_px=1,
            height_px=1, length_unit=None, calibration_mode="scalar",
        )

    info = FusionRunInfo(
        unit_kind="pair", top_session_id="t", side_session_id="s", fusion_frame_offset=2,
        fusion_axis="x", fusion_flip=False, fusion_surface_row=1.0, fusion_floor_row=2.0,
        fusion_tank_height_cm=20.0, fusion_overlap_frames=5, fusion_fused_fish=2,
        fusion_unmatched_top="", fusion_unmatched_side="", fusion_outside_column=0,
        fusion_agreement_rms_cm=0.5, fusion_agreement_warning=False,
        fusion_agreement_skipped=None, side_trajectory_sha256="ab",
    )
    plain = sessions_table([summary("a"), summary("t+s")])
    assert "unit_kind" not in plain.columns
    both = sessions_table([summary("a"), summary("t+s")], fusion={"t+s": info})
    assert list(both.columns[: len(plain.columns)]) == list(plain.columns)
    assert list(both.columns[len(plain.columns):]) == list(info.as_row())
    csv = both.to_csv(index=False, lineterminator="\n").splitlines()
    assert csv[1].endswith("," * len(info.as_row()))  # the session row is blank there
    assert ",pair,t,s,2,x,False," in csv[2]


def test_single_video_layout_records_offset_zero(tmp_path: Path) -> None:
    base = build_scene(tmp_path / "data", with_lone=False)
    pairs = [
        p.model_copy(update={"fusion": p.fusion.model_copy(update={"frame_offset": 5})})
        for p in base.view_pairs
    ]
    manifest = base.model_copy(
        update={
            "mode": base.mode.model_copy(update={"layout": "single_video_two_panels"}),
            "view_pairs": pairs,
        }
    )
    out = tmp_path / "out"
    result = Engine(manifest).run(out, exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None, None]
    assert result.sessions[0].fusion.fusion_frame_offset == 0
    assert "| Frame offset | 0 |" in (out / "t1+s1" / "README.md").read_text(encoding="utf-8")
    meta = json.loads((out / "t1+s1" / "manifest.json").read_text())
    assert meta["run_metadata"]["fusion"]["fusion_frame_offset"] == 0
    sessions = pd.read_csv(out / "sessions.csv")
    assert set(sessions.fusion_frame_offset) == {0}
