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
    # Static imports, one per module, so PyInstaller's import analysis can
    # follow them (a loop over ``__import__(name)`` is invisible to it and
    # the frozen app would ship without these exporters).
    with contextlib.suppress(ImportError):
        import track2data.exporters.csv_long as _csv_long  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.exporters.csv_wide as _csv_wide  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.exporters.excel as _excel  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.exporters.feather as _feather  # noqa: F401
    with contextlib.suppress(ImportError):
        import track2data.exporters.readme as _readme  # noqa: F401
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
