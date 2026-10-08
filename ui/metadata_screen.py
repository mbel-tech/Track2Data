"""
Stage 5 — Metadata import & mapping screen (M3 real widgets).

Widgets:
  • load_btn       QPushButton → QFileDialog CSV
  • file_label     QLabel showing loaded file path
  • skip_btn       QPushButton → sets metadata_source = None
  • preview_table  QTableWidget (first 5 rows)
  • mapping combos QComboBox per canonical field
  • mapping edits auto-commit (debounced) → MappingRule in the store; flush() on leave
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.hashing import file_sha256
from track2data.core.models import MappingRule, MetadataSource
from track2data.metadata.schema import CANONICAL, resolve_column
from ui.widgets.autocommit import AutoCommit
from ui.widgets.labels import label_for

_CANONICAL_FIELDS = list(CANONICAL)

#: field -> row label override, for the ones str.title() gets wrong.
#: title() capitalises the first letter of each word with no idea that
#: "id" is an acronym -- "session_id" -> "Session Id", not "Session
#: ID" -- so both id-suffixed fields need an explicit entry; treatment
#: and trial_date already read fine through the mechanical fallback.
_FIELD_LABELS = {
    "session_id": "Session ID",
    "trial_id": "Trial ID",
    "individual_id": "Individual ID",
    "group_id": "Group ID",
}


class MetadataScreen(QWidget):
    """Stage 5 — Attach trial metadata to sessions."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._columns: list[str] = []
        self._auto = AutoCommit(self._apply_mapping, self)
        self._build_ui()
        if store is not None:
            store.metadataChanged.connect(self._on_metadata_changed)
            store.sessionsChanged.connect(self._refresh_match_summary)
            store.sessionFactsChanged.connect(self._refresh_match_summary)
            store.projectChanged.connect(self._on_metadata_changed)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        root = QVBoxLayout(inner)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Metadata")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Attach a spreadsheet of treatments, dates and tanks. Its columns are joined onto "
            "every "
            "export row. Common names are recognised: condition → treatment, date → trial_date."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageLead")
        root.addWidget(subtitle)

        # ── file row ──────────────────────────────────────────────────────
        file_row = QHBoxLayout()
        load_btn = QPushButton("Load metadata CSV…")
        load_btn.setProperty("role", "accent")
        load_btn.clicked.connect(self._load_csv)
        skip_btn = QPushButton("Skip metadata")
        skip_btn.setProperty("role", "outline")
        skip_btn.clicked.connect(self._skip_metadata)
        self._file_label = QLabel("(no file loaded)")
        self._file_label.setProperty("role", "faint")
        file_row.addWidget(load_btn)
        file_row.addWidget(skip_btn)
        file_row.addWidget(self._file_label, 1)
        root.addLayout(file_row)

        # ── preview table ─────────────────────────────────────────────────
        self._preview = QTableWidget(0, 0)
        self._preview.setMinimumHeight(130)
        self._preview.verticalHeader().hide()
        self._preview.setShowGrid(False)
        root.addWidget(self._preview)

        # ── column mapping ────────────────────────────────────────────────
        map_label = QLabel("COLUMN MAPPING")
        map_label.setObjectName("SectionLabel")
        root.addWidget(map_label)

        # Stored on self (not just a local) so tests can inspect the
        # actual rendered row labels -- see test_metadata_screen.py's
        # pretty-label regression test.
        self._mapping_form = QFormLayout()
        self._mapping_form.setSpacing(8)
        self._combos: dict[str, QComboBox] = {}
        for field in _CANONICAL_FIELDS:
            combo = QComboBox()
            combo.addItem("(skip)")
            self._combos[field] = combo
            combo.currentIndexChanged.connect(self._auto.trigger)
            if field == "individual_id":
                combo.currentIndexChanged.connect(lambda _i: self._update_match_mode_enabled())
            self._mapping_form.addRow(f"{label_for(field, _FIELD_LABELS)}:", combo)
        root.addLayout(self._mapping_form)

        # Per-animal options (D-010 superseded): how an Individual ID value is
        # matched to an animal, and which further columns to carry through.
        self._match_mode = QComboBox()
        self._match_mode.addItem("Validator label (position if none)", userData="label")
        self._match_mode.addItem("Position, 0-based", userData="index")
        self._match_mode.setEnabled(False)
        self._match_mode.setToolTip(
            "How each Individual ID in the CSV is matched to an animal. Labels are "
            "the names set in the idtracker.ai Validator (default 1, 2, ...)."
        )
        self._match_mode.currentIndexChanged.connect(self._auto.trigger)
        self._mapping_form.addRow("Match animals by:", self._match_mode)

        extra_label = QLabel("ALSO INCLUDE THESE COLUMNS (E.G. WEIGHT, SEX)")
        extra_label.setObjectName("SectionLabel")
        root.addWidget(extra_label)
        self._extra_list = QListWidget()
        self._extra_list.setMaximumHeight(110)
        self._extra_list.itemChanged.connect(lambda _item: self._auto.trigger())
        root.addWidget(self._extra_list)

        self._match_label = QLabel("")
        self._match_label.setWordWrap(True)
        self._match_label.setProperty("role", "muted")
        root.addWidget(self._match_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _set_match_role(self, role: str) -> None:
        self._match_label.setProperty("role", role)
        self._match_label.style().unpolish(self._match_label)
        self._match_label.style().polish(self._match_label)

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load metadata CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        """Load *path* as the project's metadata file (what the dialog calls)."""
        try:
            import csv
            rows: list[list[str]] = []
            with open(path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i >= 5:  # header + 5 data rows
                        break
            if not rows:
                QMessageBox.warning(self, "Empty file", "The CSV file appears to be empty.")
                return
            headers = rows[0]
            data_rows = rows[1:]
            self._columns = headers
            self._populate_preview(headers, data_rows)
            self._populate_combos(headers)
            self._file_label.setText(Path(path).name)
            self._file_label.setProperty("role", "")
            if self._store is not None:
                csv_path = Path(path)
                self._store.update_metadata_source(
                    MetadataSource(path=csv_path, sha256=file_sha256(csv_path))
                )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{exc}")

    def _populate_preview(self, headers: list[str], rows: list[list[str]]) -> None:
        self._preview.setColumnCount(len(headers))
        self._preview.setHorizontalHeaderLabels(headers)
        self._preview.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._preview.setItem(r, c, QTableWidgetItem(val))
        self._preview.resizeColumnsToContents()

    def flush(self) -> None:
        """Commit any pending mapping edit now (called when the screen is left)."""
        self._auto.flush()

    def _populate_combos(self, headers: list[str]) -> None:
        with self._auto.suppressed():
            self._fill_combos(headers)
        self._auto.trigger()  # persist the auto-matched columns

    def _fill_extra_list(self, headers: list[str], checked: list[str] | None = None) -> None:
        """List the CSV columns that are not mapped to a field, as checkable extras."""
        mapped = {
            combo.currentText()
            for combo in self._combos.values()
            if combo.currentText() != "(skip)"
        }
        keep = set(checked or [])
        self._extra_list.clear()
        for col in headers:
            if col in mapped:
                continue
            item = QListWidgetItem(col)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = col.strip().lower() in {c.strip().lower() for c in keep}
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self._extra_list.addItem(item)

    def _update_match_mode_enabled(self) -> None:
        self._match_mode.setEnabled(self._combos["individual_id"].currentText() != "(skip)")

    def _fill_combos(self, headers: list[str]) -> None:
        for field, combo in self._combos.items():
            combo.clear()
            combo.addItem("(skip)")
            for col in headers:
                combo.addItem(col)
            # auto-select a column named like the field, or by a known alias
            # ("date" -> trial_date, "condition" -> treatment, ...)
            resolved = [resolve_column(h) for h in headers]
            if field in resolved:
                combo.setCurrentIndex(resolved.index(field) + 1)  # +1 for (skip)
        self._fill_extra_list(headers)
        self._update_match_mode_enabled()

    def _skip_metadata(self) -> None:
        if self._store is not None:
            self._store.update_metadata_source(None)
        self._file_label.setText("(skipped)")
        self._file_label.setProperty("role", "faint")
        self._preview.setRowCount(0)
        self._preview.setColumnCount(0)

    def _apply_mapping(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        rules: dict[str, str] = {}
        for field, combo in self._combos.items():
            val = combo.currentText()
            if val != "(skip)":
                rules[field] = val
        extras = [
            self._extra_list.item(i).text()
            for i in range(self._extra_list.count())
            if self._extra_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        # model_copy on the current rule so join_keys / join_regex, which this
        # screen has no widgets for, are never reset to their defaults.
        current = self._store.manifest.mapping or MappingRule()
        rule = current.model_copy(
            update={
                "rules": rules,
                "extra_columns": extras,
                "individual_match": self._match_mode.currentData() or "label",
            }
        )
        if rule == self._store.manifest.mapping:
            return
        try:
            self._store.update_mapping(rule)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply mapping:\n{exc}")

    def _on_metadata_changed(self) -> None:
        """Restore the screen from the store (reopened project) and refresh
        the match summary. A pending, uncommitted edit is never overwritten."""
        if self._store is None or self._store.manifest is None:
            return
        src = self._store.manifest.metadata_source
        if not self._auto.pending:
            if src is None:
                if self._file_label.text() not in ("(skipped)",):
                    self._file_label.setText("(no file loaded)")
            elif self._file_label.text() != src.path.name and Path(src.path).exists():
                self._restore_from_source(src)
            self._sync_combos_to_mapping()
        self._refresh_match_summary()

    def _sync_combos_to_mapping(self) -> None:
        rule = self._store.manifest.mapping if self._store and self._store.manifest else None
        if rule is None:
            return
        with self._auto.suppressed():
            for field, column in rule.rules.items():
                combo = self._combos.get(field)
                idx = combo.findText(column) if combo is not None else -1
                if idx >= 0 and combo.currentIndex() != idx:
                    combo.setCurrentIndex(idx)
            self._fill_extra_list(self._columns, rule.extra_columns)
            self._update_match_mode_enabled()
            mode_idx = self._match_mode.findData(rule.individual_match)
            if mode_idx >= 0:
                self._match_mode.setCurrentIndex(mode_idx)

    def _restore_from_source(self, src: MetadataSource) -> None:
        import csv

        with open(src.path, newline="", encoding="utf-8-sig") as fh:
            rows = [row for _, row in zip(range(6), csv.reader(fh), strict=False)]
        if not rows:
            return
        self._columns = rows[0]
        self._populate_preview(rows[0], rows[1:])
        with self._auto.suppressed():
            self._fill_combos(rows[0])
        self._file_label.setText(src.path.name)
        self._file_label.setProperty("role", "")

    def _per_animal_notes(self, manifest, result) -> list[str]:
        """Problems with per-animal rows that the engine will only log: animals
        with no row, keys matching no animal, identity-free sessions."""
        from track2data.metadata.join import resolve_animal

        notes: list[str] = []
        mode = manifest.mapping.individual_match if manifest.mapping else "label"
        for ref in manifest.sessions:
            keyed = result.matched_individuals.get(ref.session_id)
            if not keyed:
                continue
            facts = self._store.session_facts(ref.session_id)
            if ref.is_identity_free():
                notes.append(
                    f"Session {ref.session_id} is identity-free: per-animal metadata "
                    "is ignored for it."
                )
                continue
            if facts is None:
                continue  # not probed yet: cannot resolve animals
            labels = [str(x).strip().lower() for x in (facts.identities_labels or ())]
            found: set[int] = set()
            for key in keyed:
                idx = resolve_animal(key, labels, mode, facts.n_animals)
                if idx is None:
                    notes.append(f"Session {ref.session_id}: '{key}' matches no animal.")
                else:
                    found.add(idx)
            for k in range(facts.n_animals):
                if k not in found:
                    name = (
                        facts.identities_labels[k]
                        if facts.identities_labels and mode == "label"
                        else k
                    )
                    notes.append(f"Session {ref.session_id}: no row for animal {name}.")
        return notes

    def _refresh_match_summary(self) -> None:
        """"N of M sessions matched" from the same join the engine will run."""
        if self._store is None or self._store.manifest is None:
            self._match_label.setText("")
            return
        m = self._store.manifest
        if m.metadata_source is None or m.mapping is None or not m.sessions:
            self._match_label.setText("")
            return
        try:
            from track2data.metadata.join import match
            from track2data.metadata.loader import load
            from track2data.metadata.mapping import apply_mapping

            mapped = apply_mapping(load(m.metadata_source.path), m.mapping)
            result = match([r.session_id for r in m.sessions], mapped, m.mapping)
        except Exception as exc:
            self._match_label.setText(f"Could not match sessions: {exc}")
            self._set_match_role("warn")
            return
        total = len(m.sessions)
        text = f"{len(result.matched)} of {total} sessions matched."
        if result.unmatched_sessions:
            text += " No row for: " + ", ".join(result.unmatched_sessions) + "."
        if result.conflicts:
            text += (
                f" {len(result.conflicts)} session(s) matched several rows "
                "(the first row is used)."
            )
        notes = self._per_animal_notes(m, result)
        if result.matched_individuals:
            n_rows = sum(len(v) for v in result.matched_individuals.values())
            text += f" {n_rows} animal rows matched."
        if notes:
            text += " " + " ".join(notes)
        ok = len(result.matched) == total and not result.conflicts and not notes
        self._match_label.setText(text)
        self._set_match_role("ok" if ok else "warn")
