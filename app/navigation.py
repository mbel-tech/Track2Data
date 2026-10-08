"""Left-rail wizard sidebar navigation widget."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
)

from app.theme import theme

# 9 wizard stages, one sidebar row per page (Preview and Export share the
# last row). The number lives in the painted dot, not the label.
# Each entry: (display label, first-page index in the QStackedWidget).
STAGES: list[tuple[str, int]] = [
    ("Project", 0),
    ("Sessions", 1),
    ("Calibration", 2),
    ("Zones", 3),
    ("Metadata", 4),
    ("Preprocessing", 5),
    ("Metrics", 6),
    ("Processing", 7),
    ("Preview & Export", 8),
]

# Maps each page index → its parent stage index (9 stages, 10 pages).
PAGE_TO_STAGE: list[int] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 8]

STATUS_ROLE = Qt.ItemDataRole.UserRole
SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 1
LOCKED_ROLE = Qt.ItemDataRole.UserRole + 2


class StageDelegate(QStyledItemDelegate):
    """Paints one stage row: numbered dot, name and a one-line live summary."""

    ROW_H = 56
    DOT = 22

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 -- Qt override
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        active = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        status = index.data(STATUS_ROLE) or "empty"
        locked = bool(index.data(LOCKED_ROLE))
        done = status in ("valid", "warning") and not locked

        if active:
            painter.fillRect(r, theme.color("sideActive"))
            painter.fillRect(QRectF(r.left(), r.top(), 3, r.height()), theme.color("mustard"))
        elif hover and not locked:
            painter.fillRect(r, theme.color("sideHover"))

        cx, cy = r.left() + 20 + self.DOT / 2, r.center().y()
        dot = QRectF(cx - self.DOT / 2, cy - self.DOT / 2, self.DOT, self.DOT)
        number = str(index.row() + 1)
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        if done:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color("mustard"))
            painter.drawEllipse(dot)
            painter.setPen(theme.color("mustardFg"))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, "✓")
        elif active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(dot)
            painter.setPen(QColor("#1c5866"))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, number)
        else:
            ring = theme.color("sideLocked")
            painter.setPen(QPen(ring, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(dot.adjusted(1, 1, -1, -1))
            painter.setPen(ring if locked else theme.color("sideSub"))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, number)

        text_x = int(dot.right()) + 12
        width = r.right() - text_x - 8
        name_rect = QRectF(text_x, r.top() + 9, width, 20)
        sub_rect = QRectF(text_x, r.top() + 29, width, 18)
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(theme.color("sideLocked") if locked else QColor("#ffffff"))
        painter.drawText(
            name_rect, Qt.AlignmentFlag.AlignVCenter, index.data(Qt.ItemDataRole.DisplayRole)
        )
        font.setPixelSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(theme.color("sideLocked") if locked else theme.color("sideSub"))
        summary = painter.fontMetrics().elidedText(
            index.data(SUMMARY_ROLE) or "", Qt.TextElideMode.ElideRight, int(sub_rect.width())
        )
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignVCenter, summary)
        painter.restore()


class WizardSidebar(QListWidget):
    """Vertical stage list; clicking a stage signals the main window."""

    stage_page_selected = Signal(int)  # emits the first-page index of the stage
    locked_clicked = Signal(int)  # a locked stage was clicked

    _STATUSES = ("empty", "valid", "warning", "blocked")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StageList")
        self.setFixedWidth(236)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setItemDelegate(StageDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._completions: list[bool] = [False] * len(STAGES)
        self._locked: set[int] = set()
        for label, _ in STAGES:
            item = QListWidgetItem(label)
            item.setData(STATUS_ROLE, "empty")
            self.addItem(item)
        self._statuses: list[str | None] = [None] * len(STAGES)

        self.currentRowChanged.connect(self._on_row_changed)
        theme.changed.connect(self._on_theme_changed)

    # ── public ─────────────────────────────────────────────────────────────

    def sync_to_page(self, page_index: int) -> None:
        """Highlight the stage that owns *page_index*."""
        if page_index < 0 or page_index >= len(PAGE_TO_STAGE):
            return
        stage = PAGE_TO_STAGE[page_index]
        self.blockSignals(True)
        self.setCurrentRow(stage)
        self.blockSignals(False)
        self.viewport().update()

    def mark_complete(self, stage_index: int, complete: bool = True) -> None:
        self.set_status(stage_index, "valid" if complete else "empty")

    def set_status(
        self, stage_index: int, status: str, tooltip: str = "", summary: str | None = None
    ) -> None:
        """Set a stage's status (valid / warning / blocked / empty), tooltip and summary line."""
        if stage_index < 0 or stage_index >= len(STAGES) or status not in self._STATUSES:
            return
        self._statuses[stage_index] = status
        self._completions[stage_index] = status == "valid"
        item = self.item(stage_index)
        item.setData(STATUS_ROLE, status)
        item.setData(SUMMARY_ROLE, summary if summary is not None else tooltip)
        item.setToolTip(tooltip)
        self.viewport().update()

    def set_locked(self, stage_index: int, locked: bool) -> None:
        """A locked stage looks disabled; clicking it emits ``locked_clicked``."""
        if locked:
            self._locked.add(stage_index)
        else:
            self._locked.discard(stage_index)
        self.item(stage_index).setData(LOCKED_ROLE, locked)
        self.viewport().update()

    def status(self, stage_index: int) -> str | None:
        return self._statuses[stage_index] if 0 <= stage_index < len(STAGES) else None

    def _on_theme_changed(self, _name: str) -> None:
        self.viewport().update()

    # ── private ────────────────────────────────────────────────────────────

    def _on_row_changed(self, stage_index: int) -> None:
        if stage_index < 0 or stage_index >= len(STAGES):
            return
        if stage_index in self._locked:
            self.locked_clicked.emit(stage_index)
            return
        _, first_page = STAGES[stage_index]
        self.stage_page_selected.emit(first_page)
