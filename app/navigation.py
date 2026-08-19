"""Left-rail wizard sidebar navigation widget."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidget, QListWidgetItem

# 7 wizard stages defined in PRD §14.
# Each entry: (display label, first-page index in the QStackedWidget).
STAGES: list[tuple[str, int]] = [
    ("1 · Project",                  0),
    ("2 · Sessions",                 1),
    ("3 · Calibration",              2),
    ("4 · Zones",                    3),
    ("5 · Metadata",                 4),
    ("6 · Preprocessing & Metrics",  5),
    ("7 · Preview & Export",         8),
]

# Maps each page index → its parent stage index (7 stages, 10 pages).
# Pages 0-4 are one-to-one with stages 0-4.
# Pages 5-7 belong to stage 5 (Preprocessing + Metrics + Processing).
# Pages 8-9 belong to stage 6 (Preview + Export).
PAGE_TO_STAGE: list[int] = [0, 1, 2, 3, 4, 5, 5, 5, 6, 6]


class WizardSidebar(QListWidget):
    """Vertical stage list; clicking a stage signals the main window."""

    stage_page_selected = Signal(int)  # emits the first-page index of the stage

    _NORMAL_FG = "#ecf0f1"
    _ACTIVE_FG = "#ffffff"
    _DONE_FG = "#2ecc71"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setSpacing(2)
        self.setStyleSheet(
            """
            QListWidget {
                background: #2c3e50;
                border: none;
            }
            QListWidget::item {
                color: #bdc3c7;
                padding: 10px 14px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background: #3d5166;
                color: #ffffff;
                font-weight: bold;
            }
            QListWidget::item:hover:!selected {
                background: #34495e;
            }
            """
        )
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)

        self._completions: list[bool] = [False] * len(STAGES)
        for label, _ in STAGES:
            item = QListWidgetItem(f"  {label}")
            self.addItem(item)

        self.currentRowChanged.connect(self._on_row_changed)

    # ── public ─────────────────────────────────────────────────────────────

    def sync_to_page(self, page_index: int) -> None:
        """Highlight the stage that owns *page_index*."""
        if page_index < 0 or page_index >= len(PAGE_TO_STAGE):
            return
        stage = PAGE_TO_STAGE[page_index]
        self.blockSignals(True)
        self.setCurrentRow(stage)
        self.blockSignals(False)

    def mark_complete(self, stage_index: int, complete: bool = True) -> None:
        """Add or remove a completion tick on a sidebar stage item."""
        if stage_index < 0 or stage_index >= len(STAGES):
            return
        self._completions[stage_index] = complete
        label, _ = STAGES[stage_index]
        prefix = "✓ " if complete else "  "
        self.item(stage_index).setText(f"{prefix}{label}")

    # ── private ────────────────────────────────────────────────────────────

    def _on_row_changed(self, stage_index: int) -> None:
        if stage_index < 0 or stage_index >= len(STAGES):
            return
        _, first_page = STAGES[stage_index]
        self.stage_page_selected.emit(first_page)
