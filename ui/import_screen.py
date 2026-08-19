"""
Stage 2 — Session import screen (M3 real widgets).

Widgets:
  • session_list   QListWidget showing imported session folders
  • add_btn        QPushButton → QFileDialog.getExistingDirectory
  • remove_btn     QPushButton → remove selected
  • status_label   QLabel  "{n} sessions imported"
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ImportScreen(QWidget):
    """Stage 2 — Import idtracker.ai session folders."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.sessionsChanged.connect(self._refresh_list)
            store.projectChanged.connect(self._refresh_list)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Sessions")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Add one or more <tt>idtracker.ai</tt> output folders."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── list ──────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setMinimumHeight(180)
        root.addWidget(self._list)

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Folders…")
        add_btn.clicked.connect(self._add_folder)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── status ─────────────────────────────────────────────────────
        self._status_label = QLabel("0 sessions imported")
        self._status_label.setStyleSheet("font-size: 13px; color: #555;")
        root.addWidget(self._status_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select session folder")
        if not directory:
            return
        folder = Path(directory)
        try:
            if self._store is not None:
                self._store.add_session(folder)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to add session:\n{exc}")

    def _remove_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        ids_to_remove = {item.data(32) for item in selected}
        if self._store is not None and self._store.manifest is not None:
            sessions = [
                s for s in self._store.manifest.sessions
                if s.session_id not in ids_to_remove
            ]
            self._store.update_sessions(sessions)

    def _refresh_list(self) -> None:
        self._list.clear()
        if self._store is None or self._store.manifest is None:
            self._status_label.setText("0 sessions imported")
            return
        sessions = self._store.manifest.sessions
        for ref in sessions:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(f"{ref.session_id}  —  {ref.folder}")
            item.setData(32, ref.session_id)
            self._list.addItem(item)
        n = len(sessions)
        self._status_label.setText(f"{n} session{'s' if n != 1 else ''} imported")
