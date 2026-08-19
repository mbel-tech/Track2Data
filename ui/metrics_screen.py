"""
Stage 6b — Metric selection screen (M3 real widgets).

QTabWidget with three tabs: Individual / Group / Zone.
Each tab: QListWidget with checkable items.
Quality threshold QDoubleSpinBox + Apply button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import MetricSelection

_INDIVIDUAL_METRICS = ["IL-1", "IL-2", "IL-4", "IL-5"]
_GROUP_METRICS = ["GL-1", "GL-3", "GL-5", "GL-7"]
_ZONE_METRICS = ["Z-1", "Z-3"]


class MetricsScreen(QWidget):
    """Stage 6b — Select behavioural metrics to compute."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Metrics")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Choose which behavioural metrics to extract."
        )
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── tabs ──────────────────────────────────────────────────────────
        self._tabs = QTabWidget()

        self._ind_list = self._make_list(_INDIVIDUAL_METRICS)
        self._grp_list = self._make_list(_GROUP_METRICS)
        self._zone_list = self._make_list(_ZONE_METRICS)

        self._tabs.addTab(self._ind_list, "Individual")
        self._tabs.addTab(self._grp_list, "Group")
        self._tabs.addTab(self._zone_list, "Zone")

        root.addWidget(self._tabs, 1)

        # ── quality threshold ─────────────────────────────────────────────
        qform = QFormLayout()
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 1.0)
        self._quality_spin.setSingleStep(0.05)
        self._quality_spin.setDecimals(2)
        self._quality_spin.setValue(0.0)
        qform.addRow("Quality threshold:", self._quality_spin)
        root.addLayout(qform)

        # ── apply ─────────────────────────────────────────────────────────
        apply_btn = QPushButton("Apply selection")
        apply_btn.setFixedWidth(130)
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn)

    @staticmethod
    def _make_list(metric_ids: list[str]) -> QListWidget:
        lw = QListWidget()
        for mid in metric_ids:
            item = QListWidgetItem(mid)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            lw.addItem(item)
        return lw

    @staticmethod
    def _checked_ids(lw: QListWidget) -> list[str]:
        result = []
        for i in range(lw.count()):
            item = lw.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    # ── slots ──────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        sel = MetricSelection(
            individual=self._checked_ids(self._ind_list),
            group=self._checked_ids(self._grp_list),
            zone=self._checked_ids(self._zone_list),
            quality_threshold=self._quality_spin.value(),
        )
        try:
            self._store.update_metrics(sel)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply metric selection:\n{exc}")

    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sel = self._store.manifest.metrics
        self._set_checked(self._ind_list, sel.individual)
        self._set_checked(self._grp_list, sel.group)
        self._set_checked(self._zone_list, sel.zone)
        self._quality_spin.setValue(sel.quality_threshold)

    @staticmethod
    def _set_checked(lw: QListWidget, ids: list[str]) -> None:
        for i in range(lw.count()):
            item = lw.item(i)
            if item is not None:
                state = Qt.CheckState.Checked if item.text() in ids else Qt.CheckState.Unchecked
                item.setCheckState(state)
