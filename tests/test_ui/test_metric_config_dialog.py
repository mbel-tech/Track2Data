"""
Tests for ui/dialogs/metric_config_dialog.py -- the per-metric ⚙
parameter dialog. Renders one row per MetricParameter, driven by its
`kind`; derived parameters render read-only; Save/Cancel via the
standard QDialog accept/reject.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QSpinBox

from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter


class _NoParamsMetric(Metric):
    id = "X-0"
    name = "no_params"
    label = "No Params"
    level = "individual"
    priority = "primary"
    requires_identity = False
    output_columns: list[str] = []
    documentation = MetricDocumentation(
        definition="d", formula_plain="f", inputs=[], assumptions=[], warnings=[],
    )

    def compute(self, session, cfg=None):
        return None


class _ConfigurableMetric(Metric):
    id = "X-1"
    name = "configurable"
    label = "Configurable Metric"
    level = "individual"
    priority = "primary"
    requires_identity = False
    output_columns: list[str] = []
    documentation = MetricDocumentation(
        definition="d", formula_plain="f", inputs=[], assumptions=[], warnings=[],
    )
    parameters = [
        MetricParameter(
            name="threshold_px_s", label="Threshold", kind="float",
            default=1.5, minimum=0.0, maximum=100.0, unit="px/s",
            help="Speed above which an animal counts as active.",
        ),
        MetricParameter(
            name="min_bout_frames", label="Minimum bout length", kind="int",
            default=5, minimum=1, unit="frames",
        ),
        MetricParameter(
            name="cohesion_source", label="Cohesion source", kind="choice",
            default="nnd", choices=["nnd", "iid"],
        ),
        MetricParameter(
            name="use_smoothing", label="Use smoothing", kind="bool", default=True,
        ),
        MetricParameter(
            name="centre", label="Arena centre", kind="float", derived=True,
        ),
    ]

    def compute(self, session, cfg=None):
        return None


class _OptionalFloatParamMetric(Metric):
    """A metric whose float parameter has no declared default -- e.g.
    IL-4/IL-7's `threshold_px_s`: if the user never sets it, the
    metric auto-computes one from the session's own data at run time.
    `default=None` here means "omit the key, let the engine decide",
    NOT "the default value is 0" -- the two are very different
    thresholds and must never be conflated."""

    id = "X-2"
    name = "optional_param"
    label = "Optional Param Metric"
    level = "individual"
    priority = "primary"
    requires_identity = False
    output_columns: list[str] = []
    documentation = MetricDocumentation(
        definition="d", formula_plain="f", inputs=[], assumptions=[], warnings=[],
    )
    parameters = [
        MetricParameter(
            name="threshold_px_s", label="Activity threshold", kind="float",
            unit="px/s", help="Auto-computed when unset.",
        ),
    ]

    def compute(self, session, cfg=None):
        return None


def test_dialog_has_no_editable_rows_for_a_metric_with_no_parameters(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_NoParamsMetric, {})
    qtbot.addWidget(dlg)

    assert dlg.findChildren(QDoubleSpinBox) == []
    assert dlg.findChildren(QSpinBox) == []
    assert dlg.findChildren(QComboBox) == []
    assert dlg.findChildren(QCheckBox) == []


def test_dialog_title_shows_the_label_not_the_id(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    assert "Configurable Metric" in dlg.windowTitle()
    assert _ConfigurableMetric.id not in dlg.windowTitle()


def test_float_parameter_gets_a_double_spin_box(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    widget = dlg._widgets["threshold_px_s"]
    assert isinstance(widget, QDoubleSpinBox)
    assert widget.value() == pytest.approx(1.5)  # default, no current value supplied


def test_int_parameter_gets_a_spin_box(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    widget = dlg._widgets["min_bout_frames"]
    assert isinstance(widget, QSpinBox)
    assert widget.value() == 5


def test_choice_parameter_gets_a_combo_box_with_the_declared_choices(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    widget = dlg._widgets["cohesion_source"]
    assert isinstance(widget, QComboBox)
    items = [widget.itemText(i) for i in range(widget.count())]
    assert items == ["nnd", "iid"]
    assert widget.currentText() == "nnd"


def test_bool_parameter_gets_a_checkbox(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    widget = dlg._widgets["use_smoothing"]
    assert isinstance(widget, QCheckBox)
    assert widget.isChecked() is True


def test_current_values_override_defaults(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {"threshold_px_s": 9.0, "min_bout_frames": 12})
    qtbot.addWidget(dlg)

    assert dlg._widgets["threshold_px_s"].value() == pytest.approx(9.0)
    assert dlg._widgets["min_bout_frames"].value() == 12


def test_derived_parameter_renders_read_only_and_is_not_in_widgets(qtbot) -> None:
    """derived=True parameters (e.g. IL-3's arena centre) can never be
    user-set -- the dialog must show them as an informational label,
    not an editable widget, and values() must never include them."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    assert "centre" not in dlg._widgets
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any("derived" in text.lower() for text in labels)


def test_values_returns_only_non_derived_parameters(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    values = dlg.values()

    assert values == {
        "threshold_px_s": 1.5,
        "min_bout_frames": 5,
        "cohesion_source": "nnd",
        "use_smoothing": True,
    }


def test_values_reflects_edited_widgets(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {})
    qtbot.addWidget(dlg)

    dlg._widgets["threshold_px_s"].setValue(42.0)
    dlg._widgets["min_bout_frames"].setValue(9)
    dlg._widgets["cohesion_source"].setCurrentText("iid")
    dlg._widgets["use_smoothing"].setChecked(False)

    values = dlg.values()

    assert values["threshold_px_s"] == pytest.approx(42.0)
    assert values["min_bout_frames"] == 9
    assert values["cohesion_source"] == "iid"
    assert values["use_smoothing"] is False


def test_reset_button_restores_the_default_for_its_row(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {"threshold_px_s": 42.0})
    qtbot.addWidget(dlg)
    assert dlg._widgets["threshold_px_s"].value() == pytest.approx(42.0)

    dlg._reset_buttons["threshold_px_s"].click()

    assert dlg._widgets["threshold_px_s"].value() == pytest.approx(1.5)  # back to default


def test_reset_button_does_not_affect_other_rows(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(
        _ConfigurableMetric, {"threshold_px_s": 42.0, "min_bout_frames": 99}
    )
    qtbot.addWidget(dlg)

    dlg._reset_buttons["threshold_px_s"].click()

    assert dlg._widgets["min_bout_frames"].value() == 99  # untouched


# ── optional (default=None, "auto-computed when unset") parameters ────────────


def test_optional_float_parameter_is_omitted_from_values_when_left_untouched(qtbot) -> None:
    """0.0 is a real, very different threshold from 'let the engine
    auto-compute one' -- must not silently coerce None to 0.0."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_OptionalFloatParamMetric, {})
    qtbot.addWidget(dlg)

    assert dlg.values() == {}


def test_setting_an_optional_float_parameter_includes_it_in_values(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_OptionalFloatParamMetric, {})
    qtbot.addWidget(dlg)

    dlg._widgets["threshold_px_s"].setValue(3.5)

    assert dlg.values() == {"threshold_px_s": pytest.approx(3.5)}


def test_current_saved_value_for_an_optional_parameter_is_shown(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_OptionalFloatParamMetric, {"threshold_px_s": 7.0})
    qtbot.addWidget(dlg)

    assert dlg.values() == {"threshold_px_s": pytest.approx(7.0)}


def test_untouched_value_below_widget_precision_is_preserved(qtbot) -> None:
    """Regression: values() returned widget.value() for every param,
    touched or not, so the spin box's 6-decimal rounding became a silent
    write-back. Opening ⚙ on a metric whose manifest carries a very
    small threshold and clicking Save with no edits rewrote it to 0.0 --
    a materially different exclusion rule the user never chose."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {"threshold_px_s": 1e-9})
    qtbot.addWidget(dlg)

    assert dlg.values()["threshold_px_s"] == pytest.approx(1e-9)


def test_untouched_value_above_widget_range_is_preserved(qtbot) -> None:
    """Same defect via clamping rather than rounding: a saved value
    above the widget's inferred maximum was silently clamped down."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_OptionalFloatParamMetric, {"threshold_px_s": 5e9})
    qtbot.addWidget(dlg)

    assert dlg.values()["threshold_px_s"] == pytest.approx(5e9)


def test_editing_a_value_still_returns_the_edited_value(qtbot) -> None:
    """The preservation must not shadow a real edit."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {"threshold_px_s": 1e-9})
    qtbot.addWidget(dlg)

    dlg._widgets["threshold_px_s"].setValue(2.5)

    assert dlg.values()["threshold_px_s"] == pytest.approx(2.5)


def test_reset_overrides_a_preserved_value(qtbot) -> None:
    """↺ is an explicit user action: it must win over preservation."""
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_ConfigurableMetric, {"threshold_px_s": 1e-9})
    qtbot.addWidget(dlg)

    dlg._reset_buttons["threshold_px_s"].click()

    assert dlg.values()["threshold_px_s"] == pytest.approx(1.5)  # the declared default


def test_reset_returns_an_optional_parameter_to_auto(qtbot) -> None:
    from ui.dialogs.metric_config_dialog import MetricConfigDialog

    dlg = MetricConfigDialog(_OptionalFloatParamMetric, {"threshold_px_s": 7.0})
    qtbot.addWidget(dlg)

    dlg._reset_buttons["threshold_px_s"].click()

    assert dlg.values() == {}
