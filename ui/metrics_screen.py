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
    QDialog,
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
from ui.dialogs.metric_config_dialog import MetricConfigDialog
from ui.dialogs.metric_info_dialog import MetricInfoDialog

_COLUMN_HEADERS = ["Include", "Name", "Info", "Config"]
_COL_INCLUDE, _COL_NAME, _COL_INFO, _COL_CONFIG = range(4)
_ROLE_METRIC_ID = Qt.ItemDataRole.UserRole
_ROLE_REQUIRES_IDENTITY = Qt.ItemDataRole.UserRole + 1


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
        self._build_ui()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)
            store.sessionsChanged.connect(self._update_identity_graying)
            store.zonesChanged.connect(self._update_zone_tab_enabled)
            self._update_identity_graying()
            self._update_zone_tab_enabled()

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
                name_item.setToolTip(
                    f"{metric_cls.label} is kept for output compatibility with "
                    f"existing projects. {superseded_by} computes the same idea "
                    "with a better statistic -- see its ⓘ for details."
                )
            table.setItem(row, _COL_NAME, name_item)

            doc = metric_cls.documentation
            if doc.formula_plain is not None or doc.citation is not None:
                info_btn = QPushButton("ⓘ")
                info_btn.setFixedWidth(28)
                info_btn.clicked.connect(partial(self._show_metric_info, metric_cls))
                table.setCellWidget(row, _COL_INFO, info_btn)

            config_btn = QPushButton("⚙")
            config_btn.setFixedWidth(28)
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
            }
        )

    def _apply(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        sel = self._selection_from_widgets(self._store.manifest.metrics)
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
        self._update_identity_graying()
        self._update_zone_tab_enabled()

    def _update_identity_graying(self) -> None:
        """Reflect each session's identity-free status onto the rows.

        Keyed on SessionRef.is_identity_free() rather than
        has_stable_identities, which also folds in coverage heuristics and
        so used to grey rows the engine would happily have computed (and
        vice versa). That predicate reads the manifest's cached
        track_wo_identities plus the user's override; the engine re-reads
        the flag from the session file itself, but the background probe
        fills that cache from the same value, so the two agree for every
        session this screen can see. Three cases:

        * every session identity-free -> disable the row; nothing it could
          produce would be meaningful.
        * some sessions identity-free -> leave it selectable but say, by
          name, which sessions it will be skipped for. Metric selection is
          one global list, so refusing the tick outright would make those
          metrics unavailable for the sessions that *can* support them.
        * none -> clear.
        """
        if self._store is None or self._store.manifest is None:
            return
        sessions = self._store.manifest.sessions
        free_ids = [s.session_id for s in sessions if s.is_identity_free()]
        all_identity_free = bool(sessions) and len(free_ids) == len(sessions)
        some_identity_free = bool(free_ids) and not all_identity_free

        if all_identity_free:
            blocked_tooltip = (
                "Every session in this project is identity-free, so this "
                "metric will be skipped for all of them."
            )
        else:
            blocked_tooltip = (
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
                flags = include_item.flags()
                if requires_identity and all_identity_free:
                    include_item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                    include_item.setToolTip(blocked_tooltip)
                    name_item.setToolTip(blocked_tooltip)
                elif requires_identity and some_identity_free:
                    include_item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                    include_item.setToolTip(blocked_tooltip)
                    name_item.setToolTip(blocked_tooltip)
                else:
                    include_item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                    include_item.setToolTip("")
                    name_item.setToolTip("")

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
