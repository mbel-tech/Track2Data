"""
Stage 6 — Preprocessing configuration screen (M3 real widgets).

Four QGroupBox sections:
  Gap Fill · Jump Detection · Smoothing · Coverage Gate
Each group's own "Enabled" QCheckBox is the single source of truth for
whether that step runs -- the QGroupBox itself is not checkable (see
_apply()'s comment for why).
Apply button → store.update_preprocess(PreprocessConfig(...))
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import (
    GapFillCfg,
    JumpCfg,
    PreprocessConfig,
    SmoothCfg,
    ValidateCfg,
)

#: engine literal -> pretty label. Every value is enumerated explicitly
#: (no ui.widgets.labels.label_for() fallback needed) since both
#: vocabularies are small and closed -- Literal-typed on the Pydantic
#: models, not open to arbitrary third-party values the way exporter
#: names are. The combo stores the real literal as
#: userData (read back via currentData()/findData()) and shows the
#: label as text -- prettifying displayed text must never change what
#: gets persisted into PreprocessConfig, which is exactly what reading
#: currentText() back as the value would do.
_JUMP_METHOD_LABELS = {
    "sd_multiple": "Standard-deviation multiple",
    "percentile": "Percentile",
}
_SMOOTH_METHOD_LABELS = {
    "none": "None",
    "moving_avg": "Moving average",
    "savgol": "Savitzky-Golay",
}


class PreprocessingScreen(QWidget):
    """Stage 6a — Configure preprocessing steps (PP-1..PP-5)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.preprocessChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 36, 48, 36)
        outer.setSpacing(16)

        title = QLabel("Preprocessing")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        outer.addWidget(title)

        subtitle = QLabel(
            "Enable and configure the preprocessing pipeline steps."
        )
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        outer.addWidget(subtitle)

        # scrollable area for all groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner_w = QWidget()
        layout = QVBoxLayout(inner_w)
        layout.setSpacing(12)

        # ── Gap Fill ──────────────────────────────────────────────────────
        self._gap_group = QGroupBox("Gap Fill")
        gap_form = QFormLayout(self._gap_group)
        self._gap_enabled = QCheckBox("Enabled")
        self._gap_enabled.setChecked(True)
        self._gap_max = QSpinBox()
        self._gap_max.setRange(1, 200)
        self._gap_max.setValue(30)
        gap_form.addRow("", self._gap_enabled)
        gap_form.addRow("Max gap frames:", self._gap_max)
        layout.addWidget(self._gap_group)

        # ── Jump Detection ────────────────────────────────────────────────
        self._jump_group = QGroupBox("Jump Detection")
        jump_form = QFormLayout(self._jump_group)
        self._jump_enabled = QCheckBox("Enabled")
        self._jump_enabled.setChecked(True)
        self._jump_method = QComboBox()
        for value, label in _JUMP_METHOD_LABELS.items():
            self._jump_method.addItem(label, userData=value)
        self._jump_sd = QDoubleSpinBox()
        self._jump_sd.setRange(0.1, 1000.0)
        self._jump_sd.setValue(10.0)
        self._jump_sd.setSingleStep(1.0)
        self._jump_pct = QDoubleSpinBox()
        self._jump_pct.setRange(0.1, 100.0)
        self._jump_pct.setValue(99.0)
        self._jump_pct.setSingleStep(1.0)
        jump_form.addRow("", self._jump_enabled)
        jump_form.addRow("Method:", self._jump_method)
        jump_form.addRow("SD multiplier:", self._jump_sd)
        jump_form.addRow("Percentile:", self._jump_pct)
        layout.addWidget(self._jump_group)

        # ── Smoothing ─────────────────────────────────────────────────────
        self._smooth_group = QGroupBox("Smoothing")
        smooth_form = QFormLayout(self._smooth_group)
        self._smooth_enabled = QCheckBox("Enabled")
        self._smooth_enabled.setChecked(True)
        self._smooth_method = QComboBox()
        for value, label in _SMOOTH_METHOD_LABELS.items():
            self._smooth_method.addItem(label, userData=value)
        self._smooth_window = QSpinBox()
        self._smooth_window.setRange(1, 500)
        self._smooth_window.setValue(5)
        smooth_form.addRow("", self._smooth_enabled)
        smooth_form.addRow("Method:", self._smooth_method)
        smooth_form.addRow("Window:", self._smooth_window)
        layout.addWidget(self._smooth_group)

        # ── Coverage Gate ─────────────────────────────────────────────────
        cov_group = QGroupBox("Coverage Gate")
        cov_form = QFormLayout(cov_group)
        self._cov_max_nan = QDoubleSpinBox()
        self._cov_max_nan.setRange(0.0, 1.0)
        self._cov_max_nan.setSingleStep(0.01)
        self._cov_max_nan.setDecimals(3)
        self._cov_max_nan.setValue(0.10)
        cov_form.addRow("Max NaN fraction:", self._cov_max_nan)
        layout.addWidget(cov_group)

        layout.addStretch()
        scroll.setWidget(inner_w)
        outer.addWidget(scroll, 1)

        # ── Apply button ──────────────────────────────────────────────────
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(100)
        apply_btn.clicked.connect(self._apply)
        outer.addWidget(apply_btn)

    # ── slots ──────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        # Reads each group's own inner "Enabled" QCheckBox, never a
        # QGroupBox.isChecked() -- the three QGroupBoxes above used to
        # also be setCheckable(True), giving each section *two*
        # checkboxes (the group's own title checkbox, and this inner
        # one) that could show disagreeing states, since only the
        # inner one was ever read here. Removed the redundant one
        # rather than start reading a second control for the same
        # value.
        if self._store is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        try:
            cfg = PreprocessConfig(
                gap_fill=GapFillCfg(
                    enabled=self._gap_enabled.isChecked(),
                    max_gap_frames=self._gap_max.value(),
                ),
                jump=JumpCfg(
                    enabled=self._jump_enabled.isChecked(),
                    method=self._jump_method.currentData(),  # type: ignore[arg-type]
                    sd_mult=self._jump_sd.value(),
                    percentile=self._jump_pct.value(),
                ),
                smoothing=SmoothCfg(
                    enabled=self._smooth_enabled.isChecked(),
                    method=self._smooth_method.currentData(),  # type: ignore[arg-type]
                    window=self._smooth_window.value(),
                ),
                coverage=ValidateCfg(
                    max_pct_na_per_individual=self._cov_max_nan.value(),
                ),
            )
            self._store.update_preprocess(cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply preprocessing config:\n{exc}")

    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        cfg = self._store.manifest.preprocess
        self._gap_enabled.setChecked(cfg.gap_fill.enabled)
        self._gap_max.setValue(cfg.gap_fill.max_gap_frames)
        self._jump_enabled.setChecked(cfg.jump.enabled)
        idx = self._jump_method.findData(cfg.jump.method)
        if idx >= 0:
            self._jump_method.setCurrentIndex(idx)
        self._jump_sd.setValue(cfg.jump.sd_mult)
        self._jump_pct.setValue(cfg.jump.percentile)
        self._smooth_enabled.setChecked(cfg.smoothing.enabled)
        idx2 = self._smooth_method.findData(cfg.smoothing.method)
        if idx2 >= 0:
            self._smooth_method.setCurrentIndex(idx2)
        self._smooth_window.setValue(cfg.smoothing.window)
        self._cov_max_nan.setValue(cfg.coverage.max_pct_na_per_individual)
