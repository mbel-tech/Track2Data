"""Fusion editor: line a side view up with its top view and set the water column.

The spin boxes (surface row, floor row, tank height, offset) are the single source of truth for
``result_settings()``; the water view only mirrors the two rows and reports user drags. The
summary is recomputed on every edit by fusing the pair with the current settings. OK is enabled
only while the settings are valid and the pair fuses.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import FusionSettings, PanelRect, PreprocessedSession, ViewPair
from track2data.fusion import FusionError, fuse
from track2data.fusion.agreement import suggest_offset
from ui.widgets.water_column_view import WaterColumnView
from ui.widgets.weak_slot import weak_slot

_AXES = ("Top-view x", "Top-view y")
_MAX_ROW = 1_000_000.0
_FALLBACK_SIZE = 100.0
_DEFAULT_TANK_CM = 20.0
#: Pause after the last edit before the summary is recomputed (a long fuse takes ~140 ms).
_REFRESH_MS = 80
SUGGEST_NEEDS_CALIBRATION = (
    "Suggest offset needs a calibrated top view (set the scale on the Calibration page)"
)


class FusionDialog(QDialog):
    def __init__(
        self,
        top: PreprocessedSession,
        side: PreprocessedSession,
        pair: ViewPair,
        same_video: bool,
        background_path: Path | None = None,
        parent: QWidget | None = None,
        background_crop: PanelRect | None = None,
    ) -> None:
        super().__init__(parent)
        self._top, self._side, self._pair = top, side, pair
        self._same_video = same_video
        self.setWindowTitle("Fusion")
        self.setModal(True)
        self.resize(760, 700)

        video = side.session.video
        width = float(video.width_px or 0)
        height = float(video.height_px or 0)
        frame_size = (
            width if width > 0 else _FALLBACK_SIZE,
            height if height > 0 else _FALLBACK_SIZE,
        )

        layout = QVBoxLayout(self)
        self._water_view = WaterColumnView()
        self._water_view.setMinimumHeight(260)
        layout.addWidget(self._water_view, 1)

        max_row = frame_size[1] if height > 0 else _MAX_ROW
        self._surface_spin = self._row_spin(1, max_row)
        self._floor_spin = self._row_spin(1, max_row)
        self._height_spin = QDoubleSpinBox()
        self._height_spin.setDecimals(2)
        self._height_spin.setRange(0.0, 10_000.0)
        self._height_spin.setSuffix(" cm")
        self._axis_combo = QComboBox()
        self._axis_combo.addItems(list(_AXES))
        self._flip_check = QCheckBox("Flip")
        self._inverted_check = QCheckBox(
            "The side view is upside down (the surface is the lower line)"
        )
        self._upper_label = QLabel("Water surface row")
        self._lower_label = QLabel("Tank floor row")
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(-1_000_000, 1_000_000)
        self._offset_spin.setSuffix(" frames")
        self._suggest_btn = QPushButton("Suggest offset")
        self._can_suggest = top.px_per_cm is not None
        if not self._can_suggest:
            self._suggest_btn.setEnabled(False)
            self._suggest_btn.setToolTip(SUGGEST_NEEDS_CALIBRATION)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(weak_slot(self._refresh_now))

        form = QFormLayout()
        form.addRow(self._upper_label, self._surface_spin)
        form.addRow(self._lower_label, self._floor_spin)
        form.addRow(self._inverted_check)
        form.addRow("Tank height", self._height_spin)
        axis_row = QHBoxLayout()
        axis_row.addWidget(self._axis_combo)
        axis_row.addWidget(self._flip_check)
        axis_row.addStretch(1)
        form.addRow("Shared horizontal axis", axis_row)
        self._axis_help = QLabel(
            "Used to check that the two views agree; does not change the fused positions."
        )
        self._axis_help.setProperty("role", "muted")
        self._axis_help.setWordWrap(True)
        form.addRow("", self._axis_help)
        offset_row = QHBoxLayout()
        offset_row.addWidget(self._offset_spin)
        offset_row.addWidget(self._suggest_btn)
        offset_row.addStretch(1)
        self._offset_label = QLabel("Frame offset (side = top + offset)")
        form.addRow(self._offset_label, offset_row)
        layout.addLayout(form)
        if same_video:
            self._offset_label.hide()
            self._offset_spin.hide()
            self._suggest_btn.hide()

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button: QPushButton = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Backdrop once per open; later edits only move the lines.
        self._water_view.set_source(
            frame_size, background_path, video.path, side.xy, background_crop
        )

        start = pair.fusion
        inverted = False
        if start is None:
            upper, lower = 0.1 * frame_size[1], 0.9 * frame_size[1]
        else:
            # the lines are always drawn upper-then-lower; an upside-down view has the surface
            # as its lower line
            inverted = start.surface_row > start.floor_row
            upper, lower = sorted((start.surface_row, start.floor_row))
        self._fill_spin(self._surface_spin, upper)
        self._fill_spin(self._floor_spin, lower)
        was = self._inverted_check.blockSignals(True)
        self._inverted_check.setChecked(inverted)
        self._inverted_check.blockSignals(was)
        self._apply_inverted()
        self._fill_spin(self._height_spin, start.tank_height_cm if start else _DEFAULT_TANK_CM)
        was = self._axis_combo.blockSignals(True)
        self._axis_combo.setCurrentIndex(1 if start and start.horizontal_axis == "y" else 0)
        self._axis_combo.blockSignals(was)
        was = self._flip_check.blockSignals(True)
        self._flip_check.setChecked(bool(start and start.flip))
        self._flip_check.blockSignals(was)
        self._fill_spin(self._offset_spin, 0 if same_video or not start else start.frame_offset)
        self._water_view.set_rows(self._surface_spin.value(), self._floor_spin.value())

        for spin in (self._surface_spin, self._floor_spin, self._height_spin, self._offset_spin):
            spin.valueChanged.connect(weak_slot(self._on_edit))
        self._axis_combo.currentIndexChanged.connect(weak_slot(self._on_edit))
        self._flip_check.toggled.connect(weak_slot(self._on_edit))
        self._inverted_check.toggled.connect(weak_slot(self._on_inverted))
        self._water_view.rowsChanged.connect(weak_slot(self._on_rows_dragged, pass_args=True))
        self._suggest_btn.clicked.connect(weak_slot(self._on_suggest))
        self._refresh_now()

    # ---- helpers --------------------------------------------------------------

    def _apply_inverted(self) -> None:
        """Name the two lines for the camera's orientation (the picture is drawn upright)."""
        inverted = self._inverted_check.isChecked()
        self._upper_label.setText(
            "Tank floor row (upper line)" if inverted else "Water surface row"
        )
        self._lower_label.setText(
            "Water surface row (lower line)" if inverted else "Tank floor row"
        )
        self._water_view.set_inverted(inverted)

    def _on_inverted(self) -> None:
        self._apply_inverted()
        self._on_edit()

    @staticmethod
    def _row_spin(decimals: int, maximum: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(decimals)
        box.setRange(0.0, maximum)
        return box

    @staticmethod
    def _fill_spin(box: QSpinBox | QDoubleSpinBox, value: float) -> None:
        was = box.blockSignals(True)
        box.setValue(value)  # type: ignore[arg-type]
        box.blockSignals(was)

    def _current(self) -> tuple[FusionSettings | None, str]:
        """The settings shown, or ``(None, reason)`` when they are not valid."""
        if self._height_spin.value() <= 0:
            return None, "The tank height must be above 0 cm."
        inverted = self._inverted_check.isChecked()
        try:
            fs = FusionSettings(
                frame_offset=0 if self._same_video else self._offset_spin.value(),
                horizontal_axis="y" if self._axis_combo.currentIndex() == 1 else "x",
                flip=self._flip_check.isChecked(),
                # the spin boxes hold the upper and the lower line; upside down, the lower is the
                # surface
                surface_row=(
                    self._floor_spin.value() if inverted else self._surface_spin.value()
                ),
                floor_row=self._surface_spin.value() if inverted else self._floor_spin.value(),
                tank_height_cm=self._height_spin.value(),
            )
        except ValueError:
            return None, "The water surface and the tank floor must be on different rows."
        return fs, ""

    def result_settings(self) -> FusionSettings:
        fs, reason = self._current()
        if fs is None:
            raise ValueError(reason)
        return fs

    def _fuse_pair(self, fs: FusionSettings):
        pair = self._pair.model_copy(update={"fusion": fs})
        return pair, fuse(self._top, self._side, pair, same_video=self._same_video)

    # ---- events ---------------------------------------------------------------

    def accept(self) -> None:
        if self._timer.isActive():
            self._refresh_now()  # never accept on a stale summary
        if self._ok_button.isEnabled():
            super().accept()

    def _on_edit(self) -> None:
        self._water_view.set_rows(self._surface_spin.value(), self._floor_spin.value())
        self._timer.start()

    def _on_rows_dragged(self, surface: float, floor: float) -> None:
        self._fill_spin(self._surface_spin, surface)
        self._fill_spin(self._floor_spin, floor)
        self._timer.start()

    def _on_suggest(self) -> None:
        if not self._can_suggest:
            return
        self._refresh_now()
        fs, _ = self._current()
        if fs is None:
            return
        try:
            pair, _ = self._fuse_pair(fs)
        except FusionError:
            return  # the summary already shows the error
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            best = suggest_offset(self._top, self._side, pair)
        finally:
            QApplication.restoreOverrideCursor()
        if best is None:
            note = "Result: no better offset found."
        elif best == fs.frame_offset:
            note = "Result: offset already best."
        else:
            self._fill_spin(self._offset_spin, best)
            note = f"Offset set to {best} frames."
        self._refresh_now(note)

    # ---- summary --------------------------------------------------------------

    def _refresh_now(self, note: str = "") -> None:
        """Recompute the summary and the OK state now (edits go through the debounce timer)."""
        self._timer.stop()
        fs, reason = self._current()
        if fs is None:
            self._set_summary(reason, ok=False)
            return
        try:
            _, fused = self._fuse_pair(fs)
        except FusionError as err:
            self._set_summary(str(err), ok=False)
            return
        except Exception as err:  # never raise from a UI recompute
            self._set_summary(f"Cannot fuse: {err}", ok=False)
            return
        rep = fused.report
        lines = [
            f"Overlap: {rep.overlap_frames} frames",
            f"Fused: {len(rep.fused_labels)} fish",
            f"Positions outside the water column: {rep.n_outside_column}",
        ]
        if rep.agreement_skipped:
            lines.append(f"Agreement not checked: {rep.agreement_skipped}")
        elif rep.agreement_rms_cm is not None:
            lines.append(f"Agreement RMS: {rep.agreement_rms_cm:.2f} cm")
        if rep.agreement_warning:
            lines.append(
                "Warning: the two views disagree on the shared axis; check the offset, "
                "the axis and the flip."
            )
        if not self._can_suggest and not self._same_video:
            lines.append(SUGGEST_NEEDS_CALIBRATION)
        if note:
            lines.append(note)
        self._set_summary("\n".join(lines), ok=True)

    def _set_summary(self, text: str, *, ok: bool) -> None:
        self._summary.setText(text)
        self._ok_button.setEnabled(ok)
