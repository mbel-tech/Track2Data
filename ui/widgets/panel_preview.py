"""A display-only preview of a video frame with the top and side panel rectangles on it.

The backdrop is the best picture available: the background image, else the first video
frame, else the tracks drawn as points, else a blank frame. No store access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from track2data.core.models import PanelRect
from track2data.readers.video_meta import extract_frame
from ui.widgets.backdrop import load_backdrop_image
from ui.widgets.trajectory_view import ANIMAL_COLORS

BackdropKind = Literal["image", "video", "tracks", "none"]

#: At most this many points are drawn over all animals; longer tracks are strided.
_MAX_POINTS = 3000
_POINT_RADIUS = 1.5
_RECT_Z = 10
_TOP_COLOUR = "#e6194b"
_SIDE_COLOUR = "#3cb44b"


class PanelPreview(QGraphicsView):
    def __init__(self, parent=None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._kind: BackdropKind = "none"
        self._backdrop_items: list = []
        self._rect_items: list = []
        self._rects: tuple[PanelRect | None, PanelRect | None] = (None, None)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @property
    def backdrop_kind(self) -> BackdropKind:
        return self._kind

    @property
    def rect_item_count(self) -> int:
        return sum(isinstance(i, QGraphicsRectItem) for i in self._rect_items)

    def set_source(
        self,
        frame_size: tuple[float, float],
        background_path: Path | None,
        video_path: Path | None,
        tracks: np.ndarray | None,
    ) -> None:
        scene = self.scene()
        scene.clear()
        self._backdrop_items = []
        self._rect_items = []
        width, height = float(frame_size[0]), float(frame_size[1])
        scene.setSceneRect(QRectF(0, 0, width, height))

        image = load_backdrop_image(background_path)
        kind: BackdropKind = "image"
        if image is None:
            image = self._video_frame(video_path, round(width), round(height))
            kind = "video"
        if image is not None:
            item = QGraphicsPixmapItem(QPixmap.fromImage(image))
            item.setZValue(0)
            scene.addItem(item)
            self._backdrop_items.append(item)
            self._kind = kind
        elif tracks is not None and np.ndim(tracks) == 3 and np.shape(tracks)[0] > 0:
            self._draw_tracks(np.asarray(tracks, dtype=float))
            self._kind = "tracks"
        else:
            self._kind = "none"
        self._draw_rects()
        self._fit()

    def set_rects(self, top: PanelRect | None, side: PanelRect | None) -> None:
        self._rects = (top, side)
        self._draw_rects()

    @staticmethod
    def _video_frame(video_path: Path | None, w: int, h: int) -> QImage | None:
        if video_path is None or w <= 0 or h <= 0 or not Path(video_path).exists():
            return None
        try:
            data = extract_frame(Path(video_path), 0)
        except Exception:
            return None
        if not data or len(data) != w * h * 3:
            return None
        # copy() so the image owns its pixels and not the bytes object
        return QImage(data, w, h, w * 3, QImage.Format.Format_RGB888).copy()

    def _draw_tracks(self, tracks: np.ndarray) -> None:
        n_frames, n_animals = tracks.shape[0], tracks.shape[1]
        stride = max(1, -(-n_frames * n_animals // _MAX_POINTS))
        for k in range(n_animals):
            path = QPainterPath()
            for x, y in tracks[::stride, k, :2]:
                if np.isfinite(x) and np.isfinite(y):
                    path.addEllipse(QPointF(float(x), float(y)), _POINT_RADIUS, _POINT_RADIUS)
            colour = QColor(ANIMAL_COLORS[k % len(ANIMAL_COLORS)])
            item = QGraphicsPathItem(path)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QBrush(colour))
            item.setZValue(1)
            self.scene().addItem(item)
            self._backdrop_items.append(item)

    def _draw_rects(self) -> None:
        scene = self.scene()
        for item in self._rect_items:
            scene.removeItem(item)
        self._rect_items = []
        for rect, label, colour in zip(
            self._rects, ("Top view", "Side view"), (_TOP_COLOUR, _SIDE_COLOUR), strict=True
        ):
            if rect is None:
                continue
            box = QGraphicsRectItem(QRectF(rect.x, rect.y, rect.width, rect.height))
            pen = QPen(QColor(colour))
            pen.setWidth(2)
            pen.setCosmetic(True)
            box.setPen(pen)
            box.setZValue(_RECT_Z)
            text = QGraphicsSimpleTextItem(label)
            text.setBrush(QBrush(QColor(colour)))
            text.setPos(rect.x + 2, rect.y + 2)
            text.setZValue(_RECT_Z)
            scene.addItem(box)
            scene.addItem(text)
            self._rect_items.extend([box, text])

    def _fit(self) -> None:
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
