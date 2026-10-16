"""Session, pipeline and engine guards (deferred minors): each makes a silent drop visible."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from tests.test_readers.native3d_files import write_anipose_csv
from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest
from track2data.core.models import IdSwitchCfg, ProjectManifest, Session, VideoInfo


def _session(*, n_animals: int = 2, z_animals: int = 2, pixel: bool = True) -> Session:
    n = 12
    rng = np.random.default_rng(1)
    return Session(
        session_id="s1",
        folder=Path("/tmp/s1"),
        reader="test",
        video=VideoInfo(
            fps=25.0, n_frames=n, width_px=100 if pixel else 0, height_px=100 if pixel else 0
        ),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=rng.random((n, n_animals, 2)) * 50,
        raw_z=rng.random((n, z_animals)),
        has_pixel_frame=pixel,
    )


def test_keep_animals_warns_when_dropping_a_mismatched_z(caplog) -> None:
    from track2data.views.panels import keep_animals

    session = _session(n_animals=2, z_animals=3)
    with caplog.at_level(logging.WARNING, logger="track2data.views.panels"):
        out = keep_animals(session, [0])
    assert out.raw_z is None
    assert any("s1" in r.getMessage() and "raw_z" in r.getMessage() for r in caplog.records)


def test_keep_animals_is_silent_when_z_matches(caplog) -> None:
    from track2data.views.panels import keep_animals

    with caplog.at_level(logging.WARNING, logger="track2data.views.panels"):
        out = keep_animals(_session(), [1])
    assert out.raw_z is not None and out.raw_z.shape == (12, 1)
    assert not caplog.records


def test_fuse_refusal_names_the_missing_pixel_frame() -> None:
    from tests.test_fusion.test_agreement import build, walk
    from track2data.fusion.fuse import FusionError, fuse

    top, side, pair = build(walk(30, 3))
    top.session = top.session.model_copy(update={"has_pixel_frame": False})
    with pytest.raises(FusionError) as exc:
        fuse(top, side, pair, same_video=False)
    sid = top.session.session_id
    assert f"session {sid} has no pixel frame (a native 3-D session has no views to fuse)" in str(
        exc.value
    )


def _crossing_pair(n: int = 40, swap_at: int = 20):
    """Two fish on straight parallel lines whose labels swap at *swap_at*; z tells them apart."""
    t = np.arange(n, dtype=float)
    xy = np.zeros((n, 2, 2))
    xy[:, 0, 0], xy[:, 0, 1] = t, 0.0
    xy[:, 1, 0], xy[:, 1, 1] = t, 30.0
    z = np.zeros((n, 2))
    z[:, 0], z[:, 1] = 5.0, 50.0
    swapped = xy.copy()
    swapped_z = z.copy()
    swapped[swap_at:] = xy[swap_at:, ::-1]
    swapped_z[swap_at:] = z[swap_at:, ::-1]
    return xy, z, swapped, swapped_z


def test_switch_correction_reports_which_column_holds_each_identity() -> None:
    from track2data.preprocess.identity_switch import correct_switches

    xy, _, swapped, _ = _crossing_pair()
    fixed, step = correct_switches(swapped, IdSwitchCfg(enabled=True))
    np.testing.assert_allclose(fixed, xy)
    assert step.permutation is not None and step.permutation.shape == (40, 2)
    assert step.permutation[:20].tolist() == [[0, 1]] * 20
    assert step.permutation[20:].tolist() == [[1, 0]] * 20


def test_identity_switch_correction_leaves_native_z_aligned_with_xy() -> None:
    """A swapped label moves z with x and y: the animal keeps its own height."""
    from track2data.core.models import PreprocessConfig
    from track2data.preprocess.pipeline import run

    xy, z, swapped, swapped_z = _crossing_pair()
    session = _native_session(swapped, swapped_z)
    cfg = PreprocessConfig()
    cfg.identity_switch = IdSwitchCfg(enabled=True)
    cfg.smoothing.enabled = False
    cfg.gap_fill.enabled = False
    psess = run(session, cfg)
    np.testing.assert_allclose(psess.xy, xy)
    np.testing.assert_allclose(psess.z, z)


def _native_session(xy: np.ndarray, z: np.ndarray):
    from track2data.readers.assemble import assemble_native_session

    return assemble_native_session(
        session_id="pair",
        folder=Path("pair.csv"),
        reader="anipose",
        fps=25.0,
        raw_xy=xy,
        raw_z=z,
        source_unit="cm",
        target_unit="cm",
        vertical_axis="z",
        flip=False,
        keypoints=None,
        tracking_intervals=None,
        trajectory_source=None,
        trajectory_format="anipose_pose3d_csv",
    )


def test_t2d_add_names_the_unreadable_native_file(tmp_path: Path) -> None:
    root = tmp_path / "pose"
    root.mkdir()
    write_anipose_csv(root / "good.csv", ["head"], 8)
    bad = write_anipose_csv(root / "bad.csv", ["head"], 8)
    lines = bad.read_text().splitlines()
    lines[3] = lines[3].replace("1", "x", 3)  # a non-numeric cell: the full read fails
    bad.write_text("\n".join(lines) + "\n")
    now = datetime.now(tz=UTC)
    project = tmp_path / "p.t2d.json"
    write_manifest(ProjectManifest(project_name="p", created_at=now, updated_at=now), project)
    args = ["add", str(project), str(root), "--yes", "--option", "fps=50", "--option", "unit=mm"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert f"[error] {bad}: " in result.output
    assert read_manifest(project).sessions == []


def test_add_session_refuses_a_native_folder_before_listing(qtbot, tmp_path: Path) -> None:
    """A bare add cannot give a native file its unit/fps, so it is refused up front (it used to
    be listed reader-less, counted as a pixel session, and fail at its probe)."""
    pytest.importorskip("PySide6")
    from tests.test_native3d.test_project_rules import _manifest
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store._manifest = _manifest([])
    submitted: list[str] = []
    store._submit_probe = lambda sid, f: submitted.append(sid)  # type: ignore[method-assign]
    refused: list[tuple[str, str]] = []
    store.sessionRefused.connect(lambda sid, msg: refused.append((sid, msg)))
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        write_anipose_csv(folder / "fish.csv", ["head"], 8)
        store.add_session(folder)
    assert store.manifest.sessions == [] and submitted == []
    assert len(refused) == 2 and all("NATIVE_3D_NEEDS_OPTIONS" in m for _, m in refused)
    assert "t2d add" in refused[0][1]


def test_add_session_of_a_pixel_folder_keeps_a_reader_less_ref(qtbot, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from tests.test_native3d.test_project_rules import _manifest
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store._manifest = _manifest([])
    store._submit_probe = lambda sid, f: None  # type: ignore[method-assign]
    folder = tmp_path / "empty"
    folder.mkdir()
    store.add_session(folder)
    (ref,) = store.manifest.sessions
    assert ref.reader is None and ref.reader_options == {} and ref.reader_chosen_by is None


@pytest.mark.parametrize("kind", ["undetected", "pixel"])
def test_add_session_refuses_a_non_native_folder_in_a_native_project(
    qtbot, tmp_path: Path, monkeypatch, kind: str
) -> None:
    pytest.importorskip("PySide6")
    from tests.test_native3d.test_project_rules import _manifest, _ref
    from ui.store.project_store import ProjectStore

    folder = tmp_path / "other"
    folder.mkdir()
    store = ProjectStore()
    store._manifest = _manifest([_ref("n1")])
    if kind == "pixel":
        monkeypatch.setattr(ProjectStore, "_detected_reader", staticmethod(lambda f: "idtrackerai"))
    submitted: list[str] = []
    store._submit_probe = lambda sid, f: submitted.append(sid)  # type: ignore[method-assign]
    refused: list[tuple[str, str]] = []
    changed: list[int] = []
    store.sessionRefused.connect(lambda sid, msg: refused.append((sid, msg)))
    store.sessionsChanged.connect(lambda: changed.append(1))
    store.add_session(folder)
    assert submitted == [] and changed == []
    assert [r.session_id for r in store.manifest.sessions] == ["n1"]
    assert refused and "NATIVE_3D_MIXED" in refused[0][1]
