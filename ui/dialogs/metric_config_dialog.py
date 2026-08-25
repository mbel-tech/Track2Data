"""
Metric config dialog -- an editable ``QDialog`` that renders one
widget per entry in a ``Metric`` subclass's ``parameters:
list[MetricParameter]`` schema, the control driven by
``MetricParameter.kind`` (``"float"|"int"|"choice"|"bool"``). A
``derived=True`` parameter (e.g. IL-3's arena centre, Z-2's zone
areas) is computed per session and can never be user-set, so it
renders as a read-only informational label instead of a control. See
``docs/METRICS_SPEC.md`` §8 open question 3 and ``UI_DESIGN.md``
Screen 6.3 (the per-row ↺ reset-to-default control).

Mirrors ``MetricInfoDialog``'s modal shape and outside-click-to-close
event filter (same pattern, reused rather than reinvented). Unlike
the info dialog this one is editable: "Save" accepts the dialog so the
caller can read back ``values()``; "Cancel" (or an outside click, or
Escape) rejects it and discards the edits.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from track2data.metrics.base import Metric, MetricParameter


class MetricConfigDialog(QDialog):
    """Editable popup for one metric's ``parameters`` schema."""

    def __init__(
        self,
        metric_cls: type[Metric],
        current_values: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._metric_cls = metric_cls
        self._widgets: dict[str, QWidget] = {}
        self._reset_buttons: dict[str, QPushButton] = {}
        # For a numeric parameter with no declared default (e.g. IL-4/IL-7's
        # threshold_px_s: "auto-computed from data when unset") the spin
        # box's own minimum doubles as an "unset" sentinel -- see
        # _build_editable_widget. Tracked here so values()/_reset_to_default
        # can tell "left on auto" apart from "user typed this exact number".
        self._auto_sentinel: dict[str, float] = {}
        # A spin box rounds to its decimals and clamps to its range, so
        # reading a widget back is lossy for a saved value finer or larger
        # than the widget can represent. Keep the originals, and track
        # which rows the user actually edited, so an untouched row round-
        # trips its stored value verbatim instead of being silently
        # rewritten by merely opening the dialog and pressing Save.
        self._initial_values: dict[str, Any] = dict(current_values)
        self._edited: set[str] = set()

        self.setWindowTitle(f"Configure — {metric_cls.label}")
        self.resize(440, 360)
        self.setModal(True)

        layout = QVBoxLayout(self)

        header = QLabel(metric_cls.label)
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()
        for param in metric_cls.parameters:
            value = current_values.get(param.name, param.default)
            form.addRow(f"{param.label}:", self._build_field(param, value))
        layout.addLayout(form)
        layout.addStretch()

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.clicked.connect(self.accept)
        footer.addWidget(save_btn)
        layout.addLayout(footer)

    def _build_field(self, param: MetricParameter, value: Any) -> QWidget:
        """One form row's field widget: a read-only informational
        label for a derived parameter, else the editable control for
        ``param.kind`` paired with a ↺ reset-to-default button."""
        if param.derived:
            shown = "(derived from this session's zones)" if value is None else str(value)
            info = QLabel(shown)
            info.setEnabled(False)
            info.setToolTip(
                param.help or "Computed automatically for each session; not user-settable."
            )
            return info

        widget = self._build_editable_widget(param, value)
        self._widgets[param.name] = widget
        # Connect AFTER _build_editable_widget has set the initial value,
        # so populating the form doesn't mark every row as user-edited.
        self._connect_edited_signal(param, widget)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(widget)

        reset_btn = QPushButton("↺")
        reset_btn.setFixedWidth(28)
        default_label = "auto" if param.default is None else str(param.default)
        reset_btn.setToolTip(f"Reset to default ({default_label})")
        reset_btn.clicked.connect(partial(self._reset_to_default, param))
        row_layout.addWidget(reset_btn)
        self._reset_buttons[param.name] = reset_btn

        return row

    def _connect_edited_signal(self, param: MetricParameter, widget: QWidget) -> None:
        """Mark a row edited the first time its widget changes."""
        mark = partial(self._mark_edited, param.name)
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            widget.valueChanged.connect(mark)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(mark)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(mark)

    def _mark_edited(self, name: str, *_args) -> None:
        self._edited.add(name)

    def _build_editable_widget(self, param: MetricParameter, value: Any) -> QWidget:
        widget: QWidget
        if param.kind == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            upper = param.maximum if param.maximum is not None else 1e9
            if param.default is None:
                # No declared default -- e.g. IL-4/IL-7's threshold_px_s,
                # "auto-computed from data when unset". 0.0 would be a
                # real, very different threshold, so it must never be the
                # shown/returned value for "the user hasn't set this".
                # Qt's special-value text only shows when the current
                # value equals the spin box's minimum exactly, so the
                # sentinel below IS that minimum -- not just a value
                # somewhere inside a wider range.
                sentinel = (param.minimum if param.minimum is not None else 0.0) - 1
                self._auto_sentinel[param.name] = sentinel
                spin.setRange(sentinel, upper)
                spin.setSpecialValueText("Auto (data-driven)")
                spin.setValue(float(value) if value is not None else sentinel)
            else:
                spin.setRange(param.minimum if param.minimum is not None else -1e9, upper)
                spin.setValue(float(value) if value is not None else 0.0)
            if param.unit:
                spin.setSuffix(f" {param.unit}")
            widget = spin
        elif param.kind == "int":
            int_spin = QSpinBox()
            upper_i = int(param.maximum) if param.maximum is not None else 1_000_000
            if param.default is None:
                sentinel_i = int(param.minimum if param.minimum is not None else 0) - 1
                self._auto_sentinel[param.name] = sentinel_i
                int_spin.setRange(sentinel_i, upper_i)
                int_spin.setSpecialValueText("Auto (data-driven)")
                int_spin.setValue(int(value) if value is not None else sentinel_i)
            else:
                int_spin.setRange(
                    int(param.minimum) if param.minimum is not None else -1_000_000, upper_i
                )
                int_spin.setValue(int(value) if value is not None else 0)
            if param.unit:
                int_spin.setSuffix(f" {param.unit}")
            widget = int_spin
        elif param.kind == "choice":
            combo = QComboBox()
            combo.addItems(param.choices or [])
            if value is not None:
                combo.setCurrentText(str(value))
            widget = combo
        elif param.kind == "bool":
            check = QCheckBox()
            check.setChecked(bool(value))
            widget = check
        else:
            raise ValueError(f"Unknown MetricParameter.kind: {param.kind!r}")

        if param.help:
            widget.setToolTip(param.help)
        return widget

    def _reset_to_default(self, param: MetricParameter) -> None:
        # ↺ is an explicit user action, so it counts as an edit even when
        # the resulting widget value happens to match what was loaded --
        # otherwise values() would keep returning the preserved original.
        self._edited.add(param.name)
        widget = self._widgets[param.name]
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            if param.default is None:
                widget.setValue(self._auto_sentinel[param.name])
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(param.default))
            else:
                widget.setValue(int(param.default))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(param.default))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(param.default))

    def values(self) -> dict[str, Any]:
        """Return the edited, non-derived parameter values -- what the
        caller should persist into ``MetricSelection.config[metric_id]``.
        Derived parameters are never included: they are recomputed per
        session and must never be frozen into a saved override.

        A row the user did not touch returns its stored value verbatim
        rather than a widget read-back, so merely opening the dialog and
        pressing Save cannot round or clamp a value the widget is too
        coarse or too narrow to represent."""
        result: dict[str, Any] = {}
        for param in self._metric_cls.parameters:
            if param.derived:
                continue
            if param.name not in self._edited and param.name in self._initial_values:
                result[param.name] = self._initial_values[param.name]
                continue
            widget = self._widgets[param.name]
            if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                sentinel = self._auto_sentinel.get(param.name)
                if sentinel is not None and widget.value() == sentinel:
                    continue  # left on "auto" -- omit so the engine computes its own value
                result[param.name] = widget.value()
            elif isinstance(widget, QComboBox):
                result[param.name] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                result[param.name] = widget.isChecked()
        return result

    def showEvent(self, event) -> None:
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local_pos):
                self.reject()
                return True
        return super().eventFilter(watched, event)
