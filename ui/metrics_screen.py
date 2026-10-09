"""
Stage 6b — Metric selection screen (registry-driven QTableWidget).

QTabWidget with three tabs: Individual / Group / Zone. Each tab is a
QTableWidget populated from track2data.metrics.list_for_level(level),
columns: include (checkbox) / metric_name / info (ⓘ) / config (⚙ --
opens MetricConfigDialog for metrics that declare `parameters`;
disabled otherwise). Quality threshold QDoubleSpinBox + Apply button.

The registry id ("IL-1") and the snake_case internal name
("path_length") are deliberately never shown -- they're engine/export
identifiers, not something a researcher should have to read to select
a metric. The id still exists everywhere it's actually needed: as
_ROLE_METRIC_ID user-data on the Include cell (the real identifier
used for selection state and persistence), in exported column names,
and in docs/METRICS_SPEC.md.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.metrics.availability import view_unavailable_reason
from ui.dialogs.metric_config_dialog import MetricConfigDialog
from ui.dialogs.metric_info_dialog import MetricInfoDialog
from ui.widgets.autocommit import AutoCommit

_COLUMN_HEADERS = ["Include", "Name", "Info", "Config"]
_COL_INCLUDE, _COL_NAME, _COL_INFO, _COL_CONFIG = range(4)

#: Quick selections. Ids only; the screen ticks exactly these (None = all).
PRESETS: dict[str, list[str] | None] = {
    "Standard locomotor": ["IL-1", "IL-2", "IL-4"],
    "Thigmotaxis & space use": ["IL-3", "IL-14", "Z-1", "Z-8"],
    "Social dynamics": ["GL-1", "GL-2", "GL-4", "GL-6"],
    "All metrics": None,
}
_ROLE_METRIC_ID = Qt.ItemDataRole.UserRole
_ROLE_REQUIRES_IDENTITY = Qt.ItemDataRole.UserRole + 1
#: A name cell's own tooltip (e.g. 'superseded by ...'), which the availability pass keeps and
#: adds to rather than replaces.
_ROLE_BASE_TOOLTIP = Qt.ItemDataRole.UserRole + 2


def _summarise_ids(session_ids: list[str], limit: int = 3) -> str:
    """Name the first few sessions, then count the rest.

    A project can hold 70 sessions (the GOT corpus does); a tooltip that
    listed every one would be unreadable, and one that listed none would
    leave the user guessing which sessions it meant.
    """
    if len(session_ids) <= limit:
        return ", ".join(session_ids)
    shown = ", ".join(session_ids[:limit])
    return f"{shown} and {len(session_ids) - limit} more"


def _natural_sort_key(metric_cls):
    """Sort metrics naturally: GL-1, GL-2, GL-10 (not GL-1, GL-10, GL-2).

    Third-party metrics (loaded via the ``track2data.metrics`` entry
    point, see ENGINE_DESIGN.md §8.5/§11) aren't required to use the
    built-in PREFIX-NUMBER id shape -- fall back to a plain string sort
    for any id that doesn't parse, rather than crashing the whole
    screen on one non-conforming plugin metric.
    """
    prefix, _, number = metric_cls.id.rpartition("-")
    try:
        return (prefix, int(number))
    except ValueError:
        return (metric_cls.id, 0)


class MetricsScreen(QWidget):
    """Stage 6b — Select behavioural metrics to compute."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._auto = AutoCommit(self._apply, self)
        self._build_ui()
        self._update_counter()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)
            store.sessionsChanged.connect(self._update_availability)
            store.sceneChanged.connect(self._update_availability)
            store.zonesChanged.connect(self._update_zone_tab_enabled)
            self._load_from_store()
            self._update_availability()
            self._update_zone_tab_enabled()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Metrics")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Choose what to extract. Diagnostics (coverage, identity stability, crossings) "
            "always run."
        )
        subtitle.setObjectName("PageLead")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── search + presets ─────────────────────────────────────────────
        tools = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search metrics by name or ID…")
        self._search.setClearButtonEnabled(True)
        self._search.setObjectName("Search")
        self._search.textChanged.connect(self._apply_search)
        tools.addWidget(self._search, 1)
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Preset: None")
        for name in PRESETS:
            self._preset_combo.addItem(name)
        self._preset_combo.setToolTip("Replace the current selection with a preset")
        self._preset_combo.activated.connect(self._on_preset_chosen)
        tools.addWidget(self._preset_combo)
        root.addLayout(tools)
        self._search_hint = QLabel("")
        self._search_hint.setProperty("role", "faint")
        root.addWidget(self._search_hint)

        self._tabs = QTabWidget()

        self._ind_table = self._make_table("individual")
        self._grp_table = self._make_table("group")
        self._zone_table = self._make_table("zone")

        self._tabs.addTab(self._ind_table, "Individual")
        self._tabs.addTab(self._grp_table, "Group")
        self._tabs.addTab(self._zone_table, "Zone")

        root.addWidget(self._tabs, 1)

        self._counter = QLabel("")
        self._counter.setObjectName("Counter")
        self._diag_note = QLabel(
            "Diagnostic metrics (D-1 … D-10: coverage, accuracy, identity stability, …) "
            "are always computed and are not listed here."
        )
        self._diag_note.setWordWrap(True)
        self._diag_note.setProperty("role", "faint")
        root.addWidget(self._diag_note)

        qform = QHBoxLayout()
        qform.setSpacing(10)
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 1.0)
        self._quality_spin.setSingleStep(0.05)
        self._quality_spin.setDecimals(2)
        self._quality_spin.setValue(0.0)
        qform.addWidget(QLabel("Quality threshold"))
        qform.addWidget(self._quality_spin)
        qform.addSpacing(16)
        self._timepoint_spin = QDoubleSpinBox()
        self._timepoint_spin.setRange(0.0, 100000.0)
        self._timepoint_spin.setDecimals(2)
        self._timepoint_spin.setSingleStep(1.0)
        self._timepoint_spin.setSuffix(" min")
        self._timepoint_spin.setSpecialValueText("Whole session")
        self._timepoint_spin.setToolTip(
            "Split each session into time bins of this length and report every "
            "metric per bin (adds bin_index, bin_start_s, bin_end_s columns). "
            "Whole-track metrics such as tortuosity stay one row per animal."
        )
        qform.addWidget(QLabel("Time bins"))
        qform.addWidget(self._timepoint_spin)
        qform.addStretch()
        qform.addWidget(self._counter)
        root.addLayout(qform)

        # No Apply button: edits auto-commit after a pause; MainWindow
        # calls flush() when the screen is left.
        for table in (self._ind_table, self._grp_table, self._zone_table):
            table.itemChanged.connect(self._on_item_changed)
        self._quality_spin.valueChanged.connect(
            lambda _v: self._auto.trigger() if self._differs_from_store() else None
        )
        self._timepoint_spin.valueChanged.connect(
            lambda _v: self._auto.trigger() if self._differs_from_store() else None
        )

    def flush(self) -> None:
        """Commit any pending edit now (called when the screen is left)."""
        self._auto.flush()

    def _differs_from_store(self) -> bool:
        if self._store is None or self._store.manifest is None:
            return False
        current = self._store.manifest.metrics
        return self._selection_from_widgets(current) != current

    def _tables(self) -> list[tuple[str, QTableWidget]]:
        return [
            ("Individual", self._ind_table),
            ("Group", self._grp_table),
            ("Zone", self._zone_table),
        ]

    def _apply_search(self, text: str) -> None:
        needle = text.strip().lower()
        tabs_with_hits: list[str] = []
        for tab_name, table in self._tables():
            hits = 0
            for row in range(table.rowCount()):
                include = table.item(row, _COL_INCLUDE)
                name = table.item(row, _COL_NAME)
                haystack = f"{include.data(_ROLE_METRIC_ID)} {name.text() if name else ''}".lower()
                visible = not needle or needle in haystack
                table.setRowHidden(row, not visible)
                hits += visible
            if needle and hits:
                tabs_with_hits.append(f"{tab_name} ({hits})")
        if not needle:
            self._search_hint.setText("")
        elif tabs_with_hits:
            self._search_hint.setText("Matches in: " + ", ".join(tabs_with_hits))
        else:
            self._search_hint.setText("No metrics match.")

    def _on_preset_chosen(self, index: int) -> None:
        if index > 0:
            self.apply_preset(self._preset_combo.itemText(index))
        self._preset_combo.setCurrentIndex(0)

    def apply_preset(self, name: str) -> None:
        """Tick exactly the metrics of preset *name* (all others unticked)."""
        ids = PRESETS[name]
        for _tab, table in self._tables():
            for row in range(table.rowCount()):
                item = table.item(row, _COL_INCLUDE)
                wanted = ids is None or item.data(_ROLE_METRIC_ID) in ids
                item.setCheckState(Qt.CheckState.Checked if wanted else Qt.CheckState.Unchecked)

    def _update_counter(self) -> None:
        n_ind = len(self._checked_ids(self._ind_table))
        n_grp = len(self._checked_ids(self._grp_table))
        n_zone = len(self._checked_ids(self._zone_table))
        total = sum(t.rowCount() for _n, t in self._tables())
        self._counter.setText(
            f"Selected: {n_ind + n_grp + n_zone} / {total} metrics "
            f"({n_ind} individual · {n_grp} group · {n_zone} zone)"
        )
        for index, (name, table) in enumerate(self._tables()):
            checked = len(self._checked_ids(table))
            self._tabs.setTabText(index, f"{name} {checked}/{table.rowCount()}")
        self._preset_combo.setItemText(0, f"Preset: {self.current_preset_name()}")

    def current_preset_name(self) -> str:
        """The preset the ticked metrics exactly match, "None" when nothing is
        ticked, otherwise "Custom"."""
        selected = {
            mid for _n, table in self._tables() for mid in self._checked_ids(table)
        }
        if not selected:
            return "None"
        everything = {
            table.item(row, _COL_INCLUDE).data(_ROLE_METRIC_ID)
            for _n, table in self._tables()
            for row in range(table.rowCount())
        }
        for name, ids in PRESETS.items():
            if selected == (everything if ids is None else set(ids)):
                return name
        return "Custom"

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self._update_counter()
        # itemChanged also fires for flag/tooltip updates (identity graying);
        # only a selection that differs from the store is an edit to commit.
        if item.column() == _COL_INCLUDE and self._differs_from_store():
            self._auto.trigger()

    def _make_table(self, level: str) -> QTableWidget:
        metric_classes = sorted(metrics.list_for_level(level), key=_natural_sort_key)
        table = QTableWidget(len(metric_classes), len(_COLUMN_HEADERS))
        table.setHorizontalHeaderLabels(_COLUMN_HEADERS)
        table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setShowGrid(False)
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

            # .label ("Path Length"), not .name ("path_length") -- the
            # latter is the snake_case identifier used internally
            # (registry keys, exported column name suffixes), not
            # something a researcher should see in the UI.
            name = metric_cls.label
            superseded_by = getattr(metric_cls, "superseded_by", None)
            if superseded_by:
                name += f" (superseded by {superseded_by})"
            name_item = QTableWidgetItem(name)
            if superseded_by:
                superseded_note = (
                    f"{metric_cls.label} is kept for output compatibility with "
                    f"existing projects. {superseded_by} computes the same idea "
                    "with a better statistic -- see its ⓘ for details."
                )
                name_item.setData(_ROLE_BASE_TOOLTIP, superseded_note)
                name_item.setToolTip(superseded_note)
            table.setItem(row, _COL_NAME, name_item)

            doc = metric_cls.documentation
            if doc.formula_plain is not None or doc.citation is not None:
                info_btn = QPushButton("ⓘ")
                info_btn.setFixedSize(28, 28)
                info_btn.setProperty("role", "icon")
                info_btn.clicked.connect(partial(self._show_metric_info, metric_cls))
                table.setCellWidget(row, _COL_INFO, info_btn)

            config_btn = QPushButton("⚙")
            config_btn.setFixedSize(28, 28)
            config_btn.setProperty("role", "icon")
            # getattr, not metric_cls.parameters, for the same reason as
            # _natural_sort_key's fallback above -- a third-party plugin
            # metric isn't required to define it and shouldn't crash the
            # whole screen for not doing so.
            if getattr(metric_cls, "parameters", []):
                config_btn.clicked.connect(partial(self._show_metric_config, metric_cls))
            else:
                config_btn.setEnabled(False)
                config_btn.setToolTip("This metric has no configurable parameters.")
            table.setCellWidget(row, _COL_CONFIG, config_btn)

        return table

    def _show_metric_info(self, metric_cls) -> None:
        dlg = MetricInfoDialog(metric_cls, self)
        dlg.exec()

    def _show_metric_config(self, metric_cls) -> None:
        current_values: dict = {}
        if self._store is not None and self._store.manifest is not None:
            current_values = self._store.manifest.metrics.config.get(metric_cls.id, {})

        dlg = MetricConfigDialog(metric_cls, current_values, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if self._store is None or self._store.manifest is None:
            QMessageBox.information(self, "Info", "No project open.")
            return

        # Fold in what's currently on screen, not just the new config.
        # update_metrics() emits metricsChanged, which re-runs
        # _load_from_store and overwrites every checkbox and the quality
        # spin from the manifest -- so writing config alone would
        # silently discard any selection the user had ticked but not yet
        # clicked Apply on.
        current = self._store.manifest.metrics
        sel = self._selection_from_widgets(current).model_copy(
            update={"config": {**current.config, metric_cls.id: dlg.values()}}
        )
        try:
            self._store.update_metrics(sel)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save metric configuration:\n{exc}")

    # ── slots ──────────────────────────────────────────────────────────────

    def _checked_ids(self, table: QTableWidget) -> list[str]:
        result = []
        for row in range(table.rowCount()):
            item = table.item(row, _COL_INCLUDE)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(_ROLE_METRIC_ID))
        return result

    def _selection_from_widgets(self, current):
        """This screen's live widget state, layered onto `current`.

        model_copy(update=...) against the manifest's current
        MetricSelection, never a fresh MetricSelection(...) -- this
        screen has no widgets for `diagnostic` or `config`, and
        building one from scratch used to silently reset both to
        their defaults on every Apply click.
        """
        return current.model_copy(
            update={
                "individual": self._checked_ids(self._ind_table),
                "group": self._checked_ids(self._grp_table),
                "zone": self._checked_ids(self._zone_table),
                "quality_threshold": self._quality_spin.value(),
                "timepoint_minutes": self._timepoint_spin.value() or None,
            }
        )

    def _apply(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sel = self._selection_from_widgets(self._store.manifest.metrics)
        if sel == self._store.manifest.metrics:
            return
        try:
            self._store.update_metrics(sel)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply metric selection:\n{exc}")

    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        if self._auto.pending:
            return  # keep the user's not-yet-committed edit; it commits next
        sel = self._store.manifest.metrics
        with self._auto.suppressed():
            self._set_checked(self._ind_table, sel.individual)
            self._set_checked(self._grp_table, sel.group)
            self._set_checked(self._zone_table, sel.zone)
            self._quality_spin.setValue(sel.quality_threshold)
            self._timepoint_spin.setValue(sel.timepoint_minutes or 0.0)
        self._update_availability()
        self._update_zone_tab_enabled()
        self._update_counter()

    def _update_availability(self) -> None:
        """Grey the rows the project cannot run, and say why, in one pass.

        Two things rule a row out, and a row can be ruled out by both:

        * **identity** -- reflects each session's identity-free status. Keyed on
          SessionRef.is_identity_free() rather than has_stable_identities, which also folds in
          coverage heuristics and so used to grey rows the engine would happily have computed
          (and vice versa). That predicate reads the manifest's cached track_wo_identities plus
          the user's override; the engine re-reads the flag from the session file itself, but
          the background probe fills that cache from the same value, so the two agree for every
          session this screen can see. Every session identity-free -> disable the row; some ->
          leave it selectable but say, by name, which sessions it will be skipped for (metric
          selection is one global list, so refusing the tick would make the metric unavailable
          for the sessions that *can* support it); none -> nothing to say.
        * **camera view** -- a metric that is only meaningful for some views
          (metrics/availability.py) is disabled until the project declares one of them.

        Tooltips are rebuilt from their parts every time, so a note a row owns (a superseded
        metric's explanation) is kept, and a note that no longer applies disappears.
        """
        if self._store is None or self._store.manifest is None:
            return
        sessions = self._store.manifest.sessions
        free_ids = [s.session_id for s in sessions if s.is_identity_free()]
        all_identity_free = bool(sessions) and len(free_ids) == len(sessions)
        some_identity_free = bool(free_ids) and not all_identity_free
        camera_view = self._store.manifest.scene.camera_view

        if all_identity_free:
            identity_note = (
                "Every session in this project is identity-free, so this "
                "metric will be skipped for all of them."
            )
        else:
            identity_note = (
                f"Will be skipped for {len(free_ids)} of {len(sessions)} "
                f"identity-free session{'s' if len(free_ids) != 1 else ''}: "
                f"{_summarise_ids(free_ids)}."
            )

        for table in (self._ind_table, self._grp_table, self._zone_table):
            for row in range(table.rowCount()):
                include_item = table.item(row, _COL_INCLUDE)
                name_item = table.item(row, _COL_NAME)
                if include_item is None or name_item is None:
                    continue
                requires_identity = bool(include_item.data(_ROLE_REQUIRES_IDENTITY))
                view_reason = view_unavailable_reason(
                    metrics.get(include_item.data(_ROLE_METRIC_ID)), camera_view
                )

                notes: list[str] = []
                if requires_identity and (all_identity_free or some_identity_free):
                    notes.append(identity_note)
                if view_reason is not None:
                    notes.append(view_reason[0].upper() + view_reason[1:] + ".")
                blocked = (requires_identity and all_identity_free) or view_reason is not None

                flags = include_item.flags()
                if blocked:
                    include_item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                else:
                    include_item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                include_item.setToolTip("\n".join(notes))
                base = name_item.data(_ROLE_BASE_TOOLTIP)
                name_item.setToolTip("\n\n".join(part for part in (base, *notes) if part))

    def _update_zone_tab_enabled(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        zone_index = self._tabs.indexOf(self._zone_table)
        self._tabs.setTabEnabled(zone_index, bool(self._store.manifest.zones.rois))

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
