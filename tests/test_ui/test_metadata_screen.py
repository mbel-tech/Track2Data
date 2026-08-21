"""
Tests for ui/metadata_screen.py (issue #39) -- loading a metadata CSV
must persist a MetadataSource on the store, not just update local
widget state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def _make_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


# ── _load_csv(): persisting MetadataSource ──────────────────────────────────


def test_load_csv_persists_a_metadata_source_on_the_store(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.core.hashing import file_sha256
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")

    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    store = _make_store(tmp_path)
    screen = MetadataScreen(store)

    screen._load_csv()

    source = store.manifest.metadata_source
    assert source is not None
    assert source.path == csv_path
    assert source.sha256 == file_sha256(csv_path)


def test_load_csv_with_no_store_does_not_raise(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MetadataScreen() with no store is a valid construction (used by
    test_app_smoke.py's blanket widget-instantiation check) -- _load_csv
    must degrade gracefully rather than assume self._store exists."""
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")

    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    screen = MetadataScreen()
    screen._load_csv()  # must not raise


def test_skip_metadata_still_clears_any_previously_loaded_source(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")
    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    store = _make_store(tmp_path)
    screen = MetadataScreen(store)
    screen._load_csv()
    assert store.manifest.metadata_source is not None

    screen._skip_metadata()
    assert store.manifest.metadata_source is None
