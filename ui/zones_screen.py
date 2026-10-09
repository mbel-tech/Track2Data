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
                                   selected session, shown as a text
                                   list alongside the interactive
                                   canvas below
  • canvas          ZoneCanvas  -- the session's background.png with
                                   setup_points overlaid as clickable
                                   markers (ui/widgets/zone_canvas.py);
                                   clicking points in order selects
                                   them as polygon vertices
  • custom_point_btn QPushButton (checkable) -- toggles click-to-add-
                                   point mode on the canvas, for points
                                   not in setup_points
  • zone_name_edit / zone_level_combo / save_zone_btn -- name + level
                                   for the polygon the canvas selection
                                   currently describes; save_zone_btn is
                                   enabled once >= 3 points are selected
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from track2data.core.errors import ZoneValidationError
from track2data.core.models import ROI, ZoneSet
from ui.widgets.labels import label_for
from ui.widgets.mode_banner import ModeBanner
from ui.widgets.weak_slot import weak_slot
from ui.widgets.zone_canvas import ZoneCanvas, polygon_area

#: Minimum vertices for a valid polygon.
_MIN_ZONE_VERTICES = 3
_ZONE_HINT = "Select a zone to see its shape. Drag its white handles to reshape it."


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
            store.sessionFactsChanged.connect(self._refresh_canvas)
        self._refresh_session_combo()
        self._refresh_list()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── left: header, session picker, tools, canvas ──────────────────
        left = QWidget()
        root = QVBoxLayout(left)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(12)
        outer.addWidget(left, 1)

        title = QLabel("Zones")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Draw regions on a frame. Zone metrics use these. You can also load zones from a "
            "CSV file or import them from an idtracker.ai session."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageLead")
        root.addWidget(subtitle)

        if self._store is not None:
            root.addWidget(ModeBanner(self._store))

        picker_row = QHBoxLayout()
        picker_row.setSpacing(10)
        session_label = QLabel("Session")
        session_label.setObjectName("SectionLabel")
        self._session_combo = QComboBox()
        self._session_combo.setMinimumWidth(240)
        picker_row.addWidget(session_label)
        picker_row.addWidget(self._session_combo)
        picker_row.addStretch()
        root.addLayout(picker_row)

        canvas_btn_row = QHBoxLayout()
        canvas_btn_row.setSpacing(8)
        self._custom_point_btn = QPushButton("Add Custom Point")
        self._custom_point_btn.setProperty("role", "outline")
        self._custom_point_btn.setCheckable(True)

        # Shape tools: markers (default), or drag a rectangle / circle.
        self._tool_buttons: dict[str, QPushButton] = {}
        tool_group = QButtonGroup(self)
        tool_group.setExclusive(True)
        for tool, text, tip in (
            ("points", "Points", "Click markers in order to build a polygon"),
            ("rect", "Rectangle", "Drag from one corner to the opposite corner"),
            ("circle", "Circle", "Drag from the centre outwards"),
        ):
            btn = QPushButton(text)
            btn.setProperty("role", "segment")
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setChecked(tool == "points")
            tool_group.addButton(btn)
            canvas_btn_row.addWidget(btn)
            self._tool_buttons[tool] = btn
        canvas_btn_row.addSpacing(8)
        canvas_btn_row.addWidget(self._custom_point_btn)
        self._undo_btn = QPushButton("Undo point")
        self._undo_btn.setProperty("role", "outline")
        self._undo_btn.setToolTip("Remove the last vertex (Ctrl+Z)")
        canvas_btn_row.addWidget(self._undo_btn)
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setProperty("role", "outline")
        self._fit_btn.setToolTip("Fit the image to the view. Wheel = zoom, middle-drag = pan.")
        canvas_btn_row.addWidget(self._fit_btn)
        canvas_btn_row.addStretch()
        root.addLayout(canvas_btn_row)

        canvas_card = QFrame()
        canvas_card.setProperty("card", True)
        card_col = QVBoxLayout(canvas_card)
        card_col.setContentsMargins(10, 10, 10, 10)
        self._canvas = ZoneCanvas()
        card_col.addWidget(self._canvas)
        root.addWidget(canvas_card, 1)

        self._canvas.selectionChanged.connect(self._on_canvas_selection_changed)
        self._custom_point_btn.toggled.connect(self._canvas.set_custom_point_mode)
        for tool, btn in self._tool_buttons.items():
            btn.clicked.connect(weak_slot(self._set_tool, tool))
        self._undo_btn.clicked.connect(self._canvas.undo_last_point)
        self._fit_btn.clicked.connect(self._canvas.fit_to_view)

        self._selection_count_label = QLabel("0 points selected")
        self._selection_count_label.setProperty("role", "faint")
        root.addWidget(self._selection_count_label)

        # ── resolution-mismatch warning ──────────────────────────────────
        self._mismatch_label = QLabel("")
        self._mismatch_label.setWordWrap(True)
        self._mismatch_label.setProperty("role", "warn")
        self._mismatch_label.setVisible(False)
        root.addWidget(self._mismatch_label)

        # ── right: zone list and properties ──────────────────────────────
        pane = QFrame()
        pane.setObjectName("DetailPane")
        pane.setFixedWidth(280)
        pane_outer = QVBoxLayout(pane)
        pane_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        side = QVBoxLayout(inner)
        side.setContentsMargins(18, 26, 18, 18)
        side.setSpacing(10)
        scroll.setWidget(inner)
        pane_outer.addWidget(scroll)
        outer.addWidget(pane)

        zones_label = QLabel("ZONES")
        zones_label.setObjectName("SectionLabel")
        side.addWidget(zones_label)
        self._zone_list = QListWidget()
        self._zone_list.setMinimumHeight(140)
        side.addWidget(self._zone_list)
        self._count_label = QLabel("0 zones loaded")
        self._count_label.setProperty("role", "faint")
        side.addWidget(self._count_label)
        self._zone_info = QLabel(_ZONE_HINT)
        self._zone_info.setWordWrap(True)
        self._zone_info.setProperty("role", "faint")
        side.addWidget(self._zone_info)
        self._delete_zone_btn = QPushButton("Delete zone")
        self._delete_zone_btn.setProperty("role", "outline")
        self._delete_zone_btn.setEnabled(False)
        self._delete_zone_btn.clicked.connect(self._delete_selected_zone)
        side.addWidget(self._delete_zone_btn)
        self._zone_list.currentRowChanged.connect(self._on_zone_row_changed)
        self._canvas.zoneEdited.connect(self._on_zone_edited)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load CSV…")
        load_btn.setProperty("role", "outline")
        load_btn.clicked.connect(self._load_csv)
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("role", "outline")
        clear_btn.clicked.connect(self._clear_zones)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(clear_btn)
        side.addLayout(btn_row)

        import_btn = QPushButton("Import ROIs from Session")
        import_btn.setProperty("role", "outline")
        import_btn.clicked.connect(self._import_from_session)
        side.addWidget(import_btn)

        props_label = QLabel("NEW ZONE")
        props_label.setObjectName("SectionLabel")
        side.addSpacing(6)
        side.addWidget(props_label)
        save_zone_form = QFormLayout()
        self._zone_name_edit = QLineEdit()
        save_zone_form.addRow("Name", self._zone_name_edit)
        self._zone_level_combo = QComboBox()
        self._zone_level_combo.setEditable(True)
        self._zone_level_combo.addItems(["main", "secondary"])
        save_zone_form.addRow("Level", self._zone_level_combo)
        side.addLayout(save_zone_form)
        self._save_zone_btn = QPushButton("Save Zone")
        self._save_zone_btn.setProperty("role", "primary")
        self._save_zone_btn.setEnabled(False)
        self._save_zone_btn.clicked.connect(self._save_zone)
        side.addWidget(self._save_zone_btn)

        # Named validator reference points, shown as guides only -- never
        # auto-converted into ROI polygons, since a point set may mix
        # arena corners with unrelated marks (e.g. a feeder) that would
        # produce a nonsense hull.
        landmarks_label = QLabel("LANDMARKS")
        landmarks_label.setObjectName("SectionLabel")
        side.addSpacing(6)
        side.addWidget(landmarks_label)
        self._landmarks_list = QListWidget()
        self._landmarks_list.setMinimumHeight(80)
        side.addWidget(self._landmarks_list)
        side.addStretch()

        self._session_combo.currentTextChanged.connect(self._refresh_landmarks)
        self._session_combo.currentTextChanged.connect(self._refresh_canvas)

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

    # ── slots: select, reshape and delete a saved zone ───────────────────

    def _on_zone_row_changed(self, row: int) -> None:
        index = row if row >= 0 else None
        self._canvas.set_selected_zone(index)
        self._delete_zone_btn.setEnabled(index is not None)
        if index is None or self._store is None or self._store.manifest is None:
            self._zone_info.setText(_ZONE_HINT)
            return
        roi = self._store.manifest.zones.rois[index]
        area = polygon_area(roi.vertices)
        cfg = self._store.manifest.calibration
        if cfg.mode == "scalar" and cfg.px_per_cm:
            area_text = f"{area / cfg.px_per_cm**2:.0f} cm²"
        else:
            area_text = f"{area:.0f} px²"
        self._zone_info.setText(f"{len(roi.vertices)} vertices · {area_text}")

    def _on_zone_edited(self, index: int, vertices: list) -> None:
        if self._store is None or self._store.manifest is None:
            return
        try:
            self._store.update_zone_vertices(index, vertices)
        except ZoneValidationError as exc:
            QMessageBox.warning(
                self, "Zone not changed", f"{exc.args[0]}\n\n{exc.remediation}"
            )
            # Put the dragged handle and the outline back on the committed shape.
            self._canvas.set_selected_zone(index)
            self._on_zone_row_changed(index)
            return
        self._zone_list.setCurrentRow(index)

    def _delete_selected_zone(self) -> None:
        row = self._zone_list.currentRow()
        if self._store is None or self._store.manifest is None or row < 0:
            return
        zones = self._store.manifest.zones
        rois = [r for i, r in enumerate(zones.rois) if i != row]
        try:
            self._store.update_zones(zones.model_copy(update={"rois": rois}))
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to delete zone:\n{exc}")

    def _refresh_list(self) -> None:
        keep = self._zone_list.currentRow()
        self._zone_list.clear()
        if self._store is None or self._store.manifest is None:
            self._count_label.setText("0 zones loaded")
            self._canvas.set_saved_zones([])
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
        self._canvas.set_saved_zones(rois)
        if 0 <= keep < n:
            self._zone_list.setCurrentRow(keep)

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

    def _refresh_canvas(self) -> None:
        session_id = self._session_combo.currentText()
        if self._store is None or not session_id:
            self._canvas.load_session(None, None)
            return
        facts = self._store.session_facts(session_id)
        if facts is None:
            self._canvas.load_session(None, None)
            return
        self._canvas.load_session(
            facts.background_image_path,
            facts.setup_points,
            frame_size=(facts.width_px, facts.height_px),
        )

    def _set_tool(self, tool: object) -> None:
        self._canvas.set_tool(tool)

    def _on_canvas_selection_changed(self) -> None:
        n = len(self._canvas.selected_points())
        self._selection_count_label.setText(f"{n} point{'s' if n != 1 else ''} selected")
        self._save_zone_btn.setEnabled(n >= _MIN_ZONE_VERTICES)

    def _frame_size_to_record(self, zones) -> dict[str, int]:
        """The frame size to stamp on the zone set, or nothing.

        Only a zone set with no zones yet is stamped, with the frame of the session the zone
        was drawn on. A set that already holds zones keeps what it has: zones drawn before the
        canvas matched the frame carry no size, and stamping them now would relabel coordinates
        that are not video pixels as video pixels, hiding the mismatch the stamp exists to catch.
        """
        if zones.rois or self._store is None:
            return {}
        facts = self._store.session_facts(self._session_combo.currentText())
        if facts is None or facts.width_px <= 0 or facts.height_px <= 0:
            return {}
        return {"source_width_px": facts.width_px, "source_height_px": facts.height_px}

    def _save_zone(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        name = self._zone_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Give this zone a name before saving.")
            return
        vertices = self._canvas.selected_points()
        if len(vertices) < _MIN_ZONE_VERTICES:
            return
        level = self._zone_level_combo.currentText().strip() or "main"
        roi = ROI(name=name, level=level, vertices=vertices)
        zones = self._store.manifest.zones
        update: dict[str, object] = {"rois": [*zones.rois, roi]}
        update.update(self._frame_size_to_record(zones))
        try:
            self._store.update_zones(zones.model_copy(update=update))
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save zone:\n{exc}")
            return
        self._canvas.clear_selection()
        self._zone_name_edit.clear()
