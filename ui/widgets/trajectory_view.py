"""Trajectory viewer: animal paths over the arena, with zones and a heatmap.

Answers "did tracking work?" inside the app instead of after an export:
per-animal trails up to a scrubbed frame, raw vs processed paths (to see what
gap filling / jump removal / smoothing did), saved zones, and an occupancy
heatmap. Drawn with Qt's own graphics view -- no plotting dependency.

``split_on_nan`` and ``occupancy_heatmap`` are plain numpy so they can be
tested without a display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from scipy.ndimage import gaussian_filter

#: Distinguishable per-animal colours (cycled).
ANIMAL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]
#: Never draw more points per trail than this; long trails are strided.
_MAX_TRAIL_POINTS = 1500
_SOURCES = ("processed", "raw", "both")


def split_on_nan(points: np.ndarray) -> list[np.ndarray]:
    """Split an (n, 2) array into runs of consecutive finite points, so a
    path is never drawn across a tracking gap. Runs of one point are kept."""
    finite = np.isfinite(points).all(axis=1)
    if not finite.any():
        return []
    edges = np.flatnonzero(np.diff(finite.astype(np.int8))) + 1
    out = []
    for chunk, ok in zip(np.split(points, edges), np.split(finite, edges), strict=True):
        if ok[0]:
            out.append(chunk)
    return out


def occupancy_heatmap(
    xy: np.ndarray,
    width: float,
    height: float,
    cell_px: float = 8.0,
    sigma_cells: float = 1.5,
) -> np.ndarray:
    """Occupancy density over the arena, scaled to 0..1 (all zeros if empty).

    *xy* is (n_frames, n_animals, 2) in pixels; NaN and out-of-bounds
    positions are ignored. Returns shape (rows, cols).
    """
    cols = max(1, int(np.ceil(width / cell_px)))
    rows = max(1, int(np.ceil(height / cell_px)))
    pts = xy.reshape(-1, 2)
    pts = pts[np.isfinite(pts).all(axis=1)]
    heat = np.zeros((rows, cols), dtype=np.float64)
    if len(pts):
        ix = np.floor(pts[:, 0] / cell_px).astype(int)
        iy = np.floor(pts[:, 1] / cell_px).astype(int)
        ok = (ix >= 0) & (ix < cols) & (iy >= 0) & (iy < rows)
        np.add.at(heat, (iy[ok], ix[ok]), 1.0)
    if sigma_cells > 0 and heat.any():
        heat = gaussian_filter(heat, sigma_cells)
    peak = heat.max()
    return heat / peak if peak > 0 else heat


def _heat_image(heat: np.ndarray) -> QImage:
    """Blue -> yellow -> red, transparent where nothing happened."""
    rows, cols = heat.shape
    h = np.clip(heat, 0, 1)
    r = np.clip(2 * h, 0, 1)
    g = np.clip(2 * h, 0, 1) * np.clip(2 - 2 * h, 0, 1)
    b = np.clip(1 - 2 * h, 0, 1) * (h > 0)
    a = np.clip(h * 2.2, 0, 0.8)
    rgba = (np.stack([r, g, b, a], axis=-1) * 255).astype(np.uint8)
    rgba = np.ascontiguousarray(rgba)
    img = QImage(rgba.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
    return img.copy()  # detach from the numpy buffer


class TrajectoryView(QGraphicsView):
    frameChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gscene = QGraphicsScene(self)
        self.setScene(self._gscene)
        self.setMinimumHeight(360)
        self._raw: np.ndarray | None = None
        self._xy: np.ndarray | None = None
        self._rois: list[Any] = []
        self._size = (640.0, 480.0)
        self._frame = 0
        self._trail = 250
        self._source = "processed"
        self._show_zones = True
        self._show_heatmap = False
        self._dynamic: list[Any] = []
        self._zone_items: list[Any] = []
        self._heat_item: Any = None
        self._trail_items = 0
        self._trail_points = 0
        self._markers = 0
        self._highlight: int | None = None

    # ── data ──────────────────────────────────────────────────────────────

    def set_data(
        self,
        raw_xy: np.ndarray,
        xy: np.ndarray,
        fps: float,
        rois=(),
        background_path: Path | None = None,
        size: tuple[float, float] | None = None,
    ) -> None:
        """Load a session: *raw_xy* and *xy* are (n_frames, n_animals, 2) pixels."""
        self._raw, self._xy, self._rois = raw_xy, xy, list(rois)
        self._fps = fps
        self._gscene.clear()
        self._dynamic, self._zone_items, self._heat_item = [], [], None

        pixmap = None
        if background_path is not None and Path(background_path).exists():
            image = QImage(str(background_path))
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
        if pixmap is not None:
            self._gscene.addPixmap(pixmap).setZValue(0)
            self._size = (float(pixmap.width()), float(pixmap.height()))
        elif size is not None:
            self._size = (float(size[0]), float(size[1]))
        else:
            finite = xy[np.isfinite(xy).all(axis=-1)]
            top = finite.max(axis=0) if len(finite) else np.array([640.0, 480.0])
            self._size = (float(top[0]) + 20, float(top[1]) + 20)
        self._gscene.setSceneRect(0, 0, *self._size)

        self._frame = 0
        self._rebuild_zones()
        self._rebuild_heatmap()
        self._redraw()
        self.fitInView(self._gscene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @property
    def n_frames(self) -> int:
        return 0 if self._xy is None else int(self._xy.shape[0])

    @property
    def current_frame(self) -> int:
        return self._frame

    # ── controls ──────────────────────────────────────────────────────────

    def set_frame(self, frame: int) -> None:
        n = self.n_frames
        self._frame = 0 if n == 0 else max(0, min(int(frame), n - 1))
        self._redraw()
        self.frameChanged.emit(self._frame)

    def set_trail_length(self, frames: int) -> None:
        self._trail = max(1, int(frames))
        self._redraw()

    def set_source(self, source: str) -> None:
        if source not in _SOURCES:
            raise ValueError(f"source must be one of {_SOURCES}")
        self._source = source
        self._redraw()

    def set_highlight(self, animal: int | None) -> None:
        """Emphasise one animal's trail and marker; ``None`` restores the normal look."""
        self._highlight = None if animal is None else int(animal)
        self._redraw()

    def clear(self) -> None:
        """Drop the loaded session (the highlight setting is kept)."""
        self._raw = self._xy = None
        self._rois = []
        self._gscene.clear()
        self._dynamic, self._zone_items, self._heat_item = [], [], None
        self._trail_items = self._trail_points = self._markers = 0
        self._frame = 0

    @property
    def highlighted_animal(self) -> int | None:
        return self._highlight

    def set_show_zones(self, show: bool) -> None:
        self._show_zones = show
        self._rebuild_zones()

    def set_heatmap(self, show: bool) -> None:
        self._show_heatmap = show
        self._rebuild_heatmap()

    # ── introspection (also used by tests) ────────────────────────────────

    def trail_item_count(self) -> int:
        return self._trail_items

    def trail_point_count(self) -> int:
        return self._trail_points

    def marker_count(self) -> int:
        return self._markers

    def zone_item_count(self) -> int:
        return len(self._zone_items) // 2 if self._zone_items else 0

    def heatmap_visible(self) -> bool:
        return self._heat_item is not None

    # ── drawing ───────────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()

    def _remove(self, items: list[Any]) -> None:
        for item in items:
            if item.scene() is self._gscene:
                self._gscene.removeItem(item)
        items.clear()

    def _rebuild_zones(self) -> None:
        self._remove(self._zone_items)
        if not self._show_zones:
            return
        for i, roi in enumerate(self._rois):
            colour = QColor("#3498db" if i % 2 == 0 else "#e67e22")
            fill = QColor(colour)
            fill.setAlpha(40)
            poly = self._gscene.addPolygon(
                QPolygonF([QPointF(x, y) for x, y in roi.vertices]), QPen(colour, 2), QBrush(fill)
            )
            poly.setZValue(1)
            label = self._gscene.addSimpleText(roi.name)
            label.setBrush(QBrush(colour.darker(130)))
            xs, ys = zip(*roi.vertices, strict=True) if roi.vertices else ((0,), (0,))
            label.setPos(sum(xs) / len(xs), sum(ys) / len(ys))
            label.setZValue(1)
            self._zone_items += [poly, label]

    def _rebuild_heatmap(self) -> None:
        if self._heat_item is not None and self._heat_item.scene() is self._gscene:
            self._gscene.removeItem(self._heat_item)
        self._heat_item = None
        if not self._show_heatmap or self._xy is None:
            return
        heat = occupancy_heatmap(self._xy, *self._size)
        pix = QPixmap.fromImage(_heat_image(heat)).scaled(
            int(self._size[0]), int(self._size[1]),
            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._heat_item = self._gscene.addPixmap(pix)
        self._heat_item.setZValue(0.5)

    def _redraw(self) -> None:
        self._remove(self._dynamic)
        self._trail_items = self._trail_points = self._markers = 0
        if self._xy is None or self.n_frames == 0:
            return
        sources: list[tuple[np.ndarray, bool]] = []
        if self._source in ("raw", "both") and self._raw is not None:
            sources.append((self._raw, True))
        if self._source in ("processed", "both"):
            sources.append((self._xy, False))

        start = max(0, self._frame - self._trail)
        for data, is_raw in sources:
            window = data[start : self._frame + 1]
            stride = max(1, int(np.ceil(len(window) / _MAX_TRAIL_POINTS)))
            for k in range(data.shape[1]):
                colour = QColor(ANIMAL_COLORS[k % len(ANIMAL_COLORS)])
                path = QPainterPath()
                n_pts = 0
                for seg in split_on_nan(window[::stride, k, :]):
                    path.moveTo(float(seg[0, 0]), float(seg[0, 1]))
                    for x, y in seg[1:]:
                        path.lineTo(float(x), float(y))
                    n_pts += len(seg)
                width, radius = 1.5, 5.0
                pen_colour = QColor("#888888") if is_raw else colour
                if self._highlight is not None:
                    if k == self._highlight:
                        width, radius = 4.0, 8.0
                    else:
                        width, radius = 1.0, 4.0
                        colour.setAlphaF(0.35)
                        pen_colour.setAlphaF(0.35)
                pen = QPen(pen_colour, width)
                if is_raw:
                    pen.setStyle(Qt.PenStyle.DashLine)
                item = self._gscene.addPath(path, pen)
                item.setZValue(2)
                self._dynamic.append(item)
                self._trail_items += 1
                self._trail_points += n_pts
                if not is_raw:
                    x, y = data[self._frame, k]
                    if np.isfinite(x) and np.isfinite(y):
                        dot = self._gscene.addEllipse(
                            float(x) - radius, float(y) - radius, 2 * radius, 2 * radius,
                            QPen(Qt.GlobalColor.black), QBrush(colour),
                        )
                        dot.setZValue(3)
                        self._dynamic.append(dot)
                        self._markers += 1
