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


def test_switch_correction_warns_for_multi_animal_z(caplog) -> None:
    from track2data.preprocess.identity_switch import correct_switches

    xy = np.random.default_rng(2).random((10, 2, 2)) * 50
    cfg = IdSwitchCfg(enabled=True)
    with caplog.at_level(logging.WARNING, logger="track2data.preprocess.identity_switch"):
        correct_switches(xy, cfg, has_z=True)
    z_warnings = [r for r in caplog.records if "3-D z coordinate" in r.getMessage()]
    assert len(z_warnings) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="track2data.preprocess.identity_switch"):
        correct_switches(xy, cfg)
    assert not [r for r in caplog.records if "3-D z coordinate" in r.getMessage()]


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
