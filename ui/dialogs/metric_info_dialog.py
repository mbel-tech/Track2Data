"""
Metric info dialog -- a read-only ``QDialog`` that renders a
``Metric`` subclass's ``documentation: MetricDocumentation`` --
definition, formula, inputs, assumptions, warnings, and citation. See
``docs/METRICS_SPEC.md`` §5.2/§6 for the canonical field list.
``formula_latex`` is shown as a raw LaTeX source string (no renderer)
-- the "not feasible to render" fallback the spec itself allows.

Closes on the title-bar close button, Escape (QDialog's own default
behaviour), or a click outside the dialog's own rect (a
QApplication-wide event filter installed for the dialog's lifetime).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from track2data.metrics.base import Metric


class MetricInfoDialog(QDialog):
    """Read-only popup showing the documentation for one metric."""

    def __init__(self, metric_cls: type[Metric], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._metric_cls = metric_cls
        # Neither the registry id ("IL-1") nor the snake_case internal
        # name ("path_length") belongs here -- metrics_screen.py's Name
        # column already made that call for the table; the dialog used
        # to show both anyway, in the window title and the header.
        self.setWindowTitle(f"Metric info — {metric_cls.label}")
        self.resize(480, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        header = QLabel(metric_cls.label)
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        superseded_by = getattr(metric_cls, "superseded_by", None)
        if superseded_by:
            notice = QLabel(
                f"Superseded by {superseded_by} -- kept for output "
                "compatibility with existing projects; computes exactly "
                "what it always has."
            )
            notice.setStyleSheet("color: #b06a00; font-size: 12px;")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(self._format_documentation(metric_cls))
        layout.addWidget(body)

        footer = QHBoxLayout()
        doc = metric_cls.documentation
        self._copy_citation_btn = QPushButton("Copy citation")
        self._copy_citation_btn.setEnabled(doc.citation is not None)
        self._copy_citation_btn.clicked.connect(self._copy_citation)
        footer.addWidget(self._copy_citation_btn)
        footer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _copy_citation(self) -> None:
        doc = self._metric_cls.documentation
        if doc.citation is None:
            return
        text = doc.citation
        if doc.citation_doi:
            text += f" (DOI: {doc.citation_doi})"
        QApplication.clipboard().setText(text)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local_pos):
                self.reject()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _format_documentation(metric_cls: type[Metric]) -> str:
        """Render a MetricDocumentation as readable multi-line plain text."""
        doc = metric_cls.documentation
        lines: list[str] = ["Definition:", doc.definition]

        if doc.formula_plain:
            lines += ["", "Formula:", doc.formula_plain]

        if doc.formula_latex:
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

        if doc.supporting_references:
            from track2data.metrics.references import format_reference

            lines += ["", "Supporting references:"]
            lines += [f"- {format_reference(ref)}" for ref in doc.supporting_references]

        return "\n".join(lines)
