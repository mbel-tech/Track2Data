"""
Tests for ui/metrics_screen.py -- the registry-driven QTableWidget
metrics-selection screen. See
docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("individual")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    actual_ids = [
        screen._ind_table.item(row, 1).text() for row in range(screen._ind_table.rowCount())
    ]
    assert actual_ids == expected_ids


def test_group_tab_has_one_row_per_registered_group_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("group")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    actual_ids = [
        screen._grp_table.item(row, 1).text() for row in range(screen._grp_table.rowCount())
    ]
    assert actual_ids == expected_ids


def test_zone_tab_has_one_row_per_registered_zone_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("zone")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    actual_ids = [
        screen._zone_table.item(row, 1).text() for row in range(screen._zone_table.rowCount())
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


# ── per-row ⓘ / ⚙ buttons ─────────────────────────────────────────────────────


def test_every_row_has_a_config_stub_button_that_shows_a_message(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    messages: list[str] = []
    monkeypatch.setattr(
        "ui.metrics_screen.QMessageBox.information",
        staticmethod(lambda *a, **k: messages.append(a[2]) or None),
    )

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.cellWidget(row, 4).click()

    assert messages == ["Per-metric configuration isn't available yet."]


def test_info_button_opens_metric_info_dialog_for_that_row(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []

    class _StubDialog:
        def __init__(self, metric_cls, parent=None) -> None:
            opened.append(metric_cls.id)

        def exec(self) -> None:
            return None

    monkeypatch.setattr("ui.metrics_screen.MetricInfoDialog", _StubDialog)

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.cellWidget(row, 3).click()

    assert opened == ["IL-1"]

    # A different row's button must open ITS OWN metric, not IL-1 again --
    # guards against a lambda-over-loop-variable bug where every row's
    # button would close over the same (last) metric_cls.
    other_row = _row_for_id(screen._ind_table, "IL-3")
    screen._ind_table.cellWidget(other_row, 3).click()

    assert opened == ["IL-1", "IL-3"]


def test_info_button_is_absent_when_metric_has_no_formula_or_citation(qtbot, monkeypatch) -> None:
    from track2data.metrics.base import MetricDocumentation
    from ui.metrics_screen import MetricsScreen

    class _NoDocMetric:
        id = "X-1"
        name = "No-doc metric"
        label = "No-doc metric"
        level = "individual"
        priority = "diagnostic"
        requires_identity = False
        output_columns: list[str] = []
        documentation = MetricDocumentation.model_construct(
            definition="d", formula_plain=None, inputs=[], assumptions=[],
            warnings=[], citation=None, citation_doi=None,
        )

    monkeypatch.setattr("ui.metrics_screen.metrics.list_for_level", lambda level: [_NoDocMetric])

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    assert screen._ind_table.cellWidget(0, 3) is None


# ── identity-aware graying ────────────────────────────────────────────────────


def test_identity_required_rows_greyed_when_every_session_lacks_stable_identities(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")  # IL-1.requires_identity is True
    include_item = screen._ind_table.item(row, 0)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_rows_not_greyed_when_sessions_are_unprobed(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": [SessionRef(session_id="s1", folder=Path("s1"), sha256="x")]}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_rows_not_greyed_when_at_least_one_session_has_stable_identities(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
                SessionRef(
                    session_id="s2", folder=Path("s2"), sha256="y",
                    has_stable_identities=True,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


# ── zone tab disabling ────────────────────────────────────────────────────────


def test_zone_tab_disabled_when_no_zones_defined(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    zone_index = screen._tabs.indexOf(screen._zone_table)
    assert screen._tabs.isTabEnabled(zone_index) is False


def test_zone_tab_enabled_when_zones_are_defined(qtbot) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"zones": ZoneSet(rois=[ROI(name="arena", vertices=[(0, 0), (1, 0), (1, 1)])])}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    zone_index = screen._tabs.indexOf(screen._zone_table)
    assert screen._tabs.isTabEnabled(zone_index) is True


# ── live signal-path updates ──────────────────────────────────────────────────


def test_identity_graying_updates_live_when_a_stable_identity_session_arrives(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)  # initially greyed

    store.update_sessions(
        [
            SessionRef(
                session_id="s1", folder=Path("s1"), sha256="x",
                has_stable_identities=False,
            ),
            SessionRef(
                session_id="s2", folder=Path("s2"), sha256="y",
                has_stable_identities=True,
            ),
        ]
    )

    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)  # re-enabled live


def test_zone_tab_enables_live_when_zones_are_added(qtbot) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    zone_index = screen._tabs.indexOf(screen._zone_table)
    assert screen._tabs.isTabEnabled(zone_index) is False  # initially disabled

    store.update_zones(ZoneSet(rois=[ROI(name="arena", vertices=[(0, 0), (1, 0), (1, 1)])]))

    assert screen._tabs.isTabEnabled(zone_index) is True  # enabled live


def test_greyed_row_still_has_clickable_info_and_config_buttons(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)  # confirm row is greyed

    info_btn = screen._ind_table.cellWidget(row, 3)
    config_btn = screen._ind_table.cellWidget(row, 4)
    assert info_btn is not None and info_btn.isEnabled()
    assert config_btn is not None and config_btn.isEnabled()
