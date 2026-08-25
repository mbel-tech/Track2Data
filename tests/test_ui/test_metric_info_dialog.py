"""
Tests for ui/dialogs/metric_info_dialog.py -- a read-only dialog that
renders a Metric subclass's `MetricDocumentation`. The dialog takes a
`Metric` class directly (the caller already has it from the registry),
not a metric_id string to look up.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTextEdit, QWidget

from track2data import metrics


def _dialog_text(widget) -> str:
    """Collect every bit of visible/plain text under *widget*.

    Assertions below check for real ``MetricDocumentation`` content, so
    tests shouldn't care whether that content lives in a QLabel or a
    QTextEdit -- only that it's genuinely on screen somewhere.
    """
    chunks = [widget.windowTitle()]
    for lbl in widget.findChildren(QLabel):
        chunks.append(lbl.text())
    for edit in widget.findChildren(QTextEdit):
        chunks.append(edit.toPlainText())
    for edit in widget.findChildren(QPlainTextEdit):
        chunks.append(edit.toPlainText())
    return "\n".join(chunks)


# ── MetricInfoDialog: real, fully-documented metric ─────────────────────────


def test_dialog_shows_the_label_and_never_the_id_or_snake_case_name(qtbot) -> None:
    """Neither the registry id ("IL-1") nor the snake_case internal
    name ("path_length") belongs in the dialog -- metrics_screen.py's
    Name column made that call for the table; the dialog used to leak
    both anyway, in the window title and the header."""
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    metric_cls = metrics.get("IL-1")
    dlg = MetricInfoDialog(metric_cls)
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Distance Travelled" in text
    assert metric_cls.id not in text
    assert metric_cls.name not in text


def test_dialog_shows_real_definition_and_formula_text(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Total distance travelled by each individual over the session." in text
    assert "sum of ||xy[t+1,k] - xy[t,k]|| for non-NaN consecutive frame pairs" in text


def test_dialog_shows_inputs_assumptions_and_warnings(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "PreprocessedSession.xy" in text
    assert "Post-smoothing xy is used; gaps produce no displacement" in text
    assert "Under-smoothed data inflates path length" in text


def test_dialog_shows_supporting_references_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # IL-4 (Activity) carries three supporting references.
    dlg = MetricInfoDialog(metrics.get("IL-4"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Supporting references" in text
    assert "Stewart et al. 2012" in text
    assert "Kalueff et al. 2013" in text


def test_dialog_omits_supporting_references_section_when_empty(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # IL-6 (Acceleration) has no supporting_references.
    dlg = MetricInfoDialog(metrics.get("IL-6"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Supporting references" not in text


def test_dialog_shows_superseded_by_notice(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("Z-2"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Superseded by Z-8" in text


def test_dialog_omits_superseded_by_notice_for_ordinary_metrics(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Superseded by" not in text


def test_dialog_shows_citation_and_doi_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # GL-3 (Polarisation) has both citation and citation_doi set.
    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Vicsek et al. 1995, Phys. Rev. Lett." in text
    assert "10.1103/PhysRevLett.75.1226" in text


def test_dialog_shows_formula_latex_source_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # D-1 (TrackingCoverage) is the one built-in metric with formula_latex
    # set. Per the issue, a plain-text dump of the LaTeX source is an
    # acceptable "not feasible to render" fallback -- no LaTeX renderer.
    dlg = MetricInfoDialog(metrics.get("D-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert r"\text{coverage}_k" in text
    # D-1 has no DOI (its reference is an honest "no single originating
    # work") -- make sure that doesn't leak a literal "None".
    assert "None" not in text


# ── Copy citation ────────────────────────────────────────────────────────────


def test_copy_citation_button_disabled_when_no_citation(qtbot) -> None:
    """Every built-in metric now declares a citation
    (tests/test_metric_references_consistency.py enforces that), so this
    uses a stub rather than a registered metric -- the guard still
    matters for third-party plugin metrics, which have no such
    requirement."""
    from track2data.metrics.base import MetricDocumentation
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    class _UncitedMetric:
        id = "X-1"
        name = "uncited"
        label = "Uncited Metric"
        level = "individual"
        priority = "diagnostic"
        requires_identity = False
        output_columns: list[str] = []
        documentation = MetricDocumentation(
            definition="d", formula_plain="f", inputs=[], assumptions=[], warnings=[],
        )

    dlg = MetricInfoDialog(_UncitedMetric)
    qtbot.addWidget(dlg)

    assert dlg._copy_citation_btn.isEnabled() is False


def test_copy_citation_button_writes_citation_and_doi_to_clipboard(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)

    dlg._copy_citation_btn.click()

    clipboard_text = QGuiApplication.clipboard().text()
    assert "Vicsek et al. 1995, Phys. Rev. Lett." in clipboard_text
    assert "10.1103/PhysRevLett.75.1226" in clipboard_text


# ── Close behaviour ───────────────────────────────────────────────────────────


def test_escape_key_closes_the_dialog(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.keyClick(dlg, Qt.Key.Key_Escape)

    assert dlg.isVisible() is False


def test_click_outside_dialog_closes_it(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    other = QWidget()
    qtbot.addWidget(other)
    other.move(2000, 2000)
    other.resize(50, 50)
    other.show()

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.move(0, 0)
    dlg.show()

    qtbot.mouseClick(other, Qt.MouseButton.LeftButton)

    assert dlg.isVisible() is False


def test_click_inside_dialog_does_not_close_it(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.mouseClick(dlg, Qt.MouseButton.LeftButton)

    assert dlg.isVisible() is True
