"""
Stage 5 — Metadata import & mapping screen (M3 real widgets).

Widgets:
  • load_btn       QPushButton → QFileDialog CSV
  • file_label     QLabel showing loaded file path
  • skip_btn       QPushButton → sets metadata_source = None
  • preview_table  QTableWidget (first 5 rows)
  • mapping combos QComboBox per canonical field
  • apply_btn      QPushButton → build MappingRule and store
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.hashing import file_sha256
from track2data.core.models import MappingRule, MetadataSource
from ui.widgets.labels import label_for

_CANONICAL_FIELDS = ["session_id", "treatment", "trial_id", "trial_date"]

#: field -> row label override, for the ones str.title() gets wrong.
#: title() capitalises the first letter of each word with no idea that
#: "id" is an acronym -- "session_id" -> "Session Id", not "Session
#: ID" -- so both id-suffixed fields need an explicit entry; treatment
#: and trial_date already read fine through the mechanical fallback.
_FIELD_LABELS = {"session_id": "Session ID", "trial_id": "Trial ID"}


class MetadataScreen(QWidget):
    """Stage 5 — Attach trial metadata to sessions."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._columns: list[str] = []
        self._build_ui()
        if store is not None:
            store.metadataChanged.connect(self._on_metadata_changed)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Metadata")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Import a trial-metadata CSV and map columns to canonical fields."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── file row ──────────────────────────────────────────────────────
        file_row = QHBoxLayout()
        load_btn = QPushButton("Load metadata CSV…")
        load_btn.clicked.connect(self._load_csv)
        skip_btn = QPushButton("Skip metadata")
        skip_btn.clicked.connect(self._skip_metadata)
        self._file_label = QLabel("(no file loaded)")
        self._file_label.setStyleSheet("color: #666; font-style: italic;")
        file_row.addWidget(load_btn)
        file_row.addWidget(skip_btn)
        file_row.addWidget(self._file_label, 1)
        root.addLayout(file_row)

        # ── preview table ─────────────────────────────────────────────────
        self._preview = QTableWidget(0, 0)
        self._preview.setMinimumHeight(130)
        root.addWidget(self._preview)

        # ── column mapping ────────────────────────────────────────────────
        map_label = QLabel("Column mapping:")
        map_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
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
            self._mapping_form.addRow(f"{label_for(field, _FIELD_LABELS)}:", combo)
        root.addLayout(self._mapping_form)

        apply_btn = QPushButton("Apply mapping")
        apply_btn.setFixedWidth(130)
        apply_btn.clicked.connect(self._apply_mapping)
        root.addWidget(apply_btn)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load metadata CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
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
            self._file_label.setStyleSheet("color: #2c3e50;")
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

    def _populate_combos(self, headers: list[str]) -> None:
        for field, combo in self._combos.items():
            combo.clear()
            combo.addItem("(skip)")
            for col in headers:
                combo.addItem(col)
            # auto-select matching column names
            lower_headers = [h.lower() for h in headers]
            if field in lower_headers:
                idx = lower_headers.index(field) + 1  # +1 for (skip)
                combo.setCurrentIndex(idx)

    def _skip_metadata(self) -> None:
        if self._store is not None:
            self._store.update_metadata_source(None)
        self._file_label.setText("(skipped)")
        self._file_label.setStyleSheet("color: #666; font-style: italic;")
        self._preview.setRowCount(0)
        self._preview.setColumnCount(0)

    def _apply_mapping(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        rules: dict[str, str] = {}
        for field, combo in self._combos.items():
            val = combo.currentText()
            if val != "(skip)":
                rules[field] = val
        rule = MappingRule(rules=rules)
        try:
            self._store.update_mapping(rule)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply mapping:\n{exc}")

    def _on_metadata_changed(self) -> None:
        pass  # refresh logic handled by load/skip actions
