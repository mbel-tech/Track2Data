"""
Stage 2 — Session import screen (M3 real widgets).

Widgets:
  • session_table  QTableWidget, one row per imported session
                    (session_id | reader | fps | frames | animals |
                    identity | identity-free | video), ExtendedSelection so
                    multiple rows can be removed at once
  • add_btn        QPushButton → multi-select folder dialog
  • remove_btn     QPushButton → remove every selected row
  • locate_btn     QPushButton → pick the video file for the selected session
                    (stored as ProjectManifest.video_overrides)
  • scan row       progress bar + Cancel while a folder is being looked at
  • status_label   QLabel  "{n} sessions imported"

Adding is two steps. Pointing at folders (the picker, or a drop of folders or
files) starts a background scan; when it finishes, the confirm dialog shows
which tracking software wrote them and lets the user amend that. Only the
dialog's "Add" puts sessions in the project. A scan that finds nothing still
opens the dialog (its empty state says what was seen); a scan that fails is
written inline, never as a modal.

Reader/fps/frames/animals/identity are populated from
ProjectStore.session_facts(), a cache built off the background probe that
adding a session submits (see ui/store/session_facts.py) -- they show as "—"
until that probe lands. The Reader column is the exception: it comes from the
project itself, so it still names the software after a project is reopened.

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
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from track2data.readers import find_reader
from track2data.readers.confirm import ConfirmDraft
from ui.dialogs.confirm_format_dialog import ConfirmFormatDialog

_COLUMN_HEADERS = [
    "Session ID",
    "Reader",
    "FPS",
    "Frames",
    "Animals",
    "Identity",
    "Identity-free",
    "Video",
]
(
    _COL_SESSION_ID,
    _COL_READER,
    _COL_FPS,
    _COL_FRAMES,
    _COL_ANIMALS,
    _COL_IDENTITY,
    _COL_IDENTITY_FREE,
    _COL_VIDEO,
) = range(8)
_VIDEO_FILTER = "Video files (*.mp4 *.avi *.mov *.mkv *.m4v *.mpg *.mpeg *.wmv);;All files (*)"
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
    """Stage 2 — Add sessions: point at folders, confirm the software, add."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        # Guards the Identity-free checkbox against its own refresh:
        # _refresh_table() sets check states, which emits itemChanged,
        # which would write the value straight back to the store and
        # re-enter the refresh.
        self._refreshing = False
        self._scan_id: str | None = None  # the scan whose answer is still wanted
        self._dialog: ConfirmFormatDialog | None = None
        self._build_ui()
        self.setAcceptDrops(True)
        if store is not None:
            store.sessionsChanged.connect(self._refresh_table)
            store.sessionFactsChanged.connect(self._refresh_table)
            store.projectChanged.connect(self._refresh_table)
            store.scanProgress.connect(self._on_scan_progress)
            store.scanFinished.connect(self._on_scan_finished)
            store.scanCancelled.connect(self._on_scan_cancelled)
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
            "Add the folder your tracking software wrote its output to, or drag and drop it "
            "here. Track2Data looks inside, works out which software wrote it, and asks you "
            "to confirm before anything is added."
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
        add_btn.setObjectName("add_folders")
        add_btn.clicked.connect(self._add_folders)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        self._locate_btn = QPushButton("Locate Video…")
        self._locate_btn.setToolTip(
            "Point the selected session at its video file. idtracker.ai records the path "
            "the video had on the machine it was tracked on, which is often not valid here."
        )
        self._locate_btn.clicked.connect(self._locate_video)
        self._table.itemSelectionChanged.connect(self._update_locate_enabled)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(self._locate_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        self._update_locate_enabled()

        # ── scan in progress / scan failed ────────────────────────────────
        self._scan_row = QWidget()
        scan_layout = QHBoxLayout(self._scan_row)
        scan_layout.setContentsMargins(0, 0, 0, 0)
        self._scan_label = QLabel("Looking for tracking output…")
        self._scan_bar = QProgressBar()
        self._scan_bar.setRange(0, 100)
        self._scan_cancel_btn = QPushButton("Cancel")
        self._scan_cancel_btn.clicked.connect(self._cancel_scan)
        scan_layout.addWidget(self._scan_label)
        scan_layout.addWidget(self._scan_bar, 1)
        scan_layout.addWidget(self._scan_cancel_btn)
        self._scan_row.hide()
        root.addWidget(self._scan_row)

        self._scan_message = QLabel()
        self._scan_message.setWordWrap(True)
        self._scan_message.setStyleSheet("color: #c0392b;")
        self._scan_message.hide()
        root.addWidget(self._scan_message)

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
        self._import_paths([Path(p) for p in dialog.selectedFiles()])

    # ── scan -> confirm -> add ─────────────────────────────────────────────

    def _import_paths(self, paths) -> None:
        """Start looking at *paths*; the confirm dialog follows when the scan is done."""
        if self._store is None or not paths:
            return
        if self._scan_id is not None:  # a newer pick replaces one still running
            self._store.cancel_scan(self._scan_id)
        self._scan_message.hide()
        self._scan_label.setText("Looking for tracking output…")
        self._scan_bar.setValue(0)
        self._scan_row.show()
        self._scan_id = self._store.scan_folders(list(paths))

    def _cancel_scan(self) -> None:
        if self._store is not None and self._scan_id is not None:
            self._store.cancel_scan(self._scan_id)

    def _on_scan_progress(self, task_id: str, event) -> None:
        if task_id != self._scan_id:
            return
        if event.message:
            self._scan_label.setText(event.message)
        self._scan_bar.setValue(event.percent)

    def _on_scan_cancelled(self, task_id: str) -> None:
        if task_id == self._scan_id:
            self._scan_id = None
            self._scan_row.hide()

    def _on_scan_finished(self, task_id: str, result) -> None:
        if task_id != self._scan_id:
            return  # the answer to a scan that has been replaced
        self._scan_id = None
        self._scan_row.hide()
        if isinstance(result, Exception):
            self._scan_message.setText(f"Could not look at that folder: {result}")
            self._scan_message.show()
            return
        existing = list(self._store.manifest.sessions) if self._store.manifest else []
        dialog = ConfirmFormatDialog(ConfirmDraft(result, existing=existing), self)
        dialog.finished.connect(lambda code, d=dialog: self._on_confirm_finished(d, code))
        self._dialog = dialog
        # open(), never exec(): exec() would block the GUI driver's event loop.
        dialog.open()

    def _on_confirm_finished(self, dialog: ConfirmFormatDialog, code: int) -> None:
        if self._dialog is dialog:
            self._dialog = None
        if code == ConfirmFormatDialog.DialogCode.Accepted and self._store is not None:
            self._store.add_confirmed(dialog.sessions())
        dialog.deleteLater()

    # ── drag and drop ────────────────────────────────────────────────────

    def _paths_in(self, event) -> list[Path]:
        """What was dragged: folders, and single tracking files (some trackers write one)."""
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = (Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())
        return [p for p in paths if p.exists()]

    def dragEnterEvent(self, event) -> None:
        if self._paths_in(event):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._paths_in(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)

    def dropEvent(self, event) -> None:
        self._set_drag_active(False)
        paths = self._paths_in(event)
        if paths:
            self._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _set_drag_active(self, active: bool) -> None:
        # Blue-border feedback on drag-over, per UI_DESIGN.md §6.2.
        self._table.setStyleSheet("QTableWidget { border: 2px solid #2980b9; }" if active else "")

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
                s for s in self._store.manifest.sessions if s.session_id not in ids_to_remove
            ]
            self._store.update_sessions(sessions)

    def _selected_session_id(self) -> str | None:
        """The session id of the single selected row, else None."""
        rows = {index.row() for index in self._table.selectionModel().selectedIndexes()}
        if len(rows) != 1:
            return None
        item = self._table.item(next(iter(rows)), _COL_SESSION_ID)
        return None if item is None else item.data(_ROLE_SESSION_ID)

    def _update_locate_enabled(self) -> None:
        self._locate_btn.setEnabled(
            self._store is not None and self._selected_session_id() is not None
        )

    def _locate_video(self) -> None:
        session_id = self._selected_session_id()
        if self._store is None or session_id is None:
            return
        ref = next(
            (s for s in self._store.manifest.sessions if s.session_id == session_id), None
        )
        start = str(ref.folder) if ref is not None else ""
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Locate video for {session_id}", start, _VIDEO_FILTER
        )
        if not chosen:
            return
        try:
            self._store.set_video_path(session_id, Path(chosen))
        except (OSError, KeyError) as exc:
            QMessageBox.warning(self, "Locate video", str(exc))

    def _video_cell(self, ref, facts) -> tuple[str, str]:
        """(text, tooltip) for the Video column."""
        override = (
            self._store.manifest.video_overrides.get(ref.session_id)
            if self._store is not None and self._store.manifest is not None
            else None
        )
        if override is not None and Path(override).exists():
            return "Located", str(override)
        if facts is None:
            return _PLACEHOLDER, "Reading the session folder…"
        if facts.video_path is not None:
            return "Found", str(facts.video_path)
        return (
            "Not found",
            "The video path idtracker.ai recorded does not exist on this machine. "
            "Select the session and use Locate Video… to point at the file.",
        )

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
    def _reader_label(name: str) -> str:
        """The reader's display name; the bare name for one this version no longer has."""
        reader = find_reader(name)
        return (reader.display_name or name) if reader is not None else name

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
            saved_reader = self._reader_label(ref.reader) if ref.reader else None
            if facts is None:
                values = [saved_reader or _PLACEHOLDER] + [_PLACEHOLDER] * 4
            else:
                values = [
                    saved_reader or facts.reader,
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
                Qt.CheckState.Checked if ref.is_identity_free() else Qt.CheckState.Unchecked
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
            text, tip = self._video_cell(ref, facts)
            video_item = QTableWidgetItem(text)
            video_item.setToolTip(tip)
            self._table.setItem(row, _COL_VIDEO, video_item)
        n = len(sessions)
        self._status_label.setText(f"{n} session{'s' if n != 1 else ''} imported")
