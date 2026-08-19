"""
Stage 7b — Export screen (M3 real widgets).

Widgets:
  • QCheckBox per exporter: CSV Long, CSV Wide, Excel, Feather, README
  • browse_btn  QPushButton → select output directory
  • dir_label   QLabel showing path
  • export_btn  QPushButton — disabled stub
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_EXPORTERS = [
    ("CSV Long",  "csv_long",  True),
    ("CSV Wide",  "csv_wide",  True),
    ("Excel",     "excel",     False),
    ("Feather",   "feather",   False),
    ("README",    "readme",    True),
]


class ExportScreen(QWidget):
    """Stage 7b — Select export formats and write output datasets."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._output_dir: str = ""
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Export")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Choose export formats and target directory."
        )
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── exporter checkboxes ───────────────────────────────────────────
        fmt_group = QGroupBox("Export formats")
        fmt_layout = QVBoxLayout(fmt_group)
        self._checks: dict[str, QCheckBox] = {}
        for label, key, default in _EXPORTERS:
            cb = QCheckBox(label)
            cb.setChecked(default)
            self._checks[key] = cb
            fmt_layout.addWidget(cb)
        root.addWidget(fmt_group)

        # ── output directory ──────────────────────────────────────────────
        dir_row = QHBoxLayout()
        browse_btn = QPushButton("Browse output directory…")
        browse_btn.clicked.connect(self._browse_dir)
        self._dir_label = QLabel("(defaults to project directory)")
        self._dir_label.setStyleSheet("color: #666; font-style: italic;")
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(self._dir_label, 1)
        root.addLayout(dir_row)

        # ── export button ─────────────────────────────────────────────────
        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.setToolTip("Export will be available after pipeline run")
        self._export_btn.clicked.connect(self._export_stub)
        root.addWidget(self._export_btn)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        default = self._default_dir()
        directory = QFileDialog.getExistingDirectory(
            self, "Select output directory", default
        )
        if directory:
            self._output_dir = directory
            self._dir_label.setText(directory)
            self._dir_label.setStyleSheet("color: #2c3e50;")

    def _default_dir(self) -> str:
        if self._store is not None and self._store.project_dir is not None:
            return str(self._store.project_dir)
        return ""

    def _export_stub(self) -> None:
        QMessageBox.information(
            self,
            "Export",
            "Export will be available after pipeline run.",
        )

    def _on_project_changed(self) -> None:
        if (
            self._store is not None
            and self._store.has_project
            and not self._output_dir
            and self._store.project_dir is not None
        ):
            self._dir_label.setText(str(self._store.project_dir))
            self._dir_label.setStyleSheet("color: #555;")
