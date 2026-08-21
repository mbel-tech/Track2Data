"""
Tests for ui/dialogs/metric_info_dialog.py (issue #26) -- a read-only
dialog that renders a metric's `MetricDocumentation` -- plus the
`ui/metrics_screen.py` "info" affordance that opens it for whichever
metric is currently selected.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTextEdit


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


def _stub_dialog_cls(sink: list[str]) -> type:
    """A drop-in replacement for MetricInfoDialog that records the
    metric_id it was built with instead of showing a real modal."""

    class _StubDialog:
        def __init__(self, metric_id: str, parent=None) -> None:
            sink.append(metric_id)

        def exec(self) -> None:
            return None

    return _StubDialog


# ── MetricInfoDialog: real, fully-documented metric ─────────────────────────


def test_dialog_shows_id_name_and_label_for_a_known_metric(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog("IL-1")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "IL-1" in text
    assert "path_length" in text
    assert "Distance Travelled" in text


def test_dialog_shows_real_definition_and_formula_text(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog("IL-1")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    # Real content from PathLength.documentation (track2data/metrics/individual.py)
    assert "Total distance travelled by each individual over the session." in text
    assert "sum of ||xy[t+1,k] - xy[t,k]|| for non-NaN consecutive frame pairs" in text


def test_dialog_shows_inputs_assumptions_and_warnings(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog("IL-1")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "PreprocessedSession.xy" in text
    assert "Post-smoothing xy is used; gaps produce no displacement" in text
    assert "Under-smoothed data inflates path length" in text


def test_dialog_shows_citation_and_doi_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # GL-3 (Polarisation) has both citation and citation_doi set.
    dlg = MetricInfoDialog("GL-3")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Couzin et al. 2002, J. Theor. Biol." in text
    assert "10.1006/jtbi.2002.3065" in text


def test_dialog_shows_formula_latex_source_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # D-1 (TrackingCoverage) is the one built-in metric with formula_latex
    # set. Per the issue, a plain-text dump of the LaTeX source is an
    # acceptable "not feasible to render" fallback -- no LaTeX renderer.
    dlg = MetricInfoDialog("D-1")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert r"\text{coverage}_k" in text
    # D-1 has no citation -- make sure that doesn't leak a literal "None".
    assert "None" not in text


# ── MetricInfoDialog: unknown metric id ──────────────────────────────────────


def test_dialog_handles_unknown_metric_id_gracefully(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog("IL-999")
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "No documentation available for IL-999" in text
    assert "Definition:" not in text


# ── ui/metrics_screen.py wiring ──────────────────────────────────────────────


def test_info_button_opens_dialog_for_selected_individual_metric(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []
    monkeypatch.setattr("ui.metrics_screen.MetricInfoDialog", _stub_dialog_cls(opened))

    screen = MetricsScreen()
    qtbot.addWidget(screen)
    screen._ind_list.setCurrentRow(0)  # _INDIVIDUAL_METRICS[0] == "IL-1"

    screen._info_btn.click()

    assert opened == ["IL-1"]


def test_info_button_uses_whichever_tab_is_currently_active(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []
    monkeypatch.setattr("ui.metrics_screen.MetricInfoDialog", _stub_dialog_cls(opened))

    screen = MetricsScreen()
    qtbot.addWidget(screen)
    screen._tabs.setCurrentIndex(1)  # Group tab
    screen._grp_list.setCurrentRow(1)  # _GROUP_METRICS[1] == "GL-3"

    screen._info_btn.click()

    assert opened == ["GL-3"]


def test_info_button_with_no_selection_shows_message_and_opens_nothing(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []
    monkeypatch.setattr("ui.metrics_screen.MetricInfoDialog", _stub_dialog_cls(opened))
    messages: list[str] = []
    monkeypatch.setattr(
        "ui.metrics_screen.QMessageBox.information",
        staticmethod(lambda *a, **k: messages.append(a[2]) or None),
    )

    screen = MetricsScreen()
    qtbot.addWidget(screen)
    # Fresh QListWidget: nothing selected/current yet.

    screen._info_btn.click()

    assert opened == []
    assert len(messages) == 1
