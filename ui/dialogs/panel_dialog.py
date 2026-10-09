"""Panel editor: cut one shared video into a top and a side panel, or set one panel.

The session passed in is the unpanelled one, so its raw positions and video size are in
whole-frame pixels. ``mode="split"`` edits two rectangles (presets, a split slider, exact
fields, a per-fish coverage table); ``mode="single"`` edits one rectangle labelled "Panel".
OK is enabled only while every rectangle is inside the frame and keeps at least one animal.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import PanelRect, Session
from track2data.views.panels import (
    LOW_COVERAGE,
    MIN_COVERAGE,
    AnimalCoverage,
    panel_coverage,
    preset_rects,
)
from ui.widgets.panel_preview import PanelPreview
from ui.widgets.weak_slot import weak_slot

_LEFT_RIGHT = "Left | Right"
_TOP_BOTTOM = "Top | Bottom"
_CUSTOM = "Custom"
_TOP_VIEW = "Top view"
_SIDE_VIEW = "Side view"
_DASH = "—"
_MAX_PX = 1_000_000.0
_FALLBACK_SIZE = 100.0


def _frame_size(session: Session) -> tuple[float, float]:
    """The whole-frame size; when the video size is unknown (0) the extent of the positions."""
    w, h = float(session.video.width_px), float(session.video.height_px)
    if w > 0 and h > 0:
        return w, h
    xy = np.asarray(session.raw_xy, dtype=float)
    finite = xy[np.isfinite(xy).all(axis=-1)] if xy.ndim == 3 else np.empty((0, 2))
    if finite.size:
        ex, ey = (
            math.ceil(float(finite[:, 0].max())) + 1.0,
            math.ceil(float(finite[:, 1].max())) + 1.0,
        )
    else:
        ex = ey = _FALLBACK_SIZE
    return (w if w > 0 else ex), (h if h > 0 else ey)


def _spin(minimum: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(minimum, _MAX_PX)
    return box


class PanelDialog(QDialog):
    def __init__(
        self,
        session: Session,
        mode: Literal["split", "single"],
        background_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._split = mode == "split"
        self._frame_w, self._frame_h = _frame_size(session)
        self._last_preset = "left_right"
        self.setWindowTitle("Panels" if self._split else "Set panel")
        self.setModal(True)
        self.resize(760, 640)

        layout = QVBoxLayout(self)

        self._preset_combo = QComboBox()
        self._preset_combo.addItems([_LEFT_RIGHT, _TOP_BOTTOM, _CUSTOM])
        self._split_slider = QSlider(Qt.Orientation.Horizontal)
        self._split_slider.setRange(5, 95)
        self._split_slider.setValue(50)
        self._first_view_combo = QComboBox()
        self._first_view_combo.addItems([_TOP_VIEW, _SIDE_VIEW])
        self._split_label = QLabel()

        self._top_x, self._top_y = _spin(0.0), _spin(0.0)
        self._top_w, self._top_h = _spin(0.01), _spin(0.01)
        self._side_x, self._side_y = _spin(0.0), _spin(0.0)
        self._side_w, self._side_h = _spin(0.01), _spin(0.01)

        if self._split:
            form = QFormLayout()
            form.addRow("Layout", self._preset_combo)
            slider_row = QHBoxLayout()
            slider_row.addWidget(self._split_slider, 1)
            slider_row.addWidget(self._split_label)
            form.addRow("Split", slider_row)
            form.addRow("Left / top panel is the", self._first_view_combo)
            layout.addLayout(form)
        layout.addLayout(self._rect_row("Top view" if self._split else "Panel", "_top"))
        if self._split:
            layout.addLayout(self._rect_row("Side view", "_side"))

        self._preview = PanelPreview()
        self._preview.setMinimumHeight(240)
        layout.addWidget(self._preview, 1)

        self._coverage_table = QTableWidget(0, 4)
        self._coverage_table.setHorizontalHeaderLabels(["Fish", "Panel", "Inside", "Flag"])
        self._coverage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._coverage_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._coverage_table.horizontalHeader().setStretchLastSection(True)
        self._coverage_table.setMaximumHeight(180)
        layout.addWidget(self._coverage_table)
        self._coverage_table.setVisible(self._split)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button: QPushButton = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Backdrop once; later edits only move the rectangles.
        self._preview.set_source(
            (self._frame_w, self._frame_h), background_path, session.video.path, session.raw_xy
        )

        if self._split:
            self._apply_preset()
        else:
            self._fill(
                [self._top_x, self._top_y, self._top_w, self._top_h],
                PanelRect(x=0, y=0, width=self._frame_w, height=self._frame_h),
            )
        self._connect()
        self._rebuild()

    # ---- construction helpers -------------------------------------------------

    def _rect_row(self, title: str, prefix: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        for name in ("x", "y", "w", "h"):
            row.addWidget(QLabel(name))
            row.addWidget(getattr(self, f"{prefix}_{name}"))
        row.addStretch(1)
        return row

    def _connect(self) -> None:
        spins = [self._top_x, self._top_y, self._top_w, self._top_h]
        if self._split:
            spins += [self._side_x, self._side_y, self._side_w, self._side_h]
            self._preset_combo.currentIndexChanged.connect(weak_slot(self._on_preset))
            self._split_slider.valueChanged.connect(weak_slot(self._on_split_input))
            self._first_view_combo.currentIndexChanged.connect(weak_slot(self._on_split_input))
        for box in spins:
            box.valueChanged.connect(weak_slot(self._on_spin))

    # ---- state ----------------------------------------------------------------

    @staticmethod
    def _fill(boxes: list[QDoubleSpinBox], rect: PanelRect) -> None:
        for box, value in zip(boxes, (rect.x, rect.y, rect.width, rect.height), strict=True):
            was = box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(was)

    def _apply_preset(self) -> None:
        """Fill the spin boxes from the slider, first-view choice and the last preset."""
        share = self._split_slider.value() / 100
        self._split_label.setText(f"{self._split_slider.value()}%")
        top, side = preset_rects(
            self._last_preset,  # type: ignore[arg-type]
            self._frame_w,
            self._frame_h,
            share,
            first_is_top=self._first_view_combo.currentIndex() == 0,
        )
        self._fill([self._top_x, self._top_y, self._top_w, self._top_h], top)
        self._fill([self._side_x, self._side_y, self._side_w, self._side_h], side)

    def _set_preset_text(self, text: str) -> None:
        was = self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(text)
        self._preset_combo.blockSignals(was)

    def _on_preset(self) -> None:
        text = self._preset_combo.currentText()
        if text == _CUSTOM:
            return
        self._last_preset = "left_right" if text == _LEFT_RIGHT else "top_bottom"
        self._apply_preset()
        self._rebuild()

    def _on_split_input(self) -> None:
        # Moving the slider or swapping the views is an explicit request for a preset.
        self._set_preset_text(_LEFT_RIGHT if self._last_preset == "left_right" else _TOP_BOTTOM)
        self._apply_preset()
        self._rebuild()

    def _on_spin(self) -> None:
        if self._split:
            self._set_preset_text(_CUSTOM)
        self._rebuild()

    # ---- results --------------------------------------------------------------

    def _rect(self, prefix: str) -> PanelRect | None:
        try:
            return PanelRect(
                x=getattr(self, f"{prefix}_x").value(),
                y=getattr(self, f"{prefix}_y").value(),
                width=getattr(self, f"{prefix}_w").value(),
                height=getattr(self, f"{prefix}_h").value(),
            )
        except ValueError:
            return None

    def result_rects(self) -> tuple[PanelRect, PanelRect]:
        top, side = self._rect("_top"), self._rect("_side")
        if top is None or side is None:
            raise ValueError("A panel rectangle is not valid")
        return top, side

    def result_rect(self) -> PanelRect:
        rect = self._rect("_top")
        if rect is None:
            raise ValueError("The panel rectangle is not valid")
        return rect

    # ---- rebuild --------------------------------------------------------------

    def _coverage(self, rect: PanelRect | None) -> list[AnimalCoverage] | None:
        """Per-animal coverage, or None when the rectangle is invalid or outside the frame."""
        if rect is None:
            return None
        try:
            return panel_coverage(self._session, rect)
        except ValueError:
            return None

    @staticmethod
    def _keeps_animal(cov: list[AnimalCoverage] | None) -> bool:
        return cov is not None and any(c.share_inside >= MIN_COVERAGE for c in cov)

    def _rebuild(self) -> None:
        top = self._rect("_top")
        side = self._rect("_side") if self._split else None
        self._preview.set_rects(top, side)
        top_cov = self._coverage(top)
        if not self._split:
            self._ok_button.setEnabled(self._keeps_animal(top_cov))
            return
        side_cov = self._coverage(side)
        self._ok_button.setEnabled(self._keeps_animal(top_cov) and self._keeps_animal(side_cov))
        self._fill_table(top_cov, side_cov)

    def _fill_table(
        self, top_cov: list[AnimalCoverage] | None, side_cov: list[AnimalCoverage] | None
    ) -> None:
        n = self._session.raw_xy.shape[1] if np.ndim(self._session.raw_xy) == 3 else 0
        table = self._coverage_table
        table.setRowCount(n)
        for i in range(n):
            options = [
                (name, cov[i])
                for name, cov in ((_TOP_VIEW, top_cov), (_SIDE_VIEW, side_cov))
                if cov is not None and i < len(cov)
            ]
            label = options[0][1].label if options else str(i)
            if not options:
                cells = [label, _DASH, _DASH, ""]
            elif all(c.n_valid == 0 for _, c in options):
                cells = [label, _DASH, _DASH, "no data"]
            else:
                name, best = max(options, key=lambda o: o[1].share_inside)
                if best.share_inside < MIN_COVERAGE:
                    flag = "left out"
                elif best.share_inside < LOW_COVERAGE:
                    flag = "low"
                else:
                    flag = ""
                cells = [label, name, f"{round(best.share_inside * 100)}%", flag]
            for col, text in enumerate(cells):
                table.setItem(i, col, QTableWidgetItem(text))
