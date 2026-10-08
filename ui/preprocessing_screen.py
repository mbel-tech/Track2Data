"""
Stage 6 — Preprocessing configuration screen (M3 real widgets).

Five QGroupBox sections:
  Gap Fill · Jump Detection · Identity Switch · Smoothing · Coverage Gate
Each group's own "Enabled" QCheckBox is the single source of truth for
whether that step runs -- the QGroupBox itself is not checkable (see
_apply()'s comment for why).
Edits auto-commit (debounced) → store.update_preprocess(...); MainWindow
calls flush() when the screen is left. Fields the screen has no widget for
are preserved via model_copy.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.autocommit import AutoCommit

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
    "idtracker_velocity_threshold": "idtracker.ai velocity threshold",
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
        self._auto = AutoCommit(self._apply, self)
        self._build_ui()
        self._wire_autocommit()
        if store is not None:
            store.preprocessChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)
            self._load_from_store()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 26, 26)
        outer.setSpacing(14)

        title = QLabel("Preprocessing")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        subtitle = QLabel(
            "Clean trajectories before metrics. Steps run top to bottom; every frame they "
            "change is "
            "flagged in the export."
        )
        subtitle.setObjectName("PageLead")
        outer.addWidget(subtitle)

        # scrollable area for all groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner_w = QWidget()
        layout = QVBoxLayout(inner_w)
        layout.setContentsMargins(0, 0, 12, 0)
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

        # ── Identity Switch ───────────────────────────────────────────────
        self._idsw_group = QGroupBox("Identity Switch Correction")
        idsw_form = QFormLayout(self._idsw_group)
        warn = QLabel(
            "Experimental and OFF by default. It re-assigns identities from "
            "geometry alone and, on real idtracker.ai recordings, can re-permute "
            "a large share of frames and inflate path length. Enable only if you "
            "understand and accept that risk."
        )
        warn.setWordWrap(True)
        warn.setProperty("banner", "warn")
        self._idsw_enabled = QCheckBox("Enabled")
        self._idsw_ratio = QDoubleSpinBox()
        self._idsw_ratio.setRange(1.0, 100.0)
        self._idsw_ratio.setSingleStep(0.1)
        self._idsw_ratio.setValue(1.5)
        self._idsw_hungarian = QCheckBox("Tier 2: Hungarian assignment")
        self._idsw_hungarian.setChecked(True)
        self._idsw_window = QSpinBox()
        self._idsw_window.setRange(1, 500)
        self._idsw_window.setValue(5)
        idsw_form.addRow(warn)
        idsw_form.addRow("", self._idsw_enabled)
        idsw_form.addRow("Tier 1 ratio:", self._idsw_ratio)
        idsw_form.addRow("", self._idsw_hungarian)
        idsw_form.addRow("Consolidation window:", self._idsw_window)
        layout.addWidget(self._idsw_group)

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

        for toggle in (
            self._gap_enabled, self._jump_enabled, self._idsw_enabled, self._smooth_enabled,
        ):
            toggle.setProperty("switch", True)
        layout.addStretch()
        scroll.setWidget(inner_w)
        outer.addWidget(scroll, 1)

    def _wire_autocommit(self) -> None:
        for w in (
            self._gap_enabled, self._jump_enabled, self._idsw_enabled,
            self._idsw_hungarian, self._smooth_enabled,
        ):
            w.toggled.connect(self._auto.trigger)
        for w in (
            self._gap_max, self._jump_sd, self._jump_pct, self._idsw_ratio,
            self._idsw_window, self._smooth_window, self._cov_max_nan,
        ):
            w.valueChanged.connect(self._auto.trigger)
        for w in (self._jump_method, self._smooth_method):
            w.currentIndexChanged.connect(self._auto.trigger)

    def flush(self) -> None:
        """Commit any pending edit now (called when the screen is left)."""
        self._auto.flush()

    # ── slots ──────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        # Reads each group's own inner "Enabled" QCheckBox, never a
        # QGroupBox.isChecked() -- the groups are deliberately not
        # checkable (two checkboxes per section could disagree).
        # model_copy() on the current config so fields with no widget
        # here (jump.pct_mult/replacement, smoothing.polyorder,
        # coverage.min_track_frames) are never reset to defaults.
        if self._store is None or self._store.manifest is None:
            return
        cur = self._store.manifest.preprocess
        cfg = cur.model_copy(
            update={
                "gap_fill": cur.gap_fill.model_copy(
                    update={
                        "enabled": self._gap_enabled.isChecked(),
                        "max_gap_frames": self._gap_max.value(),
                    }
                ),
                "jump": cur.jump.model_copy(
                    update={
                        "enabled": self._jump_enabled.isChecked(),
                        "method": self._jump_method.currentData(),
                        "sd_mult": self._jump_sd.value(),
                        "percentile": self._jump_pct.value(),
                    }
                ),
                "identity_switch": cur.identity_switch.model_copy(
                    update={
                        "enabled": self._idsw_enabled.isChecked(),
                        "tier1_ratio": self._idsw_ratio.value(),
                        "tier2_hungarian": self._idsw_hungarian.isChecked(),
                        "consolidate_window": self._idsw_window.value(),
                    }
                ),
                "smoothing": cur.smoothing.model_copy(
                    update={
                        "enabled": self._smooth_enabled.isChecked(),
                        "method": self._smooth_method.currentData(),
                        "window": self._smooth_window.value(),
                    }
                ),
                "coverage": cur.coverage.model_copy(
                    update={"max_pct_na_per_individual": self._cov_max_nan.value()}
                ),
            }
        )
        if cfg != cur:
            self._store.update_preprocess(cfg)

    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        cfg = self._store.manifest.preprocess
        with self._auto.suppressed():
            self._populate(cfg)

    def _populate(self, cfg) -> None:
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
        sw = cfg.identity_switch
        self._idsw_enabled.setChecked(sw.enabled)
        self._idsw_ratio.setValue(sw.tier1_ratio)
        self._idsw_hungarian.setChecked(sw.tier2_hungarian)
        self._idsw_window.setValue(sw.consolidate_window)
