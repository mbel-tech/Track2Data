"""
Tests for ui/preview_screen.py (issue #25) -- Diagnostics and Metrics
tabs driven by store.run_results / store.runResultsChanged.

RunResult/SessionRunResult are constructed directly with small synthetic
DataFrames matching the real D-1..D-5 output_columns (see
track2data/metrics/diagnostic.py) -- this screen only ever *reads*
store.run_results, it never produces one, so no real pipeline run is
needed here (that's ProcessingScreen's job, already covered by
tests/test_ui/test_processing_screen.py).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QTableWidget

from track2data.core.models import PPStepResult, PreprocessReport, RunResult, SessionRunResult

# ── synthetic RunResult builders ──────────────────────────────────────────────


def _diagnostics_for(
    session_id: str,
    *,
    coverage: list[tuple[int, float, int]],
    accuracy: tuple[float, float, str],
    id_prob: list[tuple[int, float, float, float, float]],
    inconsistent: tuple[int, float],
    stability: str,
) -> dict[str, pd.DataFrame]:
    """Build the D-1..D-5 DataFrames exactly as track2data.metrics.diagnostic
    would (same output_columns), for one synthetic session."""
    d1 = pd.DataFrame(
        [
            {
                "session_id": session_id,
                "individual_id": ind,
                "coverage_fraction": cov,
                "nan_frames_count": n,
            }
            for ind, cov, n in coverage
        ]
    )
    d2 = pd.DataFrame(
        [
            {
                "session_id": session_id,
                "estimated_accuracy": accuracy[0],
                "fraction_identified": accuracy[1],
                "note": accuracy[2],
            }
        ]
    )
    d3 = pd.DataFrame(
        [
            {
                "session_id": session_id,
                "individual_id": ind,
                "id_prob_median": med,
                "id_prob_p10": p10,
                "id_prob_p90": p90,
                "id_prob_frac_above_0p9": frac,
            }
            for ind, med, p10, p90, frac in id_prob
        ]
    )
    d4 = pd.DataFrame(
        [
            {
                "session_id": session_id,
                "inconsistent_frame_count": inconsistent[0],
                "inconsistent_frame_fraction": inconsistent[1],
            }
        ]
    )
    d5 = pd.DataFrame([{"session_id": session_id, "identity_stability_status": stability}])
    return {"D-1": d1, "D-2": d2, "D-3": d3, "D-4": d4, "D-5": d5}


def _session1() -> SessionRunResult:
    return SessionRunResult(
        session_id="s1",
        diagnostics=_diagnostics_for(
            "s1",
            coverage=[(0, 0.9, 1), (1, 0.8, 2)],
            accuracy=(0.95, 0.99, ""),
            id_prob=[(0, 0.99, 0.9, 1.0, 0.8), (1, 0.97, 0.85, 1.0, 0.7)],
            inconsistent=(3, 0.03),
            stability="stable",
        ),
        metric_previews={
            "IL-1": pd.DataFrame({"session_id": ["s1"], "value": [1.23456]}),
            "GL-1": pd.DataFrame({"session_id": ["s1"], "value": [42.0]}),
        },
        duration_s=1.5,
    )


def _session2() -> SessionRunResult:
    return SessionRunResult(
        session_id="s2",
        diagnostics=_diagnostics_for(
            "s2",
            coverage=[(0, 0.5, 5), (1, 0.4, 6)],
            accuracy=(0.70, 0.60, "low accuracy"),
            id_prob=[(0, 0.5, 0.1, 0.9, 0.2), (1, 0.4, 0.05, 0.8, 0.1)],
            inconsistent=(10, 0.5),
            stability="weak",
        ),
        metric_previews={
            "IL-1": pd.DataFrame({"session_id": ["s2"], "value": [2.71828]}),
        },
        duration_s=2.5,
    )


def _session3_with_preprocess_report() -> SessionRunResult:
    return SessionRunResult(
        session_id="s3",
        diagnostics=_diagnostics_for(
            "s3",
            coverage=[(0, 0.9, 1)],
            accuracy=(0.9, 0.9, ""),
            id_prob=[(0, 0.9, 0.8, 1.0, 0.7)],
            inconsistent=(1, 0.01),
            stability="stable",
        ),
        metric_previews={"IL-1": pd.DataFrame({"session_id": ["s3"], "value": [1.0]})},
        preprocess_report=PreprocessReport(
            steps=[
                PPStepResult(
                    step_name="gap_fill",
                    affected_frames=12,
                    affected_per_individual=[7, 5],
                    notes="filled short gaps",
                ),
                PPStepResult(
                    step_name="jump_detect",
                    affected_frames=3,
                    affected_per_individual=[3, 0],
                    notes="",
                ),
            ]
        ),
    )


# ── table-content helpers ─────────────────────────────────────────────────────


def _headers(table: QTableWidget) -> list[str]:
    return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]


def _row_dict(table: QTableWidget, row: int) -> dict[str, str]:
    return {
        table.horizontalHeaderItem(c).text(): table.item(row, c).text()
        for c in range(table.columnCount())
    }


def _find_row(table: QTableWidget, **kv: str) -> dict[str, str] | None:
    for r in range(table.rowCount()):
        d = _row_dict(table, r)
        if all(d.get(k) == v for k, v in kv.items()):
            return d
    return None


# ── construction ─────────────────────────────────────────────────────────────


def test_screen_constructs_without_a_store(qtbot) -> None:
    from ui.preview_screen import PreviewScreen

    screen = PreviewScreen()
    qtbot.addWidget(screen)
    assert screen is not None
    assert screen._diag_placeholder.text() == "Run the pipeline to see diagnostics."
    assert screen._metrics_placeholder.text() == "Run the pipeline to see metric previews."


# ── placeholders before any run ─────────────────────────────────────────────


def test_diagnostics_tab_shows_placeholder_before_any_run(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    assert store.run_results is None
    assert screen._diag_placeholder.text() == "Run the pipeline to see diagnostics."
    assert screen._diag_placeholder.isHidden() is False
    assert screen._diag_individual_table.rowCount() == 0
    assert screen._diag_session_table.rowCount() == 0
    assert screen._diag_preprocess_table.rowCount() == 0
    assert screen._diag_session_combo.count() == 0


def test_metrics_tab_shows_placeholder_before_any_run(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    assert screen._metrics_placeholder.text() == "Run the pipeline to see metric previews."
    assert screen._metrics_placeholder.isHidden() is False
    assert screen._metrics_table.rowCount() == 0
    assert screen._metrics_session_combo.count() == 0
    assert screen._metrics_metric_combo.count() == 0


def test_diagnostics_and_metrics_tabs_show_placeholder_when_run_has_no_sessions(qtbot) -> None:
    """A RunResult with zero sessions (e.g. every session failed to
    import) must fall back to the placeholder, not an empty table with a
    stray, confusing session selector."""
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[]))

    assert screen._diag_placeholder.isHidden() is False
    assert screen._metrics_placeholder.isHidden() is False
    assert screen._diag_session_combo.count() == 0
    assert screen._metrics_session_combo.count() == 0


# ── Diagnostics tab: populated after a run ──────────────────────────────────


def test_diagnostics_tab_populates_after_set_run_results(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[_session1()]))

    assert screen._diag_placeholder.isHidden() is True
    assert screen._diag_session_combo.count() == 1
    assert screen._diag_session_combo.currentText() == "s1"

    # Per-individual table: D-1 (2 rows) + D-3 (2 rows), stacked with a
    # leading metric_id column. D-3 is per-individual too (it has an
    # individual_id column -- see track2data/metrics/diagnostic.py) even
    # though it is easy to mis-summarise as session-level; both belong here.
    ind_table = screen._diag_individual_table
    assert ind_table.rowCount() == 4
    assert "metric_id" in _headers(ind_table)
    d1_row0 = _find_row(ind_table, metric_id="D-1", individual_id="0")
    assert d1_row0["coverage_fraction"] == "0.9"
    assert d1_row0["nan_frames_count"] == "1"
    assert d1_row0["id_prob_median"] == ""  # not a D-1 column -> NaN -> ""
    d3_row0 = _find_row(ind_table, metric_id="D-3", individual_id="0")
    assert d3_row0["id_prob_median"] == "0.99"
    assert d3_row0["id_prob_p10"] == "0.9"
    assert d3_row0["coverage_fraction"] == ""  # not a D-3 column -> NaN -> ""

    # Session-level table: D-2 + D-4 + D-5, one row each, stacked the same way.
    sess_table = screen._diag_session_table
    assert sess_table.rowCount() == 3
    d2_row = _find_row(sess_table, metric_id="D-2")
    assert d2_row["estimated_accuracy"] == "0.95"
    assert d2_row["fraction_identified"] == "0.99"
    d4_row = _find_row(sess_table, metric_id="D-4")
    assert d4_row["inconsistent_frame_count"] == "3"
    assert d4_row["inconsistent_frame_fraction"] == "0.03"
    d5_row = _find_row(sess_table, metric_id="D-5")
    assert d5_row["identity_stability_status"] == "stable"


def test_diagnostics_tab_session_selector_switches_sessions(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    store.set_run_results(RunResult(sessions=[_session1(), _session2()]))

    assert screen._diag_session_combo.count() == 2
    assert [screen._diag_session_combo.itemText(i) for i in range(2)] == ["s1", "s2"]
    assert screen._diag_session_combo.currentText() == "s1"
    d2_row = _find_row(screen._diag_session_table, metric_id="D-2")
    assert d2_row["estimated_accuracy"] == "0.95"

    screen._diag_session_combo.setCurrentText("s2")

    assert screen._diag_session_combo.currentText() == "s2"
    d2_row = _find_row(screen._diag_session_table, metric_id="D-2")
    assert d2_row["estimated_accuracy"] == "0.7"
    assert d2_row["note"] == "low accuracy"
    ind_row = _find_row(screen._diag_individual_table, metric_id="D-1", individual_id="0")
    assert ind_row["coverage_fraction"] == "0.5"


def test_diagnostics_tab_shows_preprocess_steps_table(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[_session3_with_preprocess_report()]))

    table = screen._diag_preprocess_table
    assert table.rowCount() == 2
    assert _headers(table) == ["step_name", "affected_frames", "affected_per_individual", "notes"]
    row0 = _row_dict(table, 0)
    assert row0["step_name"] == "gap_fill"
    assert row0["affected_frames"] == "12"
    assert row0["affected_per_individual"] == "[7, 5]"
    assert row0["notes"] == "filled short gaps"
    row1 = _row_dict(table, 1)
    assert row1["step_name"] == "jump_detect"
    assert row1["affected_frames"] == "3"


def test_diagnostics_tab_preprocess_table_empty_when_report_is_none(qtbot) -> None:
    """s1 has no preprocess_report (defaults to None) -- the steps table
    must render empty rather than crash on a missing report."""
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[_session1()]))

    assert screen._diag_preprocess_table.rowCount() == 0


def test_diagnostics_tab_preprocess_table_empty_when_report_has_no_steps(qtbot) -> None:
    """A report that exists but logged no steps is distinct from None and
    must also render as an empty table, not a header-only ghost row."""
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    session = _session1()
    session.preprocess_report = PreprocessReport(steps=[])
    store.set_run_results(RunResult(sessions=[session]))

    assert screen._diag_preprocess_table.rowCount() == 0
    assert screen._diag_preprocess_table.columnCount() == 0


def test_diagnostics_tab_preprocess_table_clears_when_switching_to_a_reportless_session(
    qtbot,
) -> None:
    """The stale-table regression guard: switching from a session that has
    a report to one that doesn't (and back) must repopulate each time
    rather than leaving the previous session's steps on screen."""
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    store.set_run_results(
        RunResult(sessions=[_session3_with_preprocess_report(), _session1()])
    )

    assert screen._diag_session_combo.currentText() == "s3"
    assert screen._diag_preprocess_table.rowCount() == 2

    screen._diag_session_combo.setCurrentText("s1")
    assert screen._diag_preprocess_table.rowCount() == 0

    screen._diag_session_combo.setCurrentText("s3")
    assert screen._diag_preprocess_table.rowCount() == 2
    assert _row_dict(screen._diag_preprocess_table, 0)["step_name"] == "gap_fill"


# ── Metrics tab: populated after a run ──────────────────────────────────────


def test_metrics_tab_populates_after_set_run_results(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[_session1()]))

    assert screen._metrics_placeholder.isHidden() is True
    assert screen._metrics_session_combo.count() == 1
    assert screen._metrics_metric_combo.count() == 2
    metric_ids = [screen._metrics_metric_combo.itemText(i) for i in range(2)]
    assert metric_ids == ["IL-1", "GL-1"]

    # Defaults to the first metric preview for the (only) selected session.
    assert screen._metrics_table.rowCount() == 1
    assert screen._metrics_table.item(0, 1).text() == "1.235"  # IL-1's "value" column

    screen._metrics_metric_combo.setCurrentText("GL-1")
    assert screen._metrics_table.item(0, 1).text() == "42"


def test_metrics_tab_session_selector_updates_available_metric_ids(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    store.set_run_results(RunResult(sessions=[_session1(), _session2()]))

    # s1 has two metric previews (IL-1, GL-1); s2 has only IL-1.
    assert screen._metrics_metric_combo.count() == 2

    screen._metrics_session_combo.setCurrentText("s2")

    assert screen._metrics_metric_combo.count() == 1
    assert screen._metrics_metric_combo.itemText(0) == "IL-1"
    assert screen._metrics_table.item(0, 1).text() == "2.718"


# ── runResultsChanged actually triggers a re-render ─────────────────────────


def test_run_results_changed_rerenders_diagnostics_and_metrics_tabs(qtbot) -> None:
    """Not just 'doesn't crash': a second set_run_results() call with
    genuinely different data must change the rendered table contents."""
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)

    store.set_run_results(RunResult(sessions=[_session1()]))
    first_accuracy = _find_row(screen._diag_session_table, metric_id="D-2")["estimated_accuracy"]
    first_metric_value = screen._metrics_table.item(0, 1).text()
    assert first_accuracy == "0.95"
    assert first_metric_value == "1.235"

    store.set_run_results(RunResult(sessions=[_session2()]))

    second_accuracy = _find_row(screen._diag_session_table, metric_id="D-2")["estimated_accuracy"]
    second_metric_value = screen._metrics_table.item(0, 1).text()
    assert second_accuracy == "0.7"
    assert second_accuracy != first_accuracy
    assert second_metric_value == "2.718"
    assert second_metric_value != first_metric_value
    # The session combo must reflect the new RunResult's sessions, not the old one.
    assert screen._diag_session_combo.count() == 1
    assert screen._diag_session_combo.currentText() == "s2"


# ── Trajectories tab (GUI-02) ────────────────────────────────────────────────


def _trajectory_store(tmp_path: Path, folder: Path):
    from datetime import UTC, datetime

    from track2data.core.models import (
        CalibrationConfig,
        MetricSelection,
        ProjectManifest,
        SessionRef,
    )
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    store = ProjectStore()
    store._manifest = ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=folder.name, folder=folder, sha256="x")],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1"]),
    )
    store._project_dir = tmp_path
    return store


def test_load_trajectory_data_returns_raw_and_processed(tiny_real_session: Path, tmp_path) -> None:
    from ui.preview_screen import load_trajectory_data

    store = _trajectory_store(tmp_path, tiny_real_session)
    data = load_trajectory_data(store.manifest, tiny_real_session.name, store.cache_dir)
    assert data.raw_xy.shape == data.xy.shape
    assert data.fps > 0
    assert data.xy.ndim == 3


def test_load_trajectory_data_uses_and_fills_the_cache(
    tiny_real_session: Path, tmp_path, monkeypatch
) -> None:
    import track2data.preprocess.pipeline as pl
    from ui.preview_screen import load_trajectory_data

    calls = []
    real = pl.run
    monkeypatch.setattr(pl, "run", lambda *a, **k: calls.append(1) or real(*a, **k))
    store = _trajectory_store(tmp_path, tiny_real_session)
    load_trajectory_data(store.manifest, tiny_real_session.name, store.cache_dir)
    load_trajectory_data(store.manifest, tiny_real_session.name, store.cache_dir)
    assert len(calls) == 1


def test_trajectories_tab_loads_a_session_into_the_view(
    qtbot, tiny_real_session: Path, tmp_path
) -> None:
    from ui.preview_screen import PreviewScreen

    store = _trajectory_store(tmp_path, tiny_real_session)
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    assert screen._traj_view.n_frames == 0
    assert screen._traj_session_combo.currentText() == tiny_real_session.name

    screen._traj_load_btn.click()
    qtbot.waitUntil(lambda: screen._traj_view.n_frames > 0, timeout=15000)
    assert screen._traj_slider.maximum() == screen._traj_view.n_frames - 1

    screen._traj_slider.setValue(5)
    assert screen._traj_view.current_frame == 5


def test_trajectories_controls_drive_the_view(qtbot, tiny_real_session: Path, tmp_path) -> None:
    from ui.preview_screen import PreviewScreen

    screen = PreviewScreen(_trajectory_store(tmp_path, tiny_real_session))
    qtbot.addWidget(screen)
    screen._traj_load_btn.click()
    qtbot.waitUntil(lambda: screen._traj_view.n_frames > 0, timeout=15000)

    screen._traj_heatmap_check.setChecked(True)
    assert screen._traj_view.heatmap_visible()
    screen._traj_source_combo.setCurrentIndex(screen._traj_source_combo.findData("both"))
    assert screen._traj_view._source == "both"
    screen._traj_trail_spin.setValue(30)
    assert screen._traj_view._trail == 30


def test_trajectories_tab_without_sessions_says_so(qtbot) -> None:
    from ui.preview_screen import PreviewScreen

    screen = PreviewScreen()
    qtbot.addWidget(screen)
    assert not screen._traj_load_btn.isEnabled()


def test_quality_grid_has_a_row_verdict_chips_and_reasons_per_session(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    store.set_run_results(RunResult(sessions=[_session1()]))

    table = screen._quality_table
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "s1"
    # the worst animal in the fixture is covered in 80 % of frames: below the 85 % line
    assert table.item(0, 1).text() == "80.0 %"
    assert table.item(0, 6).text() == "Review"
    assert screen._verdict_chips["Review"].text() == "1 review"
    assert screen._why_card.isHidden() is False
    assert "Only 80.0 %" in screen._why_body.text()


def test_quality_grid_clears_when_results_go_away(qtbot) -> None:
    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    screen = PreviewScreen(store)
    qtbot.addWidget(screen)
    store.set_run_results(RunResult(sessions=[_session1()]))
    store.set_run_results(None)

    assert screen._quality_table.rowCount() == 0
    assert screen._why_card.isHidden() is True


def test_screen_is_freed_by_refcount_not_left_to_interpreter_exit(qtbot) -> None:
    """Regression: a ``lambda`` over ``self`` in a connect() makes the screen a
    reference cycle (PySide holds the closure strongly). An unregistered screen
    then survives until interpreter shutdown, is torn down after the
    QApplication, and aborts pytest at exit ("shared QObject was deleted
    directly", exit 134). Connect bound methods instead."""
    import gc
    import weakref

    from ui.preview_screen import PreviewScreen
    from ui.store.project_store import ProjectStore

    gc.collect()
    gc.disable()
    try:
        screen = PreviewScreen(ProjectStore())
        ref = weakref.ref(screen)
        del screen
        assert ref() is None
    finally:
        gc.enable()


def test_load_trajectory_data_fills_crop_from_the_refs_panel(
    tiny_real_session: Path, tmp_path
) -> None:
    from track2data.core.models import PanelRect
    from ui.preview_screen import load_trajectory_data

    store = _trajectory_store(tmp_path, tiny_real_session)
    assert load_trajectory_data(store.manifest, tiny_real_session.name, None).crop is None
    panel = PanelRect(x=0, y=0, width=10, height=10)
    ref = store.manifest.sessions[0]
    store.manifest.sessions[0] = ref.model_copy(update={"panel": panel})
    data = load_trajectory_data(store.manifest, tiny_real_session.name, None)
    assert data.crop == panel
