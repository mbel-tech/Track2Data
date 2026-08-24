"""
Tests for ui/preprocessing_screen.py.

No prior coverage existed for this screen (only the blanket
instantiate-all check in test_app_smoke.py). Added alongside the
combo-box display/storage split: the Method combos now show a pretty
label ("Standard-deviation multiple") while persisting the real engine
literal ("sd_multiple") as userData -- these tests are the correctness
proof that the two never get confused with each other.
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


# ── combo display vs. persisted value ───────────────────────────────────────


def test_jump_method_combo_shows_labels_not_raw_literals(qtbot) -> None:
    from ui.preprocessing_screen import PreprocessingScreen

    screen = PreprocessingScreen()
    qtbot.addWidget(screen)

    displayed = [screen._jump_method.itemText(i) for i in range(screen._jump_method.count())]
    assert "sd_multiple" not in displayed
    assert "Standard-deviation multiple" in displayed


def test_smooth_method_combo_shows_labels_not_raw_literals(qtbot) -> None:
    from ui.preprocessing_screen import PreprocessingScreen

    screen = PreprocessingScreen()
    qtbot.addWidget(screen)

    displayed = [screen._smooth_method.itemText(i) for i in range(screen._smooth_method.count())]
    assert "savgol" not in displayed
    assert "Savitzky-Golay" in displayed


def test_apply_persists_the_real_literal_not_the_display_label(qtbot, tmp_path: Path) -> None:
    """The critical correctness check: selecting the pretty-labelled
    "Savitzky-Golay" entry must write the engine literal "savgol" into
    PreprocessConfig, not the label text itself."""
    from ui.preprocessing_screen import PreprocessingScreen

    store = _make_store(tmp_path)
    screen = PreprocessingScreen(store)
    qtbot.addWidget(screen)

    idx = screen._smooth_method.findData("savgol")
    assert idx >= 0, "savgol not found among combo values"
    screen._smooth_method.setCurrentIndex(idx)

    idx2 = screen._jump_method.findData("percentile")
    assert idx2 >= 0
    screen._jump_method.setCurrentIndex(idx2)

    screen._apply()

    assert store.manifest.preprocess.smoothing.method == "savgol"
    assert store.manifest.preprocess.jump.method == "percentile"


def test_load_from_store_reselects_the_combo_for_a_non_default_value(
    qtbot, tmp_path: Path
) -> None:
    """The round-trip in the other direction: a manifest saved with a
    non-default method literal must re-select the matching combo entry
    on load, via findData() (the value), not findText() (the label)."""
    from track2data.core.models import JumpCfg, PreprocessConfig
    from ui.preprocessing_screen import PreprocessingScreen

    store = _make_store(tmp_path)
    store.update_preprocess(PreprocessConfig(jump=JumpCfg(method="percentile")))

    screen = PreprocessingScreen(store)
    qtbot.addWidget(screen)
    screen._load_from_store()

    assert screen._jump_method.currentData() == "percentile"
    assert screen._jump_method.currentText() == "Percentile"


# ── the checkable-group-box bug ─────────────────────────────────────────────


def test_group_boxes_are_not_independently_checkable(qtbot) -> None:
    """Regression test: the three QGroupBoxes used to also be
    setCheckable(True), giving each section two checkboxes (the
    group's own title checkbox, and the inner "Enabled" one) that
    could disagree, since _apply() only ever read the inner one."""
    from ui.preprocessing_screen import PreprocessingScreen

    screen = PreprocessingScreen()
    qtbot.addWidget(screen)

    assert screen._gap_group.isCheckable() is False
    assert screen._jump_group.isCheckable() is False
    assert screen._smooth_group.isCheckable() is False
