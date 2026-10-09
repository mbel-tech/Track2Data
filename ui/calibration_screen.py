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
  • view_combo           QComboBox       camera view (Not set / Top-down / Side view);
                          committed to store.update_scene on its own, never through
                          the calibration commit
  • edits auto-commit (debounced) → store.update_calibration; flush() on leave
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from track2data.calibration.session_unit import session_scale
from track2data.core.models import SceneConfig
from ui.widgets.autocommit import AutoCommit

_UNIT_CHOICES = ["cm", "mm", "m"]

_IDT_INFO = (
    "Uses each session's own calibration ratio, recorded by the "
    "idtracker.ai validator's Length Calibration tool."
)
_OTHER_INFO = (
    "Only idtracker.ai records a calibration. For this tracker's files, Session calibration "
    'uses the scale you gave when importing them ("Scale (pixels per cm)").'
)
_NO_SCALE_TIP = (
    "None of these sessions carries a calibration. idtracker.ai sessions record one in the "
    'validator; for other trackers give "Scale (pixels per cm)" when importing.'
)


_IDT_DOC = "https://idtracker.ai/latest/reference/generated/idtrackerai.Session.html"
_CTRAX_DOC = "https://ctrax.sourceforge.net/bmat.html"

#: (raw stat value, label) for the choice between several length calibrations.
_STAT_CHOICES = (
    ("mean", "Average (idtracker.ai's own length unit)"),
    ("median", "Median of the calibrations"),
)


def _is_idtrackerai(reader: str) -> bool:
    return reader.startswith("idtrackerai")


def _is_ctrax(reader: str) -> bool:
    return reader in ("ctrax_mat", "trx_mat")


def _info_html(readers: set[str]) -> str:
    """What each tracker records, for the trackers in the project (all of them when none yet)."""
    idt = any(_is_idtrackerai(r) for r in readers)
    ctrax = any(_is_ctrax(r) for r in readers)
    other = any(not _is_idtrackerai(r) and not _is_ctrax(r) for r in readers)
    everything = not readers
    parts: list[str] = []
    if idt or everything:
        parts.append(
            "<p><b>idtracker.ai</b> records the scale itself: the Validator's Length Calibration "
            "tool saves one or more measurements, and <code>length_unit</code> is their average. "
            "When a session holds several, choose the average or the median below. "
            f'<a href="{_IDT_DOC}">idtrackerai.Session reference</a></p>'
        )
    if ctrax or everything:
        parts.append(
            "<p><b>Ctrax / JAABA <code>trx.mat</code></b> records <code>pxpermm</code> (pixels per "
            "millimetre) once its units have been converted; Track2Data turns it into pixels per "
            "cm and ignores the tool's default of exactly 1. Ctrax's raw <code>.mat</code> "
            "records no scale. "
            f'<a href="{_CTRAX_DOC}">Ctrax trx fields</a></p>'
        )
    if other or everything:
        parts.append(
            "<p><b>DeepLabCut, SLEAP and Ctrax raw files</b> record no scale. Give "
            "&ldquo;Scale (pixels per cm)&rdquo; when importing them, or use Custom or "
            "Body length.</p>"
        )
    return "".join(parts)


class _InfoBubble(QFrame):
    """A small popup that closes when you click elsewhere; its links open in the browser."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setProperty("card", True)
        self.setMaximumWidth(420)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setOpenExternalLinks(True)
        col.addWidget(self._label)

    def show_at(self, html: str, anchor: QWidget) -> None:
        self._label.setText(html)
        self.adjustSize()
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.show()


#: (raw CameraView value, label, what it means for the project).
_VIEW_CHOICES = (
    (
        "unknown",
        "Not set",
        "Tell Track2Data how the camera looked at the animals. Metrics that only make sense "
        "for one view stay off until you do.",
    ),
    (
        "top",
        "Top-down",
        "The camera looks down on the arena. Every metric that does not need a side view applies.",
    ),
    (
        "side",
        "Side view",
        "The camera looks at the tank from the side, so image height is depth. Draw the main "
        "zone from the waterline to the floor on the Zones screen; this switches on Vertical "
        "Position (IL-15).",
    ),
)


class _ModeCard(QFrame):
    """A selectable card around one calibration radio button."""

    def __init__(self, radio: QRadioButton, description: str) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.setProperty("selected", False)
        self._radio = radio
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(6)
        col.addWidget(radio)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setProperty("role", "muted")
        col.addWidget(desc)
        radio.toggled.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.setProperty("selected", self._radio.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        self._radio.setChecked(True)
        super().mousePressEvent(event)


class CalibrationScreen(QWidget):
    """Stage 3 — Arena calibration (body length, custom, or session)."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._auto = AutoCommit(self._apply, self)
        # The camera view is not a calibration: it has its own commit, so a calibration that is
        # unchanged (and returns early) or blocked can never swallow it.
        self._view_auto = AutoCommit(self._apply_scene, self)
        self._build_ui()
        if store is not None:
            store.calibrationChanged.connect(self._on_calibration_changed)
            store.projectChanged.connect(self._on_calibration_changed)
            store.sceneChanged.connect(self._on_calibration_changed)
            store.sessionsChanged.connect(self._refresh_readiness)
            store.sessionFactsChanged.connect(self._refresh_readiness)
        self._on_calibration_changed()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Calibration")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "How pixels become real units. Distances, speeds and areas in every export use this."
        )
        subtitle.setObjectName("PageLead")
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

        mode_row.setSpacing(14)
        for radio, text in (
            (
                self._radio_bl,
                "Scales each animal by its own median body length. Outputs in BL and cm.",
            ),
            (self._radio_scalar, "One px-per-cm factor for every session. Measure it on a frame."),
            (
                self._radio_session,
                "Use the scale each session already carries: idtracker.ai's length unit, "
                "or the scale set at import.",
            ),
        ):
            mode_row.addWidget(_ModeCard(radio, text), 1)
        root.addLayout(mode_row)

        # ── BL info ───────────────────────────────────────────────────────
        self._bl_label = QLabel("Body length will be derived from session bounding boxes.")
        self._bl_label.setProperty("role", "muted")
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
        self._px_spin.setMinimumWidth(180)
        scalar_form.addRow("Pixels per unit:", self._px_spin)
        self._measure_btn = QPushButton("Measure on frame…")
        self._measure_btn.setProperty("role", "outline")
        self._measure_btn.setToolTip(
            "Click both ends of an object of known length on a session frame"
        )
        self._measure_btn.clicked.connect(self._measure_on_frame)
        scalar_form.addRow("", self._measure_btn)
        root.addWidget(self._scalar_widget)

        # ── session calibration controls ────────────────────────────────
        self._session_widget = QWidget()
        session_layout = QVBoxLayout(self._session_widget)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(8)

        info_row = QHBoxLayout()
        session_info = QLabel(_IDT_INFO)
        self._session_info = session_info
        session_info.setProperty("role", "muted")
        session_info.setWordWrap(True)
        info_row.addWidget(session_info, 1)
        self._info_btn = QToolButton()
        self._info_btn.setText("\u24d8")
        self._info_btn.setAutoRaise(True)
        self._info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._info_btn.setToolTip("What each tracker records, with links to its documentation")
        self._info_btn.setAccessibleName("Calibration info")
        self._info_btn.clicked.connect(self._show_info)
        info_row.addWidget(self._info_btn, 0, Qt.AlignmentFlag.AlignTop)
        session_layout.addLayout(info_row)
        self._bubble = _InfoBubble(self)

        unit_form = QFormLayout()
        unit_form.setContentsMargins(0, 0, 0, 0)
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(_UNIT_CHOICES)
        unit_form.addRow("Unit:", self._unit_combo)
        self._stat_combo = QComboBox()
        for value, label in _STAT_CHOICES:
            self._stat_combo.addItem(label, value)
        self._stat_combo.setToolTip(
            "Used when a session holds several length calibrations (idtracker.ai)."
        )
        self._stat_label = QLabel("Several calibrations:")
        unit_form.addRow(self._stat_label, self._stat_combo)
        session_layout.addLayout(unit_form)

        self._confirm_check = QCheckBox(
            "I confirm these sessions were calibrated in the unit selected above."
        )
        session_layout.addWidget(self._confirm_check)

        readiness_label = QLabel("Per-session readiness:")
        readiness_label.setObjectName("SectionLabel")
        readiness_label.setText("PER-SESSION READINESS")
        session_layout.addWidget(readiness_label)
        self._readiness_list = QListWidget()
        self._readiness_list.setMinimumHeight(100)
        session_layout.addWidget(self._readiness_list)

        root.addWidget(self._session_widget)

        # ── camera view ───────────────────────────────────────────────────
        view_label = QLabel("CAMERA VIEW")
        view_label.setObjectName("SectionLabel")
        root.addWidget(view_label)
        view_form = QFormLayout()
        view_form.setContentsMargins(0, 0, 0, 0)
        self._view_combo = QComboBox()
        for value, label, _help in _VIEW_CHOICES:
            self._view_combo.addItem(label, value)
        view_form.addRow("Recorded from:", self._view_combo)
        root.addLayout(view_form)
        self._view_help = QLabel()
        self._view_help.setProperty("role", "muted")
        self._view_help.setWordWrap(True)
        root.addWidget(self._view_help)
        self._update_view_help()

        root.addStretch()

        # wire radio changes
        self._radio_bl.toggled.connect(self._update_mode_visibility)
        self._radio_scalar.toggled.connect(self._update_mode_visibility)
        self._radio_session.toggled.connect(self._update_mode_visibility)
        self._update_mode_visibility()
        self._refresh_readiness()

        # auto-commit (no Apply button): every edit is saved after a pause
        for radio in (self._radio_bl, self._radio_scalar, self._radio_session):
            radio.toggled.connect(self._auto.trigger)
        self._px_spin.valueChanged.connect(self._auto.trigger)
        self._unit_combo.currentIndexChanged.connect(self._auto.trigger)
        self._stat_combo.currentIndexChanged.connect(self._auto.trigger)
        self._stat_combo.currentIndexChanged.connect(self._refresh_readiness)
        self._confirm_check.toggled.connect(self._auto.trigger)
        self._view_combo.currentIndexChanged.connect(self._update_view_help)
        self._view_combo.currentIndexChanged.connect(self._view_auto.trigger)

    def flush(self) -> None:
        """Commit any pending edit now (called when the screen is left)."""
        self._auto.flush()
        self._view_auto.flush()

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
            updates["session_calibration_stat"] = self._stat_combo.currentData()
            updates["length_unit_label"] = self._unit_combo.currentText()
            updates["length_unit_confirmed_by_user"] = self._confirm_check.isChecked()
        cfg = current.model_copy(update=updates)
        if cfg == current:
            return
        try:
            self._store.update_calibration(cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply calibration:\n{exc}")

    def _update_view_help(self) -> None:
        value = self._view_combo.currentData()
        for choice, _label, text in _VIEW_CHOICES:
            if choice == value:
                self._view_help.setText(text)
                return

    def _apply_scene(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        current = self._store.manifest.scene
        # Validated, so the combo's value can never put a bad view in the manifest; built from
        # the current scene so a field this screen does not show is preserved.
        scene = SceneConfig.model_validate(
            {**current.model_dump(), "camera_view": self._view_combo.currentData()}
        )
        if scene != current:
            self._store.update_scene(scene)

    def _on_calibration_changed(self) -> None:
        with self._auto.suppressed(), self._view_auto.suppressed():
            self._populate()

    def _populate(self) -> None:
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
                self._stat_combo.setCurrentIndex(
                    max(0, self._stat_combo.findData(cfg.session_calibration_stat))
                )
                self._confirm_check.setChecked(cfg.length_unit_confirmed_by_user)
            else:
                self._radio_bl.setChecked(True)
            self._view_combo.setCurrentIndex(
                max(0, self._view_combo.findData(self._store.manifest.scene.camera_view))
            )
        self._update_mode_visibility()
        self._refresh_readiness()

    def _measure_on_frame(self) -> None:
        """Open the two-point ruler on the first session with facts and, if
        accepted, put its pixels-per-unit into the spin box."""
        from ui.widgets.ruler_dialog import RulerDialog

        background, size = None, (640.0, 480.0)
        if self._store is not None and self._store.manifest is not None:
            for ref in self._store.manifest.sessions:
                facts = self._store.session_facts(ref.session_id)
                if facts is not None:
                    background = facts.background_image_path
                    size = (float(facts.width_px), float(facts.height_px))
                    break
        dialog = RulerDialog(background, size, parent=self)
        if dialog.exec() == RulerDialog.DialogCode.Accepted:
            scale = dialog.px_per_unit()
            if scale is not None:
                self._px_spin.setValue(min(scale, self._px_spin.maximum()))

    def body_length_summary(self) -> str:
        """Median / range of the sessions' per-animal body lengths (pixels)."""
        values: list[float] = []
        n_sessions = 0
        if self._store is not None and self._store.manifest is not None:
            for ref in self._store.manifest.sessions:
                facts = self._store.session_facts(ref.session_id)
                if facts is not None and facts.body_length_px:
                    n_sessions += 1
                    values.extend(v for v in facts.body_length_px if v == v)
        if not values:
            return "Body length will be derived from session bounding boxes."
        import statistics

        return (
            f"Body length from {len(values)} animal(s) in {n_sessions} session(s): "
            f"median {statistics.median(values):.1f} px "
            f"(range {min(values):.1f} to {max(values):.1f} px). "
            "Distances are reported in body lengths; physical units need a scale."
        )

    def _refresh_readiness(self) -> None:
        self._bl_label.setText(self.body_length_summary())
        self._readiness_list.clear()
        if self._store is None or self._store.manifest is None:
            self._set_session_available(True)
            return
        all_facts = []
        for ref in self._store.manifest.sessions:
            facts = self._store.session_facts(ref.session_id)
            all_facts.append(facts)
            if facts is None:
                text = f"{ref.session_id} — checking…"
            elif (scale := self._scale_of(facts)) is not None:
                many = len(facts.calibration_ratios)
                how = (
                    f", {self._stat_combo.currentText().split(' (')[0].lower()} of {many}"
                    if many > 1
                    else ""
                )
                text = f"{ref.session_id} — calibrated ({scale:.4g} px per unit{how})"
            elif _is_idtrackerai(facts.reader):
                text = f"{ref.session_id} — not calibrated"
            else:
                text = f"{ref.session_id} — no scale set at import"
            self._readiness_list.addItem(text)

        known = [f for f in all_facts if f is not None]
        has_idt = any(_is_idtrackerai(f.reader) for f in known)
        has_other = any(not _is_idtrackerai(f.reader) for f in known)
        if has_other and not has_idt:
            self._session_info.setText(_OTHER_INFO)
        elif has_other:
            self._session_info.setText(_IDT_INFO + " " + _OTHER_INFO)
        else:
            self._session_info.setText(_IDT_INFO)
        # Offered unless every session is known and none can supply a scale. Never withdrawn
        # while the mode is selected, so a saved choice stays visible.
        available = (
            len(known) < len(all_facts)
            or not known
            or has_idt
            or any(self._scale_of(f) is not None for f in known)
        )
        # The average/median choice only matters for idtracker.ai sessions.
        self._stat_label.setVisible(has_idt)
        self._stat_combo.setVisible(has_idt)
        self._set_session_available(available)

    def _scale_of(self, facts) -> float | None:
        ratios = list(facts.calibration_ratios)
        return session_scale(
            facts.length_unit,
            [{"point_A": [0, 0], "point_B": [r, 0], "distance": 1.0} for r in ratios],
            self._stat_combo.currentData() or "mean",
        )

    def _show_info(self) -> None:
        readers: set[str] = set()
        if self._store is not None and self._store.manifest is not None:
            for ref in self._store.manifest.sessions:
                facts = self._store.session_facts(ref.session_id)
                if facts is not None:
                    readers.add(facts.reader)
        self._bubble.show_at(_info_html(readers), self._info_btn)

    def _set_session_available(self, available: bool) -> None:
        enabled = available or self._radio_session.isChecked()
        self._radio_session.setEnabled(enabled)
        self._radio_session.setToolTip("" if available else _NO_SCALE_TIP)
