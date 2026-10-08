"""The options a reader needs to be told, as a form.

Most trackers record neither the frame rate nor the frame size, and several need a choice (which
keypoint stands for the animal). A reader declares these as ``ReaderParameter``s; this widget shows
one control per option, chosen by the parameter's kind, and says where each value came from (the
file, the video, or the user).

It decides nothing about validity: whether a value is acceptable is the reader's own rule, applied
by ``ConfirmDraft``. This only turns a control into a value, or into "not set" (``None``): a
number box sits on a reserved lowest value that reads "required", a choice on a prompt row, so an
option the files do not record can never look as though it had been answered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QWidget,
)

from track2data.readers.params import ReaderParameter

_FLOAT_LOW, _FLOAT_HIGH = -1e9, 1e9
_INT_LOW, _INT_HIGH = -2_000_000_000, 2_000_000_000
_NOTES = {
    "file": "from the file",
    "video": "from the video",
    "tool-default": "the tool's default",
    "user": "you typed this",
    "required": "required",
}


class ReaderOptionsForm(QWidget):
    """One control per declared option; ``valueChanged(name, value)`` when the user edits one."""

    #: (option name, new value); the value is None when the user put the control back to "not set".
    valueChanged = Signal(str, object)

    def __init__(self, parameters: Sequence[ReaderParameter], parent: QWidget | None = None):
        super().__init__(parent)
        self._specs = {p.name: p for p in parameters}
        self._controls: dict[str, QWidget] = {}
        self._labels: dict[str, QLabel] = {}
        self._notes: dict[str, QLabel] = {}
        self._sentinels: dict[str, float | int] = {}
        self._sources: dict[str, str] = {}
        self._typed: set[str] = set()
        self._silent = False
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for spec in parameters:
            label = QLabel(f"{spec.label} *" if spec.required else spec.label)
            note = QLabel("")
            note.setStyleSheet(" font-size: 11px;")
            control = self._build_control(spec)
            if spec.help:
                control.setToolTip(spec.help)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(control, 1)
            row_layout.addWidget(note)
            layout.addRow(label, row)
            self._controls[spec.name] = control
            self._labels[spec.name] = label
            self._notes[spec.name] = note
        self._refresh_notes()

    # ── reading and writing ────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        return not self._specs

    def widget_for(self, name: str) -> Any:
        return self._controls[name]

    def label_for(self, name: str) -> str:
        return self._labels[name].text()

    def note_for(self, name: str) -> str:
        return self._notes[name].text()

    def values(self) -> dict[str, Any]:
        """What the controls hold now; an option that is "not set" is left out."""
        values: dict[str, Any] = {}
        for name in self._specs:
            value = self._read(name)
            if value is not None:
                values[name] = value
        return values

    def set_values(
        self, values: Mapping[str, Any], sources: Mapping[str, str] | None = None
    ) -> None:
        """Show *values* (anything absent goes back to "not set"), without announcing them."""
        self._silent = True
        try:
            for name, spec in self._specs.items():
                self._write(name, spec, values.get(name))
        finally:
            self._silent = False
        self._sources = dict(sources or {})
        self._typed.clear()
        self._refresh_notes()

    # ── building ───────────────────────────────────────────────────────────

    def _build_control(self, spec: ReaderParameter) -> QWidget:
        name, kind = spec.name, spec.kind
        if kind == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            low = (spec.minimum - 1) if spec.minimum is not None else _FLOAT_LOW
            spin.setRange(low, spec.maximum if spec.maximum is not None else _FLOAT_HIGH)
            spin.setSpecialValueText("required" if spec.required else "not set")
            self._sentinels[name] = low
            spin.setValue(float(spec.default) if spec.default is not None else low)
            spin.valueChanged.connect(lambda v, n=name: self._edited(n, self._read(n)))
            return spin
        if kind == "int":
            int_spin = QSpinBox()
            low_i = int(spec.minimum) - 1 if spec.minimum is not None else _INT_LOW
            int_spin.setRange(low_i, int(spec.maximum) if spec.maximum is not None else _INT_HIGH)
            int_spin.setSpecialValueText("required" if spec.required else "not set")
            self._sentinels[name] = low_i
            int_spin.setValue(int(spec.default) if spec.default is not None else low_i)
            int_spin.valueChanged.connect(lambda v, n=name: self._edited(n, self._read(n)))
            return int_spin
        if kind == "bool":
            check = QCheckBox()
            check.setChecked(bool(spec.default))
            check.toggled.connect(lambda checked, n=name: self._edited(n, self._read(n)))
            return check
        if kind == "choice":
            combo = QComboBox()
            if spec.default is None:
                combo.addItem("(choose…)" if spec.required else "(not set)")
            combo.addItems(list(spec.choices))
            if spec.default is not None:
                combo.setCurrentText(str(spec.default))
            combo.currentIndexChanged.connect(lambda i, n=name: self._edited(n, self._read(n)))
            return combo
        if kind == "multichoice":
            listing = QListWidget()
            for choice in spec.choices:
                item = QListWidgetItem(choice)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                listing.addItem(item)
            listing.setMaximumHeight(min(110, 24 * max(1, len(spec.choices)) + 8))
            listing.itemChanged.connect(lambda item, n=name: self._edited(n, self._read(n)))
            return listing
        if kind == "path":
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit()
            edit.textChanged.connect(lambda text, n=name: self._edited(n, self._read(n)))
            browse = QPushButton("Browse…")
            browse.setProperty("role", "outline")
            browse.clicked.connect(lambda _checked=False, e=edit: self._browse(e))
            holder_layout.addWidget(edit, 1)
            holder_layout.addWidget(browse)
            return holder
        edit_text = QLineEdit()
        edit_text.setPlaceholderText("required" if spec.required else "optional")
        edit_text.textChanged.connect(lambda text, n=name: self._edited(n, self._read(n)))
        return edit_text

    def _browse(self, edit: QLineEdit) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self, "Choose a file")
        if chosen:
            edit.setText(chosen)

    # ── controls to values and back ─────────────────────────────────────────

    def _read(self, name: str) -> Any:
        spec, control = self._specs[name], self._controls[name]
        if isinstance(control, QDoubleSpinBox):
            value = control.value()
            return None if value == self._sentinels[name] else float(value)
        if isinstance(control, QSpinBox):
            int_value = control.value()
            return None if int_value == self._sentinels[name] else int(int_value)
        if isinstance(control, QCheckBox):
            return control.isChecked()
        if isinstance(control, QComboBox):
            if spec.default is None and control.currentIndex() == 0:
                return None
            return control.currentText()
        if isinstance(control, QListWidget):
            ticked = [
                control.item(i).text()
                for i in range(control.count())
                if control.item(i).checkState() == Qt.CheckState.Checked
            ]
            return ticked or None
        if spec.kind == "path":
            text = control.findChild(QLineEdit).text()
            return text or None
        text = control.text() if isinstance(control, QLineEdit) else ""
        return text or None

    def _write(self, name: str, spec: ReaderParameter, value: Any) -> None:
        control = self._controls[name]
        if isinstance(control, QDoubleSpinBox):
            fallback = float(spec.default) if spec.default is not None else self._sentinels[name]
            control.setValue(float(value) if value is not None else float(fallback))
        elif isinstance(control, QSpinBox):
            fallback_i = int(spec.default) if spec.default is not None else self._sentinels[name]
            control.setValue(int(value) if value is not None else int(fallback_i))
        elif isinstance(control, QCheckBox):
            control.setChecked(bool(value) if value is not None else bool(spec.default))
        elif isinstance(control, QComboBox):
            if value is None:
                index = 0 if spec.default is None else self._index_of(control, spec.default)
                control.setCurrentIndex(index)
            else:
                # A non-editable combo ignores an unknown value and stays on its first row,
                # showing something nobody chose. Offer the value instead.
                if control.findText(str(value)) < 0:
                    control.addItem(str(value))
                control.setCurrentText(str(value))
        elif isinstance(control, QListWidget):
            wanted = set(value or [])
            for i in range(control.count()):
                item = control.item(i)
                item.setCheckState(
                    Qt.CheckState.Checked if item.text() in wanted else Qt.CheckState.Unchecked
                )
        elif spec.kind == "path":
            control.findChild(QLineEdit).setText("" if value is None else str(value))
        elif isinstance(control, QLineEdit):
            control.setText("" if value is None else str(value))

    @staticmethod
    def _index_of(combo: QComboBox, text: Any) -> int:
        index = combo.findText(str(text))
        return max(index, 0)

    # ── announcing and annotating ───────────────────────────────────────────

    def _edited(self, name: str, value: Any) -> None:
        if self._silent:
            return
        self._typed.add(name)
        self._refresh_notes()
        self.valueChanged.emit(name, value)

    def _refresh_notes(self) -> None:
        for name, spec in self._specs.items():
            if name in self._typed:
                text = _NOTES["user"]
            elif name in self._sources and self._read(name) is not None:
                text = _NOTES.get(self._sources[name], "")
            elif spec.required and self._read(name) is None:
                text = _NOTES["required"]
            else:
                text = ""
            self._notes[name].setText(text)
