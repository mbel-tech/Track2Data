"""
Stage 1 — Project screen (M3 real widgets).

Widgets:
  • project_name_input  QLineEdit
  • browse_dir_button   QPushButton → QFileDialog.getExistingDirectory
  • dir_label           QLabel showing selected directory
  • create_button       QPushButton → store.new_project
  • open_button         QPushButton → store.open_project via QFileDialog
  • status_label        QLabel updated by store.projectChanged
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProjectScreen(QWidget):
    """Stage 1 — Create or open a project."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._selected_dir: str = ""
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Project")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel("Create a new project or open an existing one.")
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── form ──────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(10)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My experiment")
        form.addRow("Project name:", self._name_edit)

        dir_row = QHBoxLayout()
        self._dir_label = QLabel("(no directory selected)")
        self._dir_label.setStyleSheet("color: #666; font-style: italic;")
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._dir_label, 1)
        dir_row.addWidget(browse_btn)
        form.addRow("Directory:", dir_row)

        root.addLayout(form)

        # ── action buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._create_btn = QPushButton("Create Project")
        self._create_btn.clicked.connect(self._create_project)
        open_btn = QPushButton("Open Project…")
        open_btn.clicked.connect(self._open_project)
        btn_row.addWidget(self._create_btn)
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── status ─────────────────────────────────────────────────────
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 13px; color: #2c3e50; margin-top: 8px;")
        root.addWidget(self._status_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select project directory")
        if directory:
            self._selected_dir = directory
            self._dir_label.setText(directory)
            self._dir_label.setStyleSheet("color: #2c3e50;")

    def _create_project(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Project name must not be empty.")
            return
        if not self._selected_dir:
            QMessageBox.warning(self, "Validation", "Please select a project directory.")
            return
        directory = Path(self._selected_dir)
        if not directory.exists():
            QMessageBox.warning(self, "Validation", f"Directory does not exist:\n{directory}")
            return
        try:
            if self._store is not None:
                self._store.new_project(name, directory)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to create project:\n{exc}")

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Track2Data project (*.t2d.json)"
        )
        if not path:
            return
        try:
            if self._store is not None:
                self._store.open_project(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open project:\n{exc}")

    def _on_project_changed(self) -> None:
        if self._store is not None and self._store.manifest is not None:
            name = self._store.manifest.project_name
            self._status_label.setText(f"Project: {name}")
