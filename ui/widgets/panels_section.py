"""Panels section of the Views page: cut one shared video into panels.

Shown only for a 3-D project in the "One video, two panels" layout. The editor needs the
session's raw positions, so a click first loads the unpanelled session on the store's
worker pool; the dialog opens when that load finishes, and its result is written through
the store. A rebuild of the table never writes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import PanelRect
from ui.dialogs.panel_dialog import PanelDialog
from ui.widgets.weak_slot import weak_slot

WHOLE_VIDEO = "whole video"
_SPLIT = "split"
_SET = "set"


def panel_text(rect: PanelRect | None) -> str:
    if rect is None:
        return WHOLE_VIDEO

    def num(v: float) -> str:
        return f"{v:g}"

    return f"{num(rect.x)}, {num(rect.y)}, {num(rect.width)} \u00d7 {num(rect.height)}"


def load_unpanelled_session(manifest, session_id: str, cache_dir: Path | None):
    """Import one session with its panel removed. Runs on a worker thread; raises on failure."""
    from track2data.api import Engine

    ref = next(r for r in manifest.sessions if r.session_id == session_id)
    return Engine(manifest, cache_dir=cache_dir).import_ref(ref.model_copy(update={"panel": None}))


class PanelsSection(QGroupBox):
    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__("Panels", parent)
        self._store = store
        self._pending: dict[str, tuple[str, str]] = {}  # task id -> (action, session id)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lead = QLabel("Cut the shared video into a top and a side panel, or set one panel.")
        lead.setObjectName("PageLead")
        lead.setWordWrap(True)
        lay.addWidget(lead)
        self._table = QTableWidget(0, 2)
        self._table.setObjectName("ViewsPanelsTable")
        self._table.setHorizontalHeaderLabels(["Session", "Panel"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        lay.addWidget(self._table)
        row = QHBoxLayout()
        self._split_btn = QPushButton("Split into panels…")
        self._set_btn = QPushButton("Set panel…")
        self._clear_btn = QPushButton("Clear panel")
        for btn in (self._split_btn, self._set_btn, self._clear_btn):
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._status = QLabel("")
        self._status.setObjectName("ErrorLabel")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        self._table.itemSelectionChanged.connect(weak_slot(self._update_buttons))
        self._split_btn.clicked.connect(weak_slot(self._start, _SPLIT))
        self._set_btn.clicked.connect(weak_slot(self._start, _SET))
        self._clear_btn.clicked.connect(weak_slot(self._clear))
        if store is not None:
            store.taskFinished.connect(self._on_task_finished)
            store.projectChanged.connect(self._on_project_changed)
        self.rebuild()

    # ── store helpers ──────────────────────────────────────────────────────

    def _refs(self):
        m = None if self._store is None else self._store.manifest
        return list(m.sessions) if m is not None else []

    def _applies(self) -> bool:
        m = None if self._store is None else self._store.manifest
        return (
            m is not None
            and m.mode.dimension == "3d"
            and m.mode.layout == "single_video_two_panels"
        )

    def _selected_id(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        item = self._table.item(rows[0].row(), 0) if rows else None
        return item.text() if item is not None else None

    def _ref(self, session_id: str | None):
        return next((r for r in self._refs() if r.session_id == session_id), None)

    # ── rebuild (never writes) ─────────────────────────────────────────────

    def rebuild(self) -> None:
        applies = self._applies()
        self.setVisible(applies)
        refs = self._refs() if applies else []
        keep = self._selected_id()
        table = self._table
        table.blockSignals(True)
        try:
            table.clearSelection()
            table.setRowCount(len(refs))
            for row, ref in enumerate(refs):
                for col, text in enumerate((ref.session_id, panel_text(ref.panel))):
                    item = QTableWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    table.setItem(row, col, item)
                if ref.session_id == keep:
                    table.selectRow(row)
        finally:
            table.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        ref = self._ref(self._selected_id())
        self._split_btn.setEnabled(ref is not None and ref.panel is None)
        self._set_btn.setEnabled(ref is not None)
        self._clear_btn.setEnabled(ref is not None and ref.panel is not None)

    # ── actions ────────────────────────────────────────────────────────────

    def _start(self, action: str) -> None:
        sid = self._selected_id()
        if sid is None or self._store is None or self._store.manifest is None:
            return
        self._status.setText("")
        self._pending = {}  # a newer click supersedes an in-flight load
        store = self._store
        manifest, cache_dir = store.manifest, store.cache_dir

        def work():
            return load_unpanelled_session(manifest, sid, cache_dir)

        self._pending[store.tasks.submit(work)] = (action, sid)
        self._status.setText("Loading the session…")

    def _on_project_changed(self) -> None:
        self._pending = {}
        self._status.setText("")

    def _on_task_finished(self, task_id: str, result: object) -> None:
        entry = self._pending.pop(task_id, None)
        if entry is None:
            return
        action, sid = entry
        if isinstance(result, BaseException):
            self._status.setText(f"Could not load {sid}: {result}")
            return
        self._status.setText("")
        if self._ref(sid) is None:
            self._status.setText(f"{sid} is no longer in the project.")
            return
        try:
            self._run_dialog(action, sid, result)
        except Exception as exc:  # the store rejected the change, or the dialog failed
            self._status.setText(str(exc))

    def _run_dialog(self, action: str, sid: str, session) -> None:
        bg = getattr(session, "background_image_path", None)
        bg = Path(bg) if bg is not None and Path(bg).is_file() else None
        ref = self._ref(sid)
        initial = ref.panel if ref is not None and action != _SPLIT else None
        dialog = PanelDialog(
            session, _SPLIT if action == _SPLIT else "single", bg, self, initial_rect=initial
        )
        if not dialog.exec():
            return
        if self._ref(sid) is None:
            self._status.setText(f"{sid} is no longer in the project.")
            return
        if action == _SPLIT:
            top, side = dialog.result_rects()
            self._store.split_session_into_panels(sid, top, side)
        else:
            self._store.set_session_panel(sid, dialog.result_rect())

    def _clear(self) -> None:
        sid = self._selected_id()
        if sid is None or self._ref(sid) is None:
            return
        try:
            self._store.set_session_panel(sid, None)
        except Exception as exc:
            self._status.setText(str(exc))
