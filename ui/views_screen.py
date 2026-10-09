"""Views page (3-D projects only): assign view roles and pair the two views."""

from __future__ import annotations

import functools

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import PairingPatterns, ViewPair
from track2data.views.pairing import (
    fish_labels,
    identity_map,
    pair_by_regex,
    validate_fish_map,
)
from ui.preview_screen import TrajectoryData, load_trajectory_data
from ui.widgets.autocommit import AutoCommit
from ui.widgets.regex_help import RegexHelpPopover
from ui.widgets.trajectory_view import TrajectoryView
from ui.widgets.weak_slot import weak_slot

ROLE_ITEMS = (("(not set)", None), ("Top", "top"), ("Side", "side"))
NEEDS_MATCHING = "Needs matching"
NO_MATCH = "(no match)"
USED_MARK = " (used)"
EMPTY_TEXT = "Open a 3-D project and add sessions to set up the views."


class ViewsScreen(QWidget):
    """Roles per session and the name patterns that pair top with side sessions."""

    # (top_id, side_id) or None: a user change, or None when the selected pair vanishes
    pairSelected = Signal(object)

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

        self._pairs_box = QWidget()
        pairs_lay = QVBoxLayout(self._pairs_box)
        pairs_lay.setContentsMargins(0, 0, 0, 0)
        pairs_lay.setSpacing(8)
        pairs_heading = QLabel("Pairs")
        pairs_heading.setObjectName("SectionTitle")
        pairs_lay.addWidget(pairs_heading)
        self._pairs_table = QTableWidget(0, 5)
        self._pairs_table.setObjectName("ViewsPairsTable")
        self._pairs_table.setHorizontalHeaderLabels(
            ["Top session", "Side session", "Same IDs", "Status", ""]
        )
        self._pairs_table.horizontalHeader().setStretchLastSection(False)
        self._pairs_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._pairs_table.verticalHeader().setVisible(False)
        self._pairs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pairs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pairs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        pairs_lay.addWidget(self._pairs_table)
        manual = QHBoxLayout()
        self._manual_top_combo = QComboBox()
        self._manual_side_combo = QComboBox()
        self._manual_add_btn = QPushButton("Add pair")
        manual.addWidget(QLabel("Top"))
        manual.addWidget(self._manual_top_combo, 1)
        manual.addWidget(QLabel("Side"))
        manual.addWidget(self._manual_side_combo, 1)
        manual.addWidget(self._manual_add_btn)
        pairs_lay.addLayout(manual)
        root.addWidget(self._pairs_box)

        self._match_box = QWidget()
        mbox = QVBoxLayout(self._match_box)
        mbox.setContentsMargins(0, 0, 0, 0)
        mbox.setSpacing(8)
        match_heading = QLabel("Match fish")
        match_heading.setObjectName("SectionTitle")
        mbox.addWidget(match_heading)
        self._match_table = QTableWidget(0, 2)
        self._match_table.setObjectName("ViewsMatchTable")
        self._match_table.setHorizontalHeaderLabels(["Top fish", "Side fish"])
        self._match_table.horizontalHeader().setStretchLastSection(True)
        self._match_table.verticalHeader().setVisible(False)
        self._match_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._match_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._match_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self._match_table)
        self._match_issues = QLabel("")
        self._match_issues.setObjectName("ErrorLabel")
        self._match_issues.setWordWrap(True)
        left.addWidget(self._match_issues)
        self._match_status = QLabel("")
        self._match_status.setObjectName("PageLead")
        self._match_status.setWordWrap(True)
        left.addWidget(self._match_status)
        plots = QHBoxLayout()
        self._top_plot = TrajectoryView()
        self._side_plot = TrajectoryView()
        for plot in (self._top_plot, self._side_plot):
            plot.setMinimumHeight(200)
            plots.addWidget(plot, 1)
        body.addLayout(left, 1)
        body.addLayout(plots, 2)
        mbox.addLayout(body)
        self._match_box.setVisible(False)
        root.addWidget(self._match_box)
        self._load_tasks: dict[str, str] = {}
        self._match_table.itemSelectionChanged.connect(weak_slot(self._apply_highlight))
        self.pairSelected.connect(self._on_pair_selected)
        self._rebuilding = False
        self._last_pair: tuple[str, str] | None = None
        self._force_emit = False
        self._match_key: tuple[str, str] | None = None
        self._loaded_facts: object = None
        self._pairs_table.itemSelectionChanged.connect(self._on_pair_selection)
        self._manual_add_btn.clicked.connect(self._add_manual_pair)

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
            store.projectChanged.connect(self._on_project_changed)
            store.sessionsChanged.connect(self._refresh)
            store.modeChanged.connect(self._refresh)
            store.viewsChanged.connect(self._refresh)
            store.sessionFactsChanged.connect(self._on_facts_changed)
            store.taskFinished.connect(self._on_traj_task_finished)
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
        self._pairs_box.setVisible(self._is_3d())
        with self._commit.suppressed():
            self._fill_roles(sessions)
            self._fill_pairs(sessions)
            patterns = m.mode.pairing if m is not None else PairingPatterns()
            for edit, text in (
                (self._top_regex_edit, patterns.top_regex),
                (self._side_regex_edit, patterns.side_regex),
            ):
                if edit.text() != text and not edit.hasFocus():
                    edit.blockSignals(True)
                    edit.setText(text)
                    edit.blockSignals(False)
        self._fill_match()
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

    # ── pairs ──────────────────────────────────────────────────────────────

    @property
    def _current_pair(self) -> tuple[str, str] | None:
        rows = self._pairs_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        top, side = self._pairs_table.item(row, 0), self._pairs_table.item(row, 1)
        return (top.text(), side.text()) if top and side else None

    def _labels(self, session_id: str) -> list[str]:
        facts = self._store.session_facts(session_id)
        return fish_labels(
            facts.identities_labels if facts else None, facts.n_animals if facts else 0
        )

    def _pair_state(self, pair: ViewPair, free: set[str]):
        """(status text, tooltip) for one pair."""
        top_l, side_l = self._labels(pair.top_session_id), self._labels(pair.side_session_id)
        msgs = validate_fish_map(
            pair.fish_map,
            top_l,
            side_l,
            top_identity_free=pair.top_session_id in free,
            side_identity_free=pair.side_session_id in free,
        )
        if msgs:
            return msgs[0], "\n".join(msgs)
        if not pair.fish_map:
            return NEEDS_MATCHING, ""
        left_top = [x for x in top_l if x not in pair.fish_map]
        left_side = [x for x in side_l if x not in set(pair.fish_map.values())]
        tip = ""
        if left_top or left_side:
            tip = (
                "Not matched: top " + (", ".join(left_top) or "none")
                + "; side " + (", ".join(left_side) or "none")
            )
        return "Matched", tip

    def _fill_pairs(self, sessions) -> None:
        table = self._pairs_table
        m = self._manifest()
        pairs = list(m.view_pairs) if m is not None and self._is_3d() else []
        free = {s.session_id for s in sessions if s.is_identity_free()}
        keep = self._last_pair
        self._rebuilding = True
        table.blockSignals(True)
        try:
            table.clearSelection()
            table.setRowCount(len(pairs))
            for row, pair in enumerate(pairs):
                for col, text in enumerate((pair.top_session_id, pair.side_session_id)):
                    item = QTableWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    table.setItem(row, col, item)
                status, tip = self._pair_state(pair, free)
                st = QTableWidgetItem(status)
                st.setToolTip(tip)
                st.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                table.setItem(row, 3, st)
                tick = QCheckBox()
                tick.setChecked(pair.same_ids)
                tick.setEnabled(
                    pair.top_session_id not in free and pair.side_session_id not in free
                )
                tick.toggled.connect(weak_slot(self._on_same_ids, pair.top_session_id,
                                               pair.side_session_id, tick))
                table.setCellWidget(row, 2, tick)
                btn = QPushButton("Remove")
                btn.clicked.connect(
                    weak_slot(self._remove_pair, pair.top_session_id, pair.side_session_id)
                )
                table.setCellWidget(row, 4, btn)
            table.setCurrentCell(-1, -1)
            table.clearSelection()
            for row, pair in enumerate(pairs):
                if keep == (pair.top_session_id, pair.side_session_id):
                    table.selectRow(row)
        finally:
            table.blockSignals(False)
            self._rebuilding = False
        self._fill_manual(sessions, pairs)
        now = self._current_pair
        force, self._force_emit = self._force_emit, False
        if now != self._last_pair or force:
            self._last_pair = now
            self.pairSelected.emit(now)

    def _fill_manual(self, sessions, pairs) -> None:
        used = {sid for p in pairs for sid in (p.top_session_id, p.side_session_id)}
        for combo, role in ((self._manual_top_combo, "top"), (self._manual_side_combo, "side")):
            ids = [
                s.session_id
                for s in sessions
                if s.view_role == role and s.session_id not in used
            ]
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(ids)
            if previous in ids:
                combo.setCurrentText(previous)
            combo.blockSignals(False)
        self._manual_add_btn.setEnabled(
            self._manual_top_combo.count() > 0 and self._manual_side_combo.count() > 0
        )

    def _on_pair_selection(self) -> None:
        if self._rebuilding:
            return
        now = self._current_pair
        if now != self._last_pair:
            self._last_pair = now
            self.pairSelected.emit(now)

    def _find_pair(self, top_id: str, side_id: str) -> ViewPair | None:
        m = self._manifest()
        for p in m.view_pairs if m is not None else []:
            if (p.top_session_id, p.side_session_id) == (top_id, side_id):
                return p
        return None

    def _on_same_ids(self, top_id: str, side_id: str, tick: QCheckBox) -> None:
        pair = self._find_pair(top_id, side_id)
        if pair is None or not tick.isEnabled():
            return
        if tick.isChecked():
            shared, _ = identity_map(self._labels(top_id), self._labels(side_id))
            update = {"same_ids": True, "fish_map": shared}
        else:
            update = {"same_ids": False}
        try:
            self._store.update_view_pair(pair.model_copy(update=update))
        except ValueError as exc:
            self._refresh()
            self._error_label.setText(str(exc))

    def _remove_pair(self, top_id: str, side_id: str) -> None:
        self._store.remove_view_pair(top_id, side_id)

    def _add_manual_pair(self) -> None:
        top, side = self._manual_top_combo.currentText(), self._manual_side_combo.currentText()
        if not top or not side:
            return
        try:
            self._store.update_view_pair(ViewPair(top_session_id=top, side_session_id=side))
        except ValueError as exc:
            self._error_label.setText(str(exc))

    # ── manual matching ────────────────────────────────────────────────────

    def _facts_of(self, pair: object) -> object:
        if not pair or self._store is None:
            return None
        return tuple(self._store.session_facts(sid) for sid in pair)

    def _on_project_changed(self) -> None:
        # A new project: drop in-flight loads and stale tracks, and make a
        # still-valid selection (same ids) re-emit so it reloads.
        self._load_tasks = {}
        self._top_plot.clear()
        self._side_plot.clear()
        self._force_emit = True
        self._refresh()

    def _on_facts_changed(self) -> None:
        pair = self._current_pair
        if pair is not None and self._facts_of(pair) != self._loaded_facts:
            self._force_emit = True
        self._refresh()
        self._force_emit = False

    def _on_pair_selected(self, pair: object) -> None:
        """Idempotent; None clears the panel. Never writes to the store."""
        self._load_tasks = {}
        self._match_key = None
        self._top_plot.clear()
        self._side_plot.clear()
        self._loaded_facts = self._facts_of(pair)
        self._match_status.setText("")
        if not pair or self._store is None or self._store.manifest is None:
            self._match_box.setVisible(False)
            self._fill_match()
            return
        self._match_box.setVisible(True)
        self._fill_match()
        top_id, side_id = pair
        self._match_status.setText("Loading tracks…")
        for role, sid in (("top", top_id), ("side", side_id)):
            fn = functools.partial(
                load_trajectory_data, self._store.manifest, sid, self._store.cache_dir
            )
            self._load_tasks[self._store.tasks.submit(fn)] = role

    def _on_traj_task_finished(self, task_id: str, result: object) -> None:
        role = self._load_tasks.pop(task_id, None)
        if role is None:
            return
        if isinstance(result, Exception) or not isinstance(result, TrajectoryData):
            self._match_status.setText(f"Could not load {role} tracks: {result}")
            return
        plot = self._top_plot if role == "top" else self._side_plot
        plot.set_data(
            result.raw_xy, result.xy, result.fps,
            background_path=result.background, size=result.size,
        )
        plot.set_trail_length(plot.n_frames)
        plot.set_frame(plot.n_frames - 1)
        if not self._load_tasks and not self._match_status.text().startswith("Could not"):
            self._match_status.setText("Select a fish to highlight it in both views.")

    def _fill_match(self) -> None:
        """Rebuild the matching table from the store (no store writes)."""
        table = self._match_table
        pair = self._find_pair(*self._current_pair) if self._current_pair else None
        keep = table.selectionModel().selectedRows()
        keep_row = keep[0].row() if keep else None
        key = (pair.top_session_id, pair.side_session_id) if pair else None
        if key != self._match_key:
            keep_row = None
        self._match_key = key
        table.blockSignals(True)
        try:
            table.clearSelection()
            if pair is None:
                table.setRowCount(0)
                table.setEnabled(True)
                self._match_issues.setText("")
                return
            top_l = self._labels(pair.top_session_id)
            side_l = self._labels(pair.side_session_id)
            free = {s.session_id for s in self._manifest().sessions if s.is_identity_free()}
            msgs = validate_fish_map(
                pair.fish_map, top_l, side_l,
                top_identity_free=pair.top_session_id in free,
                side_identity_free=pair.side_session_id in free,
            )
            self._match_issues.setText("\n".join(msgs))
            table.setEnabled(not (pair.top_session_id in free or pair.side_session_id in free))
            table.setRowCount(len(top_l))
            for row, label in enumerate(top_l):
                item = QTableWidgetItem(label)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                table.setItem(row, 0, item)
                chosen = pair.fish_map.get(label)
                used = {v for k, v in pair.fish_map.items() if k != label}
                combo = QComboBox()
                combo.blockSignals(True)
                combo.addItem(NO_MATCH, None)
                for side in side_l:
                    combo.addItem(side + (USED_MARK if side in used else ""), side)
                combo.setCurrentIndex(side_l.index(chosen) + 1 if chosen in side_l else 0)
                combo.blockSignals(False)
                combo.currentIndexChanged.connect(weak_slot(self._on_match_changed, label, combo))
                table.setCellWidget(row, 1, combo)
            if keep_row is not None and keep_row < len(top_l) and table.isEnabled():
                table.selectRow(keep_row)
        finally:
            table.blockSignals(False)
        self._apply_highlight()

    def _on_match_changed(self, top_label: str, combo: QComboBox) -> None:
        cur = self._current_pair
        pair = self._find_pair(*cur) if cur else None
        if pair is None:
            return
        fish_map = dict(pair.fish_map)
        side = combo.currentData()
        if side is None:
            fish_map.pop(top_label, None)
        else:
            fish_map[top_label] = side
        try:
            self._store.update_view_pair(pair.model_copy(update={"fish_map": fish_map}))
        except ValueError as exc:
            self._refresh()
            self._match_issues.setText(str(exc))

    def _apply_highlight(self) -> None:
        rows = self._match_table.selectionModel().selectedRows()
        cur = self._current_pair
        pair = self._find_pair(*cur) if cur else None
        if not rows or pair is None:
            self._top_plot.set_highlight(None)
            self._side_plot.set_highlight(None)
            return
        row = rows[0].row()
        top_l = self._labels(pair.top_session_id)
        side_l = self._labels(pair.side_session_id)
        mapped = pair.fish_map.get(top_l[row]) if row < len(top_l) else None
        self._top_plot.set_highlight(row)
        self._side_plot.set_highlight(side_l.index(mapped) if mapped in side_l else None)

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
