"""
Stage 6c — Pipeline run screen (M3 real widgets).

Widgets:
  • validate_btn   QPushButton — shows QMessageBox with validation summary
  • run_btn        QPushButton — disabled stub
  • progress_bar   QProgressBar
  • status_label   QLabel  ("Ready" / …)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProcessingScreen(QWidget):
    """Stage 6c — Validate and run the preprocessing + metrics pipeline."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.projectChanged.connect(self._on_project_changed)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Processing")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel(
            "Validate the pipeline configuration and run preprocessing + "
            "metric extraction across all sessions."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        # ── buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._validate_btn = QPushButton("Validate pipeline")
        self._validate_btn.clicked.connect(self._validate)
        self._run_btn = QPushButton("Run pipeline")
        self._run_btn.setEnabled(False)
        self._run_btn.setToolTip("Pipeline execution will be implemented in Wave 3")
        self._run_btn.clicked.connect(self._run_stub)
        btn_row.addWidget(self._validate_btn)
        btn_row.addWidget(self._run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── progress + status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("font-size: 13px; color: #555;")
        root.addWidget(self._status_label)

        root.addStretch()

    # ── slots ──────────────────────────────────────────────────────────────

    def _validate(self) -> None:
        if self._store is None or self._store.manifest is None:
            QMessageBox.warning(self, "Validation", "No project is open.")
            return
        m = self._store.manifest
        lines: list[str] = []
        ok = True
        n_sessions = len(m.sessions)
        if n_sessions == 0:
            lines.append("✗  No sessions imported")
            ok = False
        else:
            lines.append(f"✓  {n_sessions} session(s) imported")
        if m.calibration.mode == "scalar" and (
            m.calibration.px_per_cm is None or m.calibration.px_per_cm <= 0
        ):
            lines.append("✗  Scalar calibration: px_per_cm not set")
            ok = False
        else:
            lines.append(f"✓  Calibration: {m.calibration.mode}")
        if m.metrics.individual or m.metrics.group or m.metrics.zone:
            total = len(m.metrics.individual) + len(m.metrics.group) + len(m.metrics.zone)
            lines.append(f"✓  {total} metric(s) selected")
        else:
            lines.append("⚠  No metrics selected")
        summary = "\n".join(lines)
        icon = QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning
        box = QMessageBox(icon, "Pipeline validation", summary, QMessageBox.StandardButton.Ok, self)
        box.exec()

    def _run_stub(self) -> None:
        QMessageBox.information(
            self,
            "Pipeline",
            "Pipeline execution will be implemented in Wave 3.",
        )

    def _on_project_changed(self) -> None:
        has = self._store is not None and self._store.has_project
        self._validate_btn.setEnabled(has)
