"""UI objects must be garbage-collectable once they are released.

PySide keeps a ``lambda`` or ``functools.partial`` slot strongly, in the C++
connection table where the garbage collector cannot see it. A slot that captures
``self`` and is connected to a signal of one of ``self``'s own children therefore
makes the owner immortal: its Python wrapper survives to interpreter shutdown,
is destroyed after the QApplication, and Qt aborts with "shared QObject was
deleted directly" -- a segfault after every test has passed. It was intermittent
(heap layout decides whether it faults) and failed CI on a green test run, so
this pins the cause, not the symptom: each class must actually be freed.
"""

from __future__ import annotations

import gc
import weakref
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


def _drain() -> None:
    """Run deferred deletes and collect, the way a finished test's teardown does."""
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        gc.collect()


def _new_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


def _shutdown(store) -> None:
    store.tasks.shutdown(3000)


SCREENS = [
    ("ui.metrics_screen", "MetricsScreen"),
    ("ui.metadata_screen", "MetadataScreen"),
    ("ui.preprocessing_screen", "PreprocessingScreen"),
    ("ui.calibration_screen", "CalibrationScreen"),
    ("ui.zones_screen", "ZonesScreen"),
    ("ui.processing_screen", "ProcessingScreen"),
    ("ui.import_screen", "ImportScreen"),
    ("ui.export_screen", "ExportScreen"),
    ("ui.preview_screen", "PreviewScreen"),
    ("ui.project_screen", "ProjectScreen"),
]


@pytest.mark.parametrize(("module", "name"), SCREENS, ids=[n for _, n in SCREENS])
def test_a_released_screen_is_freed(qtbot, tmp_path: Path, module: str, name: str) -> None:
    import importlib

    store = _new_store(tmp_path)
    screen = getattr(importlib.import_module(module), name)(store=store)
    screen_ref = weakref.ref(screen)
    screen.deleteLater()
    del screen
    _drain()
    leaked = screen_ref() is not None
    _shutdown(store)
    assert not leaked, f"{name} is still alive after being released"


def test_a_released_project_store_is_freed(qtbot, tmp_path: Path) -> None:
    store = _new_store(tmp_path)
    ref = weakref.ref(store)
    _shutdown(store)
    del store
    _drain()
    assert ref() is None, "ProjectStore is still alive after being released"


def test_a_released_main_window_is_freed(qtbot) -> None:
    from app.main_window import MainWindow

    win = MainWindow()
    win_ref = weakref.ref(win)
    store_ref = weakref.ref(win._store)
    win.close()
    win._store.tasks.shutdown(3000)
    win.deleteLater()
    del win
    _drain()
    assert win_ref() is None, "MainWindow is still alive after being closed"
    assert store_ref() is None, "the MainWindow's ProjectStore is still alive"


def test_a_task_runner_callback_does_not_keep_its_runner_alive(qtbot) -> None:
    """The cleanup slot is held strongly by the signals object of a task that
    has not finished; if it held the runner strongly too, every runner with an
    unfinished task would be immortal."""
    from ui.store.task_runner import TaskRunner

    runner = TaskRunner()
    ref = weakref.ref(runner)
    cleanup = runner._forget("task-id")
    runner.shutdown(1000)
    del runner
    _drain()
    assert ref() is None, "the runner is kept alive by its own cleanup callback"
    cleanup()  # a late signal after the runner is gone must be harmless
