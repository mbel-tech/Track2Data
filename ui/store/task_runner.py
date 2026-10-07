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

import time
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
        cancel_check_enabled: bool = False,
    ) -> None:
        super().__init__()
        self._cancel_check_enabled = cancel_check_enabled
        self._task_id = task_id
        self._fn = fn
        self._signals = signals
        self._token = token
        self._progress_enabled = progress_enabled

    def run(self) -> None:
        if self._token.is_cancelled:
            # Cancelled while still queued (shutdown, new project): never start.
            self._signals.cancelled.emit(self._task_id)
            return
        self._signals.started.emit(self._task_id)
        try:
            if self._progress_enabled:
                kwargs: dict[str, Any] = {"progress": self._on_progress}
                if self._cancel_check_enabled:
                    # Lets the engine notice Cancel between preprocessing
                    # steps and metrics, not only at stage-boundary events.
                    kwargs["cancel_check"] = self._token.raise_if_cancelled
                result = self._fn(**kwargs)
            else:
                result = self._fn()
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


#: Task lanes. "run": pipeline runs, exports, previews -- serialised so two
#: triggers can't race on one output directory. "probe": cheap session reads
#: made when a folder is added, kept off the run lane so they are never queued
#: behind a long run, and silent on the generic task signals (see below).
LANES = ("run", "probe")


class TaskRunner(QObject):
    """
    Owns one private QThreadPool(max_threads=1) per lane -- deliberately not
    QThreadPool.globalInstance() -- so tasks within a lane are serialised and
    waitForDone() is deterministic for shutdown.

    Run-lane tasks report on taskStarted/Progress/Event/Log/Finished/Failed/
    Cancelled, which the main window uses to drive its Cancel button and
    failure dialog. Probe-lane tasks report only on probeFinished/
    probeFailed/probeCancelled, so a session probe can neither flash Cancel
    nor pop a "pipeline run failed" dialog.
    """

    taskStarted = Signal(str)
    taskProgress = Signal(str, int)
    taskEvent = Signal(str, object)
    taskLog = Signal(str, str)
    taskFinished = Signal(str, object)
    taskFailed = Signal(str, str, str)
    taskCancelled = Signal(str)
    probeFinished = Signal(str, object)
    probeFailed = Signal(str, str, str)
    probeCancelled = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pools: dict[str, QThreadPool] = {}
        for lane in LANES:
            pool = QThreadPool()
            pool.setMaxThreadCount(1)
            self._pools[lane] = pool
        self._lane_of: dict[str, str] = {}
        self._tokens: dict[str, CancellationToken] = {}
        # Explicit strong references to each in-flight task's _WorkerSignals
        # and _EngineTask, keyed by task_id. Both are local variables inside
        # _submit() otherwise -- once that method returns, nothing but Qt's
        # C++-side bookkeeping would keep them alive, and under load that
        # can race with Python's GC: a pool thread emitting a signal into
        # (or QThreadPool auto-deleting) a Python wrapper object that's
        # concurrently being collected is a real access-violation crash,
        # reproduced during this module's own test development. Cleared
        # only once a task reaches a terminal state (see _forget).
        self._active: dict[str, tuple[_WorkerSignals, _EngineTask]] = {}

    def submit(self, fn: Callable[[], Any], *, lane: str = "run") -> str:
        """Submit a plain callable that takes no arguments -- e.g.
        Engine.validate, Engine.preview_frame -- neither of which
        accepts a progress= kwarg."""
        return self._submit(fn, progress_enabled=False, lane=lane)

    def submit_with_progress(
        self, fn: Callable[..., Any], *, cancel_check: bool = False
    ) -> str:
        """Submit a callable that accepts progress=<ProgressCallback>,
        e.g. a functools.partial(engine.run, out_dir, exporters=...).
        With ``cancel_check=True`` the callable must also accept
        ``cancel_check=<Callable[[], None]>`` (as ``Engine.run`` does).
        Explicit rather than magic-detected: mixing the call shapes
        silently would be a subtle bug, not a convenience."""
        return self._submit(fn, progress_enabled=True, cancel_check_enabled=cancel_check)

    def _submit(
        self,
        fn: Callable[..., Any],
        *,
        progress_enabled: bool,
        cancel_check_enabled: bool = False,
        lane: str = "run",
    ) -> str:
        if lane not in self._pools:
            raise ValueError(f"unknown lane {lane!r}; expected one of {LANES}")
        task_id = uuid.uuid4().hex
        token = CancellationToken()
        self._tokens[task_id] = token
        self._lane_of[task_id] = lane

        signals = _WorkerSignals()
        if lane == "probe":
            signals.finished.connect(self.probeFinished)
            signals.failed.connect(self.probeFailed)
            signals.cancelled.connect(self.probeCancelled)
        else:
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

        task = _EngineTask(
            task_id,
            fn,
            signals,
            token,
            progress_enabled=progress_enabled,
            cancel_check_enabled=cancel_check_enabled,
        )
        # Qt's C++ side would otherwise auto-delete the QRunnable itself
        # once run() returns; Python's own reference in self._active is
        # now the sole owner of its lifetime, cleared only in _forget.
        task.setAutoDelete(False)
        self._active[task_id] = (signals, task)
        self._pools[lane].start(task)
        return task_id

    def _forget(self, task_id: str) -> Callable[..., None]:
        def _cleanup(*_args: object) -> None:
            self._tokens.pop(task_id, None)
            self._active.pop(task_id, None)
            self._lane_of.pop(task_id, None)
        return _cleanup

    def cancel(self, task_id: str) -> None:
        """Request cancellation of one in-flight task. Cooperative: the
        task only actually stops the next time its callable checks in
        via a progress() call."""
        token = self._tokens.get(task_id)
        if token is not None:
            token.cancel()

    def cancel_all(self, lane: str | None = None) -> None:
        """Request cancellation of every in-flight task, or of those in one
        *lane* (the toolbar Cancel passes ``"run"`` so it never touches probes)."""
        for task_id, token in list(self._tokens.items()):
            if lane is None or self._lane_of.get(task_id) == lane:
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
        deadline = time.monotonic() + msecs / 1000
        drained = True
        for pool in self._pools.values():
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            drained = pool.waitForDone(remaining) and drained
        return drained
