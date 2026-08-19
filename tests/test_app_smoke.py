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

        assert len(STAGES) == 7
        assert STAGES[0][0].startswith("1")
        assert STAGES[-1][0].startswith("7")

    def test_page_to_stage_mapping_length(self) -> None:
        from app.navigation import PAGE_TO_STAGE, STAGES

        # 10 pages, 7 stages — all stage indices in range.
        assert len(PAGE_TO_STAGE) == 10
        assert all(0 <= s < len(STAGES) for s in PAGE_TO_STAGE)

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

    def test_wizard_sidebar_creation(self, qt_app) -> None:
        from app.navigation import WizardSidebar

        sidebar = WizardSidebar()
        assert sidebar.count() == 7

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
