"""ProcessPoolExecutor wrapper with worker-cap policy."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

T = TypeVar("T")

_MAX_WORKERS = 8


def worker_count(user_setting: int | None = None) -> int:
    cpu = os.cpu_count() or 1
    cap = min(cpu - 1, _MAX_WORKERS)
    if user_setting is not None:
        cap = min(user_setting, cap)
    return max(cap, 1)


def map_sessions(
    fn: Callable[..., T],
    items: Iterable,
    n_workers: int = 1,
) -> list[T]:
    """Apply *fn* to each item, optionally in parallel."""
    items = list(items)
    if n_workers <= 1:
        return [fn(item) for item in items]
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        return list(pool.map(fn, items))
