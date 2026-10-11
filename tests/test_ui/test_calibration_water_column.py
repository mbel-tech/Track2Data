"""The Calibration page's water column fields (surface z, floor z) of a native 3-D project."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import SessionRef, WaterColumn


def _store(tmp_path: Path, reader: str | None = "anipose", unit: str = "cm"):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    options = {"fps": 25.0, "unit": "mm", "target_unit": unit} if reader == "anipose" else {}
    store.update_sessions(
        [SessionRef(session_id="s", folder=tmp_path / "s", sha256="", reader=reader,
                    reader_options=options)]
    )
    return store


def _screen(qtbot, store):
    from ui.calibration_screen import CalibrationScreen

    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)
    screen.show()
    return screen


def _type(screen, surface: str, floor: str) -> None:
    screen._surface_edit.setText(surface)
    screen._floor_edit.setText(floor)
    screen.flush()


def test_calibration_fields_only_for_native_projects(qtbot, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    pixel = _screen(qtbot, _store(tmp_path / "a", reader=None))
    assert pixel._water_group.isHidden()
    (tmp_path / "b").mkdir()
    native = _screen(qtbot, _store(tmp_path / "b"))
    assert not native._water_group.isHidden()
    assert native._surface_label.text() == "Surface z (cm)"
    assert native._floor_label.text() == "Floor z (cm)"


def test_fields_are_labelled_with_the_project_unit(qtbot, tmp_path: Path) -> None:
    store = _store(tmp_path, unit="m")
    store.update_calibration(
        store.manifest.calibration.model_copy(update={"length_unit_label": "m"})
    )
    screen = _screen(qtbot, store)
    assert screen._surface_label.text() == "Surface z (m)"
    assert screen._floor_label.text() == "Floor z (m)"


def test_water_column_fields_round_trip_through_the_store(qtbot, tmp_path: Path) -> None:
    store = _store(tmp_path)
    screen = _screen(qtbot, store)
    assert store.manifest.calibration.water_column is None
    _type(screen, "0", "20.5")
    assert store.manifest.calibration.water_column == WaterColumn(surface_z=0.0, floor_z=20.5)
    assert screen._water_error.isHidden()
    # reversed order is fine
    _type(screen, "20.5", "0")
    assert store.manifest.calibration.water_column == WaterColumn(surface_z=20.5, floor_z=0.0)
    # clearing one clears the column
    _type(screen, "20.5", "")
    assert store.manifest.calibration.water_column is None
    # the screen shows what the store holds
    store.update_water_column(WaterColumn(surface_z=1.0, floor_z=4.0))
    assert screen._surface_edit.text() == "1" and screen._floor_edit.text() == "4"


def test_invalid_water_column_is_refused_with_the_field_named(qtbot, tmp_path: Path) -> None:
    store = _store(tmp_path)
    screen = _screen(qtbot, store)
    _type(screen, "0", "20")
    good = store.manifest.calibration.water_column
    assert good is not None
    _type(screen, "5", "5")
    assert store.manifest.calibration.water_column == good
    assert not screen._water_error.isHidden()
    assert "floor z" in screen._water_error.text() and "surface z" in screen._water_error.text()
    _type(screen, "abc", "20")
    assert store.manifest.calibration.water_column == good
    assert "surface z" in screen._water_error.text()
    _type(screen, "0", "nan")
    assert store.manifest.calibration.water_column == good
    assert "floor z" in screen._water_error.text()
    _type(screen, "0", "inf")
    assert store.manifest.calibration.water_column == good
    assert "floor z" in screen._water_error.text()
    _type(screen, "1", "9")
    assert screen._water_error.isHidden()
    assert store.manifest.calibration.water_column == WaterColumn(surface_z=1.0, floor_z=9.0)


def test_mode_changes_keep_the_water_column(qtbot, tmp_path: Path) -> None:
    store = _store(tmp_path)
    screen = _screen(qtbot, store)
    _type(screen, "0", "20")
    screen._radio_session.setChecked(True)
    screen.flush()
    assert store.manifest.calibration.water_column == WaterColumn(surface_z=0.0, floor_z=20.0)


def test_the_water_column_help_says_one_column_serves_every_session(qtbot, tmp_path: Path) -> None:
    screen = _screen(qtbot, _store(tmp_path))
    text = screen._water_help.text()
    assert "every session" in text and "origin" in text
    assert "left out" in text  # the samples outside are excluded from the 3-D metrics too
