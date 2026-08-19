"""
Stage 4 — Zone definition screen (M3 real widgets).

Widgets:
  • load_btn    QPushButton → QFileDialog CSV → store.update_zones
  • clear_btn   QPushButton → clear list
  • zone_list   QListWidget showing ROI name + level
  • count_label QLabel  "{n} zones loaded"
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import ZoneSet


class ZonesScreen(QWidget):
    """Stage 4 — Define arena zones (polygon ROIs)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.zonesChanged.connect(self._refresh_list)
            store.projectChanged.connect(self._refresh_list)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Zones")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Load zone definitions from a CSV file or clear the current zones."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── list ──────────────────────────────────────────────────────────
        self._zone_list = QListWidget()
        self._zone_list.setMinimumHeight(160)
        root.addWidget(self._zone_list)

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load zones from CSV…")
        load_btn.clicked.connect(self._load_csv)
        clear_btn = QPushButton("Clear Zones")
        clear_btn.clicked.connect(self._clear_zones)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── count ──────────────────────────────────────────────────────
        self._count_label = QLabel("0 zones loaded")
        self._count_label.setStyleSheet("font-size: 13px; color: #555;")
        root.addWidget(self._count_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load zones CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            from track2data.zones.io import load_zones_csv  # type: ignore[import]
            zone_set: ZoneSet = load_zones_csv(path)
            if self._store is not None:
                self._store.update_zones(zone_set)
        except Exception as exc:
            QMessageBox.warning(self, "Import error", f"Could not load zones:\n{exc}")

    def _clear_zones(self) -> None:
        if self._store is not None:
            try:
                self._store.update_zones(ZoneSet())
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Failed to clear zones:\n{exc}")

    def _refresh_list(self) -> None:
        self._zone_list.clear()
        if self._store is None or self._store.manifest is None:
            self._count_label.setText("0 zones loaded")
            return
        rois = self._store.manifest.zones.rois
        for roi in rois:
            self._zone_list.addItem(f"{roi.name}  [{roi.level}]")
        n = len(rois)
        self._count_label.setText(f"{n} zone{'s' if n != 1 else ''} loaded")
