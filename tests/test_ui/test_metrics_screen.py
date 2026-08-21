"""
Tests for ui/metrics_screen.py -- the registry-driven QTableWidget
metrics-selection screen. See
docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from track2data import metrics
from track2data.core.models import MetricSelection, ProjectManifest


def _make_store():
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    store = ProjectStore()
    store._manifest = ProjectManifest(project_name="test_project", created_at=now, updated_at=now)
    return store


def _row_for_id(table, metric_id: str) -> int:
    for row in range(table.rowCount()):
        if table.item(row, 1).text() == metric_id:
            return row
    raise AssertionError(f"{metric_id} not found in table")


# ── registry-driven rows ──────────────────────────────────────────────────────


def test_individual_tab_has_one_row_per_registered_individual_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(m.id for m in metrics.list_for_level("individual"))
    actual_ids = [
        screen._ind_table.item(row, 1).text() for row in range(screen._ind_table.rowCount())
    ]
    assert actual_ids == expected_ids


def test_group_tab_has_one_row_per_registered_group_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(m.id for m in metrics.list_for_level("group"))
    actual_ids = [
        screen._grp_table.item(row, 1).text() for row in range(screen._grp_table.rowCount())
    ]
    assert actual_ids == expected_ids


# ── checkbox selection round-trip ─────────────────────────────────────────────


def test_apply_selection_reads_checked_rows_from_each_tab(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    screen._apply()

    assert store.manifest.metrics.individual == ["IL-1"]


def test_load_from_store_checks_rows_matching_the_manifest_selection(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"metrics": MetricSelection(individual=["IL-1"])}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    store.metricsChanged.emit()

    row = _row_for_id(screen._ind_table, "IL-1")
    assert screen._ind_table.item(row, 0).checkState() == Qt.CheckState.Checked
