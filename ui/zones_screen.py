"""
Stage 4 — Zone definition screen (M3 real widgets).

Widgets:
  • load_btn        QPushButton → QFileDialog CSV → store.update_zones
  • clear_btn       QPushButton → clear list
  • zone_list       QListWidget showing ROI name + level
  • count_label     QLabel  "{n} zones loaded"
  • session_combo   QComboBox   -- pick a session to import from
  • import_btn      QPushButton → zone_set_from_roi_list(session's roi_list)
  • mismatch_label  QLabel      -- warns when ZoneSet.source_width_px/
                                   height_px disagree with a project
                                   session's own video dimensions
  • landmarks_list  QListWidget -- Session.setup_points for the
                                   selected session, shown as reference
                                   guides only (never turned into
                                   auto-generated polygons)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from track2data.core.models import ZoneSet
from ui.widgets.labels import label_for


class ZonesScreen(QWidget):
    """Stage 4 — Define arena zones (polygon ROIs)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.zonesChanged.connect(self._refresh_list)
            store.zonesChanged.connect(self._refresh_mismatch_warning)
            store.projectChanged.connect(self._refresh_list)
            store.projectChanged.connect(self._refresh_session_combo)
            store.sessionsChanged.connect(self._refresh_session_combo)
            store.sessionFactsChanged.connect(self._refresh_mismatch_warning)
            store.sessionFactsChanged.connect(self._refresh_landmarks)
        self._refresh_session_combo()
        self._refresh_list()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Zones")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Load zone definitions from a CSV file, import them from an "
            "idtracker.ai session, or clear the current zones."
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

        # ── resolution-mismatch warning ──────────────────────────────────
        self._mismatch_label = QLabel("")
        self._mismatch_label.setWordWrap(True)
        self._mismatch_label.setStyleSheet("color: #b8860b; font-size: 13px;")
        self._mismatch_label.setVisible(False)
        root.addWidget(self._mismatch_label)

        # ── import from session ──────────────────────────────────────────
        import_label = QLabel("Import from session:")
        import_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        root.addWidget(import_label)

        import_row = QFormLayout()
        self._session_combo = QComboBox()
        import_row.addRow("Session:", self._session_combo)
        root.addLayout(import_row)

        import_btn_row = QHBoxLayout()
        import_btn = QPushButton("Import ROIs from Session")
        import_btn.clicked.connect(self._import_from_session)
        import_btn_row.addWidget(import_btn)
        import_btn_row.addStretch()
        root.addLayout(import_btn_row)

        # ── landmarks (setup_points) ─────────────────────────────────────
        # Named validator reference points, shown as guides only -- never
        # auto-converted into ROI polygons, since a point set may mix
        # arena corners with unrelated marks (e.g. a feeder) that would
        # produce a nonsense hull. The user still draws/imports the
        # actual ROI polygons above.
        landmarks_label = QLabel("Landmarks (from the validator):")
        landmarks_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        root.addWidget(landmarks_label)
        self._landmarks_list = QListWidget()
        self._landmarks_list.setMinimumHeight(80)
        root.addWidget(self._landmarks_list)

        self._session_combo.currentTextChanged.connect(self._refresh_landmarks)

        root.addStretch()

    # ── slots: CSV load/clear ────────────────────────────────────────────

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

    # ── slots: import from session ───────────────────────────────────────

    def _refresh_session_combo(self) -> None:
        self._session_combo.clear()
        if self._store is None or self._store.manifest is None:
            return
        for ref in self._store.manifest.sessions:
            self._session_combo.addItem(ref.session_id)

    def _import_from_session(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        session_id = self._session_combo.currentText()
        if not session_id:
            return
        facts = self._store.session_facts(session_id)
        if facts is None or not facts.roi_list:
            QMessageBox.information(
                self,
                "No ROI data",
                f"Session '{session_id}' has no roi_list to import from "
                "(it may still be loading, or was never traced with a "
                "saved arena boundary).",
            )
            return
        from track2data.zones.io import zone_set_from_roi_list

        zone_set = zone_set_from_roi_list(
            facts.roi_list, width_px=facts.width_px, height_px=facts.height_px
        )
        try:
            self._store.update_zones(zone_set)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to import zones:\n{exc}")

    # ── slots: refresh ────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._zone_list.clear()
        if self._store is None or self._store.manifest is None:
            self._count_label.setText("0 zones loaded")
            return
        rois = self._store.manifest.zones.rois
        for roi in rois:
            # roi.name is user-authored free text (whatever the
            # researcher, or the session's roi_list, named the arena) --
            # shown verbatim, never relabelled. roi.level is a free-text
            # field too, but its conventional values ("main"/"secondary")
            # are lowercase engine-side defaults, so title-case just
            # that part.
            self._zone_list.addItem(f"{roi.name}  [{label_for(roi.level)}]")
        n = len(rois)
        self._count_label.setText(f"{n} zone{'s' if n != 1 else ''} loaded")

    def _refresh_mismatch_warning(self) -> None:
        if self._store is None or self._store.manifest is None:
            self._mismatch_label.setText("")
            self._mismatch_label.setVisible(False)
            return
        zone_set = self._store.manifest.zones
        sw, sh = zone_set.source_width_px, zone_set.source_height_px
        if sw is None or sh is None:
            self._mismatch_label.setText("")
            self._mismatch_label.setVisible(False)
            return
        mismatched = []
        for ref in self._store.manifest.sessions:
            facts = self._store.session_facts(ref.session_id)
            if facts is None:
                continue
            if facts.width_px != sw or facts.height_px != sh:
                mismatched.append(ref.session_id)
        if mismatched:
            self._mismatch_label.setText(
                "These zones were defined at "
                f"{sw}x{sh}px, but the following sessions were tracked at a "
                "different resolution and may need their own zones: "
                + ", ".join(mismatched)
            )
            self._mismatch_label.setVisible(True)
        else:
            self._mismatch_label.setText("")
            self._mismatch_label.setVisible(False)

    def _refresh_landmarks(self) -> None:
        self._landmarks_list.clear()
        if self._store is None:
            return
        session_id = self._session_combo.currentText()
        if not session_id:
            return
        facts = self._store.session_facts(session_id)
        if facts is None or not facts.setup_points:
            return
        for name, point in facts.setup_points.items():
            self._landmarks_list.addItem(f"{name}: {point}")
