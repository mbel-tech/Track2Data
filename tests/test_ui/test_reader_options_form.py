"""ReaderOptionsForm: one control per option a reader declares, driven by the parameter's kind.

A reader says what its files do not record (frame rate, frame size, which keypoint); this is
the form the confirm dialog shows for it. It never decides what is valid -- the draft does, by
the reader's own validation -- it only turns a control into a value or into "not set".
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QListWidget,
    QSpinBox,
)

from track2data.readers.params import ReaderParameter
from ui.widgets.reader_options_form import ReaderOptionsForm

FPS = ReaderParameter(
    name="fps", label="Frame rate", kind="float", required=True, minimum=1, maximum=1000,
    help="Frames per second of the video.",
)  # fmt: skip
WIDTH = ReaderParameter(name="width_px", label="Frame width", kind="int", required=True, minimum=1)
KEYPOINT = ReaderParameter(name="keypoint", label="Keypoint", kind="str")
SMOOTH = ReaderParameter(name="smooth", label="Smooth", kind="bool", default=False)
VARIANT = ReaderParameter(
    name="variant", label="Variant", kind="choice", choices=("raw", "filtered"), default="raw"
)
ENGINE = ReaderParameter(
    name="engine", label="Engine", kind="choice", choices=("a", "b"), required=True
)
PARTS = ReaderParameter(name="parts", label="Parts", kind="multichoice", choices=("x", "y", "z"))
VIDEO = ReaderParameter(name="video", label="Video file", kind="path")


@pytest.fixture
def form(qtbot):
    f = ReaderOptionsForm([FPS, WIDTH, KEYPOINT, SMOOTH, VARIANT, ENGINE, PARTS, VIDEO])
    qtbot.addWidget(f)
    return f


def test_each_kind_gets_the_control_that_suits_it(form) -> None:
    assert isinstance(form.widget_for("fps"), QDoubleSpinBox)
    assert isinstance(form.widget_for("width_px"), QSpinBox)
    assert isinstance(form.widget_for("keypoint"), QLineEdit)
    assert isinstance(form.widget_for("smooth"), QCheckBox)
    assert isinstance(form.widget_for("variant"), QComboBox)
    assert isinstance(form.widget_for("parts"), QListWidget)
    assert isinstance(form.widget_for("video").findChild(QLineEdit), QLineEdit)


def test_a_required_option_is_marked_and_explains_itself(form) -> None:
    assert form.label_for("fps") == "Frame rate *"
    assert form.label_for("keypoint") == "Keypoint"
    assert form.widget_for("fps").toolTip() == "Frames per second of the video."


def test_nothing_is_set_until_the_user_or_the_files_set_it(form) -> None:
    assert form.values() == {"smooth": False, "variant": "raw"}  # only declared defaults show


def test_a_required_number_starts_unset_and_says_so(form) -> None:
    assert form.widget_for("fps").specialValueText() == "required"
    assert form.values().get("fps") is None


def test_typing_a_number_sets_it_and_announces_it(qtbot, form) -> None:
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("fps").setValue(25.0)
    assert blocker.args == ["fps", 25.0]
    assert form.values()["fps"] == 25.0


def test_an_int_option_gives_an_int(qtbot, form) -> None:
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("width_px").setValue(1920)
    assert blocker.args == ["width_px", 1920]
    assert isinstance(form.values()["width_px"], int)


def test_putting_a_number_back_to_unset_announces_none(qtbot, form) -> None:
    form.widget_for("fps").setValue(25.0)
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("fps").setValue(form.widget_for("fps").minimum())
    assert blocker.args == ["fps", None]
    assert "fps" not in form.values()


def test_text_sets_and_clears(qtbot, form) -> None:
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("keypoint").setText("snout")
    assert blocker.args == ["keypoint", "snout"]
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("keypoint").clear()
    assert blocker.args == ["keypoint", None]


def test_a_checkbox_announces_true_and_false(qtbot, form) -> None:
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("smooth").setChecked(True)
    assert blocker.args == ["smooth", True]
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        form.widget_for("smooth").setChecked(False)
    assert blocker.args == ["smooth", False]


def test_a_choice_with_a_default_shows_it_and_announces_a_change(qtbot, form) -> None:
    combo = form.widget_for("variant")
    assert combo.currentText() == "raw"
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        combo.setCurrentText("filtered")
    assert blocker.args == ["variant", "filtered"]


def test_a_required_choice_starts_on_a_prompt_that_means_unset(qtbot, form) -> None:
    combo = form.widget_for("engine")
    assert combo.currentIndex() == 0 and combo.currentText() == "(choose…)"
    assert "engine" not in form.values()
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        combo.setCurrentText("b")
    assert blocker.args == ["engine", "b"]
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        combo.setCurrentIndex(0)
    assert blocker.args == ["engine", None]


def test_a_multichoice_announces_what_is_ticked(qtbot, form) -> None:
    parts = form.widget_for("parts")
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        parts.item(0).setCheckState(parts.item(0).checkState().__class__.Checked)
    assert blocker.args == ["parts", ["x"]]
    parts.item(2).setCheckState(parts.item(2).checkState().__class__.Checked)
    assert form.values()["parts"] == ["x", "z"]


def test_a_path_is_typed_or_browsed_and_announced_as_text(qtbot, form) -> None:
    edit = form.widget_for("video").findChild(QLineEdit)
    with qtbot.waitSignal(form.valueChanged, timeout=500) as blocker:
        edit.setText("clips/a.mp4")
    assert blocker.args == ["video", "clips/a.mp4"]


def test_values_set_from_outside_are_shown_without_being_announced(qtbot, form) -> None:
    heard: list[tuple[str, object]] = []
    form.valueChanged.connect(lambda name, value: heard.append((name, value)))
    form.set_values({"fps": 30.0, "keypoint": "nose", "variant": "filtered"})
    assert form.widget_for("fps").value() == 30.0
    assert form.widget_for("keypoint").text() == "nose"
    assert form.widget_for("variant").currentText() == "filtered"
    assert heard == []


def test_values_set_from_outside_replace_everything_including_what_was_typed(form) -> None:
    form.widget_for("fps").setValue(25.0)
    form.set_values({"width_px": 100})
    assert "fps" not in form.values()
    assert form.values()["width_px"] == 100


def test_where_a_value_came_from_is_written_next_to_it(form) -> None:
    form.set_values({"fps": 30.0}, {"fps": "file"})
    assert form.note_for("fps") == "from the file"
    assert form.note_for("width_px") == "required"
    form.widget_for("fps").setValue(25.0)
    assert form.note_for("fps") == "you typed this"
    form.set_values({"fps": 30.0}, {"fps": "video"})
    assert form.note_for("fps") == "from the video"
    assert form.note_for("keypoint") == ""


def test_a_form_for_a_reader_with_no_options_is_empty(qtbot) -> None:
    f = ReaderOptionsForm([])
    qtbot.addWidget(f)
    assert f.values() == {}
    assert f.is_empty


def test_a_value_the_choices_do_not_contain_is_still_shown_not_replaced(form) -> None:
    form.set_values({"variant": "weird"})
    assert form.widget_for("variant").currentText() == "weird"
