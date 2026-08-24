"""
Stage 3 — Calibration screen (M3 real widgets).

Widgets:
  • radio_bl / radio_scalar / radio_session   QRadioButton inside a
                                               QButtonGroup (three modes)
  • px_per_cm_spin       QDoubleSpinBox  (Custom mode only)
  • bl_info_label        QLabel          (Body length mode only)
  • unit_combo           QComboBox       (Session calibration mode only)
  • confirm_check        QCheckBox       (Session calibration mode only)
  • readiness_list       QListWidget     (Session calibration mode only) --
                          per-session length_unit readiness, from
                          ProjectStore.session_facts()
  • apply_btn            QPushButton → store.update_calibration
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

_UNIT_CHOICES = ["cm", "mm", "m"]


class CalibrationScreen(QWidget):
    """Stage 3 — Arena calibration (body length, custom, or session)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.calibrationChanged.connect(self._on_calibration_changed)
            store.projectChanged.connect(self._on_calibration_changed)
            store.sessionsChanged.connect(self._refresh_readiness)
            store.sessionFactsChanged.connect(self._refresh_readiness)
        self._on_calibration_changed()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Calibration")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Convert pixel distances to real-world units."
        )
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── mode selection ────────────────────────────────────────────────
        mode_row = QHBoxLayout()
        self._radio_bl = QRadioButton("Body length (recommended)")
        self._radio_scalar = QRadioButton("Custom (px per unit)")
        self._radio_session = QRadioButton("Session calibration")
        self._radio_bl.setChecked(True)

        self._btn_group = QButtonGroup(self)
        self._btn_group.addButton(self._radio_bl)
        self._btn_group.addButton(self._radio_scalar)
        self._btn_group.addButton(self._radio_session)

        mode_row.addWidget(self._radio_bl)
        mode_row.addWidget(self._radio_scalar)
        mode_row.addWidget(self._radio_session)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # ── BL info ───────────────────────────────────────────────────────
        self._bl_label = QLabel(
            "Body length will be derived from session bounding boxes."
        )
        self._bl_label.setStyleSheet("color: #555; font-size: 13px;")
        self._bl_label.setWordWrap(True)
        root.addWidget(self._bl_label)

        # ── custom (scalar) controls ─────────────────────────────────────
        self._scalar_widget = QWidget()
        scalar_form = QFormLayout(self._scalar_widget)
        scalar_form.setContentsMargins(0, 0, 0, 0)
        self._px_spin = QDoubleSpinBox()
        self._px_spin.setRange(0.01, 10000.0)
        self._px_spin.setValue(1.0)
        self._px_spin.setDecimals(4)
        self._px_spin.setSuffix(" px per unit")
        scalar_form.addRow("Pixels per unit:", self._px_spin)
        root.addWidget(self._scalar_widget)

        # ── session calibration controls ────────────────────────────────
        self._session_widget = QWidget()
        session_layout = QVBoxLayout(self._session_widget)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(8)

        session_info = QLabel(
            "Uses each session's own calibration ratio, recorded by the "
            "idtracker.ai validator's Length Calibration tool."
        )
        session_info.setStyleSheet("color: #555; font-size: 13px;")
        session_info.setWordWrap(True)
        session_layout.addWidget(session_info)

        unit_form = QFormLayout()
        unit_form.setContentsMargins(0, 0, 0, 0)
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(_UNIT_CHOICES)
        unit_form.addRow("Unit:", self._unit_combo)
        session_layout.addLayout(unit_form)

        self._confirm_check = QCheckBox(
            "I confirm these sessions were calibrated in the unit selected above."
        )
        session_layout.addWidget(self._confirm_check)

        readiness_label = QLabel("Per-session readiness:")
        readiness_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        session_layout.addWidget(readiness_label)
        self._readiness_list = QListWidget()
        self._readiness_list.setMinimumHeight(100)
        session_layout.addWidget(self._readiness_list)

        root.addWidget(self._session_widget)

        # ── apply button ──────────────────────────────────────────────────
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(100)
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn)

        root.addStretch()

        # wire radio changes
        self._radio_bl.toggled.connect(self._update_mode_visibility)
        self._radio_scalar.toggled.connect(self._update_mode_visibility)
        self._radio_session.toggled.connect(self._update_mode_visibility)
        self._update_mode_visibility()
        self._refresh_readiness()

    # ── slots ──────────────────────────────────────────────────────────────

    def _update_mode_visibility(self) -> None:
        self._bl_label.setVisible(self._radio_bl.isChecked())
        self._scalar_widget.setVisible(self._radio_scalar.isChecked())
        self._session_widget.setVisible(self._radio_session.isChecked())

    def _current_mode(self) -> str:
        if self._radio_scalar.isChecked():
            return "scalar"
        if self._radio_session.isChecked():
            return "session"
        return "bodylength"

    def _apply(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        mode = self._current_mode()
        # model_copy(update=...) against the manifest's current
        # CalibrationConfig, never a fresh CalibrationConfig(...) --
        # constructing one from scratch used to silently reset
        # bl_min_samples/length_unit_label/length_unit_confirmed_by_user
        # to their defaults on every Apply, discarding whatever had
        # already been set for a mode the user isn't currently on.
        current = self._store.manifest.calibration
        updates: dict[str, object] = {
            "mode": mode,
            "px_per_cm": self._px_spin.value() if mode == "scalar" else None,
        }
        if mode == "session":
            updates["length_unit_label"] = self._unit_combo.currentText()
            updates["length_unit_confirmed_by_user"] = self._confirm_check.isChecked()
        cfg = current.model_copy(update=updates)
        try:
            self._store.update_calibration(cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply calibration:\n{exc}")

    def _on_calibration_changed(self) -> None:
        if self._store is not None and self._store.manifest is not None:
            cfg = self._store.manifest.calibration
            if cfg.mode == "scalar":
                self._radio_scalar.setChecked(True)
                if cfg.px_per_cm is not None:
                    self._px_spin.setValue(cfg.px_per_cm)
            elif cfg.mode == "session":
                self._radio_session.setChecked(True)
                if cfg.length_unit_label in _UNIT_CHOICES:
                    self._unit_combo.setCurrentText(cfg.length_unit_label)
                self._confirm_check.setChecked(cfg.length_unit_confirmed_by_user)
            else:
                self._radio_bl.setChecked(True)
        self._update_mode_visibility()
        self._refresh_readiness()

    def _refresh_readiness(self) -> None:
        self._readiness_list.clear()
        if self._store is None or self._store.manifest is None:
            return
        for ref in self._store.manifest.sessions:
            facts = self._store.session_facts(ref.session_id)
            if facts is None:
                text = f"{ref.session_id} — checking…"
            elif facts.length_unit is not None:
                text = f"{ref.session_id} — calibrated ({facts.length_unit:.4g} px per unit)"
            else:
                text = f"{ref.session_id} — not calibrated"
            self._readiness_list.addItem(text)
