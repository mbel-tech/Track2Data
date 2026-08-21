"""
Stage 7a — Preview & diagnostics screen (M3 real widgets, issue #25).

QTabWidget: Summary / Diagnostics / Metrics
Summary tab updated from store.projectChanged/sessionsChanged/metricsChanged.
Diagnostics/Metrics tabs updated from store.runResultsChanged, reading
store.run_results (a track2data.core.models.RunResult | None) -- both
fall back to their original placeholder text while it is None.

Diagnostics tab, per selected session (store.run_results.sessions):
  - a per-individual table stacking D-1 (TrackingCoverage) and D-3
    (IdProbabilityStats): both carry an individual_id column in
    track2data/metrics/diagnostic.py's output_columns, so both are
    per-individual despite D-3 sometimes being easy to mis-file as
    session-level.
  - a session-level table stacking D-2 (TrackingAccuracy), D-4
    (InconsistentFrameCount), D-5 (IdentityStability) -- each
    contributes exactly one row per session.
  Both tables are built by concatenating the metric DataFrames with a
  leading "metric_id" column (pd.concat(..., sort=False), which is an
  outer join on the union of columns).

  - a preprocessing-steps table listing SessionRunResult.preprocess_report
    .steps (step_name/affected_frames/affected_per_individual/notes), one
    row per PPStepResult. preprocess_report is None for a session whose
    preprocessing failed (see Engine._run_one_session in
    track2data/api.py), in which case this table just renders empty.

Metrics tab: a session selector + a metric-ID selector (populated from
the selected session's SessionRunResult.metric_previews keys) showing
that metric's preview table.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.dataframe_table import clear_table, populate_table

#: Diagnostic metric IDs shown in the Diagnostics tab's per-individual table.
_PER_INDIVIDUAL_DIAGNOSTIC_IDS = ["D-1", "D-3"]
#: Diagnostic metric IDs shown in the Diagnostics tab's session-level table.
_SESSION_LEVEL_DIAGNOSTIC_IDS = ["D-2", "D-4", "D-5"]


class PreviewScreen(QWidget):
    """Stage 7a — Preview trajectories, QC diagnostics, and metric outputs."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._update_summary)
            store.sessionsChanged.connect(self._update_summary)
            store.metricsChanged.connect(self._update_summary)
            store.runResultsChanged.connect(self._update_diagnostics)
            store.runResultsChanged.connect(self._update_metrics)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Preview & Diagnostics")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Inspect project summary, quality-control diagnostics, and metric previews."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── tabs ──────────────────────────────────────────────────────────
        tabs = QTabWidget()

        tabs.addTab(self._build_summary_tab(), "Summary")
        tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        tabs.addTab(self._build_metrics_tab(), "Metrics")

        root.addWidget(tabs, 1)

    def _build_summary_tab(self) -> QWidget:
        summary_w = QWidget()
        summary_layout = QVBoxLayout(summary_w)
        self._summary_label = QLabel("(no project open)")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("font-size: 13px; color: #2c3e50;")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()
        return summary_w

    def _build_diagnostics_tab(self) -> QWidget:
        diag_w = QWidget()
        diag_layout = QVBoxLayout(diag_w)

        self._diag_placeholder = QLabel("Run the pipeline to see diagnostics.")
        self._diag_placeholder.setStyleSheet("color: #aaa; font-style: italic;")
        diag_layout.addWidget(self._diag_placeholder)

        selector_form = QFormLayout()
        self._diag_session_combo = QComboBox()
        self._diag_session_combo.currentIndexChanged.connect(
            self._render_diagnostics_for_current_selection
        )
        selector_form.addRow("Session:", self._diag_session_combo)
        diag_layout.addLayout(selector_form)

        individual_label = QLabel("Per-individual (D-1 coverage, D-3 ID-probability stats)")
        individual_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        diag_layout.addWidget(individual_label)
        self._diag_individual_table = QTableWidget()
        diag_layout.addWidget(self._diag_individual_table)

        session_label = QLabel(
            "Session-level (D-2 accuracy, D-4 inconsistent frames, D-5 identity stability)"
        )
        session_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        diag_layout.addWidget(session_label)
        self._diag_session_table = QTableWidget()
        diag_layout.addWidget(self._diag_session_table)

        preprocess_label = QLabel("Preprocessing steps")
        preprocess_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        diag_layout.addWidget(preprocess_label)
        self._diag_preprocess_table = QTableWidget()
        diag_layout.addWidget(self._diag_preprocess_table)

        diag_layout.addStretch()
        return diag_w

    def _build_metrics_tab(self) -> QWidget:
        metric_w = QWidget()
        metric_layout = QVBoxLayout(metric_w)

        self._metrics_placeholder = QLabel("Run the pipeline to see metric previews.")
        self._metrics_placeholder.setStyleSheet("color: #aaa; font-style: italic;")
        metric_layout.addWidget(self._metrics_placeholder)

        selector_form = QFormLayout()
        self._metrics_session_combo = QComboBox()
        self._metrics_session_combo.currentIndexChanged.connect(self._refresh_metrics_combo)
        selector_form.addRow("Session:", self._metrics_session_combo)
        self._metrics_metric_combo = QComboBox()
        self._metrics_metric_combo.currentIndexChanged.connect(
            self._render_metrics_table_for_current_selection
        )
        selector_form.addRow("Metric:", self._metrics_metric_combo)
        metric_layout.addLayout(selector_form)

        self._metrics_table = QTableWidget()
        metric_layout.addWidget(self._metrics_table)

        metric_layout.addStretch()
        return metric_w

    # ── slots: Summary ────────────────────────────────────────────────────

    def _update_summary(self) -> None:
        if self._store is None or self._store.manifest is None:
            self._summary_label.setText("(no project open)")
            return
        m = self._store.manifest
        n_ind = len(m.metrics.individual)
        n_grp = len(m.metrics.group)
        n_zone = len(m.metrics.zone)
        text = (
            f"<b>Name:</b> {m.project_name}<br/>"
            f"<b>Sessions:</b> {len(m.sessions)}<br/>"
            f"<b>Calibration:</b> {m.calibration.mode}<br/>"
            f"<b>Metrics:</b> {n_ind} individual, {n_grp} group, {n_zone} zone"
        )
        self._summary_label.setText(text)

    # ── slots: Diagnostics ───────────────────────────────────────────────

    def _update_diagnostics(self) -> None:
        run_results = self._store.run_results if self._store is not None else None
        if run_results is None or not run_results.sessions:
            self._diag_placeholder.show()
            self._diag_session_combo.hide()
            self._diag_individual_table.hide()
            self._diag_session_table.hide()
            self._diag_preprocess_table.hide()
            self._diag_session_combo.clear()
            clear_table(self._diag_individual_table)
            clear_table(self._diag_session_table)
            clear_table(self._diag_preprocess_table)
            return

        self._diag_placeholder.hide()
        self._diag_session_combo.show()
        self._diag_individual_table.show()
        self._diag_session_table.show()
        self._diag_preprocess_table.show()
        _repopulate_session_combo(self._diag_session_combo, run_results)
        self._render_diagnostics_for_current_selection()

    def _render_diagnostics_for_current_selection(self) -> None:
        run_results = self._store.run_results if self._store is not None else None
        if run_results is None:
            return
        session_result = _session_by_id(run_results, self._diag_session_combo.currentText())
        if session_result is None:
            clear_table(self._diag_individual_table)
            clear_table(self._diag_session_table)
            clear_table(self._diag_preprocess_table)
            return

        individual_df = _stack_diagnostics(
            session_result.diagnostics, _PER_INDIVIDUAL_DIAGNOSTIC_IDS
        )
        populate_table(self._diag_individual_table, individual_df)

        session_df = _stack_diagnostics(
            session_result.diagnostics, _SESSION_LEVEL_DIAGNOSTIC_IDS
        )
        populate_table(self._diag_session_table, session_df)

        preprocess_df = _preprocess_steps_to_dataframe(session_result.preprocess_report)
        populate_table(self._diag_preprocess_table, preprocess_df)

    # ── slots: Metrics ───────────────────────────────────────────────────

    def _update_metrics(self) -> None:
        run_results = self._store.run_results if self._store is not None else None
        if run_results is None or not run_results.sessions:
            self._metrics_placeholder.show()
            self._metrics_session_combo.hide()
            self._metrics_metric_combo.hide()
            self._metrics_table.hide()
            self._metrics_session_combo.clear()
            self._metrics_metric_combo.clear()
            clear_table(self._metrics_table)
            return

        self._metrics_placeholder.hide()
        self._metrics_session_combo.show()
        self._metrics_metric_combo.show()
        self._metrics_table.show()
        _repopulate_session_combo(self._metrics_session_combo, run_results)
        self._refresh_metrics_combo()

    def _refresh_metrics_combo(self) -> None:
        run_results = self._store.run_results if self._store is not None else None
        if run_results is None:
            return
        session_result = _session_by_id(run_results, self._metrics_session_combo.currentText())
        metric_ids = list(session_result.metric_previews.keys()) if session_result else []

        combo = self._metrics_metric_combo
        combo.blockSignals(True)
        current = combo.currentText()
        combo.clear()
        combo.addItems(metric_ids)
        if current in metric_ids:
            combo.setCurrentText(current)
        combo.blockSignals(False)

        self._render_metrics_table_for_current_selection()

    def _render_metrics_table_for_current_selection(self) -> None:
        run_results = self._store.run_results if self._store is not None else None
        if run_results is None:
            return
        session_result = _session_by_id(run_results, self._metrics_session_combo.currentText())
        metric_id = self._metrics_metric_combo.currentText()
        df = session_result.metric_previews.get(metric_id) if session_result else None
        if df is None:
            clear_table(self._metrics_table)
            return
        populate_table(self._metrics_table, df)


# ── module-level helpers (no Qt state; easy to reason about/test) ──────────────


def _session_by_id(run_results, session_id: str):
    """Return the SessionRunResult matching *session_id*, or None."""
    for session_result in run_results.sessions:
        if session_result.session_id == session_id:
            return session_result
    return None


def _repopulate_session_combo(combo: QComboBox, run_results) -> None:
    """Replace *combo*'s items with run_results' session IDs, preserving
    the current selection when it still exists."""
    combo.blockSignals(True)
    current = combo.currentText()
    combo.clear()
    session_ids = [s.session_id for s in run_results.sessions]
    combo.addItems(session_ids)
    if current in session_ids:
        combo.setCurrentText(current)
    combo.blockSignals(False)


def _stack_diagnostics(diagnostics: dict, metric_ids: list[str]) -> pd.DataFrame:
    """Concatenate the named diagnostic DataFrames (outer join on the
    union of their columns) with a leading metric_id column identifying
    which metric each row came from."""
    frames = []
    for metric_id in metric_ids:
        df = diagnostics.get(metric_id)
        if df is None:
            continue
        labeled = df.copy()
        labeled.insert(0, "metric_id", metric_id)
        frames.append(labeled)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _preprocess_steps_to_dataframe(report) -> pd.DataFrame:
    """Build a step_name/affected_frames/affected_per_individual/notes
    DataFrame from a PreprocessReport's steps, or an empty DataFrame when
    *report* is None (a session whose preprocessing failed)."""
    if report is None or not report.steps:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "step_name": s.step_name,
                "affected_frames": s.affected_frames,
                "affected_per_individual": s.affected_per_individual,
                "notes": s.notes,
            }
            for s in report.steps
        ]
    )
