"""
Engine-side progress reporting and cancellation contract.

Stdlib-only (dataclasses, threading, typing) so the engine stays
PySide6-free (D-001 in DECISIONS.md) -- the UI layer adapts
ProgressEvent/ProgressCallback to Qt signals on its own side. This
module must never import anything from PySide6, app/, or ui/.

Engine methods accept a single keyword-only ``progress: ProgressCallback
| None`` parameter and call ``emit(progress, event)`` at stage
boundaries only -- never per-frame, which would queue tens of thousands
of events and freeze a Qt-backed UI worse than running synchronously.

Cancellation is callback-driven, not a separate parameter: whoever
constructs the ``ProgressCallback`` (e.g. the UI's TaskRunner) can hold
a ``CancellationToken`` and raise ``OperationCancelled`` from inside the
callback when it's been cancelled. Engine code must never catch
``OperationCancelled`` itself -- only let it propagate -- or a
cancellation request would be silently swallowed instead of stopping
the run.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from track2data.core.errors import Track2DataError

Stage = Literal["import", "preprocess", "metrics", "export", "session", "run"]


@dataclass(frozen=True)
class ProgressEvent:
    """One progress checkpoint. Immutable -- safe to hand across threads."""

    stage: Stage
    current: int
    total: int
    session_id: str | None = None
    message: str = ""

    @property
    def percent(self) -> int:
        """0-100, clamped. 0 when total <= 0 (avoids division by zero)."""
        if self.total <= 0:
            return 0
        pct = round(100 * self.current / self.total)
        return max(0, min(100, pct))


ProgressCallback = Callable[[ProgressEvent], None]


class OperationCancelled(Track2DataError):
    """Raised by a ProgressCallback to abort a run in progress.

    Engine code must never catch this -- only let it propagate -- so a
    user's cancellation request stops the run instead of being treated
    as just another failure to log and skip.
    """

    def __init__(self, message: str = "Operation cancelled by user.") -> None:
        super().__init__(message, code="CANCELLED", severity="info")


class CancellationToken:
    """Thin wrapper over threading.Event for cooperative cancellation."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled()


def emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    """Call *callback* with *event* if not None.

    Never swallows an exception raised by the callback -- in particular
    OperationCancelled must propagate to the caller so cancellation
    actually stops the run rather than being silently absorbed here.
    """
    if callback is not None:
        callback(event)
