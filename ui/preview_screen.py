"""
Stage 7a — Preview & diagnostics screen (M3 real widgets).

QTabWidget: Summary / Diagnostics / Metrics
Summary tab updated from store.projectChanged.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


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

        # Summary tab
        summary_w = QWidget()
        summary_layout = QVBoxLayout(summary_w)
        self._summary_label = QLabel("(no project open)")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("font-size: 13px; color: #2c3e50;")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()
        tabs.addTab(summary_w, "Summary")

        # Diagnostics tab
        diag_w = QWidget()
        diag_layout = QVBoxLayout(diag_w)
        diag_label = QLabel("Run the pipeline to see diagnostics.")
        diag_label.setStyleSheet("color: #aaa; font-style: italic;")
        diag_layout.addWidget(diag_label)
        diag_layout.addStretch()
        tabs.addTab(diag_w, "Diagnostics")

        # Metrics tab
        metric_w = QWidget()
        metric_layout = QVBoxLayout(metric_w)
        metric_label = QLabel("Run the pipeline to see metric previews.")
        metric_label.setStyleSheet("color: #aaa; font-style: italic;")
        metric_layout.addWidget(metric_label)
        metric_layout.addStretch()
        tabs.addTab(metric_w, "Metrics")

        root.addWidget(tabs, 1)

    # ── slots ──────────────────────────────────────────────────────────────

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
