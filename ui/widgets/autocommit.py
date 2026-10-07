"""Debounced auto-commit for parameter screens (replaces "Apply" buttons).

A screen connects its input widgets' change signals to ``trigger()``; the
commit callback runs once after the user pauses. ``flush()`` commits any
pending edit immediately -- ``MainWindow`` calls it before leaving a screen
so a change made less than ``delay_ms`` before navigating is never lost.
``suppressed()`` silences triggers while the screen repopulates its widgets
from the store, which would otherwise commit (and re-emit) in a loop.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject, QTimer


class AutoCommit(QObject):
    def __init__(
        self, commit: Callable[[], None], parent: QObject | None = None, delay_ms: int = 200
    ) -> None:
        super().__init__(parent)
        self._commit = commit
        self._suppressed = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._fire)

    @property
    def pending(self) -> bool:
        return self._timer.isActive()

    def trigger(self, *_args: object) -> None:
        if self._suppressed:
            return
        self._timer.start()

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._fire()

    @contextmanager
    def suppressed(self) -> Iterator[None]:
        self._suppressed += 1
        try:
            yield
        finally:
            self._suppressed -= 1

    def _fire(self) -> None:
        self._commit()
