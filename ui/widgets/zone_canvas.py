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

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeySequence, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

#: Click-to-point tolerance, in image pixels (scene units == image
#: pixels here, since the background pixmap is added at its native
#: size with no extra scaling transform).
_HIT_RADIUS_PX = 10.0

_SETUP_POINT_COLOR = QColor("#2980b9")
_CUSTOM_POINT_COLOR = QColor("#e67e22")
_SELECTED_COLOR = QColor("#2ecc71")
_ZOOM_MIN, _ZOOM_MAX = 0.02, 40.0
#: Distinct translucent fills for saved zones, cycled by order.
_SAVED_ZONE_COLORS = ["#3498db", "#e67e22", "#9b59b6", "#1abc9c", "#e74c3c", "#f1c40f"]
#: Vertices used when a circle is drawn (a polygon is all a ROI can hold).
_CIRCLE_VERTICES = 32


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

    def hit_selected_custom(self, x: float, y: float) -> str | None:
        """Name of a *selected custom* point within the hit radius (the only
        points a drag may move), or None."""
        hit = self._find_hit(x, y)
        if hit is not None and hit in self._selected_order and hit.startswith("Custom "):
            return hit
        return None

    def undo(self) -> str | None:
        """Take back the most recent vertex. A custom point is deleted
        outright; a setup landmark is only deselected (landmarks are the
        validator's data, never ours to remove). Returns its name."""
        if not self._selected_order:
            return None
        name = self._selected_order.pop()
        if name.startswith("Custom "):
            self._points.pop(name, None)
        return name

    def move_point(self, name: str, x: float, y: float) -> bool:
        """Drag a custom point; landmarks are fixed. True if it moved."""
        if not name.startswith("Custom ") or name not in self._points:
            return False
        self._points[name] = (float(x), float(y))
        return True

    def _replace_selection_with(self, vertices: list[tuple[float, float]]) -> None:
        self._selected_order = []
        for vx, vy in vertices:
            self._custom_counter += 1
            name = f"Custom {self._custom_counter}"
            self._points[name] = (float(vx), float(vy))
            self._selected_order.append(name)

    def add_rectangle(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Select the four corners of the axis-aligned rectangle spanned by
        two opposite corners (any order). Zero-area rectangles are ignored."""
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left <= 0 or bottom - top <= 0:
            return
        self._replace_selection_with(
            [(left, top), (right, top), (right, bottom), (left, bottom)]
        )

    def add_circle(self, cx: float, cy: float, radius: float, n_vertices: int = 32) -> None:
        """Select an *n_vertices*-gon inscribed in the circle."""
        if radius <= 0 or n_vertices < 3:
            return
        self._replace_selection_with(
            [
                (
                    cx + radius * math.cos(2 * math.pi * i / n_vertices),
                    cy + radius * math.sin(2 * math.pi * i / n_vertices),
                )
                for i in range(n_vertices)
            ]
        )


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
        self._outline_items: list[object] = []
        self._polygon_item: object | None = None
        self._saved_rois: list[Any] = []
        self._saved_items: list[object] = []
        self._tool = "points"
        self._press_xy: tuple[float, float] | None = None
        self._drag_name: str | None = None
        self._drag_moved = False
        self._pan_last = None
        self._preview_item: object | None = None
        self.setMinimumHeight(360)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── loading ────────────────────────────────────────────────────────────

    def load_session(self, background_image_path: Path | None, setup_points) -> None:
        """Load a new session's backdrop + setup_points, discarding any
        prior selection -- called when the Zones screen's session
        picker changes."""
        self._gscene.clear()
        self._marker_items = {}
        self._label_items = {}
        self._outline_items = []
        self._polygon_item = None
        self._saved_items = []
        self._preview_item = None
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

        self._rebuild_saved_zones()
        self._rebuild_markers()
        self.fit_to_view()

    # ── view: zoom / pan / fit ────────────────────────────────────────────

    def zoom_by(self, factor: float) -> None:
        """Scale the view by *factor*, clamped to a sane absolute range."""
        current = self.transform().m11()
        target = min(_ZOOM_MAX, max(_ZOOM_MIN, current * factor))
        if current > 0:
            self.scale(target / current, target / current)

    def fit_to_view(self) -> None:
        rect = self._gscene.sceneRect()
        if rect.width() > 0 and rect.height() > 0:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    # ── saved zones overlay ───────────────────────────────────────────────

    def set_saved_zones(self, rois) -> None:
        """Show every saved ROI (translucent fill + name) under the markers."""
        self._saved_rois = list(rois)
        self._rebuild_saved_zones()

    def saved_zone_names(self) -> list[str]:
        return [roi.name for roi in self._saved_rois]

    def _rebuild_saved_zones(self) -> None:
        for item in self._saved_items:
            if item.scene() is self._gscene:
                self._gscene.removeItem(item)
        self._saved_items = []
        for i, roi in enumerate(self._saved_rois):
            colour = QColor(_SAVED_ZONE_COLORS[i % len(_SAVED_ZONE_COLORS)])
            fill = QColor(colour)
            fill.setAlpha(55)
            poly = QPolygonF([QPointF(x, y) for x, y in roi.vertices])
            item = self._gscene.addPolygon(poly, QPen(colour, 2), QBrush(fill))
            item.setZValue(1)
            item.setToolTip(f"{roi.name} ({roi.level})")
            self._saved_items.append(item)
            if roi.vertices:
                cx = sum(v[0] for v in roi.vertices) / len(roi.vertices)
                cy = sum(v[1] for v in roi.vertices) / len(roi.vertices)
                label = self._gscene.addSimpleText(roi.name)
                label.setBrush(QBrush(colour.darker(130)))
                label.setPos(cx - label.boundingRect().width() / 2, cy - 8)
                label.setZValue(1)
                self._saved_items.append(label)

    # ── interaction ───────────────────────────────────────────────────────

    def set_tool(self, tool: str) -> None:
        """"points" (click markers), "rect" or "circle" (drag a shape)."""
        if tool not in {"points", "rect", "circle"}:
            raise ValueError(f"unknown tool {tool!r}")
        self._tool = tool

    def undo_last_point(self) -> None:
        self._selector.undo()
        self._rebuild_markers()
        self.selectionChanged.emit()

    def drag_shape(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        """Create a rectangle/circle selection from a drag (tool-dependent).
        Public so tests do not need synthesized mouse events."""
        if self._tool == "rect":
            self._selector.add_rectangle(start[0], start[1], end[0], end[1])
        elif self._tool == "circle":
            self._selector.add_circle(
                start[0], start[1], math.hypot(end[0] - start[0], end[1] - start[1]),
                _CIRCLE_VERTICES,
            )
        else:
            return
        self._rebuild_markers()
        self.selectionChanged.emit()

    def drag_vertex(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        """Move the selected custom vertex under *start* to *end*."""
        name = self._selector.hit_selected_custom(*start)
        if name is None or not self._selector.move_point(name, *end):
            return False
        self._rebuild_markers()
        self.selectionChanged.emit()
        return True

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
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.pos())
            xy = (pos.x(), pos.y())
            if self._tool in ("rect", "circle"):
                self._press_xy = xy
            else:
                name = self._selector.hit_selected_custom(*xy)
                if name is not None:
                    self._drag_name, self._drag_moved, self._press_xy = name, False, xy
                else:
                    self.click_at(*xy)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_last is not None:
            delta = event.pos() - self._pan_last
            self._pan_last = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        pos = self.mapToScene(event.pos())
        if self._drag_name is not None:
            self._drag_moved = True
            self._selector.move_point(self._drag_name, pos.x(), pos.y())
            self._rebuild_markers()
        elif self._press_xy is not None and self._tool in ("rect", "circle"):
            self._show_shape_preview((pos.x(), pos.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.pos())
            if self._drag_name is not None:
                if self._drag_moved:
                    self.selectionChanged.emit()
                elif self._press_xy is not None:
                    self.click_at(*self._press_xy)  # a plain click: toggle off
                self._drag_name, self._press_xy = None, None
            elif self._press_xy is not None and self._tool in ("rect", "circle"):
                self._clear_shape_preview()
                self.drag_shape(self._press_xy, (pos.x(), pos.y()))
                self._press_xy = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo_last_point()
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_shape_preview(self) -> None:
        if self._preview_item is not None and self._preview_item.scene() is self._gscene:
            self._gscene.removeItem(self._preview_item)
        self._preview_item = None

    def _show_shape_preview(self, end: tuple[float, float]) -> None:
        self._clear_shape_preview()
        if self._press_xy is None:
            return
        x0, y0 = self._press_xy
        pen = QPen(_SELECTED_COLOR, 2, Qt.PenStyle.DashLine)
        if self._tool == "rect":
            item = self._gscene.addRect(
                min(x0, end[0]), min(y0, end[1]), abs(end[0] - x0), abs(end[1] - y0), pen
            )
        else:
            r = math.hypot(end[0] - x0, end[1] - y0)
            item = self._gscene.addEllipse(x0 - r, y0 - r, 2 * r, 2 * r, pen)
        item.setZValue(4)
        self._preview_item = item

    # ── rendering ─────────────────────────────────────────────────────────

    def _rebuild_markers(self) -> None:
        for item in self._marker_items.values():
            self._gscene.removeItem(item)
        for item in self._label_items.values():
            self._gscene.removeItem(item)
        self._marker_items = {}
        self._label_items = {}
        self._draw_selection_outline()

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

    def _draw_selection_outline(self) -> None:
        """Edges between the selected vertices, and a translucent fill once
        they form a polygon -- so the user can see the shape they are making."""
        for item in [*self._outline_items, self._polygon_item]:
            if item is not None and item.scene() is self._gscene:
                self._gscene.removeItem(item)
        self._outline_items = []
        self._polygon_item = None

        pts = self._selector.selected_points()
        pen = QPen(_SELECTED_COLOR, 2)
        if len(pts) == 2:
            line = self._gscene.addLine(pts[0][0], pts[0][1], pts[1][0], pts[1][1], pen)
            line.setZValue(1.5)
            self._outline_items.append(line)
        elif len(pts) >= 3:
            fill = QColor(_SELECTED_COLOR)
            fill.setAlpha(70)
            poly = self._gscene.addPolygon(
                QPolygonF([QPointF(x, y) for x, y in pts]), pen, QBrush(fill)
            )
            poly.setZValue(1.5)
            self._polygon_item = poly

    def polygon_item(self):
        """The translucent selection polygon, or None with fewer than 3 vertices."""
        return self._polygon_item

    def outline_item_count(self) -> int:
        return len(self._outline_items)
