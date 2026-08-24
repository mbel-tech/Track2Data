"""
Interactive zone-polygon canvas: a session's background.png with its
setup_points overlaid as clickable markers. Clicking markers in order
builds an ordered vertex list a zone polygon is saved from (see
ui/zones_screen.py's "Save Zone" action) -- selecting existing
validator landmarks, or points the user drops directly on the image
via custom-point mode, are exactly the same mechanism.

Split into two pieces on purpose:

  PointSelector  -- plain Python, no Qt import at all. Owns the actual
                    click/selection/custom-point state machine. Fully
                    unit-testable without a QApplication.
  ZoneCanvas     -- the QGraphicsView that renders PointSelector's
                    state and translates real mouse clicks into
                    PointSelector.click_at() calls. Also exposes
                    click_at() directly, so tests drive it with plain
                    image coordinates instead of synthesizing a real
                    QMouseEvent (which has its own Qt/PySide lifetime
                    pitfalls -- see test_import_screen.py's drag-event
                    tests for a worked example of that class of bug).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

#: Click-to-point tolerance, in image pixels (scene units == image
#: pixels here, since the background pixmap is added at its native
#: size with no extra scaling transform).
_HIT_RADIUS_PX = 10.0

_SETUP_POINT_COLOR = QColor("#2980b9")
_CUSTOM_POINT_COLOR = QColor("#e67e22")
_SELECTED_COLOR = QColor("#2ecc71")


def _unwrap_point(raw: Any) -> tuple[float, float]:
    """Real idtracker.ai session.json setup_points map a name to a
    *list containing one* [x, y] pair -- {"BP1": [[303, 477]]}, not
    {"BP1": [303, 477]} -- verified against the real 70-session corpus.
    Also accept the flat form, since hand-authored fixtures elsewhere
    in this repo use it."""
    if len(raw) == 1 and not isinstance(raw[0], int | float):
        x, y = raw[0]
    else:
        x, y = raw
    return float(x), float(y)


class PointSelector:
    """Click/selection state machine for a zone-polygon canvas.

    No Qt dependency by design -- see this module's docstring.
    """

    def __init__(self) -> None:
        self._points: dict[str, tuple[float, float]] = {}
        self._selected_order: list[str] = []
        self._custom_point_mode = False
        self._custom_counter = 0

    def load_setup_points(self, setup_points: dict[str, Any] | None) -> None:
        """Reset to a fresh point set from a session's Session.setup_points
        (or SessionFacts.setup_points). Clears any prior selection and
        custom points -- this is called when the user switches sessions
        in the Zones screen's session picker."""
        self._points = {}
        self._selected_order = []
        self._custom_counter = 0
        if not setup_points:
            return
        for name, raw in setup_points.items():
            self._points[name] = _unwrap_point(raw)

    def set_custom_point_mode(self, active: bool) -> None:
        self._custom_point_mode = active

    @property
    def custom_point_mode(self) -> bool:
        return self._custom_point_mode

    def points(self) -> dict[str, tuple[float, float]]:
        return dict(self._points)

    def selected_names(self) -> list[str]:
        return list(self._selected_order)

    def selected_points(self) -> list[tuple[float, float]]:
        return [self._points[name] for name in self._selected_order]

    def _find_hit(self, x: float, y: float) -> str | None:
        best: str | None = None
        best_dist = _HIT_RADIUS_PX
        for name, (px, py) in self._points.items():
            dist = math.hypot(px - x, py - y)
            if dist <= best_dist:
                best = name
                best_dist = dist
        return best

    def click_at(self, x: float, y: float) -> str | None:
        """Handle a click at image-pixel coordinates (x, y).

        Hitting an existing point (setup or custom) toggles its
        selection. Missing every point either adds and selects a new
        custom point (when custom_point_mode is on) or does nothing.

        Returns the name of the point toggled/added, or None if the
        click landed on nothing and custom-point mode is off.
        """
        hit = self._find_hit(x, y)
        if hit is not None:
            self._toggle(hit)
            return hit
        if self._custom_point_mode:
            self._custom_counter += 1
            name = f"Custom {self._custom_counter}"
            self._points[name] = (x, y)
            self._selected_order.append(name)
            return name
        return None

    def _toggle(self, name: str) -> None:
        if name in self._selected_order:
            self._selected_order.remove(name)
        else:
            self._selected_order.append(name)

    def clear_selection(self) -> None:
        """Deselect everything without discarding placed custom points
        -- they stay available to build the next zone."""
        self._selected_order = []


class ZoneCanvas(QGraphicsView):
    """QGraphicsView rendering a session's background image with
    clickable setup_point/custom-point markers, backed by a
    PointSelector."""

    selectionChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gscene = QGraphicsScene(self)
        self.setScene(self._gscene)
        self._selector = PointSelector()
        self._marker_items: dict[str, object] = {}
        self._label_items: dict[str, object] = {}
        self.setMinimumHeight(360)

    # ── loading ────────────────────────────────────────────────────────────

    def load_session(self, background_image_path: Path | None, setup_points) -> None:
        """Load a new session's backdrop + setup_points, discarding any
        prior selection -- called when the Zones screen's session
        picker changes."""
        self._gscene.clear()
        self._marker_items = {}
        self._label_items = {}
        self._selector.load_setup_points(setup_points)

        pixmap: QPixmap | None = None
        if background_image_path is not None and Path(background_image_path).exists():
            image = QImage(str(background_image_path))
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)

        if pixmap is not None:
            self._gscene.addPixmap(pixmap)
            self._gscene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        else:
            # No backdrop available (session probe still pending, or
            # this session shipped no preprocessing/background.png) --
            # still usable: markers render over a blank scene sized to
            # fit them.
            self._gscene.setSceneRect(0, 0, 640, 480)

        self._rebuild_markers()

    # ── interaction ───────────────────────────────────────────────────────

    def set_custom_point_mode(self, active: bool) -> None:
        self._selector.set_custom_point_mode(active)

    def click_at(self, x: float, y: float) -> None:
        """Handle a click at image-pixel coordinates. Exposed directly
        (not only via mousePressEvent) so tests can drive it
        deterministically without synthesizing a real QMouseEvent."""
        self._selector.click_at(x, y)
        self._rebuild_markers()
        self.selectionChanged.emit()

    def clear_selection(self) -> None:
        self._selector.clear_selection()
        self._rebuild_markers()
        self.selectionChanged.emit()

    def selected_points(self) -> list[tuple[float, float]]:
        return self._selector.selected_points()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            self.click_at(scene_pos.x(), scene_pos.y())
        super().mousePressEvent(event)

    # ── rendering ─────────────────────────────────────────────────────────

    def _rebuild_markers(self) -> None:
        for item in self._marker_items.values():
            self._gscene.removeItem(item)
        for item in self._label_items.values():
            self._gscene.removeItem(item)
        self._marker_items = {}
        self._label_items = {}

        selected = self._selector.selected_names()
        for name, (x, y) in self._selector.points().items():
            is_selected = name in selected
            radius = 7.0 if is_selected else 6.0
            if is_selected:
                color = _SELECTED_COLOR
            elif name.startswith("Custom "):
                color = _CUSTOM_POINT_COLOR
            else:
                color = _SETUP_POINT_COLOR
            marker = self._gscene.addEllipse(
                x - radius, y - radius, radius * 2, radius * 2,
                QPen(Qt.GlobalColor.black), QBrush(color),
            )
            marker.setZValue(2)
            marker.setToolTip(name)
            self._marker_items[name] = marker
            if is_selected:
                order = selected.index(name) + 1
                label = self._gscene.addSimpleText(str(order))
                label.setPos(x - 4, y - radius - 16)
                label.setBrush(QBrush(QColor("white")))
                label.setZValue(3)
                self._label_items[name] = label
