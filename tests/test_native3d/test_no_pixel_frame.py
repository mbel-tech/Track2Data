"""A native 3-D session has no pixel frame: no consumer may read ``video.width_px = 0``.

The Qt halves (Zones screen) are here too; they skip when PySide6 is missing.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from tests.test_metrics.test_derived import _make_psess
from tests.test_readers.native3d_files import write_anipose_csv
from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest
from track2data.core.models import (
    CalibrationConfig,
    ProjectManifest,
    Session,
    VideoInfo,
    WaterColumn,
    ZoneSet,
)
from track2data.core.session_consistency import (
    SessionSummary,
    heterogeneity_warnings,
    sessions_table,
)
from track2data.metrics.derived import (
    NO_PIXEL_FRAME_ARENA_WARNING,
    derive_metric_params,
)

WARNING = "no pixel frame: the arena was taken from the extent of the tracked positions"


def _native_psess(xy: np.ndarray):
    psess = _make_psess(width_px=0, height_px=0, xy=xy)
    session = psess.session.model_copy(update={"has_pixel_frame": False, "coordinate_unit": "cm"})
    return replace(psess, session=session)


def _extent_xy() -> np.ndarray:
    xy = np.full((6, 2, 2), np.nan)
    xy[:, 0, 0] = np.linspace(0.0, 10.0, 6)
    xy[:, 0, 1] = np.linspace(10.0, 0.0, 6)
    xy[:, 1, 0] = 5.0
    xy[:, 1, 1] = 5.0
    return xy


def test_warning_text_is_exact() -> None:
    assert NO_PIXEL_FRAME_ARENA_WARNING == WARNING


def test_arena_fallback_uses_extent_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    psess = _native_psess(_extent_xy())
    with caplog.at_level(logging.WARNING, logger="track2data.metrics.derived"):
        il3 = derive_metric_params("IL-3", psess, ZoneSet())
    assert il3["centre"] == pytest.approx([5.0, 5.0])
    assert il3["arena_radius"] == pytest.approx(5.0)
    assert il3["centres"] == [[5.0, 5.0], [5.0, 5.0]]
    assert il3["arena_radii"] == pytest.approx([5.0, 5.0])
    assert il3["arena_warning"] == WARNING
    assert WARNING in caplog.text
    il14 = derive_metric_params("IL-14", psess, ZoneSet())
    assert il14["arena_polygon_vertices"] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert il14["arena_warning"] == WARNING


def test_arena_fallback_ignores_non_finite_and_handles_no_data() -> None:
    xy = _extent_xy()
    xy[2, 0] = [np.inf, np.nan]
    il3 = derive_metric_params("IL-3", _native_psess(xy), ZoneSet())
    assert il3["arena_radius"] == pytest.approx(5.0)
    empty = derive_metric_params("IL-3", _native_psess(np.full((4, 1, 2), np.nan)), ZoneSet())
    assert "centre" not in empty and "arena_radius" not in empty
    assert empty["arena_warning"] == WARNING


def test_pixel_session_arena_unchanged() -> None:
    psess = _make_psess(width_px=1000, height_px=800)
    result = derive_metric_params("IL-3", psess, ZoneSet())
    assert result["centre"] == [500.0, 400.0]
    assert result["arena_radius"] == 400.0
    assert "arena_warning" not in result
    assert "arena_warning" not in derive_metric_params("IL-14", psess, ZoneSet())


def _native_session(session_id: str = "n1") -> Session:
    n = 8
    return Session(
        session_id=session_id,
        folder=Path("/tmp") / session_id,
        reader="anipose",
        video=VideoInfo(fps=25.0, n_frames=n, width_px=0, height_px=0),
        n_animals=1,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.random.default_rng(0).normal(size=(n, 1, 2)),
        raw_z=np.zeros((n, 1)),
        length_unit=1.0,
        has_pixel_frame=False,
        coordinate_unit="cm",
    )


def test_pixel_size_known() -> None:
    native = _native_session()
    assert native.pixel_size_known is False
    pixel = native.model_copy(
        update={
            "has_pixel_frame": True,
            "video": VideoInfo(fps=25.0, n_frames=8, width_px=640, height_px=480),
        }
    )
    assert pixel.pixel_size_known is True
    zero = VideoInfo(fps=25.0, n_frames=8, width_px=0, height_px=0)
    unknown = pixel.model_copy(update={"video": zero})
    assert unknown.pixel_size_known is False


def test_no_consumer_reads_zero_video_size() -> None:
    from ui.store.session_facts import SessionFacts

    native = _native_session("n1")
    other = _native_session("n2")
    pixel = native.model_copy(
        update={
            "session_id": "p1",
            "has_pixel_frame": True,
            "video": VideoInfo(fps=25.0, n_frames=8, width_px=640, height_px=480),
        }
    )
    kwargs = {"calibration_mode": "session"}
    s1 = SessionSummary.from_session(native, **kwargs)
    s2 = SessionSummary.from_session(other, **kwargs)
    assert heterogeneity_warnings([s1, s2]) == []
    # defence in depth: a stray pixel session beside a native one is not a resolution complaint
    sp = SessionSummary.from_session(pixel, **kwargs)
    assert not any("resolution" in w for w in heterogeneity_warnings([s1, sp]))
    # two pixel sessions at different sizes still are (unchanged)
    sp2 = replace(sp, session_id="p2", width_px=800)
    assert any("resolution" in w for w in heterogeneity_warnings([sp, sp2]))

    table = sessions_table([s1, s2])
    assert table["width_px"].isna().all() and table["height_px"].isna().all()
    pixel_table = sessions_table([sp, sp2])
    assert list(pixel_table["width_px"]) == [640, 800]

    facts = SessionFacts.from_session(native)
    assert facts.has_pixel_frame is False
    assert (facts.width_px, facts.height_px) == (0, 0)


# ── Zones screen ─────────────────────────────────────────────────────────────


def _native_store(tmp_path: Path):
    pytest.importorskip("PySide6")
    from track2data.core.models import SessionRef
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    ref = SessionRef(
        session_id="n1",
        folder=tmp_path / "n1.csv",
        sha256="",
        reader="anipose",
        reader_options={"fps": 25.0, "unit": "mm"},
    )
    store.update_sessions([ref])
    return store


def test_zones_screen_is_disabled_for_native(qtbot, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from ui.zones_screen import NATIVE_ZONES_NOTICE, ZonesScreen

    assert NATIVE_ZONES_NOTICE == (
        "This project's sessions have no pixel frame (native 3-D); zones are not available."
    )
    store = _native_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    assert not screen._native_notice.isHidden()
    assert screen._native_notice.text() == NATIVE_ZONES_NOTICE
    assert not screen._canvas.isEnabled()
    assert not screen._save_zone_btn.isEnabled()
    screen._zone_name_edit.setText("arena")
    screen._canvas.selected_points = lambda: [(0, 0), (1, 0), (1, 1)]  # type: ignore[method-assign]
    screen._save_zone()
    assert store.manifest.zones.rois == []


def test_zones_screen_unchanged_for_pixel_projects(qtbot, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from track2data.core.models import SessionRef
    from ui.store.project_store import ProjectStore
    from ui.zones_screen import ZonesScreen

    store = ProjectStore()
    store.new_project("p", tmp_path)
    store.update_sessions([SessionRef(session_id="s", folder=tmp_path, sha256="")])
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    assert screen._native_notice.isHidden()
    assert screen._canvas.isEnabled()


def test_zones_screen_follows_the_project(qtbot, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from ui.zones_screen import ZonesScreen

    store = _native_store(tmp_path)
    screen = ZonesScreen(store)
    qtbot.addWidget(screen)
    store.update_sessions([])
    assert screen._native_notice.isHidden()
    assert screen._canvas.isEnabled()


# ── stage status ─────────────────────────────────────────────────────────────


def test_native_side_view_project_has_no_zone_water_column_warning() -> None:
    from tests.test_native3d.test_project_rules import SESSION_CM, _manifest, _ref
    from ui.store.stage_status import compute_stage_statuses, stage_summaries

    native = _manifest(
        [_ref("n1")], calibration=SESSION_CM, individual=("IL-15",), camera_view="side"
    )
    info = compute_stage_statuses(native, has_run_results=False)[3]
    assert "waterline" not in info.message
    assert stage_summaries(native, has_run_results=False)[3] != "Draw the water column"
    pixel = _manifest([_ref("p1", None)], individual=("IL-15",), camera_view="side")
    assert "waterline" in compute_stage_statuses(pixel, has_run_results=False)[3].message


# ── README block ─────────────────────────────────────────────────────────────


def _readme_for(tmp_path: Path, water_column: WaterColumn | None, flip: bool = False) -> str:
    import pandas as pd

    from track2data.exporters.base import ExportPayload, SessionProvenance
    from track2data.exporters.readme import ReadmeExporter

    native = {
        "source_unit": "mm",
        "target_unit": "cm",
        "vertical_axis": "y",
        "flip": flip,
        "water_column": (
            {"surface_z": water_column.surface_z, "floor_z": water_column.floor_z}
            if water_column
            else None
        ),
    }
    payload = ExportPayload(
        session_id="n1",
        project_name="proj",
        project_hash="0" * 16,
        app_version="x",
        fish_by_frame=pd.DataFrame(),
        provenance=SessionProvenance(
            reader="anipose",
            source_software="Anipose",
            reader_verification="synthetic_only",
            length_unit=1.0,
            length_unit_label="cm",
            length_unit_confirmed_by_user=True,
            native_3d=native,
        ),
    )
    ReadmeExporter().write(payload, tmp_path)
    return (tmp_path / "README.md").read_text(encoding="utf-8")


def test_readme_native_block(tmp_path: Path) -> None:
    text = _readme_for(tmp_path, WaterColumn(surface_z=0.0, floor_z=20.0), flip=True)
    assert "## Native 3-D source" in text
    assert "| Reader | `anipose` |" in text
    assert "| File unit | mm |" in text
    assert "| Project unit | cm |" in text
    assert "| Vertical axis | y |" in text
    assert "| Flipped | True |" in text
    assert "| Water column | surface z 0 cm, floor z 20 cm |" in text
    assert "px per cm" not in text


def test_readme_native_block_without_water_column(tmp_path: Path) -> None:
    text = _readme_for(tmp_path / "a", None)
    assert "| Water column | *(not set)* |" in text


def test_readme_unchanged_for_pixel_sessions(tmp_path: Path) -> None:
    import pandas as pd

    from track2data.exporters.base import ExportPayload
    from track2data.exporters.readme import ReadmeExporter

    payload = ExportPayload(
        session_id="s", project_name="p", project_hash="0" * 16, app_version="x",
        fish_by_frame=pd.DataFrame(),
    )
    ReadmeExporter().write(payload, tmp_path)
    assert "Native 3-D source" not in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_engine_provenance_carries_the_native_block(tmp_path: Path) -> None:
    from track2data.api import Engine
    from track2data.core.models import SessionRef

    csv = write_anipose_csv(tmp_path / "n1.csv", ["head"], 30)
    ref = SessionRef(
        session_id="n1", folder=csv, sha256="", reader="anipose",
        reader_options={"fps": 50.0, "unit": "mm", "vertical_axis": "z"},
    )
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p", created_at=now, updated_at=now, sessions=[ref],
        calibration=CalibrationConfig(
            mode="session", length_unit_label="cm", length_unit_confirmed_by_user=True,
            water_column=WaterColumn(surface_z=0.0, floor_z=5.0),
        ),
    )
    engine = Engine(manifest)
    session = engine.read_ref(ref)
    block = engine.native_3d_provenance(session)
    assert block == {
        "source_unit": "mm",
        "target_unit": "cm",
        "vertical_axis": "z",
        "flip": False,
        "water_column": {"surface_z": 0.0, "floor_z": 5.0},
    }
    pixel = session.model_copy(update={"has_pixel_frame": True})
    assert engine.native_3d_provenance(pixel) is None


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_import_options(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    write_anipose_csv(root / "fish1.csv", ["head", "tail"], 10)
    now = datetime.now(tz=UTC)
    project = tmp_path / "p.t2d.json"
    write_manifest(ProjectManifest(project_name="p", created_at=now, updated_at=now), project)
    result = CliRunner().invoke(
        cli, ["add", str(project), str(root), "--option", "unit=mm", "--option", "fps=100", "--yes"]
    )
    assert result.exit_code == 0, result.output
    manifest = read_manifest(project)
    assert [r.reader for r in manifest.sessions] == ["anipose"]
    ref = manifest.sessions[0]
    assert ref.reader_options["unit"] == "mm"
    assert ref.reader_options["fps"] == 100.0
    assert manifest.calibration.mode == "session"
    assert manifest.calibration.length_unit_label == "cm"
    assert manifest.calibration.length_unit_confirmed_by_user is True


def test_cli_import_without_required_options_names_them(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    write_anipose_csv(root / "fish1.csv", ["head"], 10)
    now = datetime.now(tz=UTC)
    project = tmp_path / "p.t2d.json"
    write_manifest(ProjectManifest(project_name="p", created_at=now, updated_at=now), project)
    args = ["add", str(project), str(root), "--option", "unit=mm", "--yes"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "fps" in result.output
