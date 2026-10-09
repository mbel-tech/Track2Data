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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import ProjectMode
from ui.store.stage_status import SESSIONS_NEEDS_LAYOUT
from ui.widgets.weak_slot import weak_slot


class ProjectScreen(QWidget):
    """Stage 1 — Create or open a project."""

    #: The pending-3-D-layout state changed; ask :meth:`pending_mode_message`.
    pendingModeChanged = Signal()

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._selected_dir: str = ""
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)
            store.projectChanged.connect(self._sync_from_store)
            store.modeChanged.connect(self._sync_from_store)
            store.sessionsChanged.connect(self._sync_from_store)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Project")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Everything you set up is saved to one .t2d.json file, so someone else can re-run it."
        )
        subtitle.setObjectName("PageLead")
        subtitle.setWordWrap(True)
        subtitle.setMaximumWidth(600)
        root.addWidget(subtitle)

        # ── form ──────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(10)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My experiment")
        form.addRow("Project name", self._name_edit)

        dir_row = QHBoxLayout()
        self._dir_label = QLabel("(no directory selected)")
        self._dir_label.setProperty("role", "faint")
        browse_btn = QPushButton("Browse…")
        browse_btn.setProperty("role", "outline")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._dir_label, 1)
        dir_row.addWidget(browse_btn)
        form.addRow("Project folder", dir_row)

        form_box = QWidget()
        form_box.setMaximumWidth(600)
        form_box.setLayout(form)
        form.setContentsMargins(0, 0, 0, 0)
        root.addWidget(form_box)

        # ── analysis type (2D / 3D) ─────────────────────────────────────
        mode_box = QWidget()
        mode_box.setMaximumWidth(600)
        mode_lay = QVBoxLayout(mode_box)
        mode_lay.setContentsMargins(0, 0, 0, 0)
        mode_lay.setSpacing(6)
        mode_lay.addWidget(QLabel("Analysis type"))
        dim_row = QHBoxLayout()
        self._dim_2d = QRadioButton("2D")
        self._dim_3d = QRadioButton("3D")
        self._dim_2d.setChecked(True)
        self._dim_group = QButtonGroup(self)
        self._dim_group.addButton(self._dim_2d)
        self._dim_group.addButton(self._dim_3d)
        dim_row.addWidget(self._dim_2d)
        dim_row.addWidget(self._dim_3d)
        dim_row.addStretch()
        mode_lay.addLayout(dim_row)

        self._layout_box = QWidget()
        layout_lay = QVBoxLayout(self._layout_box)
        layout_lay.setContentsMargins(18, 0, 0, 0)
        layout_lay.setSpacing(2)
        self._layout_single = QRadioButton("One video, two panels (top and side in one frame)")
        self._layout_two = QRadioButton("Two videos (top and side tracked separately)")
        # Non-exclusive so "3D chosen, no layout yet" can show neither selected.
        self._layout_group = QButtonGroup(self)
        self._layout_group.setExclusive(False)
        self._layout_group.addButton(self._layout_single)
        self._layout_group.addButton(self._layout_two)
        layout_lay.addWidget(self._layout_single)
        layout_lay.addWidget(self._layout_two)
        self._layout_box.setVisible(False)
        mode_lay.addWidget(self._layout_box)

        self._lock_label = QLabel("")
        self._lock_label.setProperty("role", "muted")
        self._lock_label.setVisible(False)
        mode_lay.addWidget(self._lock_label)
        root.addWidget(mode_box)

        self._dim_2d.toggled.connect(self._on_dim_toggled)
        self._dim_3d.toggled.connect(self._on_dim_toggled)
        self._layout_single.toggled.connect(
            weak_slot(self._on_layout_toggled, self._layout_single, pass_args=True)
        )
        self._layout_two.toggled.connect(
            weak_slot(self._on_layout_toggled, self._layout_two, pass_args=True)
        )

        # ── action buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._create_btn = QPushButton("Create Project")
        self._create_btn.setProperty("role", "primary")
        self._create_btn.clicked.connect(self._create_project)
        open_btn = QPushButton("Open Project…")
        open_btn.setProperty("role", "outline")
        open_btn.clicked.connect(self._open_project)
        btn_row.addWidget(self._create_btn)
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── status ─────────────────────────────────────────────────────
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "muted")
        root.addWidget(self._status_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select project directory")
        if directory:
            self._selected_dir = directory
            self._dir_label.setText(directory)
            self._dir_label.setProperty("role", "mono")
            self._dir_label.style().unpolish(self._dir_label)
            self._dir_label.style().polish(self._dir_label)

    def _create_project(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Project name must not be empty.")
            return
        if not self._selected_dir:
            QMessageBox.warning(self, "Validation", "Please select a project directory.")
            return
        mode = self._selected_mode()
        if mode is None:
            QMessageBox.warning(self, "Validation", SESSIONS_NEEDS_LAYOUT + ".")
            return
        if self._store is not None and self._store.mode_locked is not None:
            # The radios are disabled and show the open project, not a choice for this one.
            mode = ProjectMode()
        directory = Path(self._selected_dir)
        if not directory.exists():
            QMessageBox.warning(self, "Validation", f"Directory does not exist:\n{directory}")
            return
        try:
            if self._store is not None:
                self._store.new_project(name, directory, mode=mode)
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

    # ── mode controls ──────────────────────────────────────────────────────

    def _selected_layout(self) -> str | None:
        if self._layout_single.isChecked():
            return "single_video_two_panels"
        if self._layout_two.isChecked():
            return "two_videos"
        return None

    def _selected_mode(self) -> ProjectMode | None:
        """The mode the radios describe, or None for 3D with no layout yet."""
        if self._dim_3d.isChecked():
            layout = self._selected_layout()
            if layout is None:
                return None
            return ProjectMode(dimension="3d", layout=layout)
        return ProjectMode()

    def _on_dim_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._layout_box.setVisible(self._dim_3d.isChecked())
        self._write_mode()
        self._refresh_pending()

    def _on_layout_toggled(self, button: QRadioButton, checked: bool) -> None:
        if checked:
            other = self._layout_two if button is self._layout_single else self._layout_single
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        elif (
            self._store is not None
            and self._store.manifest is not None
            and self._store.manifest.mode.layout is not None
        ):
            # Unchecking a committed layout would desync UI from the store.
            self._sync_from_store()
            return
        self._write_mode()
        self._refresh_pending()

    def _write_mode(self) -> None:
        """Push the radios into the open project; ignore incomplete 3D choices."""
        if self._store is None or self._store.manifest is None:
            return
        mode = self._selected_mode()
        if mode is None or mode == self._store.manifest.mode:
            return
        try:
            self._store.update_mode(mode)
        except ValueError:
            self._sync_from_store()

    def _sync_from_store(self) -> None:
        """Show the stored mode and lock state without writing anything back."""
        store = self._store
        if store is None or store.manifest is None:
            return
        mode = store.manifest.mode
        widgets = (self._dim_2d, self._dim_3d, self._layout_single, self._layout_two)
        for w in widgets:
            w.blockSignals(True)
        try:
            is_3d = mode.dimension == "3d"
            self._dim_2d.setChecked(not is_3d)
            self._dim_3d.setChecked(is_3d)
            self._layout_single.setChecked(mode.layout == "single_video_two_panels")
            self._layout_two.setChecked(mode.layout == "two_videos")
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._layout_box.setVisible(is_3d)
        lock = store.mode_locked
        for w in widgets:
            w.setEnabled(lock is None)
        self._refresh_pending()

    def pending_mode_message(self) -> str | None:
        """Why the user must stay on this page: 3D is picked but no layout is.

        The store keeps the old mode until a layout is chosen, so without this the
        choice would be lost silently once a session is added.
        """
        store = self._store
        if store is None or store.manifest is None or store.mode_locked is not None:
            return None
        if self._dim_3d.isChecked() and self._selected_layout() is None:
            return SESSIONS_NEEDS_LAYOUT
        return None

    def _refresh_pending(self) -> None:
        store = self._store
        lock = store.mode_locked if store is not None else None
        text = lock or self.pending_mode_message() or ""
        self._lock_label.setText(text)
        self._lock_label.setVisible(bool(text))
        self.pendingModeChanged.emit()
