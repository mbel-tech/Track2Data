"""
Exporter registry and built-in exporters.

Usage::

    from track2data.exporters import get_exporter, list_exporters
    exp = get_exporter("csv_long")
    paths = exp.write(payload, out_dir)
"""

from __future__ import annotations

import contextlib

from track2data.exporters.base import Exporter

_registry: dict[str, type[Exporter]] = {}


def register(exporter_cls: type[Exporter]) -> None:
    """Register an Exporter class by its ``name`` attribute."""
    _registry[exporter_cls.name] = exporter_cls


def get_exporter(name: str) -> Exporter | None:
    """Return an instantiated Exporter for *name*, or None."""
    cls = _registry.get(name)
    return cls() if cls is not None else None


def list_exporters() -> list[str]:
    """Return sorted list of registered exporter names."""
    return sorted(_registry.keys())


def _load_builtins() -> None:
    for mod in (
        "track2data.exporters.csv_long",
        "track2data.exporters.csv_wide",
        "track2data.exporters.excel",
        "track2data.exporters.feather",
        "track2data.exporters.readme",
    ):
        with contextlib.suppress(ImportError):
            __import__(mod)
    # External entry-point exporters.
    try:
        import importlib.metadata as _meta
        for ep in _meta.entry_points(group="track2data.exporters"):
            with contextlib.suppress(Exception):
                cls = ep.load()
                register(cls)
    except Exception:
        pass


_load_builtins()
