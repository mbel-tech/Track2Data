"""
Phase 1 smoke tests — app shell and project state.

Tests are split into two classes:
  TestEngineLayer   — no PySide6 required; tests core models + store logic.
  TestUILayer       — requires PySide6 and a display; auto-skipped otherwise.

Run:
    pytest tests/test_app_smoke.py -v
    pytest tests/test_app_smoke.py -v -k TestEngineLayer   # headless only
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────


def _has_pyside6() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except ImportError:
        return False


requires_pyside6 = pytest.mark.skipif(
    not _has_pyside6(), reason="PySide6 not installed"
)


# ── engine-layer tests (no PySide6 required) ───────────────────────────────────


class TestEngineLayer:
    """Verify core engine models import and work independently of the GUI."""

    def test_track2data_imports(self) -> None:
        import track2data  # noqa: F401

    def test_core_models_import(self) -> None:
        from track2data.core.models import (  # noqa: F401
            CalibrationConfig,
            GapFillCfg,
            MetricSelection,
            PreprocessConfig,
            ProjectManifest,
            ZoneSet,
        )

    def test_create_project_manifest(self) -> None:
        from track2data.core.models import ProjectManifest

        now = datetime.now(tz=UTC)
        m = ProjectManifest(
            project_name="smoke-test",
            created_at=now,
            updated_at=now,
        )
        assert m.project_name == "smoke-test"
        assert m.schema_version == 1
        assert m.sessions == []
        assert m.calibration.mode == "bodylength"

    def test_manifest_project_hash_is_deterministic(self) -> None:
        from track2data.core.models import ProjectManifest

        now = datetime.now(tz=UTC)
        kwargs = dict(project_name="hash-test", created_at=now, updated_at=now)
        h1 = ProjectManifest(**kwargs).project_hash()
        h2 = ProjectManifest(**kwargs).project_hash()
        assert h1 == h2
        assert len(h1) == 16

    def test_preprocess_config_defaults(self) -> None:
        from track2data.core.models import PreprocessConfig

        cfg = PreprocessConfig()
        assert cfg.gap_fill.enabled is True
        assert cfg.gap_fill.max_gap_frames == 30
        assert cfg.jump.method == "sd_multiple"
        assert cfg.smoothing.method == "savgol"

    def test_metric_selection_has_diagnostic_field(self) -> None:
        from track2data.core.models import MetricSelection

        sel = MetricSelection(individual=["IL-1", "IL-2"])
        assert "IL-1" in sel.individual
        assert sel.diagnostic == []
        assert sel.quality_threshold == 0.0

    def test_engine_import(self) -> None:
        from track2data.api import Engine  # noqa: F401

    def test_manifest_read_write_roundtrip(self, tmp_path: Path) -> None:
        from track2data.core.manifest import read, write
        from track2data.core.models import ProjectManifest

        now = datetime.now(tz=UTC)
        m = ProjectManifest(
            project_name="roundtrip",
            created_at=now,
            updated_at=now,
        )
        out = tmp_path / "test.t2d.json"
        write(m, out)
        loaded = read(out)
        assert loaded.project_name == "roundtrip"
        assert loaded.schema_version == m.schema_version


# ── UI-layer tests (PySide6 required) ─────────────────────────────────────────


@requires_pyside6
class TestUILayer:
    """Verify PySide6 app shell imports and basic instantiation."""

    def test_app_modules_import(self) -> None:
        from app import (
            main,  # noqa: F401
            main_window,  # noqa: F401
            navigation,  # noqa: F401
            state,  # noqa: F401
        )

    def test_ui_screen_modules_import(self) -> None:
        from ui import (
            calibration_screen,  # noqa: F401
            export_screen,  # noqa: F401
            import_screen,  # noqa: F401
            metadata_screen,  # noqa: F401
            metrics_screen,  # noqa: F401
            preprocessing_screen,  # noqa: F401
            preview_screen,  # noqa: F401
            processing_screen,  # noqa: F401
            project_screen,  # noqa: F401
            zones_screen,  # noqa: F401
        )

    def test_stages_constant(self) -> None:
        from app.navigation import STAGES

        # 9 stages, not 7: Preprocessing/Metrics/Processing each got
        # their own sidebar row so every page is directly reachable --
        # see app/navigation.py's module comment.
        assert len(STAGES) == 9
        assert STAGES[0][0].startswith("1")
        assert STAGES[-1][0].startswith("9")

    def test_page_to_stage_mapping_length(self) -> None:
        from app.navigation import PAGE_TO_STAGE, STAGES

        # 10 pages, 9 stages — all stage indices in range.
        assert len(PAGE_TO_STAGE) == 10
        assert all(0 <= s < len(STAGES) for s in PAGE_TO_STAGE)

    def test_page_to_stage_is_one_to_one_except_preview_export(self) -> None:
        """Every page has its own stage now, except pages 8-9 (Preview,
        Export), which still share one row -- the one pairing that was
        never the source of the "can't reach this screen" bug."""
        from app.navigation import PAGE_TO_STAGE

        assert PAGE_TO_STAGE[:8] == [0, 1, 2, 3, 4, 5, 6, 7]
        assert PAGE_TO_STAGE[8] == PAGE_TO_STAGE[9] == 8

    def test_app_state_is_a_genuine_reexport_not_a_duplicate(self) -> None:
        """D-004 / issue #27: app/state.py is a deprecated shim over
        ui/store/project_store.py, not a second copy of the class."""
        from app.state import ProjectStore as ShimProjectStore
        from ui.store.project_store import ProjectStore as RealProjectStore

        assert ShimProjectStore is RealProjectStore

    @pytest.fixture(scope="class")
    def qt_app(self):
        """One QApplication per test class (cannot create more than one)."""
        import sys

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        yield app

    def test_project_store_starts_empty(self, qt_app) -> None:
        from app.state import ProjectStore

        store = ProjectStore()
        assert store.manifest is None
        assert store.has_project is False

    def test_project_store_new_project(self, qt_app, tmp_path: Path) -> None:
        from app.state import ProjectStore

        store = ProjectStore()
        store.new_project("my-exp", tmp_path)
        assert store.has_project
        assert store.manifest is not None
        assert store.manifest.project_name == "my-exp"
        assert store.project_dir == tmp_path

    def test_project_store_save_and_reload(self, qt_app, tmp_path: Path) -> None:
        from app.state import ProjectStore

        store = ProjectStore()
        store.new_project("save-test", tmp_path)
        saved = store.save_project()
        assert saved is not None
        assert saved.exists()

        store2 = ProjectStore()
        store2.open_project(saved)
        assert store2.manifest is not None
        assert store2.manifest.project_name == "save-test"

    def test_project_store_update_metadata_source(self, qt_app, tmp_path: Path) -> None:
        from app.state import ProjectStore
        from track2data.core.models import MetadataSource

        store = ProjectStore()
        store.new_project("meta-test", tmp_path)
        fired: list[bool] = []
        store.metadataChanged.connect(lambda: fired.append(True))

        source = MetadataSource(path=tmp_path / "meta.csv", sha256="abc123")
        store.update_metadata_source(source)

        assert store.manifest.metadata_source == source
        assert fired == [True]

    def test_project_store_update_metadata_source_to_none(
        self, qt_app, tmp_path: Path
    ) -> None:
        """Skipping metadata must be representable -- source goes back to None."""
        from app.state import ProjectStore
        from track2data.core.models import MetadataSource

        store = ProjectStore()
        store.new_project("meta-skip-test", tmp_path)
        store.update_metadata_source(MetadataSource(path=tmp_path / "m.csv", sha256="x"))

        store.update_metadata_source(None)

        assert store.manifest.metadata_source is None

    def test_project_store_update_mapping(self, qt_app, tmp_path: Path) -> None:
        from app.state import ProjectStore
        from track2data.core.models import MappingRule

        store = ProjectStore()
        store.new_project("mapping-test", tmp_path)
        fired: list[bool] = []
        store.metadataChanged.connect(lambda: fired.append(True))

        rule = MappingRule(rules={"treatment": "condition"})
        store.update_mapping(rule)

        assert store.manifest.mapping == rule
        assert fired == [True]

    def test_project_store_update_export_targets(self, qt_app, tmp_path: Path) -> None:
        """exportChanged has never had an emitter anywhere in the codebase
        before this setter -- this is what makes the export wizard stage
        able to persist anything at all."""
        from app.state import ProjectStore
        from track2data.core.models import ExportTarget

        store = ProjectStore()
        store.new_project("export-test", tmp_path)
        fired: list[bool] = []
        store.exportChanged.connect(lambda: fired.append(True))

        targets = [ExportTarget(exporter_name="csv_long"), ExportTarget(exporter_name="readme")]
        store.update_export_targets(targets)

        assert store.manifest.export_targets == targets
        assert fired == [True]

    def test_project_store_setters_are_noop_without_a_project(self, qt_app) -> None:
        """Matches the existing guard on every other setter (update_calibration,
        update_zones, etc.): silently do nothing when no project is open,
        rather than crash on self._manifest.model_copy(...)."""
        from app.state import ProjectStore
        from track2data.core.models import ExportTarget, MappingRule, MetadataSource

        store = ProjectStore()
        assert store.manifest is None

        store.update_metadata_source(MetadataSource(path=Path("x.csv"), sha256="x"))
        store.update_mapping(MappingRule())
        store.update_export_targets([ExportTarget(exporter_name="csv_long")])

        assert store.manifest is None

    # ── tasks property + forwarding, run_results (issue #27) ───────────────

    def test_store_owns_a_single_task_runner_instance(self, qt_app) -> None:
        from app.state import ProjectStore
        from ui.store.task_runner import TaskRunner

        store = ProjectStore()
        assert isinstance(store.tasks, TaskRunner)
        assert store.tasks is store.tasks  # same instance, not re-created

    def test_store_forwards_task_progress(self, qtbot, qt_app) -> None:
        from app.state import ProjectStore
        from track2data.core.progress import ProgressEvent

        store = ProjectStore()
        forwarded: list[tuple[str, int]] = []
        store.taskProgress.connect(lambda tid, pct: forwarded.append((tid, pct)))

        def do_work(progress) -> str:
            progress(ProgressEvent(stage="run", current=1, total=2))
            return "ok"

        with qtbot.waitSignal(store.taskFinished, timeout=2000):
            store.tasks.submit_with_progress(do_work)

        assert forwarded == [(forwarded[0][0], 50)]

    def test_store_forwards_successful_task_result(self, qtbot, qt_app) -> None:
        from app.state import ProjectStore

        store = ProjectStore()
        with qtbot.waitSignal(store.taskFinished, timeout=2000) as blocker:
            store.tasks.submit(lambda: "the result")

        _task_id, result = blocker.args
        assert result == "the result"

    def test_store_forwards_task_failure_as_exception_on_task_finished(
        self, qtbot, qt_app
    ) -> None:
        """
        taskFailed -> taskFinished, per taskFinished's documented
        "result-or-exception" contract -- so UI code only ever needs to
        listen to one signal to learn a task is done, success or not.
        """
        from app.state import ProjectStore

        store = ProjectStore()

        def boom() -> None:
            raise RuntimeError("simulated failure")

        with qtbot.waitSignal(store.taskFinished, timeout=2000) as blocker:
            store.tasks.submit(boom)

        _task_id, result = blocker.args
        assert isinstance(result, Exception)
        assert "simulated failure" in str(result)
        assert "RuntimeError" in result.traceback
        assert "boom" in result.traceback

    def test_store_run_results_starts_none_and_set_run_results_emits(
        self, qt_app
    ) -> None:
        from app.state import ProjectStore
        from track2data.core.models import RunResult, SessionRunResult

        store = ProjectStore()
        assert store.run_results is None
        fired: list[bool] = []
        store.runResultsChanged.connect(lambda: fired.append(True))

        result = RunResult(sessions=[SessionRunResult(session_id="s1")])
        store.set_run_results(result)

        assert store.run_results is result
        assert fired == [True]

    def test_wizard_sidebar_creation(self, qt_app) -> None:
        from app.navigation import WizardSidebar

        sidebar = WizardSidebar()
        assert sidebar.count() == 9

    def test_sidebar_reaches_every_page(self, qt_app) -> None:
        """Regression test for the actual bug: clicking every sidebar row
        used to land on only 7 of 10 pages (0,1,2,3,4,5,8 -- Metrics and
        Processing were unreachable except via the toolbar's Next
        button). Each stage must now land on a page no other stage
        does, except the shared Preview/Export pair."""
        from app.main_window import MainWindow

        win = MainWindow()
        landed = []
        for row in range(win._sidebar.count()):
            win._sidebar.setCurrentRow(row)
            landed.append(win._stack.currentIndex())
        win.close()

        assert landed == [0, 1, 2, 3, 4, 5, 6, 7, 8]

    def test_main_window_creation(self, qt_app) -> None:
        from app.main_window import MainWindow

        win = MainWindow()
        assert win.windowTitle() == "Track2Data"
        # Stack has 10 pages.
        assert win._stack.count() == 10
        win.close()

    def test_main_window_navigation(self, qt_app) -> None:
        from app.main_window import MainWindow

        win = MainWindow()
        assert win._stack.currentIndex() == 0
        win._go_to_page(3)
        assert win._stack.currentIndex() == 3
        win._go_back()
        assert win._stack.currentIndex() == 2
        win._go_next()
        assert win._stack.currentIndex() == 3
        win.close()

    def test_all_screen_widgets_instantiate(self, qt_app) -> None:
        from app.state import ProjectStore
        from ui.calibration_screen import CalibrationScreen
        from ui.export_screen import ExportScreen
        from ui.import_screen import ImportScreen
        from ui.metadata_screen import MetadataScreen
        from ui.metrics_screen import MetricsScreen
        from ui.preprocessing_screen import PreprocessingScreen
        from ui.preview_screen import PreviewScreen
        from ui.processing_screen import ProcessingScreen
        from ui.project_screen import ProjectScreen
        from ui.zones_screen import ZonesScreen

        store = ProjectStore()
        screens = [
            ProjectScreen(store),
            ImportScreen(store),
            CalibrationScreen(store),
            ZonesScreen(store),
            MetadataScreen(store),
            PreprocessingScreen(store),
            MetricsScreen(store),
            ProcessingScreen(store),
            PreviewScreen(store),
            ExportScreen(store),
        ]
        assert len(screens) == 10
        for screen in screens:
            assert isinstance(screen, __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget)
