"""
Reader registry and discovery.

Built-in readers are registered here.  External readers register via the
'track2data.readers' entry point in their own pyproject.toml.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from track2data.core.errors import ImportError_
from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.deeplabcut import DeepLabCutReader
from track2data.readers.idtrackerai.reader import IDTrackerAiReader
from track2data.readers.idtrackerai_v4 import looks_like_v4
from track2data.readers.idtrackerai_v5 import IDTrackerAiV5Reader
from track2data.readers.params import resolve_options

log = logging.getLogger(__name__)

_REGISTRY: list[type[SessionReader]] = []


def register(reader_cls: type[SessionReader]) -> None:
    if reader_cls not in _REGISTRY:
        _REGISTRY.append(reader_cls)
        _REGISTRY.sort(key=lambda r: r.priority, reverse=True)


def _load_entry_points() -> None:
    try:
        eps = importlib.metadata.entry_points(group="track2data.readers")
        for ep in eps:
            try:
                cls = ep.load()
                register(cls)
            except Exception as exc:
                log.warning("Failed to load reader entry point %s: %s", ep.name, exc)
    except Exception as exc:
        log.debug("Entry-point discovery failed: %s", exc)


# Register built-ins — the unified reader has the highest priority (20) so it
# wins over the legacy v5 reader (10) when a folder is detected by both. The v4
# placeholder is deliberately not registered: its detect() is always False, so it
# could never be selected, and a registered class that only raises is worse than
# an absent one (DECISIONS D-012). Its module only supplies ``looks_like_v4``.
register(IDTrackerAiReader)
register(IDTrackerAiV5Reader)
register(DeepLabCutReader)
_load_entry_points()


def detect_reader(folder: Path) -> type[SessionReader] | None:
    """Return the highest-priority reader that detects *folder*, or None."""
    for cls in _REGISTRY:
        try:
            if cls.detect(folder):
                return cls
        except Exception as exc:
            log.debug("Reader %s raised during detect: %s", cls.name, exc)
    return None


def find_reader(name: str) -> type[SessionReader] | None:
    """Return the registered reader called *name*, or None.

    For callers that only want to describe a reader (its display name, whether it was verified).
    Use :func:`get_reader` when a missing reader is an error.
    """
    for cls in _REGISTRY:
        if cls.name == name:
            return cls
    return None


def get_reader(name: str) -> type[SessionReader]:
    """Return the registered reader called *name*."""
    cls = find_reader(name)
    if cls is not None:
        return cls
    raise ImportError_(
        f"No reader named {name!r} is registered",
        code="READER_UNKNOWN",
        subject=name,
        remediation="Check the spelling (the registered names are listed by "
        "`track2data list-readers`) or install the plug-in that provides it.",
    )


def reader_names() -> list[str]:
    """Registered reader names, highest priority first."""
    return [cls.name for cls in _REGISTRY]


def _reader_kwargs(
    cls: type[SessionReader], *, allow_pickle: bool, options: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The keywords ``cls`` declares it takes, and only those.

    This is what keeps the contract additive: a reader written against the original
    one-argument ``read(folder)`` never sees ``allow_pickle`` or ``options``.
    """
    kwargs: dict[str, Any] = {}
    if cls.accepts_allow_pickle:
        kwargs["allow_pickle"] = allow_pickle
    # Also rejects options given to a reader that declares none.
    resolved = resolve_options(cls.name, cls.parameters, options)
    if cls.parameters:
        kwargs["options"] = resolved
    return kwargs


def _call_read(
    cls: type[SessionReader],
    path: Path,
    *,
    allow_pickle: bool,
    options: Mapping[str, Any] | None,
) -> Session:
    """Call ``cls().read(path)``, passing each keyword only to readers that declare it."""
    return cls().read(path, **_reader_kwargs(cls, allow_pickle=allow_pickle, options=options))


def _call_probe(
    cls: type[SessionReader],
    path: Path,
    *,
    allow_pickle: bool,
    options: Mapping[str, Any] | None,
) -> Session:
    """Call ``cls().probe(path)`` with exactly the keywords ``read`` would get."""
    return cls().probe(path, **_reader_kwargs(cls, allow_pickle=allow_pickle, options=options))


def _require_reader(folder: Path) -> type[SessionReader]:
    """The reader for *folder*, or a specific ``ImportError_`` explaining why none."""
    cls = detect_reader(folder)
    if cls is not None:
        return cls
    if looks_like_v4(folder):
        raise ImportError_(
            f"This looks like idtracker.ai v4 output, which Track2Data cannot read yet: {folder}",
            code="V4_NOT_SUPPORTED",
            subject=str(folder),
            remediation=(
                "Only idtracker.ai v5 output is supported. To help add v4, follow "
                "docs/IDTRACKERAI_V4_SAMPLES.md (IDTRACKERAI_V4_SAMPLES)."
            ),
        )
    raise ImportError_(
        f"No reader recognised the session folder: {folder}",
        code="NO_READER",
        subject=str(folder),
        remediation="Ensure the folder is a valid idtracker.ai output directory.",
    )


def _choose(folder: Path, reader: str | None) -> type[SessionReader]:
    """The reader named *reader*, else the one that detects *folder*; an error if neither."""
    return get_reader(reader) if reader is not None else _require_reader(folder)


def read_session(
    folder: Path,
    *,
    allow_pickle: bool = False,
    reader: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> Session:
    """Return a Session for *folder*, auto-detecting the reader unless one is named.

    ``reader`` names a registered reader and skips detection, which is how a confirmed
    choice is replayed. ``options`` are that reader's declared parameters (frame rate,
    keypoint, ...); a required one that is missing is an error, never a default.

    ``allow_pickle`` permits trajectory formats whose deserialisation executes code from
    the file (idtracker.ai's ``trajectories.npy``). Defaults to False.

    ``allow_pickle`` and ``options`` are forwarded only to readers that declare them
    (``accepts_allow_pickle``, ``parameters``). External readers written against the
    original one-argument ``read(folder)`` signature therefore keep working -- but they
    also never see the flag, so a third-party reader that unpickles is trusting whatever
    it is pointed at, and should opt in.
    """
    return _call_read(
        _choose(folder, reader), folder, allow_pickle=allow_pickle, options=options
    )


def probe_session(
    folder: Path,
    *,
    allow_pickle: bool = False,
    reader: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> Session:
    """Like ``read_session`` but via ``SessionReader.probe`` -- the cheap path
    the GUI uses to describe a folder without loading every artefact.

    ``allow_pickle``, ``reader`` and ``options`` mean what they mean for ``read_session``:
    a probe opens the same trajectory file, so it needs the project's consent, and a session
    whose reader was chosen is probed by that reader with its saved options.
    """
    return _call_probe(
        _choose(folder, reader), folder, allow_pickle=allow_pickle, options=options
    )


__all__ = [
    "IDTrackerAiReader",
    "IDTrackerAiV5Reader",
    "SessionReader",
    "detect_reader",
    "find_reader",
    "get_reader",
    "probe_session",
    "read_session",
    "reader_names",
    "register",
]
