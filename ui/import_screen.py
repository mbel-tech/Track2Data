"""
Stage 2 — Session import screen (M3 real widgets).

Widgets:
  • session_table  QTableWidget, one row per imported session
                    (session_id | reader | fps | frames | animals |
                    identity | identity-free), ExtendedSelection so
                    multiple rows can be removed at once
  • add_btn        QPushButton → multi-select folder dialog
  • remove_btn     QPushButton → remove every selected row
  • status_label   QLabel  "{n} sessions imported"

Also accepts folders dropped directly onto the screen (setAcceptDrops)
-- see dragEnterEvent/dragMoveEvent/dropEvent below.

Reader/fps/frames/animals/identity are populated from
ProjectStore.session_facts(), a cache built off the same background
read_session() probe add_session() already submits (see
ui/store/session_facts.py) -- they show as "—" until that probe lands.

The Identity-free column is the one editable cell on this screen. It
starts from what idtracker.ai declared (session.json's
``track_wo_identities``) and the user can overrule it, because the
tracker only knows whether it was *asked* to assign identities -- not
whether the identities it produced are trustworthy enough to build
per-individual metrics on. Ticking it makes Engine.compute_metrics
refuse every metric whose ``requires_identity`` is True for that session,
and greys those rows on the Metrics screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

_COLUMN_HEADERS = [
    "Session ID", "Reader", "FPS", "Frames", "Animals", "Identity", "Identity-free",
]
(
    _COL_SESSION_ID,
    _COL_READER,
    _COL_FPS,
    _COL_FRAMES,
    _COL_ANIMALS,
    _COL_IDENTITY,
    _COL_IDENTITY_FREE,
) = range(7)
_ROLE_SESSION_ID = Qt.ItemDataRole.UserRole
_PLACEHOLDER = "—"

# Captured from the real QFileDialog at import time, before
# ui.import_screen.QFileDialog can be monkeypatched by a test double
# (see test_import_screen.py's _FakeMultiSelectDialog) -- referencing
# QFileDialog.<enum> directly inside _add_folders would break under
# that patch, since the double only defines the methods it stands in
# for, not the enum namespaces.
_DIALOG_ACCEPTED = QFileDialog.DialogCode.Accepted
_FILE_MODE_DIRECTORY = QFileDialog.FileMode.Directory
_OPTION_DONT_USE_NATIVE = QFileDialog.Option.DontUseNativeDialog


class ImportScreen(QWidget):
    """Stage 2 — Import idtracker.ai session folders."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        # Guards the Identity-free checkbox against its own refresh:
        # _refresh_table() sets check states, which emits itemChanged,
        # which would write the value straight back to the store and
        # re-enter the refresh.
        self._refreshing = False
        self._build_ui()
        self.setAcceptDrops(True)
        if store is not None:
            store.sessionsChanged.connect(self._refresh_table)
            store.sessionFactsChanged.connect(self._refresh_table)
            store.projectChanged.connect(self._refresh_table)
        # A screen built against a store that already has sessions (e.g.
        # navigating back to this page) must show them immediately, not
        # only after the next signal -- the constructor never called
        # this before, so a populated store rendered an empty table.
        self._refresh_table()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Sessions")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Add one or more <tt>idtracker.ai</tt> output folders, "
            "or drag and drop them here."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── table ─────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_COLUMN_HEADERS))
        self._table.setHorizontalHeaderLabels(_COLUMN_HEADERS)
        self._table.setMinimumHeight(180)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self._table.horizontalHeader()
        # Session ID stretches rather than the last column: the last column
        # is now the Identity-free checkbox, which needs no more than its
        # header width, while session ids ("session_trial10_Segment1") were
        # being elided to fit a fixed slice.
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_SESSION_ID, QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self._table)

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Folders…")
        add_btn.clicked.connect(self._add_folders)
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

    # ── multi-folder dialog ───────────────────────────────────────────────

    def _add_folders(self) -> None:
        # PySide6 has no getExistingDirectories() counterpart to Qt's
        # C++-only QFileDialog::getExistingDirectories() -- a native
        # directory picker only ever returns one folder. Multi-select
        # requires a non-native dialog with ExtendedSelection forced
        # onto its internal view. This looks like a hack because it is
        # one; do not "simplify" it back to a single-folder picker.
        dialog = QFileDialog(self, "Select session folders")
        dialog.setFileMode(_FILE_MODE_DIRECTORY)
        dialog.setOption(_OPTION_DONT_USE_NATIVE, True)
        for view_cls in (QListView, QTreeView):
            for view in dialog.findChildren(view_cls):
                view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        if dialog.exec() != _DIALOG_ACCEPTED:
            return
        self._import_folders(Path(p) for p in dialog.selectedFiles())

    def _import_folders(self, folders) -> None:
        if self._store is None:
            return
        failed: list[str] = []
        for folder in folders:
            try:
                self._store.add_session(folder)
            except Exception as exc:
                failed.append(f"{folder}: {exc}")
        if failed:
            QMessageBox.critical(
                self, "Error", "Failed to add session(s):\n" + "\n".join(failed)
            )

    # ── drag and drop ────────────────────────────────────────────────────

    def _directories_in(self, event) -> list[Path]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = (Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())
        return [p for p in paths if p.is_dir()]

    def dragEnterEvent(self, event) -> None:
        if self._directories_in(event):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._directories_in(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)

    def dropEvent(self, event) -> None:
        self._set_drag_active(False)
        folders = self._directories_in(event)
        if folders:
            self._import_folders(folders)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _set_drag_active(self, active: bool) -> None:
        # Blue-border feedback on drag-over, per UI_DESIGN.md §6.2.
        self._table.setStyleSheet(
            "QTableWidget { border: 2px solid #2980b9; }" if active else ""
        )

    # ── slots ──────────────────────────────────────────────────────────────

    def _remove_selected(self) -> None:
        rows = {index.row() for index in self._table.selectionModel().selectedIndexes()}
        if not rows:
            return
        ids_to_remove = {
            self._table.item(row, _COL_SESSION_ID).data(_ROLE_SESSION_ID) for row in rows
        }
        if self._store is not None and self._store.manifest is not None:
            sessions = [
                s for s in self._store.manifest.sessions
                if s.session_id not in ids_to_remove
            ]
            self._store.update_sessions(sessions)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Write an Identity-free toggle back to the store.

        Sets an explicit override in both directions, including one that
        agrees with the tracker: an explicit "no, this session is fine"
        is a different statement from "never asked", and re-probing must
        not silently discard it.
        """
        if self._refreshing or item.column() != _COL_IDENTITY_FREE:
            return
        if self._store is None:
            return
        session_id = item.data(_ROLE_SESSION_ID)
        if session_id is None:
            return
        self._store.set_session_identity_free(
            session_id, item.checkState() == Qt.CheckState.Checked
        )

    @staticmethod
    def _identity_free_tooltip(ref, facts) -> str:
        if facts is None:
            return "Reading the session folder…"
        declared = facts.track_wo_identities
        if declared is True:
            detected = "idtracker.ai tracked this session without identification."
        elif declared is False:
            detected = "idtracker.ai tracked this session with identification."
        else:
            detected = "This session's format does not report how it was tracked."

        if ref.identity_free_override is None:
            return (
                f"{detected} Tick this to treat the session as identity-free anyway "
                "— identity-dependent metrics will then be skipped for it."
            )
        if ref.identity_free_override:
            return (
                f"{detected} You have marked it identity-free: identity-dependent "
                "metrics will be skipped for this session."
            )
        return (
            f"{detected} You have marked it identity-preserving: identity-dependent "
            "metrics will be computed for this session."
        )

    def _refresh_table(self) -> None:
        self._refreshing = True
        try:
            self._populate_table()
        finally:
            self._refreshing = False

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        if self._store is None or self._store.manifest is None:
            self._status_label.setText("0 sessions imported")
            return
        sessions = self._store.manifest.sessions
        self._table.setRowCount(len(sessions))
        for row, ref in enumerate(sessions):
            facts = self._store.session_facts(ref.session_id)
            id_item = QTableWidgetItem(ref.session_id)
            id_item.setData(_ROLE_SESSION_ID, ref.session_id)
            self._table.setItem(row, _COL_SESSION_ID, id_item)
            if facts is None:
                values = [_PLACEHOLDER] * 5
            else:
                values = [
                    facts.reader,
                    str(facts.fps),
                    str(facts.n_frames),
                    str(facts.n_animals),
                    "Stable" if facts.has_stable_identities else "Unstable",
                ]
            for col, value in zip(
                (_COL_READER, _COL_FPS, _COL_FRAMES, _COL_ANIMALS, _COL_IDENTITY),
                values,
                strict=True,
            ):
                self._table.setItem(row, col, QTableWidgetItem(value))

            free_item = QTableWidgetItem()
            free_item.setData(_ROLE_SESSION_ID, ref.session_id)
            # setCheckState() before setFlags(): Qt turns ItemIsUserCheckable
            # back on as a side effect of setting a check state, so clearing
            # it first would be silently undone.
            free_item.setCheckState(
                Qt.CheckState.Checked
                if ref.is_identity_free()
                else Qt.CheckState.Unchecked
            )
            flags = free_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            # Not checkable until the probe has landed: before that the box
            # would show unchecked for a genuinely identity-free session,
            # and a user who ticked it would be overriding a value they have
            # not been shown yet.
            if facts is None:
                flags &= ~(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            else:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            free_item.setFlags(flags)
            free_item.setToolTip(self._identity_free_tooltip(ref, facts))
            self._table.setItem(row, _COL_IDENTITY_FREE, free_item)
        n = len(sessions)
        self._status_label.setText(f"{n} session{'s' if n != 1 else ''} imported")
