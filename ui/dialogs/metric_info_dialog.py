"""
Metric info dialog (issue #26).

A small read-only ``QDialog`` that looks up a metric by id in the
``track2data.metrics`` registry and renders its ``documentation:
MetricDocumentation`` -- definition, formula, inputs, assumptions,
warnings, and citation. See ``docs/METRICS_SPEC.md`` §5.2/§6 for the
canonical field list; this is a deliberately minimal renderer (no
LaTeX rendering, no copy-citation button, no per-row popup) -- a
plain-text dump of ``formula_latex`` is used as the "not feasible to
render" fallback the spec itself allows.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.metrics.base import Metric


class MetricInfoDialog(QDialog):
    """Read-only popup showing the documentation for one metric.

    Looks up *metric_id* in the metric registry at construction time.
    If it isn't registered (e.g. a stale id from a caller's own list),
    a graceful "no documentation available" message is shown instead
    of raising.
    """

    def __init__(self, metric_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._metric_id = metric_id
        self.setWindowTitle(f"Metric info — {metric_id}")
        self.resize(480, 420)

        layout = QVBoxLayout(self)

        metric_cls = metrics.get(metric_id)
        if metric_cls is None:
            missing = QLabel(f"No documentation available for {metric_id}")
            missing.setWordWrap(True)
            layout.addWidget(missing)
        else:
            header = QLabel(f"{metric_cls.id} — {metric_cls.name} ({metric_cls.label})")
            header.setStyleSheet("font-weight: bold; font-size: 14px;")
            header.setWordWrap(True)
            layout.addWidget(header)

            body = QTextEdit()
            body.setReadOnly(True)
            body.setPlainText(self._format_documentation(metric_cls))
            layout.addWidget(body)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    @staticmethod
    def _format_documentation(metric_cls: type[Metric]) -> str:
        """Render a MetricDocumentation as readable multi-line plain text."""
        doc = metric_cls.documentation
        lines: list[str] = ["Definition:", doc.definition, "", "Formula:", doc.formula_plain]

        if doc.formula_latex:
            # Not feasible to render LaTeX here -- show the raw source
            # string, per the issue's own documented fallback.
            lines += ["", "Formula (LaTeX source):", doc.formula_latex]

        lines += ["", "Inputs:"]
        lines += [f"- {item}" for item in doc.inputs]

        lines += ["", "Assumptions:"]
        lines += [f"- {item}" for item in doc.assumptions]

        lines += ["", "Warnings:"]
        lines += [f"- {item}" for item in doc.warnings]

        if doc.citation:
            citation_line = doc.citation
            if doc.citation_doi:
                citation_line += f" (DOI: {doc.citation_doi})"
            lines += ["", "Citation:", citation_line]

        return "\n".join(lines)
