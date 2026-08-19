"""Verify track2data.readers entry points are registered and loadable."""

from __future__ import annotations

import importlib.metadata


def _reader_names() -> set[str]:
    return {ep.name for ep in importlib.metadata.entry_points(group="track2data.readers")}


def test_unified_reader_registered() -> None:
    assert "idtrackerai" in _reader_names(), (
        f"Unified 'idtrackerai' entry point missing; registered: {_reader_names()}"
    )


def test_legacy_readers_registered() -> None:
    names = _reader_names()
    assert "idtrackerai_v5" in names, f"idtrackerai_v5 missing; registered: {names}"
    assert "idtrackerai_v4" in names, f"idtrackerai_v4 missing; registered: {names}"


def test_unified_reader_loadable() -> None:
    eps = importlib.metadata.entry_points(group="track2data.readers")
    unified = next(ep for ep in eps if ep.name == "idtrackerai")
    cls = unified.load()
    assert hasattr(cls, "name"), "IDTrackerAiReader must have a 'name' class attribute"
    assert hasattr(cls, "priority"), "IDTrackerAiReader must have a 'priority' class attribute"
    assert cls.priority >= 20, f"Unified reader priority must be ≥ 20; got {cls.priority}"


def test_legacy_readers_loadable() -> None:
    eps = {ep.name: ep for ep in importlib.metadata.entry_points(group="track2data.readers")}
    for name in ("idtrackerai_v5", "idtrackerai_v4"):
        cls = eps[name].load()
        assert hasattr(cls, "priority"), f"{name} missing 'priority' attribute"
