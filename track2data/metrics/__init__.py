"""
Metric registry and built-in metric catalogue.

Built-in metrics are registered at import time.  External metrics use the
``track2data.metrics`` entry point (see ENGINE_DESIGN.md §8.5 and §11).

Usage::

    from track2data.metrics import registry
    all_group = registry.list_for_level("group")
    il2_cls = registry.get("IL-2")
"""

from __future__ import annotations

import contextlib

from track2data.metrics.base import Metric

# ── Registry ──────────────────────────────────────────────────────────────────

_registry: dict[str, type[Metric]] = {}


def register(metric_cls: type[Metric]) -> None:
    """Register a Metric class by its ``id`` attribute."""
    _registry[metric_cls.id] = metric_cls


def get(metric_id: str) -> type[Metric] | None:
    """Return the Metric class for *metric_id*, or None if not registered."""
    return _registry.get(metric_id)


def list_for_level(
    level: str,
) -> list[type[Metric]]:
    """Return all registered metrics for *level* (individual/group/zone/diagnostic)."""
    return [m for m in _registry.values() if m.level == level]


def _natural_sort_key(metric_id: str) -> tuple[str, int]:
    """Sort metric IDs naturally: GL-1, GL-2, GL-10 (not GL-1, GL-10, GL-2)."""
    prefix, _, number = metric_id.rpartition("-")
    return (prefix, int(number))


def all_ids() -> list[str]:
    """Return sorted list of all registered metric IDs."""
    return sorted(_registry.keys(), key=_natural_sort_key)


# ── Load built-in metrics ──────────────────────────────────────────────────────
# Each sub-module calls register() at import time.  We import lazily so that
# missing optional deps (scipy, shapely) don't break basic model imports.

def _load_builtins() -> None:
    with contextlib.suppress(ImportError):
        import track2data.metrics.diagnostic as _d  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.metrics.individual as _i  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.metrics.group as _g  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.metrics.zone as _z  # noqa: F401
    # Load external entry-point metrics.
    try:
        import importlib.metadata as _meta
        for ep in _meta.entry_points(group="track2data.metrics"):
            with contextlib.suppress(Exception):
                cls = ep.load()
                register(cls)
    except Exception:
        pass


_load_builtins()
