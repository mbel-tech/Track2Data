"""A side-view preview with two horizontal lines for the water surface and the tank floor.

A display widget: it composes a ``PanelPreview`` for the backdrop and draws the lines in the
same scene so they scale with the view. The user drags a line; ``rowsChanged`` reports it.
No store access.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.panel_preview import PanelPreview
from ui.widgets.weak_slot import weak_slot

_LINE_Z = 20
_SURFACE_COLOUR = "#1f77b4"
_FLOOR_COLOUR = "#ff7f0e"
#: Width in view pixels of the strip around a line that grabs the mouse.
_GRAB_PX = 10.0


class _RowLine(QGraphicsLineItem):
    """A horizontal line at scene row ``y`` (the item sits at x=0 and is moved to y)."""

    def __init__(
        self, label: str, colour: str, on_drag: Callable[[float], None], width: float
    ) -> None:
        super().__init__(0.0, 0.0, width, 0.0)
        self._on_drag = on_drag
        self._grab = 4.0  # scene units; refreshed by the owner when the view scales
        pen = QPen(QColor(colour))
        pen.setWidth(2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(_LINE_Z)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._label = QGraphicsSimpleTextItem(label, self)
        self._label.setBrush(QBrush(QColor(colour)))
        self._label.setPos(2, 0)
        self._label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def label_text(self) -> str:
        return self._label.text()

    def set_grab(self, scene_units: float) -> None:
        if scene_units != self._grab:
            self.prepareGeometryChange()
            self._grab = scene_units

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        line = self.line()
        path.addRect(QRectF(line.x1(), -self._grab, line.length(), 2 * self._grab))
        return path

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect().united(super().boundingRect())

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self._on_drag(event.scenePos().y())
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        event.accept()


class _Preview(PanelPreview):
    """A PanelPreview that tells its owner after each resize (the view scale changed)."""

    def __init__(self, on_resized: Callable[[], None]) -> None:
        super().__init__()
        self._on_resized = on_resized

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._on_resized()


class WaterColumnView(QWidget):
    """Side-view backdrop with draggable "Surface" and "Floor" lines.

    ``rowsChanged(surface, floor)`` is emitted only for user drags, and only when both lines
    are set (the signal carries two numbers). ``set_rows`` never emits.
    """

    rowsChanged = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.preview = _Preview(weak_slot(self._sync))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview)
        # Requested rows (unclamped, so a frame change does not lose the user's values).
        self._surface: float | None = None
        self._floor: float | None = None
        self._surface_line: _RowLine | None = None
        self._floor_line: _RowLine | None = None
        self._rebuild_lines()

    # -- public API -------------------------------------------------------------------
    @property
    def line_count(self) -> int:
        return sum(
            1
            for item in (self._surface_line, self._floor_line)
            if item is not None and item.isVisible()
        )

    def set_source(
        self,
        frame_size: tuple[float, float],
        background_path: Path | None,
        video_path: Path | None,
        tracks: np.ndarray | None,
    ) -> None:
        """Pass through to the preview and redraw the lines on the new scene. Never raises."""
        self.preview.set_source(frame_size, background_path, video_path, tracks)
        self._rebuild_lines()

    def set_rows(self, surface: float | None, floor: float | None) -> None:
        """Place the lines (None or a non-finite value removes one). Never emits."""
        self._surface = self._finite(surface)
        self._floor = self._finite(floor)
        self._sync()

    def rows(self) -> tuple[float | None, float | None]:
        """The rows as drawn: clamped to the frame, surface above floor."""
        height = self._frame_height()
        surface, floor = self._surface, self._floor
        if floor is not None:
            floor = min(max(floor, 0.0), height)
        if surface is not None:
            surface = min(max(surface, 0.0), height)
            if floor is not None:
                surface = min(surface, max(floor - self._gap(), 0.0))
        return surface, floor

    # -- internals --------------------------------------------------------------------
    @staticmethod
    def _finite(value: float | None) -> float | None:
        try:
            if value is None or not math.isfinite(float(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _frame_height(self) -> float:
        return float(self.preview.scene().sceneRect().height())

    def _gap(self) -> float:
        return min(1.0, self._frame_height() * 0.01)

    def _drag_line(self, which: str, y: float) -> None:
        """Move a line to scene row *y* (clamped) and emit ``rowsChanged``."""
        y = self._finite(y)
        if y is None:
            return
        surface, floor = self.rows()
        height, gap = self._frame_height(), self._gap()
        if which == "surface":
            surface = min(max(y, 0.0), height if floor is None else max(floor - gap, 0.0))
        elif which == "floor":
            floor = min(max(y, 0.0 if surface is None else min(surface + gap, height)), height)
        else:
            raise ValueError(f"unknown line {which!r}")
        if (surface, floor) == (self._surface, self._floor):
            return
        self._surface, self._floor = surface, floor
        self._sync()
        if surface is not None and floor is not None:
            self.rowsChanged.emit(surface, floor)

    def _rebuild_lines(self) -> None:
        """(Re)create the line items in the preview's current scene."""
        scene = self.preview.scene()
        width = scene.sceneRect().width()
        self._surface_line = _RowLine(
            "Surface", _SURFACE_COLOUR, weak_slot(self._drag_line, "surface", pass_args=True), width
        )
        self._floor_line = _RowLine(
            "Floor", _FLOOR_COLOUR, weak_slot(self._drag_line, "floor", pass_args=True), width
        )
        for item in (self._surface_line, self._floor_line):
            scene.addItem(item)
        self._sync()

    def _sync(self) -> None:
        surface, floor = self.rows()
        scale = self.preview.transform().m11() or 1.0
        for item, row in ((self._surface_line, surface), (self._floor_line, floor)):
            if item is None:
                continue
            item.set_grab(_GRAB_PX / 2 / abs(scale))
            item.setVisible(row is not None)
            if row is not None:
                item.setPos(QPointF(0.0, row))
