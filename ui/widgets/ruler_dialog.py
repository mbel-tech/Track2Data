"""Two-point calibration ruler.

The user clicks both ends of an object of known length on a session's
background frame and types its real length; the pixel distance divided by
that length is the pixels-per-unit scale. ``Ruler`` holds the state with no
Qt dependency; ``RulerCanvas`` / ``RulerDialog`` are the thin Qt layer.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import PanelRect
from ui.widgets.backdrop import load_backdrop_image

_COLOR = QColor("#e74c3c")


class Ruler:
    """Up to two clicked points; a third click starts over."""

    def __init__(self) -> None:
        self.points: list[tuple[float, float]] = []

    def click(self, x: float, y: float) -> None:
        if len(self.points) >= 2:
            self.points = []
        self.points.append((float(x), float(y)))

    def distance_px(self) -> float | None:
        if len(self.points) != 2:
            return None
        (x0, y0), (x1, y1) = self.points
        return math.hypot(x1 - x0, y1 - y0)

    def px_per_unit(self, length: float) -> float | None:
        d = self.distance_px()
        if d is None or d <= 0 or length <= 0:
            return None
        return d / length


class RulerCanvas(QGraphicsView):
    changed = Signal()

    def __init__(
        self,
        background: Path | None,
        size: tuple[float, float],
        parent=None,
        crop: PanelRect | None = None,
    ) -> None:
        super().__init__(parent)
        self.ruler = Ruler()
        self._gscene = QGraphicsScene(self)
        self.setScene(self._gscene)
        self.setMinimumSize(480, 320)
        pixmap = None
        image = load_backdrop_image(background, crop)
        if image is not None:
            pixmap = QPixmap.fromImage(image)
        if pixmap is not None:
            self._gscene.addPixmap(pixmap)
            self._gscene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        else:
            self._gscene.setSceneRect(0, 0, float(size[0]), float(size[1]))
        self._items: list = []

    def click_at(self, x: float, y: float) -> None:
        self.ruler.click(x, y)
        self._redraw()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(event.pos())
            self.click_at(p.x(), p.y())
        super().mousePressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.fitInView(self._gscene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _redraw(self) -> None:
        for item in self._items:
            self._gscene.removeItem(item)
        self._items = []
        pts = self.ruler.points
        if len(pts) == 2:
            self._items.append(
                self._gscene.addLine(pts[0][0], pts[0][1], pts[1][0], pts[1][1],
                                     QPen(_COLOR, 2))
            )
        for x, y in pts:
            dot = self._gscene.addEllipse(x - 5, y - 5, 10, 10, QPen(Qt.GlobalColor.black),
                                          QBrush(_COLOR))
            dot.setZValue(2)
            self._items.append(dot)


class RulerDialog(QDialog):
    """Measure a known length on a frame; ``px_per_unit()`` is the result."""

    def __init__(
        self,
        background: Path | None,
        size: tuple[float, float],
        unit_label: str = "cm",
        parent: QWidget | None = None,
        crop: PanelRect | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Measure on frame")
        lay = QVBoxLayout(self)
        lay.addWidget(
            QLabel(
                "Click both ends of an object of known length (a ruler, the "
                "arena diameter, a calibration bar). A third click starts over."
            )
        )
        self.canvas = RulerCanvas(background, size, crop=crop)
        lay.addWidget(self.canvas, 1)

        form = QFormLayout()
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0.0, 100000.0)
        self.length_spin.setDecimals(3)
        self.length_spin.setSuffix(f" {unit_label}")
        form.addRow("Real length:", self.length_spin)
        lay.addLayout(form)

        self.result_label = QLabel("")
        lay.addWidget(self.result_label)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        lay.addWidget(self._buttons)

        self.canvas.changed.connect(self._update)
        self.length_spin.valueChanged.connect(self._update)
        self._update()

    def px_per_unit(self) -> float | None:
        return self.canvas.ruler.px_per_unit(self.length_spin.value())

    def ok_enabled(self) -> bool:
        return self._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()

    def _update(self) -> None:
        d = self.canvas.ruler.distance_px()
        scale = self.px_per_unit()
        if d is None:
            self.result_label.setText("Place two points.")
        elif scale is None:
            self.result_label.setText(f"Measured {d:.1f} px. Enter the real length.")
        else:
            self.result_label.setText(f"Measured {d:.1f} px  →  {scale:.4g} px per unit")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(scale is not None)
