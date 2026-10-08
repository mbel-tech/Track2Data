"""Bundled font registration must never fail the app when the files are missing."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_missing_font_folder_registers_nothing(qtbot, tmp_path) -> None:
    from app.fonts import load_bundled_fonts

    assert load_bundled_fonts(tmp_path / "nope") == []


def test_non_font_files_are_ignored(qtbot, tmp_path) -> None:
    from app.fonts import load_bundled_fonts

    (tmp_path / "notes.txt").write_text("not a font")
    (tmp_path / "broken.ttf").write_bytes(b"not really a font")
    assert load_bundled_fonts(tmp_path) == []


def test_applying_a_theme_loads_fonts_once(qtbot, monkeypatch) -> None:
    import app.theme as theme_module

    calls: list[int] = []
    monkeypatch.setattr(theme_module, "load_bundled_fonts", lambda: calls.append(1) or [])
    manager = theme_module.ThemeManager()
    manager.apply("dark", persist=False)
    manager.apply("light", persist=False)
    assert calls == [1]


def test_the_bundled_fonts_register_both_families(qtbot) -> None:
    from app.fonts import load_bundled_fonts

    families = load_bundled_fonts()
    assert "Atkinson Hyperlegible" in families
    assert "IBM Plex Mono" in families


def test_each_bundled_font_ships_with_its_licence() -> None:
    from app.fonts import FONT_DIR

    names = {p.name for p in FONT_DIR.iterdir()}
    assert {"OFL-AtkinsonHyperlegible.txt", "OFL-IBMPlexMono.txt"} <= names
