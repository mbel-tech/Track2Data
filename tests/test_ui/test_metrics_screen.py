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
    """Resolve a row by the real identifier, stored as UserRole data on
    the Include cell (column 0) -- not by any column's displayed text.
    The Name column shows a pretty label, not the registry id, and
    columns get reshuffled from time to time; this must survive that."""
    for row in range(table.rowCount()):
        if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == metric_id:
            return row
    raise AssertionError(f"{metric_id} not found in table")


def _ids_in_table(table) -> list[str]:
    return [
        table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount())
    ]


# ── registry-driven rows ──────────────────────────────────────────────────────


def test_individual_tab_has_one_row_per_registered_individual_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("individual")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    assert _ids_in_table(screen._ind_table) == expected_ids


def test_name_column_shows_the_display_label_not_the_snake_case_name(qtbot) -> None:
    """Metric declares both `name` (snake_case identifier, e.g.
    "path_length") and `label` (display string, e.g. "Path Length") --
    track2data/metrics/base.py:37-38. The Name column must show the
    label. MetricInfoDialog and cli.py already do this correctly; the
    table read the wrong attribute."""
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    metric_cls = metrics.get("IL-1")
    assert metric_cls.label != metric_cls.name  # otherwise this test proves nothing
    assert screen._ind_table.item(row, 1).text() == metric_cls.label


def test_id_and_snake_case_name_never_appear_anywhere_in_the_table(qtbot) -> None:
    """Neither the registry id ("IL-1") nor the snake_case internal
    name ("path_length") is user-facing text -- they must not appear
    as the text of any cell (they still live as UserRole data, which
    is never rendered)."""
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    for table in (screen._ind_table, screen._grp_table, screen._zone_table):
        for row in range(table.rowCount()):
            metric_id = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            metric_cls = metrics.get(metric_id)
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is None:
                    continue
                assert item.text() != metric_cls.id
                assert item.text() != metric_cls.name


def test_group_tab_has_one_row_per_registered_group_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("group")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    assert _ids_in_table(screen._grp_table) == expected_ids


def test_zone_tab_has_one_row_per_registered_zone_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(
        (m.id for m in metrics.list_for_level("zone")),
        key=lambda metric_id: (metric_id.rpartition("-")[0], int(metric_id.rpartition("-")[2])),
    )
    assert _ids_in_table(screen._zone_table) == expected_ids


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


def test_apply_preserves_fields_the_table_has_no_widgets_for(qtbot) -> None:
    """Regression: _apply() used to build a fresh MetricSelection(...)
    from only the four fields the screen's own widgets show, silently
    resetting `diagnostic` and `config` -- which nothing on this
    screen edits -- to their defaults on every Apply click."""
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "metrics": MetricSelection(
                diagnostic=["D-1", "D-2"],
                config={"IL-4": {"threshold_px_s": 2.5}},
            )
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    screen._apply()

    assert store.manifest.metrics.individual == ["IL-1"]
    assert store.manifest.metrics.diagnostic == ["D-1", "D-2"]
    assert store.manifest.metrics.config == {"IL-4": {"threshold_px_s": 2.5}}


# ── per-row ⓘ / ⚙ buttons ─────────────────────────────────────────────────────


def test_config_button_is_disabled_for_a_metric_with_no_parameters(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")  # IL-1 declares no MetricParameter entries
    config_btn = screen._ind_table.cellWidget(row, 3)

    assert config_btn is not None
    assert config_btn.isEnabled() is False
    assert config_btn.toolTip() != ""


def test_config_button_is_enabled_for_a_metric_with_parameters(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")  # declares threshold_px_s/threshold_multiplier
    config_btn = screen._ind_table.cellWidget(row, 3)

    assert config_btn is not None
    assert config_btn.isEnabled() is True


def test_config_button_opens_metric_config_dialog_for_that_row(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            opened.append(metric_cls.id)

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.cellWidget(row, 3).click()

    assert opened == ["IL-4"]

    # A different row's button must open ITS OWN metric -- guards against a
    # lambda-over-loop-variable bug where every row's button would close
    # over the same (last) metric_cls, same as the ⓘ button's test above.
    other_row = _row_for_id(screen._ind_table, "IL-7")
    screen._ind_table.cellWidget(other_row, 3).click()

    assert opened == ["IL-4", "IL-7"]


def test_metric_config_dialog_receives_the_saved_current_values(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"metrics": MetricSelection(config={"IL-4": {"threshold_px_s": 9.0}})}
    )

    received: list[dict] = []

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            received.append(current_values)

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.cellWidget(row, 3).click()

    assert received == [{"threshold_px_s": 9.0}]


def test_saving_metric_config_preserves_unapplied_selection_and_threshold(
    qtbot, monkeypatch
) -> None:
    """Regression: saving the ⚙ dialog wrote straight to the store, whose
    metricsChanged signal re-ran _load_from_store and reset every checkbox
    and the quality spin to the *persisted* values -- silently discarding
    everything the user had ticked but not yet clicked Apply on."""
    from PySide6.QtWidgets import QDialog

    from ui.metrics_screen import MetricsScreen

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def values(self) -> dict:
            return {"threshold_px_s": 9.0}

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    # On-screen state the user has NOT applied yet.
    il1 = _row_for_id(screen._ind_table, "IL-1")
    il4 = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.item(il1, 0).setCheckState(Qt.CheckState.Checked)
    screen._ind_table.item(il4, 0).setCheckState(Qt.CheckState.Checked)
    screen._quality_spin.setValue(0.75)

    screen._ind_table.cellWidget(il4, 3).click()  # open ⚙ and Save

    assert screen._ind_table.item(il1, 0).checkState() == Qt.CheckState.Checked
    assert screen._ind_table.item(il4, 0).checkState() == Qt.CheckState.Checked
    assert screen._quality_spin.value() == pytest.approx(0.75)
    assert store.manifest.metrics.config == {"IL-4": {"threshold_px_s": 9.0}}


def test_saving_metric_config_dialog_persists_into_manifest_config(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    from ui.metrics_screen import MetricsScreen

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def values(self) -> dict:
            return {"threshold_px_s": 9.0, "threshold_multiplier": 0.2}

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.cellWidget(row, 3).click()

    assert store.manifest.metrics.config == {
        "IL-4": {"threshold_px_s": 9.0, "threshold_multiplier": 0.2}
    }


def test_cancelling_metric_config_dialog_does_not_change_config(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    from ui.metrics_screen import MetricsScreen

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

        def values(self) -> dict:
            raise AssertionError("values() must not be read when the dialog is cancelled")

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.cellWidget(row, 3).click()

    assert store.manifest.metrics.config == {}


def test_saving_metric_config_preserves_other_metrics_saved_config(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    from ui.metrics_screen import MetricsScreen

    class _StubDialog:
        def __init__(self, metric_cls, current_values, parent=None) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def values(self) -> dict:
            return {"threshold_px_s": 9.0}

    monkeypatch.setattr("ui.metrics_screen.MetricConfigDialog", _StubDialog)

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"metrics": MetricSelection(config={"GL-6": {"cohesion_source": "iid"}})}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-4")
    screen._ind_table.cellWidget(row, 3).click()

    assert store.manifest.metrics.config == {
        "GL-6": {"cohesion_source": "iid"},
        "IL-4": {"threshold_px_s": 9.0},
    }


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
    screen._ind_table.cellWidget(row, 2).click()

    assert opened == ["IL-1"]

    # A different row's button must open ITS OWN metric, not IL-1 again --
    # guards against a lambda-over-loop-variable bug where every row's
    # button would close over the same (last) metric_cls.
    other_row = _row_for_id(screen._ind_table, "IL-3")
    screen._ind_table.cellWidget(other_row, 2).click()

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

    assert screen._ind_table.cellWidget(0, 2) is None


# ── identity-aware graying ─────────────────────────────────────────────
#
# The trigger is SessionRef.is_identity_free() -- the same predicate
# Engine.compute_metrics gates on -- not has_stable_identities, which also
# folds in coverage heuristics and so used to grey rows the engine would
# happily have computed.


def _sessions(*specs):
    """SessionRefs from (session_id, track_wo_identities, override) triples."""
    from track2data.core.models import SessionRef

    return [
        SessionRef(
            session_id=sid,
            folder=Path(sid),
            sha256=sid,
            track_wo_identities=declared,
            identity_free_override=override,
        )
        for sid, declared, override in specs
    ]


def _il1_include_item(screen):
    return screen._ind_table.item(_row_for_id(screen._ind_table, "IL-1"), 0)


def test_identity_required_rows_greyed_when_every_session_is_identity_free(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    include_item = _il1_include_item(screen)  # IL-1.requires_identity is True
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "identity-free" in include_item.toolTip()


def test_rows_not_greyed_when_sessions_are_unprobed(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": [SessionRef(session_id="s1", folder=Path("s1"), sha256="x")]}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    assert bool(_il1_include_item(screen).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_rows_not_greyed_when_at_least_one_session_preserves_identity(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None), ("s2", False, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    # Selection is one global list, so refusing the tick outright would make
    # IL-1 unavailable for s2, which can support it.
    assert bool(_il1_include_item(screen).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_partially_identity_free_project_names_the_affected_sessions(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None), ("s2", False, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    tooltip = _il1_include_item(screen).toolTip()
    assert "1 of 2" in tooltip
    assert "s1" in tooltip
    assert "s2" not in tooltip


def test_many_identity_free_sessions_are_summarised_not_all_listed(qtbot) -> None:
    """A 70-session project (the GOT corpus is one) must not produce a
    tooltip listing every session id."""
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": _sessions(
                *[(f"s{i}", True, None) for i in range(6)],
                ("keeper", False, None),
            )
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    tooltip = _il1_include_item(screen).toolTip()
    assert "and 3 more" in tooltip
    assert "s5" not in tooltip


def test_low_coverage_session_alone_does_not_grey_identity_rows(qtbot) -> None:
    """Deliberate change of behaviour: greying used to fire on
    has_stable_identities, so a session that merely had poor coverage disabled
    every individual metric even though the engine would still compute them.
    Only an identity-free session gates now."""
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False, track_wo_identities=False,
                )
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    assert bool(_il1_include_item(screen).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_user_override_greys_rows_for_a_session_the_tracker_called_identified(
    qtbot,
) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", False, True))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    assert not (_il1_include_item(screen).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_user_override_ungreys_rows_for_a_session_tracked_without_identities(
    qtbot,
) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, False))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    assert bool(_il1_include_item(screen).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_identity_independent_rows_are_never_greyed(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    # GL-1 (nearest-neighbour distance) is an unordered per-frame point set --
    # genuinely identity-free, so it stays selectable.
    row = _row_for_id(screen._grp_table, "GL-1")
    include_item = screen._grp_table.item(row, 0)
    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert include_item.toolTip() == ""


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


def test_identity_graying_updates_live_when_an_identified_session_arrives(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    include_item = _il1_include_item(screen)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)  # initially greyed

    store.update_sessions(_sessions(("s1", True, None), ("s2", False, None)))

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
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": _sessions(("s1", True, None))}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    # IL-4: requires_identity, and (unlike IL-1) declares parameters, so its
    # ⚙ button is enabled on its own merits -- proving graying doesn't ALSO
    # disable it.
    row = _row_for_id(screen._ind_table, "IL-4")
    include_item = screen._ind_table.item(row, 0)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)  # confirm row is greyed

    info_btn = screen._ind_table.cellWidget(row, 2)
    config_btn = screen._ind_table.cellWidget(row, 3)
    assert info_btn is not None and info_btn.isEnabled()
    assert config_btn is not None and config_btn.isEnabled()


# ── sort-key robustness ───────────────────────────────────────────────────────


def test_table_builds_without_crashing_for_a_non_conforming_plugin_metric_id(
    qtbot, monkeypatch
) -> None:
    """Third-party metrics (loaded via the track2data.metrics entry
    point) aren't required to use the built-in PREFIX-NUMBER id shape.
    _natural_sort_key must fall back gracefully instead of crashing the
    whole screen on one non-conforming plugin metric id."""
    from track2data.metrics.base import MetricDocumentation
    from ui.metrics_screen import MetricsScreen

    class _PluginMetric:
        id = "MyPluginMetric"  # no "-NUMBER" suffix at all
        name = "Plugin metric"
        label = "Plugin metric"
        level = "individual"
        priority = "diagnostic"
        requires_identity = False
        output_columns: list[str] = []
        documentation = MetricDocumentation.model_construct(
            definition="d", formula_plain="f", inputs=[], assumptions=[],
            warnings=[], citation=None, citation_doi=None,
        )

    original_list_for_level = metrics.list_for_level

    def _with_plugin_metric(level: str):
        real = original_list_for_level(level)
        return [*real, _PluginMetric] if level == "individual" else real

    monkeypatch.setattr("ui.metrics_screen.metrics.list_for_level", _with_plugin_metric)

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    assert "MyPluginMetric" in _ids_in_table(screen._ind_table)
