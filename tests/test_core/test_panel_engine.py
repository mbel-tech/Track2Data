"""Engine.import_ref / preprocess_ref / _cache_key read a session through its panel."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.support.toy_reader import OPTIONS
from track2data.api import Engine
from track2data.core.models import PanelRect, ProjectManifest, SessionRef

LEFT = PanelRect(x=0, y=0, width=50, height=80)
RIGHT = PanelRect(x=50, y=0, width=50, height=80)
#: Holds both toy animals (they walk around x 20-60), shifted by 10.
WIDE = PanelRect(x=10, y=0, width=90, height=80)


def _ref(folder: Path, panel: PanelRect | None = None) -> SessionRef:
    return SessionRef(
        session_id="trial1",
        folder=folder,
        sha256="",
        reader="toy_csv",
        reader_options=dict(OPTIONS),
        panel=panel,
    )


def _engine(ref: SessionRef, cache: Path | None = None) -> Engine:
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now, sessions=[ref])
    return Engine(manifest, cache_dir=cache)


def _assert_shifted(panel_xy: np.ndarray, whole_xy: np.ndarray) -> None:
    """Every position kept in the panel is the whole-frame one minus the panel origin."""
    kept = np.isfinite(panel_xy[..., 0])
    assert kept.any()
    assert np.allclose(panel_xy[kept] + [WIDE.x, WIDE.y], whole_xy[kept])


def test_a_ref_without_a_panel_is_unchanged(toy_reader: None, toy_folder: Path) -> None:
    session = _engine(_ref(toy_folder)).import_ref(_ref(toy_folder))
    assert session.video.width_px == 100
    assert session.n_animals == 2


def test_a_panel_ref_returns_the_panel_session(toy_reader: None, toy_folder: Path) -> None:
    whole = _engine(_ref(toy_folder)).import_ref(_ref(toy_folder))
    ref = _ref(toy_folder, WIDE)
    session = _engine(ref).import_ref(ref)
    assert (session.video.width_px, session.video.height_px) == (90, 80)
    assert session.session_id == "trial1"
    assert session.n_animals == 2
    _assert_shifted(session.raw_xy, whole.raw_xy)


def test_the_auto_detect_branch_applies_the_panel(toy_reader: None, toy_folder: Path) -> None:
    ref = _ref(toy_folder, LEFT).model_copy(update={"reader": None, "reader_options": {}})
    engine = _engine(ref)
    # the toy reader needs options, so stand in for detection with the same read
    engine.import_session = lambda folder: _engine(_ref(toy_folder)).import_ref(_ref(toy_folder))  # type: ignore[method-assign]
    assert engine.import_ref(ref).video.width_px == 50


def test_a_panel_outside_the_video_raises(toy_reader: None, toy_folder: Path) -> None:
    ref = _ref(toy_folder, PanelRect(x=60, y=0, width=80, height=80))
    with pytest.raises(ValueError):
        _engine(ref).import_ref(ref)


def test_the_cache_key_changes_with_the_panel(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"

    def key(panel: PanelRect | None) -> str:
        ref = _ref(toy_folder, panel)
        found = _engine(ref, cache)._cache_key(ref)
        assert found is not None
        return found[1]

    assert key(None) != key(LEFT)
    assert key(LEFT) != key(RIGHT)
    assert key(LEFT) == key(PanelRect(x=0, y=0, width=50, height=80))


def test_the_no_panel_key_is_the_one_it_was_before_panels(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    from track2data import __version__
    from track2data.cache.store import CacheStore
    from track2data.core.hashing import dict_sha256, folder_fingerprint

    cache = tmp_path / "cache"
    ref = _ref(toy_folder)
    engine = _engine(ref, cache)
    m = engine.manifest
    old_hash = dict_sha256(
        {
            "schema": engine._CACHE_SCHEMA,
            "app": __version__,
            "reader_options": ref.reader_options,
            "import_settings": engine._import_settings_fingerprint(ref),
            "preprocess": m.preprocess.model_dump(mode="json"),
            "calibration": m.calibration.model_dump(mode="json"),
            "zones": m.zones.model_dump(mode="json"),
        }
    )
    store = CacheStore(cache)
    expected = store.key("toy_csv", folder_fingerprint(ref.folder), old_hash)
    found = engine._cache_key(ref)
    assert found is not None
    assert found[1] == expected


def test_preprocess_ref_returns_panel_relative_xy(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    ref = _ref(toy_folder, WIDE)
    psess = _engine(ref, tmp_path / "cache").preprocess_ref(ref)
    whole = _engine(_ref(toy_folder)).import_ref(_ref(toy_folder))
    assert psess.session.video.width_px == 90
    _assert_shifted(psess.session.raw_xy, whole.raw_xy)
