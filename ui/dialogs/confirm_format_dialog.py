"""Confirm which tracking software wrote a folder, before its sessions are added.

The second step of adding sessions (point at a folder, **confirm or amend what was found**, then
carry on). A scan has looked at the folder and ranked the readers that recognised it; this is the
user's chance to see why, change the software, fill in what the files do not record (frame rate,
frame size), leave sessions out or rename them. Nothing is added until "Add".

A thin view over :class:`~track2data.readers.confirm.ConfirmDraft`: every rule (what is missing,
what clashes, what the sessions are called) lives there. This shows its state, sends the user's
edits to it, and enables "Add" only when adding would succeed.

Three rules for a dialog the user is expected to trust:

* It is opened with ``open()`` and reports how it ended on ``finished``. ``exec()`` would block the
  GUI driver, whose modal guard patches only ``QMessageBox``.
* It installs no outside-click filter. A combo popup is a separate window, so a click on it would
  be mistaken for a click outside and dismiss the dialog while the user is choosing software.
* Escape cancels, Enter adds when that is possible, and the disabled "Add" says why in its tooltip.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import SessionRef
from track2data.readers import get_reader, reader_names
from track2data.readers.confirm import ConfirmDraft
from track2data.readers.detection import Confidence
from ui.widgets.reader_options_form import ReaderOptionsForm

_COL_INCLUDE, _COL_ID, _COL_SOURCE, _COL_NOTE = range(4)
_ROLE_ORIGINAL_ID = Qt.ItemDataRole.UserRole
_CONFIDENCE_COLOUR = {
    Confidence.HIGH: "#27ae60",
    Confidence.MEDIUM: "#e67e22",
    Confidence.LOW: "#c0392b",
}
_UNVERIFIED = (
    "Unverified: this reader was written from the format's documentation and is not yet checked "
    "against real output from the tracker. Compare a few trajectories with the "
    "tracker's own output before relying on the numbers."
)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class ConfirmFormatDialog(QDialog):
    """Show a ``ConfirmDraft`` and let the user amend it; accepted means "add these"."""

    def __init__(self, draft: ConfirmDraft, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._draft = draft
        self._syncing = False
        self.setWindowTitle("Confirm tracking software")
        self.setMinimumSize(780, 580)
        self._build()
        self._sync_all()

    # ── what the caller reads back ─────────────────────────────────────────

    @property
    def draft(self) -> ConfirmDraft:
        return self._draft

    @property
    def options_form(self) -> ReaderOptionsForm:
        return self._options_form

    def sessions(self) -> list[SessionRef]:
        """The entries to add. Only meaningful once the dialog has been accepted."""
        return self._draft.to_session_refs()

    # ── building ───────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("Confirm tracking software")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #555;")
        root.addWidget(self.summary_label)

        self.truncated_label = QLabel(
            "The scan stopped at its limit, so the folder may hold more than is listed here."
        )
        self.truncated_label.setWordWrap(True)
        self.truncated_label.setStyleSheet("color: #b9770e;")
        root.addWidget(self.truncated_label)

        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        self.empty_label.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.empty_label)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)

        group_row = QHBoxLayout()
        self._group_caption = QLabel("Found in this folder:")
        self.group_combo = QComboBox()
        group_row.addWidget(self._group_caption)
        group_row.addWidget(self.group_combo, 1)
        content.addLayout(group_row)

        reader_row = QHBoxLayout()
        reader_row.addWidget(QLabel("Software:"))
        self.reader_combo = QComboBox()
        self.confidence_label = QLabel()
        reader_row.addWidget(self.reader_combo, 1)
        reader_row.addWidget(self.confidence_label)
        content.addLayout(reader_row)

        self.unverified_label = QLabel(_UNVERIFIED)
        self.unverified_label.setWordWrap(True)
        self.unverified_label.setStyleSheet("color: #b9770e;")
        content.addWidget(self.unverified_label)

        self.evidence_label = QLabel()
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setStyleSheet("color: #666; font-size: 12px;")
        content.addWidget(self.evidence_label)

        self._options_holder = QVBoxLayout()
        self._options_form = ReaderOptionsForm([])
        self._options_holder.addWidget(self._options_form)
        content.addLayout(self._options_holder)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Session", "Source", "Note"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_INCLUDE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ID, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_NOTE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(_COL_ID, 190)
        self.table.setMinimumHeight(150)
        self.table.itemChanged.connect(self._on_item_changed)
        content.addWidget(self.table, 1)

        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: #b9770e;")
        content.addWidget(self.problems_label)
        root.addWidget(self._content, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("Add")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        root.addLayout(buttons)

        self.group_combo.currentIndexChanged.connect(self._on_group_chosen)
        self.reader_combo.currentIndexChanged.connect(self._on_reader_chosen)

    # ── showing the draft ──────────────────────────────────────────────────

    def _sync_all(self) -> None:
        result = self._draft.result
        roots = ", ".join(str(r) for r in result.roots)
        self.truncated_label.setVisible(result.truncated)
        if self._draft.is_empty:
            self._show_nothing_recognised(roots)
            return
        self.summary_label.setText(
            f"Scanned {result.entries} entries in {result.seconds:.1f} s: {roots}"
        )
        self.empty_label.hide()
        self._content.show()
        self.ok_button.show()
        self.cancel_button.setText("Cancel")
        self._sync_groups()
        self._sync_readers()
        self._sync_detection()

    def _show_nothing_recognised(self, roots: str) -> None:
        result = self._draft.result
        self.summary_label.setText(f"No tracking output was recognised in {roots}.")
        seen = ", ".join(
            f"{ext or '(no extension)'}: {n}" for ext, n in sorted(result.file_types.items())
        )
        readable = ", ".join(get_reader(name).display_name or name for name in reader_names())
        lines = [
            f"<b>{found.display_name}</b> ({found.count} found): {found.remediation}"
            for found in result.recognised
        ]
        if seen:
            lines.append(f"Files seen: {seen}.")
        lines.append(f"This version can read output from: {readable}.")
        lines.append("Folders are searched four levels deep.")
        self.empty_label.setText("<br>".join(lines))
        self.empty_label.show()
        self._content.hide()
        self.ok_button.hide()
        self.cancel_button.setText("Close")

    def _sync_groups(self) -> None:
        groups = self._draft.groups
        self._syncing = True
        try:
            self.group_combo.clear()
            for group in groups:
                best = group.best
                self.group_combo.addItem(
                    f"{best.display_name} - {_plural(len(best.sessions), 'session')}"
                )
            self.group_combo.setCurrentIndex(self._draft.group_index)
        finally:
            self._syncing = False
        visible = len(groups) > 1
        self.group_combo.setVisible(visible)
        self._group_caption.setVisible(visible)

    def _sync_readers(self) -> None:
        self._syncing = True
        try:
            self.reader_combo.clear()
            for alt in self._draft.alternatives:
                self.reader_combo.addItem(f"{alt.display_name} ({alt.confidence.name.title()})")
            names = [alt.reader for alt in self._draft.alternatives]
            self.reader_combo.setCurrentIndex(names.index(self._draft.reader))
        finally:
            self._syncing = False

    def _sync_detection(self) -> None:
        """Everything that depends on the selected reader: badges, options, sessions."""
        draft = self._draft
        colour = _CONFIDENCE_COLOUR[draft.confidence]
        self.confidence_label.setText(f"● {draft.confidence.name.title()} confidence")
        self.confidence_label.setStyleSheet(f"color: {colour}; font-weight: bold;")
        self.unverified_label.setVisible(draft.verification == "synthetic_only")
        why = "; ".join(draft.evidence)
        self.evidence_label.setText(f"Why: {why}" if why else "")
        self._rebuild_options()
        self._fill_table()
        self._update_ok()

    def _rebuild_options(self) -> None:
        draft = self._draft
        shared = [p for p in draft.parameters if p.scope == "group"]
        self._options_holder.removeWidget(self._options_form)
        self._options_form.deleteLater()
        self._options_form = ReaderOptionsForm(shared)
        self._options_holder.addWidget(self._options_form)
        sources = {p.name: draft.option_source(p.name) for p in shared}
        self._options_form.set_values(draft.options, sources)
        self._options_form.valueChanged.connect(self._on_option_edited)
        self._options_form.setVisible(not self._options_form.is_empty)

    def _fill_table(self) -> None:
        rows = self._draft.rows
        self._syncing = True
        try:
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                include = QTableWidgetItem()
                include.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                include.setCheckState(
                    Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked
                )
                include.setData(_ROLE_ORIGINAL_ID, row.original_id)
                self.table.setItem(r, _COL_INCLUDE, include)

                ident = QTableWidgetItem(row.session_id)
                ident.setData(_ROLE_ORIGINAL_ID, row.original_id)
                ident.setFlags(
                    Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                self.table.setItem(r, _COL_ID, ident)

                source = QTableWidgetItem(str(row.source))
                source.setToolTip(str(row.source))
                source.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, _COL_SOURCE, source)

                note = "already in the project" if row.already_added else "; ".join(row.warnings)
                note_item = QTableWidgetItem(note)
                note_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, _COL_NOTE, note_item)
        finally:
            self._syncing = False

    def _update_ok(self) -> None:
        problems = self._draft.problems()
        chosen = sum(1 for row in self._draft.rows if row.included)
        self.ok_button.setText(f"Add {_plural(chosen, 'session')}")
        self.ok_button.setEnabled(not problems)
        messages = [p.message for p in problems]
        self.ok_button.setToolTip("\n".join(messages))
        self.problems_label.setText("Before adding: " + " ".join(messages) if messages else "")
        self.problems_label.setVisible(bool(messages))

    # ── the user's edits ───────────────────────────────────────────────────

    def _on_group_chosen(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._draft.select_group(index)
        self._sync_readers()
        self._sync_detection()

    def _on_reader_chosen(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._draft.select_reader(self._draft.alternatives[index].reader)
        self._sync_detection()

    def _on_option_edited(self, name: str, value: Any) -> None:
        self._draft.set_option(name, value)
        self._update_ok()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing:
            return
        original = item.data(_ROLE_ORIGINAL_ID)
        if original is None:
            return
        if item.column() == _COL_INCLUDE:
            self._draft.set_included(original, item.checkState() == Qt.CheckState.Checked)
        elif item.column() == _COL_ID:
            self._draft.rename(original, item.text().strip())
        self._update_ok()
