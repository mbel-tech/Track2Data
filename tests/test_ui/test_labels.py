"""
Tests for ui/widgets/labels.py -- the shared "make an engine identifier
human-readable" helper, lifted from ui/export_screen.py's original
_LABELS/_label_for pattern so it isn't copied a fourth time.

No PySide6 import here: this module is pure string logic, no Qt
dependency, so these tests don't need pytest.importorskip("PySide6").
"""

from __future__ import annotations

from ui.widgets.labels import label_for


def test_override_wins_over_mechanical_title_case() -> None:
    assert label_for("savgol", {"savgol": "Savitzky-Golay"}) == "Savitzky-Golay"


def test_falls_back_to_underscore_replace_and_title_case() -> None:
    # No override provided for this value -- must still produce
    # *something* readable, not the raw identifier.
    assert label_for("moving_avg", {"savgol": "Savitzky-Golay"}) == "Moving Avg"


def test_works_with_no_overrides_dict_at_all() -> None:
    assert label_for("path_length") == "Path Length"
    assert label_for("path_length", None) == "Path Length"


def test_single_word_value_title_cased() -> None:
    assert label_for("none") == "None"


def test_empty_overrides_dict_falls_back_same_as_none() -> None:
    assert label_for("path_length", {}) == "Path Length"
