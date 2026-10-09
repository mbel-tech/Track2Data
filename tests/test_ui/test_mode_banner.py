"""Tests for ui/widgets/mode_banner.py."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from track2data.core.models import ProjectMode

BANNER = "3-D mode: this screen applies to the 2-D tracks only until fusion is available"


def _store(tmp_path: Path):
    from app.state import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


def test_banner_hidden_without_project(qtbot) -> None:
    from app.state import ProjectStore
    from ui.widgets.mode_banner import ModeBanner

    banner = ModeBanner(ProjectStore())
    qtbot.addWidget(banner)
    assert banner.isHidden()


def test_banner_hidden_in_2d(qtbot, tmp_path: Path) -> None:
    from ui.widgets.mode_banner import ModeBanner

    banner = ModeBanner(_store(tmp_path))
    qtbot.addWidget(banner)
    assert banner.isHidden()


def test_banner_visible_in_3d_with_exact_text(qtbot, tmp_path: Path) -> None:
    from ui.widgets.mode_banner import ModeBanner

    store = _store(tmp_path)
    store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    banner = ModeBanner(store)
    qtbot.addWidget(banner)
    assert not banner.isHidden()
    assert banner.text() == BANNER


def test_banner_updates_on_mode_change(qtbot, tmp_path: Path) -> None:
    from ui.widgets.mode_banner import ModeBanner

    store = _store(tmp_path)
    banner = ModeBanner(store)
    qtbot.addWidget(banner)
    store.update_mode(ProjectMode(dimension="3d", layout="two_videos"))
    assert not banner.isHidden()
    store.update_mode(ProjectMode())
    assert banner.isHidden()
