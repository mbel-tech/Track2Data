"""
Stage 3 — Calibration screen (M3 real widgets).

Widgets:
  • radio_scalar / radio_bl   QRadioButton inside QButtonGroup
  • px_per_cm_spin            QDoubleSpinBox  (scalar mode only)
  • bl_info_label             QLabel          (BL mode only)
  • apply_btn                 QPushButton → store.update_calibration
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import CalibrationConfig


class CalibrationScreen(QWidget):
    """Stage 3 — Arena calibration (scalar px-per-cm or body-length)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.calibrationChanged.connect(self._on_calibration_changed)
            store.projectChanged.connect(self._on_calibration_changed)

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
        self._radio_scalar = QRadioButton("Scalar (px/cm)")
        self._radio_bl = QRadioButton("Body length (BL)")
        self._radio_bl.setChecked(True)

        self._btn_group = QButtonGroup(self)
        self._btn_group.addButton(self._radio_scalar)
        self._btn_group.addButton(self._radio_bl)

        mode_row.addWidget(self._radio_scalar)
        mode_row.addWidget(self._radio_bl)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # ── scalar controls ───────────────────────────────────────────────
        self._scalar_widget = QWidget()
        scalar_form = QFormLayout(self._scalar_widget)
        scalar_form.setContentsMargins(0, 0, 0, 0)
        self._px_spin = QDoubleSpinBox()
        self._px_spin.setRange(0.01, 10000.0)
        self._px_spin.setValue(1.0)
        self._px_spin.setDecimals(4)
        self._px_spin.setSuffix(" px/cm")
        scalar_form.addRow("Pixels per cm:", self._px_spin)

        # ── BL info ───────────────────────────────────────────────────────
        self._bl_label = QLabel(
            "Body length will be derived from session bounding boxes."
        )
        self._bl_label.setStyleSheet("color: #555; font-size: 13px;")
        self._bl_label.setWordWrap(True)

        root.addWidget(self._scalar_widget)
        root.addWidget(self._bl_label)

        # ── apply button ──────────────────────────────────────────────────
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(100)
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn)

        root.addStretch()

        # wire radio changes
        self._radio_scalar.toggled.connect(self._update_mode_visibility)
        self._update_mode_visibility()

    # ── slots ──────────────────────────────────────────────────────────────

    def _update_mode_visibility(self) -> None:
        scalar = self._radio_scalar.isChecked()
        self._scalar_widget.setVisible(scalar)
        self._bl_label.setVisible(not scalar)

    def _apply(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        mode = "scalar" if self._radio_scalar.isChecked() else "bodylength"
        px = self._px_spin.value() if mode == "scalar" else None
        cfg = CalibrationConfig(mode=mode, px_per_cm=px)
        try:
            self._store.update_calibration(cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply calibration:\n{exc}")

    def _on_calibration_changed(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        cfg = self._store.manifest.calibration
        if cfg.mode == "scalar":
            self._radio_scalar.setChecked(True)
            if cfg.px_per_cm is not None:
                self._px_spin.setValue(cfg.px_per_cm)
        else:
            self._radio_bl.setChecked(True)
        self._update_mode_visibility()
