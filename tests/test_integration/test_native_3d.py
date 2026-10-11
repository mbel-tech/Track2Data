"""Native 3-D files end to end: synthetic Anipose files added through the real add flow (the CLI,
which sets up the project's calibration), preprocessed, and run through IL-15/IL-16/IL-17/GL-16.

Scene: a fish that moves (3, 4, 12) mm per frame at 25 fps for 11 frames (10 steps), file unit mm,
project unit cm. One step is (0.3, 0.4, 1.2) cm, so

* its length is hypot(0.3, 0.4, 1.2) = sqrt(0.09 + 0.16 + 1.44) = 1.3 cm;
* IL-16, the path, is 10 steps x 1.3 cm = 13 cm;
* IL-17, the speed, is 1.3 cm x 25 frames/s = 32.5 cm/s at every frame (mean = median = max);
* the horizontal plane (x, y with z vertical) has a step of 0.5 cm: IL-1 5 cm, IL-2 12.5 cm/s.

The second file is the same track shifted by +100 mm in x and y and +100 mm in z (+10 cm).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from tests.test_fusion.scene import build_scene
from tests.test_readers.native3d_files import write_anipose_csv
from track2data.api import NATIVE_3D_NEEDS_SESSION_CALIBRATION, Engine
from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest
from track2data.core.models import (
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    WaterColumn,
)
from track2data.metrics.availability import NEEDS_SEVERAL_ANIMALS_REASON, NEEDS_WATER_COLUMN_REASON

N_FRAMES = 11
FPS = 25.0
STEP_MM = np.array([3.0, 4.0, 12.0])
SHIFT_MM = 100.0
STEP_CM = 1.3
PATH_CM = 13.0
SPEED_CM_S = 32.5
SELECTION = MetricSelection(
    individual=["IL-1", "IL-2", "IL-15", "IL-16", "IL-17"], group=["GL-16"]
)
_STAMP = re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00")


def _track(shift_mm: float = 0.0) -> np.ndarray:
    """``(frames, 1, 3)`` mm: the fish at frame f is at f * (3, 4, 12) mm, plus the shift."""
    return np.arange(N_FRAMES, dtype=float)[:, None, None] * STEP_MM + shift_mm


def _native_project(root: Path, *extra_options: str) -> Path:
    """Two Anipose files added to a new project by ``t2d add`` (the real add flow)."""
    data = root / "data"
    data.mkdir(parents=True)
    write_anipose_csv(data / "fish1.csv", ["head"], N_FRAMES, xyz=_track())
    write_anipose_csv(data / "fish2.csv", ["head"], N_FRAMES, xyz=_track(SHIFT_MM))
    now = datetime.now(tz=UTC)
    project = root / "p.t2d.json"
    write_manifest(ProjectManifest(project_name="native", created_at=now, updated_at=now), project)
    args = ["add", str(project), str(data), "--option", "unit=mm", "--option", "fps=25", "--yes"]
    for option in extra_options:
        args += ["--option", option]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    return project


def _manifest(
    project: Path,
    water_column: WaterColumn | None = None,
    bin_minutes: float | None = None,
) -> ProjectManifest:
    manifest = read_manifest(project)
    calibration = manifest.calibration.model_copy(update={"water_column": water_column})
    metrics = SELECTION.model_copy(update={"timepoint_minutes": bin_minutes})
    return manifest.model_copy(update={"calibration": calibration, "metrics": metrics})


def _long(out: Path, session: str) -> pd.DataFrame:
    return pd.read_csv(out / session / "metrics_long.csv")


def _value(long: pd.DataFrame, metric: str, column: str) -> float:
    rows = long[(long["metric_id"] == metric) & (long["column"] == column)]
    assert len(rows) == 1, (metric, column, len(rows))
    return float(rows["value"].iloc[0])


def _difference_report(
    serial: dict[str, bytes], parallel: dict[str, bytes], lines: int = 12
) -> str:
    """What differs between two runs' files, readable in a failure message: the files only one
    run wrote, and the first changed lines of each file that differs. A run whose worker died
    differs by a 'Sessions that failed' section, which this makes visible."""
    import difflib

    out: list[str] = []
    for name in sorted(serial.keys() ^ parallel.keys()):
        out.append(f"only in the {'serial' if name in serial else 'parallel'} run: {name}")
    for name in sorted(serial.keys() & parallel.keys()):
        if serial[name] == parallel[name]:
            continue
        a = serial[name].decode("utf-8", "replace").splitlines()
        b = parallel[name].decode("utf-8", "replace").splitlines()
        diff = list(difflib.unified_diff(a, b, "serial", "parallel", lineterm="", n=0))
        out.append(f"{name} differs ({len(serial[name])} vs {len(parallel[name])} bytes):")
        out.extend(f"    {line[:200]}" for line in diff[:lines])
    return "\n".join(out)


def test_the_difference_report_names_files_and_changed_lines() -> None:
    serial = {"a.csv": b"x\n1\n", "same.txt": b"s", "only_serial": b"o"}
    parallel = {"a.csv": b"x\n2\n", "same.txt": b"s", "only_parallel": b"o"}
    report = _difference_report(serial, parallel)
    assert "only in the serial run: only_serial" in report
    assert "only in the parallel run: only_parallel" in report
    assert "a.csv differs" in report and "-1" in report and "+2" in report
    assert "same.txt" not in report
    assert _difference_report(serial, serial) == ""


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): _STAMP.sub(b"<time>", p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _native_project(tmp_path_factory.mktemp("native3d"))


@pytest.fixture(scope="module")
def run_no_column(project: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("serial")
    Engine(_manifest(project)).run(out / "o", exporters=["csv_long", "csv_wide", "readme"])
    return out / "o"


def test_the_add_flow_sets_up_the_project(project: Path) -> None:
    manifest = read_manifest(project)
    assert [r.session_id for r in manifest.sessions] == ["fish1", "fish2"]
    assert {r.reader for r in manifest.sessions} == {"anipose"}
    assert manifest.mode.dimension == "2d"
    cal = manifest.calibration
    assert (cal.mode, cal.length_unit_label, cal.length_unit_confirmed_by_user) == (
        "session",
        "cm",
        True,
    )
    assert Engine(_manifest(project)).validate() == []


def test_preprocess_keeps_the_absolute_z(project: Path) -> None:
    engine = Engine(_manifest(project))
    psess = engine.preprocess(engine.import_ref(engine.manifest.sessions[0]))
    assert psess.z is not None and psess.depth is None
    np.testing.assert_allclose(psess.z[:, 0], np.arange(N_FRAMES) * 1.2, atol=1e-12)
    np.testing.assert_allclose(psess.xy[:, 0, 0], np.arange(N_FRAMES) * 0.3, atol=1e-12)
    assert psess.px_per_cm == 1.0


def test_3d_metrics_have_the_hand_computed_values(run_no_column: Path) -> None:
    for session in ("fish1", "fish2"):
        long = _long(run_no_column, session)
        assert _value(long, "IL-16", "n_valid_steps") == 10
        assert _value(long, "IL-16", "path_length_3d_cm") == pytest.approx(PATH_CM, abs=1e-9)
        for column in ("mean_speed_3d_cm_s", "median_speed_3d_cm_s", "max_speed_3d_cm_s"):
            assert _value(long, "IL-17", column) == pytest.approx(SPEED_CM_S, abs=1e-9)


def test_group_metrics_are_unavailable_for_native_files(run_no_column: Path) -> None:
    """GL-16 (and every group metric) needs several animals in a session; a native file holds one,
    so it is skipped with its reason instead of reporting NaN."""
    long = _long(run_no_column, "fish1")
    assert "GL-16" not in set(long["metric_id"])
    readme = (run_no_column / "fish1" / "README.md").read_text(encoding="utf-8")
    assert NEEDS_SEVERAL_ANIMALS_REASON in readme


def test_the_2d_metrics_use_the_horizontal_plane(run_no_column: Path) -> None:
    long = _long(run_no_column, "fish1")
    assert _value(long, "IL-1", "path_length_cm") == pytest.approx(5.0, abs=1e-9)
    assert _value(long, "IL-2", "mean_speed_cm_s") == pytest.approx(12.5, abs=1e-9)
    frames = pd.read_csv(run_no_column / "fish1" / "master_fish_by_frame.csv")
    assert "z_cm" in frames.columns  # the vertical coordinate is exported without a water column
    assert "depth_fraction" not in frames.columns  # but no depth: that needs the water column


def test_il15_is_unavailable_without_the_water_column(
    project: Path, run_no_column: Path
) -> None:
    engine = Engine(_manifest(project))
    assert engine.skipped_metrics(False)["IL-15"] == NEEDS_WATER_COLUMN_REASON
    assert "IL-15" not in set(_long(run_no_column, "fish1")["metric_id"])
    readme = (run_no_column / "fish1" / "README.md").read_text(encoding="utf-8")
    assert NEEDS_WATER_COLUMN_REASON in readme


def test_il15_with_the_water_column_counts_the_outside_values(
    project: Path, tmp_path: Path
) -> None:
    """Surface z 0, floor z 20 cm. fish1 z = 1.2 f cm (0 to 12): depth z/20, mean 0.3 = 6 cm,
    none outside. fish2 z = 10 + 1.2 f: frames 9 and 10 (20.8, 22.0) are below the floor, so
    their depth is NaN and they are counted, never clipped: 2 of 11 outside; the other nine
    frames (z 10 to 19.6) average 14.8 cm = 0.74."""
    manifest = _manifest(project, WaterColumn(surface_z=0.0, floor_z=20.0))
    # the scene sits exactly on the surface (z = 0 at frame 0); smoothing's rounding noise
    # (-3e-16) would put that one sample outside, which is not what this test is about
    no_smoothing = manifest.preprocess.smoothing.model_copy(update={"enabled": False})
    manifest = manifest.model_copy(
        update={"preprocess": manifest.preprocess.model_copy(update={"smoothing": no_smoothing})}
    )
    Engine(manifest).run(tmp_path / "o", exporters=["csv_long", "csv_wide"])
    one = _long(tmp_path / "o", "fish1")
    assert _value(one, "IL-15", "mean_depth_fraction") == pytest.approx(0.3, abs=1e-9)
    assert _value(one, "IL-15", "mean_depth_cm") == pytest.approx(6.0, abs=1e-9)
    assert _value(one, "IL-15", "frac_outside_extent") == 0.0
    two = _long(tmp_path / "o", "fish2")
    assert _value(two, "IL-15", "mean_depth_fraction") == pytest.approx(0.74, abs=1e-9)
    assert _value(two, "IL-15", "mean_depth_cm") == pytest.approx(14.8, abs=1e-9)
    assert _value(two, "IL-15", "frac_outside_extent") == pytest.approx(2 / 11, abs=1e-12)
    # the water column also bounds the 3-D metrics: the two frames below the floor are out of the
    # path (8 of the 10 steps remain, 1.3 cm each) and have no speed; the rest is unchanged
    assert _value(two, "IL-16", "path_length_3d_cm") == pytest.approx(8 * STEP_CM, abs=1e-9)
    assert _value(two, "IL-17", "mean_speed_3d_cm_s") == pytest.approx(SPEED_CM_S, abs=1e-9)
    assert _value(two, "IL-17", "max_speed_3d_cm_s") == pytest.approx(SPEED_CM_S, abs=1e-9)
    # fish1 has nothing outside, so it keeps the full path
    assert _value(one, "IL-16", "path_length_3d_cm") == pytest.approx(PATH_CM, abs=1e-9)
    frames = pd.read_csv(tmp_path / "o" / "fish2" / "master_fish_by_frame.csv")
    depth = frames["depth_fraction"].to_numpy()
    assert np.isnan(depth[9:]).all() and np.isfinite(depth[:9]).all()
    # the exported z_cm is the file's own coordinate, outside samples included
    np.testing.assert_allclose(frames["z_cm"].to_numpy()[9:], [20.8, 22.0], atol=1e-9)


def test_a_reversed_water_column_gives_the_same_depth_cm(project: Path, tmp_path: Path) -> None:
    manifest = _manifest(project, WaterColumn(surface_z=20.0, floor_z=0.0))
    Engine(manifest).run(tmp_path / "o", exporters=["csv_long"])
    one = _long(tmp_path / "o", "fish1")
    # depth (z - 20) / (0 - 20) = 1 - z / 20: mean 0.7, i.e. 14 cm
    assert _value(one, "IL-15", "mean_depth_fraction") == pytest.approx(0.7, abs=1e-9)
    assert _value(one, "IL-15", "mean_depth_cm") == pytest.approx(14.0, abs=1e-9)


def test_serial_and_parallel_runs_write_identical_files(
    project: Path, tmp_path: Path
) -> None:
    manifest = _manifest(project, WaterColumn(surface_z=0.0, floor_z=20.0))
    exporters = ["csv_long", "csv_wide", "feather", "readme"]
    Engine(manifest).run(tmp_path / "serial", exporters=exporters)
    Engine(manifest).run(tmp_path / "parallel", exporters=exporters, n_workers=2)
    serial, parallel = _files(tmp_path / "serial"), _files(tmp_path / "parallel")
    report = _difference_report(serial, parallel)
    assert report == "", "serial and parallel runs wrote different files:\n" + report
    assert {n.split("/")[0] for n in serial} >= {"fish1", "fish2", "sessions.csv"}


def test_a_binned_run_splits_the_path_by_bin(project: Path, tmp_path: Path) -> None:
    """0.004 min = 0.24 s = 6 frames: bins hold frames 0-5 (5 steps) and 6-10 (4 steps)."""
    manifest = _manifest(project, bin_minutes=0.004)
    Engine(manifest).run(tmp_path / "o", exporters=["csv_long"])
    long = _long(tmp_path / "o", "fish1")
    rows = long[(long["metric_id"] == "IL-16") & (long["column"] == "path_length_3d_cm")]
    # the rows come in bin order
    assert rows["value"].tolist() == [
        pytest.approx(5 * STEP_CM, abs=1e-9),
        pytest.approx(4 * STEP_CM, abs=1e-9),
    ]


def test_the_vertical_axis_option_changes_the_plane_not_the_3d_path(tmp_path: Path) -> None:
    """With y vertical the horizontal plane is (x, z): a step of hypot(0.3, 1.2) cm, so IL-1 is
    10 x that; the vertical coordinate is y (0.4 cm per frame); the 3-D path is still 13 cm."""
    project = _native_project(tmp_path / "y", "vertical_axis=y")
    manifest = _manifest(project, WaterColumn(surface_z=0.0, floor_z=20.0))
    Engine(manifest).run(tmp_path / "o", exporters=["csv_long"])
    long = _long(tmp_path / "o", "fish1")
    assert _value(long, "IL-1", "path_length_cm") == pytest.approx(10 * math.hypot(0.3, 1.2))
    assert _value(long, "IL-16", "path_length_3d_cm") == pytest.approx(PATH_CM, abs=1e-9)
    assert _value(long, "IL-17", "mean_speed_3d_cm_s") == pytest.approx(SPEED_CM_S, abs=1e-9)
    # vertical y: depth = y / 20 with y = 0.4 f cm, mean over f = 0..10 is 2 cm = 0.1
    assert _value(long, "IL-15", "mean_depth_cm") == pytest.approx(2.0, abs=1e-9)


def test_the_run_refuses_a_non_session_calibration(project: Path, tmp_path: Path) -> None:
    manifest = _manifest(project)
    cal = manifest.calibration.model_copy(update={"mode": "bodylength"})
    engine = Engine(manifest.model_copy(update={"calibration": cal}))
    issues = engine.validate()
    assert NATIVE_3D_NEEDS_SESSION_CALIBRATION in issues


# ── a pixel-frame project is unchanged ───────────────────────────────────────

OLD_SESSIONS_HEADER = (
    "session_id,reader,fps,n_frames,duration_s,n_animals,width_px,height_px,calibration_mode,"
    "length_unit,px_per_cm,is_calibrated,is_identity_free,trajectory_source,trajectory_sha256,"
    "error,length_calibration_n,length_calibration_rel_sd"
)


def test_a_pixel_frame_project_is_unchanged(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": []}
    )
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=["csv_long", "csv_wide", "readme"])
    header = (out / "sessions.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == OLD_SESSIONS_HEADER
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in {".csv", ".md"}:
            text = path.read_text(encoding="utf-8")
            assert "Native 3-D" not in text and "native_3d" not in text
    frames = pd.read_csv(out / "t1" / "master_fish_by_frame.csv")
    assert "depth_fraction" not in frames.columns
    assert NEEDS_WATER_COLUMN_REASON not in (out / "t1" / "README.md").read_text(
        encoding="utf-8"
    )


def test_il15_names_the_water_column_as_its_source(project: Path) -> None:
    manifest = _manifest(project, WaterColumn(surface_z=0.0, floor_z=20.0))
    engine = Engine(manifest)
    psess = engine.preprocess(engine.import_ref(manifest.sessions[0]))
    result = engine.compute_metrics(psess)["IL-15"]
    assert set(result["depth_extent_source"]) == {"water_column"}
