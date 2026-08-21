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


def test_dialog_shows_id_name_and_label_for_a_known_metric(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "IL-1" in text
    assert "path_length" in text
    assert "Distance Travelled" in text


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


def test_dialog_shows_citation_and_doi_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # GL-3 (Polarisation) has both citation and citation_doi set.
    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Couzin et al. 2002, J. Theor. Biol." in text
    assert "10.1006/jtbi.2002.3065" in text


def test_dialog_shows_formula_latex_source_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # D-1 (TrackingCoverage) is the one built-in metric with formula_latex
    # set. Per the issue, a plain-text dump of the LaTeX source is an
    # acceptable "not feasible to render" fallback -- no LaTeX renderer.
    dlg = MetricInfoDialog(metrics.get("D-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert r"\text{coverage}_k" in text
    # D-1 has no citation -- make sure that doesn't leak a literal "None".
    assert "None" not in text


# ── Copy citation ────────────────────────────────────────────────────────────


def test_copy_citation_button_disabled_when_no_citation(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("D-1"))  # no citation
    qtbot.addWidget(dlg)

    assert dlg._copy_citation_btn.isEnabled() is False


def test_copy_citation_button_writes_citation_and_doi_to_clipboard(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)

    dlg._copy_citation_btn.click()

    clipboard_text = QGuiApplication.clipboard().text()
    assert "Couzin et al. 2002, J. Theor. Biol." in clipboard_text
    assert "10.1006/jtbi.2002.3065" in clipboard_text


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
