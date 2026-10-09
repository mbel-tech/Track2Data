"""Views page (3-D projects only): assign view roles and pair the two views."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import PairingPatterns
from track2data.views.pairing import pair_by_regex
from ui.widgets.autocommit import AutoCommit
from ui.widgets.regex_help import RegexHelpPopover
from ui.widgets.weak_slot import weak_slot

ROLE_ITEMS = (("(not set)", None), ("Top", "top"), ("Side", "side"))
EMPTY_TEXT = "Open a 3-D project and add sessions to set up the views."


class ViewsScreen(QWidget):
    """Roles per session and the name patterns that pair top with side sessions."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Views")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        lead = QLabel("Say which session is the top view and which is the side view.")
        lead.setObjectName("PageLead")
        lead.setWordWrap(True)
        lead.setMaximumWidth(600)
        root.addWidget(lead)

        self._empty_label = QLabel(EMPTY_TEXT)
        self._empty_label.setObjectName("PageLead")
        self._empty_label.setWordWrap(True)
        root.addWidget(self._empty_label)

        self._role_table = QTableWidget(0, 2)
        self._role_table.setObjectName("ViewsRoleTable")
        self._role_table.setHorizontalHeaderLabels(["Session", "View"])
        self._role_table.horizontalHeader().setStretchLastSection(True)
        self._role_table.verticalHeader().setVisible(False)
        self._role_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._role_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        root.addWidget(self._role_table, 1)

        self._pattern_box = QWidget()
        pbox = QVBoxLayout(self._pattern_box)
        pbox.setContentsMargins(0, 0, 0, 0)
        pbox.setSpacing(8)
        heading = QLabel("Pair by session name")
        heading.setObjectName("SectionTitle")
        pbox.addWidget(heading)
        self._top_regex_edit, self._top_help_btn = self._pattern_row(
            pbox, "Top sessions", "(?P<key>.+)_top$"
        )
        self._side_regex_edit, self._side_help_btn = self._pattern_row(
            pbox, "Side sessions", "(?P<key>.+)_side$"
        )
        self._error_label = QLabel("")
        self._error_label.setObjectName("ErrorLabel")
        self._error_label.setWordWrap(True)
        pbox.addWidget(self._error_label)
        self._match_label = QLabel("")
        self._match_label.setObjectName("MatchLabel")
        pbox.addWidget(self._match_label)
        self._unpaired_label = QLabel("")
        self._unpaired_label.setObjectName("UnpairedLabel")
        self._unpaired_label.setWordWrap(True)
        pbox.addWidget(self._unpaired_label)
        self._apply_btn = QPushButton("Pair by pattern")
        self._apply_btn.setObjectName("PrimaryButton")
        self._apply_btn.clicked.connect(self._apply_pairing)
        row = QHBoxLayout()
        row.addWidget(self._apply_btn)
        row.addStretch(1)
        pbox.addLayout(row)
        root.addWidget(self._pattern_box)

        self._popover = RegexHelpPopover(self)
        self._top_help_btn.clicked.connect(weak_slot(self._show_help, self._top_help_btn))
        self._side_help_btn.clicked.connect(weak_slot(self._show_help, self._side_help_btn))

        self._commit = AutoCommit(self._commit_patterns, self)
        for edit in (self._top_regex_edit, self._side_regex_edit):
            edit.textChanged.connect(self._commit.trigger)
            edit.textChanged.connect(self._update_matches)

        if store is not None:
            store.projectChanged.connect(self._refresh)
            store.sessionsChanged.connect(self._refresh)
            store.modeChanged.connect(self._refresh)
            store.viewsChanged.connect(self._refresh)
        self._refresh()

    def _pattern_row(self, layout: QVBoxLayout, caption: str, placeholder: str):
        row = QHBoxLayout()
        label = QLabel(caption)
        label.setMinimumWidth(110)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        btn = QToolButton()
        btn.setText("ⓘ")
        btn.setToolTip("What is a pattern?")
        row.addWidget(label)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        layout.addLayout(row)
        return edit, btn

    # ── store helpers ──────────────────────────────────────────────────────

    def _manifest(self):
        return None if self._store is None else self._store.manifest

    def _is_3d(self) -> bool:
        m = self._manifest()
        return m is not None and m.mode.dimension == "3d"

    # ── refresh from the store (never writes back) ─────────────────────────

    def _refresh(self) -> None:
        m = self._manifest()
        sessions = list(m.sessions) if m is not None and self._is_3d() else []
        self._empty_label.setVisible(not sessions)
        self._role_table.setVisible(bool(sessions))
        self._pattern_box.setVisible(self._is_3d())
        with self._commit.suppressed():
            self._fill_roles(sessions)
            patterns = m.mode.pairing if m is not None else PairingPatterns()
            for edit, text in (
                (self._top_regex_edit, patterns.top_regex),
                (self._side_regex_edit, patterns.side_regex),
            ):
                if edit.text() != text and not edit.hasFocus():
                    edit.blockSignals(True)
                    edit.setText(text)
                    edit.blockSignals(False)
        self._update_matches()

    def _fill_roles(self, sessions) -> None:
        table = self._role_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(sessions))
            for row, ref in enumerate(sessions):
                item = QTableWidgetItem(ref.session_id)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row, 0, item)
                combo = QComboBox()
                for text, _ in ROLE_ITEMS:
                    combo.addItem(text)
                combo.setCurrentIndex([r for _, r in ROLE_ITEMS].index(ref.view_role))
                combo.currentIndexChanged.connect(
                    weak_slot(self._on_role_changed, ref.session_id, combo)
                )
                table.setCellWidget(row, 1, combo)
        finally:
            table.blockSignals(False)

    def _on_role_changed(self, session_id: str, combo: QComboBox) -> None:
        role = ROLE_ITEMS[combo.currentIndex()][1]
        try:
            self._store.update_view_role(session_id, role)
        except ValueError as exc:
            self._error_label.setText(str(exc))

    # ── patterns ───────────────────────────────────────────────────────────

    def _session_ids(self) -> list[str]:
        m = self._manifest()
        return [s.session_id for s in m.sessions] if m is not None else []

    def _update_matches(self, *_args: object) -> None:
        result = pair_by_regex(
            self._session_ids(), self._top_regex_edit.text(), self._side_regex_edit.text()
        )
        self._error_label.setText("; ".join(result.errors))
        self._match_label.setText(
            f"Top pattern catches {len(result.top_ids)} sessions"
            f" · side pattern catches {len(result.side_ids)} sessions"
        )
        lines = []
        if result.unpaired_top or result.unpaired_side:
            lines.append("Unpaired: " + ", ".join(result.unpaired_top + result.unpaired_side))
        if result.ambiguous_keys:
            keys = ", ".join(result.ambiguous_keys)
            lines.append("Ambiguous (several sessions share a key): " + keys)
        if result.both_roles:
            lines.append("Match both patterns: " + ", ".join(result.both_roles))
        self._unpaired_label.setText("\n".join(lines))

    def _commit_patterns(self) -> None:
        if not self._is_3d():
            return
        self._store.update_pairing(
            PairingPatterns(
                top_regex=self._top_regex_edit.text(), side_regex=self._side_regex_edit.text()
            )
        )

    def _apply_pairing(self) -> None:
        if not self._is_3d():
            return
        self._commit.flush()
        result = self._store.apply_regex_pairing()
        self._error_label.setText("; ".join(result.errors))

    def _show_help(self, button: QToolButton) -> None:
        self._popover.move(button.mapToGlobal(button.rect().bottomLeft()))
        self._popover.show()
