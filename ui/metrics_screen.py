"""
Stage 6b — Metric selection screen (registry-driven QTableWidget).

QTabWidget with three tabs: Individual / Group / Zone. Each tab is a
QTableWidget populated from track2data.metrics.list_for_level(level),
columns: include (checkbox) / metric_id / metric_name / info (ⓘ) /
config (⚙, stub). Quality threshold QDoubleSpinBox + Apply button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.core.models import MetricSelection

_COLUMN_HEADERS = ["Include", "ID", "Name", "Info", "Config"]
_COL_INCLUDE, _COL_ID, _COL_NAME, _COL_INFO, _COL_CONFIG = range(5)
_ROLE_METRIC_ID = Qt.ItemDataRole.UserRole
_ROLE_REQUIRES_IDENTITY = Qt.ItemDataRole.UserRole + 1


def _natural_sort_key(metric_cls):
    """Sort metrics naturally: GL-1, GL-2, GL-10 (not GL-1, GL-10, GL-2)."""
    prefix, _, number = metric_cls.id.rpartition("-")
    return (prefix, int(number))


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

        subtitle = QLabel("Choose which behavioural metrics to extract.")
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        self._tabs = QTabWidget()

        self._ind_table = self._make_table("individual")
        self._grp_table = self._make_table("group")
        self._zone_table = self._make_table("zone")

        self._tabs.addTab(self._ind_table, "Individual")
        self._tabs.addTab(self._grp_table, "Group")
        self._tabs.addTab(self._zone_table, "Zone")

        root.addWidget(self._tabs, 1)

        qform = QFormLayout()
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 1.0)
        self._quality_spin.setSingleStep(0.05)
        self._quality_spin.setDecimals(2)
        self._quality_spin.setValue(0.0)
        qform.addRow("Quality threshold:", self._quality_spin)
        root.addLayout(qform)

        apply_btn = QPushButton("Apply selection")
        apply_btn.setFixedWidth(130)
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn)

    def _make_table(self, level: str) -> QTableWidget:
        metric_classes = sorted(metrics.list_for_level(level), key=_natural_sort_key)
        table = QTableWidget(len(metric_classes), len(_COLUMN_HEADERS))
        table.setHorizontalHeaderLabels(_COLUMN_HEADERS)
        table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, metric_cls in enumerate(metric_classes):
            include_item = QTableWidgetItem()
            include_item.setFlags(
                include_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            include_item.setCheckState(Qt.CheckState.Unchecked)
            include_item.setData(_ROLE_METRIC_ID, metric_cls.id)
            include_item.setData(_ROLE_REQUIRES_IDENTITY, metric_cls.requires_identity)
            table.setItem(row, _COL_INCLUDE, include_item)

            table.setItem(row, _COL_ID, QTableWidgetItem(metric_cls.id))
            table.setItem(row, _COL_NAME, QTableWidgetItem(metric_cls.name))

        return table

    # ── slots ──────────────────────────────────────────────────────────────

    def _checked_ids(self, table: QTableWidget) -> list[str]:
        result = []
        for row in range(table.rowCount()):
            item = table.item(row, _COL_INCLUDE)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(_ROLE_METRIC_ID))
        return result

    def _apply(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        sel = MetricSelection(
            individual=self._checked_ids(self._ind_table),
            group=self._checked_ids(self._grp_table),
            zone=self._checked_ids(self._zone_table),
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
        self._set_checked(self._ind_table, sel.individual)
        self._set_checked(self._grp_table, sel.group)
        self._set_checked(self._zone_table, sel.zone)
        self._quality_spin.setValue(sel.quality_threshold)

    @staticmethod
    def _set_checked(table: QTableWidget, ids: list[str]) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, _COL_INCLUDE)
            if item is not None:
                state = (
                    Qt.CheckState.Checked
                    if item.data(_ROLE_METRIC_ID) in ids
                    else Qt.CheckState.Unchecked
                )
                item.setCheckState(state)
