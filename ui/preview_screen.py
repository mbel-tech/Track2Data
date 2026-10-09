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
  - a preprocessing-steps table listing the steps of
    SessionRunResult.preprocess_report (step_name/affected_frames/
    affected_per_individual/notes), one row per PPStepResult. The
    report is None when the session never got past preprocessing (see
    Engine._run_one_session in track2data/api.py, which preserves it
    for failures in any later stage), in which case this table renders
    empty.
  The two diagnostic tables are built by concatenating the metric
  DataFrames with a leading "metric_id" column (pd.concat(..., sort=False),
  which is an outer join on the union of columns).

Metrics tab: a session selector + a metric-ID selector (populated from
the selected session's SessionRunResult.metric_previews keys) showing
that metric's preview table.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.store.quality_grid import SessionQuality, assess_session, count_verdicts
from ui.widgets.dataframe_table import clear_table, populate_table
from ui.widgets.dots import level_icon
from ui.widgets.trajectory_view import TrajectoryView


@dataclass
class TrajectoryData:
    """What the Trajectories tab needs from one preprocessed session."""

    raw_xy: np.ndarray
    xy: np.ndarray
    fps: float
    background: Path | None
    size: tuple[float, float]


def load_trajectory_data(manifest, session_id: str, cache_dir: Path | None) -> TrajectoryData:
    """Load (or reuse from the project cache) one session's raw and processed
    positions. Runs on a worker thread; raises on failure."""
    from track2data.api import Engine

    ref = next(r for r in manifest.sessions if r.session_id == session_id)
    psess = Engine(manifest, cache_dir=cache_dir).preprocess_ref(ref)
    video = psess.session.video
    return TrajectoryData(
        raw_xy=psess.raw_xy_aligned,
        xy=psess.xy,
        fps=video.fps,
        background=psess.session.background_image_path,
        size=(float(video.width_px), float(video.height_px)),
    )

#: Diagnostic metric IDs shown in the Diagnostics tab's per-individual table.
_PER_INDIVIDUAL_DIAGNOSTIC_IDS = ["D-1", "D-3"]
#: Diagnostic metric IDs shown in the Diagnostics tab's session-level table.
_SESSION_LEVEL_DIAGNOSTIC_IDS = ["D-2", "D-4", "D-5"]
_QUALITY_HEADERS = [
    "Session", "Coverage", "Identity", "Crossings", "Jumps", "Interpolated", "Verdict",
]


class PreviewScreen(QWidget):
    """Stage 7a — Preview trajectories, QC diagnostics, and metric outputs."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._traj_task_id: str | None = None
        self._traj_timer = QTimer(self)
        self._traj_timer.setInterval(40)
        self._traj_timer.timeout.connect(self._traj_advance)
        self._build_ui()
        if store is not None:
            store.taskFinished.connect(self._on_traj_task_finished)
            store.sessionsChanged.connect(self._refresh_traj_sessions)
            store.projectChanged.connect(self._refresh_traj_sessions)
            self._refresh_traj_sessions()
            store.projectChanged.connect(self._update_summary)
            store.sessionsChanged.connect(self._update_summary)
            store.metricsChanged.connect(self._update_summary)
            store.runResultsChanged.connect(self._update_diagnostics)
            store.runResultsChanged.connect(self._update_metrics)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Preview & Diagnostics")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Check tracking quality per session before you export."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageLead")
        root.addWidget(subtitle)

        # ── tabs ──────────────────────────────────────────────────────────
        tabs = QTabWidget()

        tabs.addTab(self._build_summary_tab(), "Summary")
        tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        tabs.addTab(self._build_metrics_tab(), "Metrics")
        tabs.addTab(self._build_trajectories_tab(), "Trajectories")

        root.addWidget(tabs, 1)
        self._tabs = tabs

    def _build_trajectories_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Session:"))
        self._traj_session_combo = QComboBox()
        top.addWidget(self._traj_session_combo, 1)
        self._traj_load_btn = QPushButton("Load trajectories")
        self._traj_load_btn.setProperty("role", "outline-primary")
        self._traj_load_btn.setEnabled(False)
        self._traj_load_btn.clicked.connect(self._load_trajectories)
        top.addWidget(self._traj_load_btn)
        lay.addLayout(top)

        self._traj_status = QLabel(
            "Load a session to inspect its tracked paths, what preprocessing "
            "changed, and where the animals spent their time."
        )
        self._traj_status.setWordWrap(True)
        self._traj_status.setProperty("role", "faint")
        lay.addWidget(self._traj_status)

        self._traj_view = TrajectoryView()
        lay.addWidget(self._traj_view, 1)

        scrub = QHBoxLayout()
        self._traj_play_btn = QPushButton("▶")
        self._traj_play_btn.setFixedWidth(36)
        self._traj_play_btn.setCheckable(True)
        self._traj_play_btn.toggled.connect(self._traj_toggle_play)
        scrub.addWidget(self._traj_play_btn)
        self._traj_slider = QSlider(Qt.Orientation.Horizontal)
        self._traj_slider.setRange(0, 0)
        self._traj_slider.valueChanged.connect(self._traj_view.set_frame)
        scrub.addWidget(self._traj_slider, 1)
        self._traj_frame_label = QLabel("frame 0")
        scrub.addWidget(self._traj_frame_label)
        lay.addLayout(scrub)
        self._traj_view.frameChanged.connect(self._traj_on_frame)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Trail:"))
        self._traj_trail_spin = QSpinBox()
        self._traj_trail_spin.setRange(1, 100000)
        self._traj_trail_spin.setValue(250)
        self._traj_trail_spin.setSuffix(" frames")
        self._traj_trail_spin.valueChanged.connect(self._traj_view.set_trail_length)
        opts.addWidget(self._traj_trail_spin)
        opts.addWidget(QLabel("Show:"))
        self._traj_source_combo = QComboBox()
        self._traj_source_combo.addItem("Processed", userData="processed")
        self._traj_source_combo.addItem("Raw", userData="raw")
        self._traj_source_combo.addItem("Raw + processed", userData="both")
        self._traj_source_combo.currentIndexChanged.connect(self._traj_on_source_changed)
        opts.addWidget(self._traj_source_combo)
        self._traj_zones_check = QCheckBox("Zones")
        self._traj_zones_check.setChecked(True)
        self._traj_zones_check.toggled.connect(self._traj_view.set_show_zones)
        opts.addWidget(self._traj_zones_check)
        self._traj_heatmap_check = QCheckBox("Occupancy heatmap")
        self._traj_heatmap_check.toggled.connect(self._traj_view.set_heatmap)
        opts.addWidget(self._traj_heatmap_check)
        opts.addStretch()
        lay.addLayout(opts)
        return w

    # ── slots: Trajectories ───────────────────────────────────────────────

    def _refresh_traj_sessions(self) -> None:
        current = self._traj_session_combo.currentText()
        self._traj_session_combo.clear()
        if self._store is not None and self._store.manifest is not None:
            ids = [r.session_id for r in self._store.manifest.sessions]
            self._traj_session_combo.addItems(ids)
            if current in ids:
                self._traj_session_combo.setCurrentText(current)
        self._traj_load_btn.setEnabled(self._traj_session_combo.count() > 0)

    def _load_trajectories(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        session_id = self._traj_session_combo.currentText()
        if not session_id:
            return
        self._traj_status.setText(f"Loading {session_id}…")
        self._traj_load_btn.setEnabled(False)
        fn = functools.partial(
            load_trajectory_data, self._store.manifest, session_id, self._store.cache_dir
        )
        self._traj_task_id = self._store.tasks.submit(fn)

    def _on_traj_task_finished(self, task_id: str, result: object) -> None:
        if task_id != self._traj_task_id:
            return
        self._traj_task_id = None
        self._traj_load_btn.setEnabled(self._traj_session_combo.count() > 0)
        if isinstance(result, Exception) or not isinstance(result, TrajectoryData):
            self._traj_status.setText(f"Could not load trajectories: {result}")
            return
        rois = self._store.manifest.zones.rois if self._store.manifest else []
        self._traj_view.set_data(
            result.raw_xy, result.xy, result.fps, rois=rois,
            background_path=result.background, size=result.size,
        )
        self._traj_slider.setRange(0, max(0, self._traj_view.n_frames - 1))
        self._traj_slider.setValue(0)
        self._traj_status.setText(
            f"{self._traj_view.n_frames} frames at {result.fps:g} fps · "
            f"{result.xy.shape[1]} animal(s). Wheel zooms."
        )

    def _traj_on_frame(self, frame: int) -> None:
        fps = getattr(self._traj_view, "_fps", 0) or 0
        t = f" · {frame / fps:.1f} s" if fps else ""
        self._traj_frame_label.setText(f"frame {frame}{t}")
        if self._traj_slider.value() != frame:
            self._traj_slider.setValue(frame)

    def _traj_on_source_changed(self, _index: int) -> None:
        # A bound method, not a lambda over ``self``: PySide holds a lambda's
        # closure strongly, which makes the screen a reference cycle that is
        # only freed at interpreter exit, after the QApplication is gone.
        self._traj_view.set_source(self._traj_source_combo.currentData())

    def _traj_toggle_play(self, playing: bool) -> None:
        self._traj_play_btn.setText("⏸" if playing else "▶")
        if playing and self._traj_view.n_frames > 1:
            self._traj_timer.start()
        else:
            self._traj_timer.stop()

    def _traj_advance(self) -> None:
        n = self._traj_view.n_frames
        step = max(1, n // 250)  # whole session in roughly ten seconds
        nxt = self._traj_view.current_frame + step
        if nxt >= n - 1:
            self._traj_view.set_frame(n - 1)
            self._traj_play_btn.setChecked(False)
        else:
            self._traj_view.set_frame(nxt)

    def _build_summary_tab(self) -> QWidget:
        summary_w = QWidget()
        summary_layout = QVBoxLayout(summary_w)
        self._summary_label = QLabel("(no project open)")
        self._summary_label.setWordWrap(True)
        self._summary_label.setProperty("role", "faint")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()
        return summary_w

    def _build_diagnostics_tab(self) -> QWidget:
        diag_w = QWidget()
        diag_layout = QVBoxLayout(diag_w)
        diag_layout.setContentsMargins(0, 8, 12, 8)
        diag_layout.setSpacing(10)

        self._diag_placeholder = QLabel("Run the pipeline to see diagnostics.")
        self._diag_placeholder.setProperty("role", "faint")
        diag_layout.addWidget(self._diag_placeholder)

        # ── traffic-light quality grid, one row per session ──────────────
        verdict_row = QHBoxLayout()
        verdict_row.setSpacing(8)
        self._verdict_chips: dict[str, QLabel] = {}
        for verdict, kind in (("Good", "ok"), ("Check", "warn"), ("Review", "err")):
            chip = QLabel()
            chip.setProperty("chip", kind)
            self._verdict_chips[verdict] = chip
            verdict_row.addWidget(chip)
        verdict_row.addStretch()
        diag_layout.addLayout(verdict_row)

        self._quality_table = QTableWidget(0, len(_QUALITY_HEADERS))
        self._quality_table.setHorizontalHeaderLabels(_QUALITY_HEADERS)
        self._quality_table.verticalHeader().hide()
        self._quality_table.verticalHeader().setDefaultSectionSize(36)
        self._quality_table.setShowGrid(False)
        self._quality_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._quality_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._quality_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._quality_table.itemSelectionChanged.connect(self._on_quality_row_selected)
        diag_layout.addWidget(self._quality_table)

        self._why_card = QFrame()
        self._why_card.setProperty("card", True)
        why_col = QVBoxLayout(self._why_card)
        why_col.setContentsMargins(16, 12, 16, 12)
        self._why_title = QLabel()
        self._why_title.setObjectName("CardTitle")
        self._why_body = QLabel()
        self._why_body.setWordWrap(True)
        self._why_open = QPushButton("Open trajectories")
        self._why_open.setProperty("role", "outline")
        self._why_open.clicked.connect(self._open_trajectories_for_selected)
        why_col.addWidget(self._why_title)
        why_col.addWidget(self._why_body)
        why_col.addWidget(self._why_open, 0, Qt.AlignmentFlag.AlignLeft)
        self._why_card.hide()
        diag_layout.addWidget(self._why_card)
        self._qualities: list[SessionQuality] = []
        self._tabs: QTabWidget | None = None

        selector_form = QFormLayout()
        self._diag_session_combo = QComboBox()
        self._diag_session_combo.currentIndexChanged.connect(
            self._render_diagnostics_for_current_selection
        )
        selector_form.addRow("Session:", self._diag_session_combo)
        diag_layout.addLayout(selector_form)

        individual_label = QLabel("Per-individual (D-1 coverage, D-3 ID-probability stats)")
        individual_label.setObjectName("SectionLabel")
        diag_layout.addWidget(individual_label)
        self._diag_individual_table = QTableWidget()
        diag_layout.addWidget(self._diag_individual_table)

        session_label = QLabel(
            "Session-level (D-2 accuracy, D-4 inconsistent frames, D-5 identity stability)"
        )
        session_label.setObjectName("SectionLabel")
        diag_layout.addWidget(session_label)
        self._diag_session_table = QTableWidget()
        diag_layout.addWidget(self._diag_session_table)

        preprocess_label = QLabel("Preprocessing steps")
        preprocess_label.setObjectName("SectionLabel")
        diag_layout.addWidget(preprocess_label)
        self._diag_preprocess_table = QTableWidget()
        diag_layout.addWidget(self._diag_preprocess_table)

        for table in (
            self._diag_individual_table, self._diag_session_table, self._diag_preprocess_table,
        ):
            table.setMinimumHeight(150)
        diag_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(diag_w)
        return scroll

    def _build_metrics_tab(self) -> QWidget:
        metric_w = QWidget()
        metric_layout = QVBoxLayout(metric_w)

        self._metrics_placeholder = QLabel("Run the pipeline to see metric previews.")
        self._metrics_placeholder.setProperty("role", "faint")
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
            self._quality_table.setRowCount(0)
            self._why_card.hide()
            for chip in self._verdict_chips.values():
                chip.setText("")
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
        self._render_quality_grid(run_results)
        self._render_diagnostics_for_current_selection()

    # ── quality grid ─────────────────────────────────────────────────────

    def _render_quality_grid(self, run_results) -> None:
        self._qualities = [assess_session(s) for s in run_results.sessions]
        counts = count_verdicts(self._qualities, set())
        for verdict, chip in self._verdict_chips.items():
            chip.setText(f"{counts[verdict]} {verdict.lower()}")
        table = self._quality_table
        table.setRowCount(len(self._qualities))
        for row, q in enumerate(self._qualities):
            first = QTableWidgetItem(q.session_id)
            table.setItem(row, 0, first)
            for col, cell in enumerate(
                (q.coverage, q.identity, q.crossings, q.jumps, q.interpolated), start=1
            ):
                item = QTableWidgetItem(cell.text)
                item.setIcon(level_icon(cell.level))
                table.setItem(row, col, item)
            verdict_item = QTableWidgetItem(q.verdict)
            verdict_item.setIcon(level_icon(q.verdict.lower()))
            table.setItem(row, len(_QUALITY_HEADERS) - 1, verdict_item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.setFixedHeight(40 + 36 * max(1, len(self._qualities)))
        if self._qualities:
            table.selectRow(0)
        self._show_reasons(self._qualities[0] if self._qualities else None)

    def _selected_quality(self) -> SessionQuality | None:
        rows = {i.row() for i in self._quality_table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = next(iter(rows))
        return self._qualities[row] if 0 <= row < len(self._qualities) else None

    def _on_quality_row_selected(self) -> None:
        quality = self._selected_quality()
        self._show_reasons(quality)
        if quality is not None:
            self._diag_session_combo.setCurrentText(quality.session_id)

    def _show_reasons(self, quality: SessionQuality | None) -> None:
        if quality is None:
            self._why_card.hide()
            return
        if quality.verdict == "Good":
            self._why_title.setText(f"{quality.session_id} looks good")
            self._why_body.setText("Every measure is within its limit.")
        else:
            word = "a check" if quality.verdict == "Check" else "review"
            self._why_title.setText(f"Why {quality.session_id} needs {word}")
            self._why_body.setText("\n".join(f"•  {r}" for r in quality.reasons))
        self._why_card.show()

    def _open_trajectories_for_selected(self) -> None:
        quality = self._selected_quality()
        if self._tabs is None or quality is None:
            return
        self._tabs.setCurrentIndex(3)
        self._traj_session_combo.setCurrentText(quality.session_id)

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
