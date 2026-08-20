"""
QThreadPool-based background execution of Engine calls, off the GUI
thread (issue #20). Per D-003 (no qasync in v1.0): QThreadPool +
QRunnable only.

``app/state.py``'s ``ProjectStore`` already declares ``taskProgress``/
``taskFinished`` signals -- they were never emitted, because nothing
ran the engine off the GUI thread. This module is what makes
Run/Validate/Export actually do something.
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from track2data.core.progress import CancellationToken, OperationCancelled, ProgressEvent


class _WorkerSignals(QObject):
    """
    Constructed on the GUI thread, before the QRunnable that owns it is
    submitted to the pool. Qt's queued-connection machinery then
    automatically marshals every emit() call made from the pool thread
    back onto the GUI thread -- no manual cross-thread plumbing needed.
    """

    started = Signal(str)              # task_id
    event = Signal(str, object)        # task_id, ProgressEvent
    progress = Signal(str, int)        # task_id, percent 0-100
    log = Signal(str, str)             # task_id, markdown line
    finished = Signal(str, object)     # task_id, result
    failed = Signal(str, str, str)     # task_id, message, traceback
    cancelled = Signal(str)            # task_id


class _EngineTask(QRunnable):
    """Runs one callable off the GUI thread, translating its outcome
    into _WorkerSignals emissions.

    Exceptions are caught here at the thread boundary -- the one
    legitimate bare `except Exception`, since this is where Python's
    call stack meets Qt's thread marshalling and nothing further up
    the pool-thread stack can handle it. OperationCancelled routes to
    its own `cancelled` signal, not `failed`.
    """

    def __init__(
        self,
        task_id: str,
        fn: Callable[..., Any],
        signals: _WorkerSignals,
        token: CancellationToken,
        *,
        progress_enabled: bool,
    ) -> None:
        super().__init__()
        self._task_id = task_id
        self._fn = fn
        self._signals = signals
        self._token = token
        self._progress_enabled = progress_enabled

    def run(self) -> None:
        self._signals.started.emit(self._task_id)
        try:
            result = (
                self._fn(progress=self._on_progress)
                if self._progress_enabled
                else self._fn()
            )
        except OperationCancelled:
            self._signals.cancelled.emit(self._task_id)
        except Exception as exc:
            self._signals.failed.emit(self._task_id, str(exc), traceback.format_exc())
        else:
            self._signals.finished.emit(self._task_id, result)

    def _on_progress(self, event: ProgressEvent) -> None:
        # Raises OperationCancelled if this task's token has been
        # cancelled; propagates straight out of the caller's fn, past
        # this method, to the except OperationCancelled above.
        self._token.raise_if_cancelled()
        self._signals.event.emit(self._task_id, event)
        self._signals.progress.emit(self._task_id, event.percent)


class TaskRunner(QObject):
    """
    Owns a private QThreadPool(max_threads=1) -- deliberately not
    QThreadPool.globalInstance() -- so runs are serialised (two
    concurrent triggers can't race on the same output directory) and
    waitForDone() is deterministic for shutdown.
    """

    taskStarted = Signal(str)
    taskProgress = Signal(str, int)
    taskEvent = Signal(str, object)
    taskLog = Signal(str, str)
    taskFinished = Signal(str, object)
    taskFailed = Signal(str, str, str)
    taskCancelled = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._tokens: dict[str, CancellationToken] = {}

    def submit(self, fn: Callable[[], Any]) -> str:
        """Submit a plain callable that takes no arguments -- e.g.
        Engine.validate, Engine.preview_frame -- neither of which
        accepts a progress= kwarg."""
        return self._submit(fn, progress_enabled=False)

    def submit_with_progress(self, fn: Callable[..., Any]) -> str:
        """Submit a callable that accepts progress=<ProgressCallback>,
        e.g. a functools.partial(engine.run, out_dir, exporters=...).
        Explicit rather than magic-detected: mixing the two call shapes
        silently would be a subtle bug, not a convenience."""
        return self._submit(fn, progress_enabled=True)

    def _submit(self, fn: Callable[..., Any], *, progress_enabled: bool) -> str:
        task_id = uuid.uuid4().hex
        token = CancellationToken()
        self._tokens[task_id] = token

        signals = _WorkerSignals()
        signals.started.connect(self.taskStarted)
        signals.event.connect(self.taskEvent)
        signals.progress.connect(self.taskProgress)
        signals.log.connect(self.taskLog)
        signals.finished.connect(self.taskFinished)
        signals.failed.connect(self.taskFailed)
        signals.cancelled.connect(self.taskCancelled)
        # Drop the token once the task reaches a terminal state, so
        # cancel()/cancel_all() never accumulate entries for tasks that
        # have already finished/failed/been cancelled.
        forget = self._forget(task_id)
        signals.finished.connect(forget)
        signals.failed.connect(forget)
        signals.cancelled.connect(forget)

        task = _EngineTask(task_id, fn, signals, token, progress_enabled=progress_enabled)
        self._pool.start(task)
        return task_id

    def _forget(self, task_id: str) -> Callable[..., None]:
        def _cleanup(*_args: object) -> None:
            self._tokens.pop(task_id, None)
        return _cleanup

    def cancel(self, task_id: str) -> None:
        """Request cancellation of one in-flight task. Cooperative: the
        task only actually stops the next time its callable checks in
        via a progress() call."""
        token = self._tokens.get(task_id)
        if token is not None:
            token.cancel()

    def cancel_all(self) -> None:
        """Request cancellation of every currently in-flight task."""
        for token in list(self._tokens.values()):
            token.cancel()

    def shutdown(self, msecs: int = 5000) -> bool:
        """
        Cancel every in-flight task, then wait up to *msecs* for the
        pool to drain. Returns True if it drained within the timeout.

        Call this before tearing down anything a running task's
        signals might emit into -- e.g. in MainWindow.closeEvent --
        before accepting the close. A pool thread emitting into an
        already-destroyed widget tree is a hard crash with no Python
        traceback.
        """
        self.cancel_all()
        return self._pool.waitForDone(msecs)
