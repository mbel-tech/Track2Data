"""When two project entries are the same part of the same recording.

One rule shared by the import dialog (``ConfirmDraft``) and the project store, so the dialog never
offers what the store would refuse, nor leaves out what the store would accept.
"""

from __future__ import annotations

from pathlib import Path

from track2data.core.models import SessionRef


def resolved(path: Path) -> Path:
    """*path* made absolute when the file system allows it, as given otherwise."""
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def session_selector(ref: SessionRef) -> tuple[tuple[str, str], ...]:
    """The options that pick *which* session in a file (an arena), not how to read it."""
    # Imported here: ``track2data.readers`` imports ``track2data.core``.
    from track2data.readers import find_reader

    reader = find_reader(ref.reader) if ref.reader else None
    names = {p.name for p in reader.parameters if p.scope == "session"} if reader else set()
    return tuple(sorted((k, repr(v)) for k, v in ref.reader_options.items() if k in names))


def same_session_part(candidate: SessionRef, existing: SessionRef) -> bool:
    """Whether *candidate* is a session the project already holds as *existing*.

    The same place, read by the same reader, picking the same arena, and covering the same part
    of the video. The rule is deliberately not symmetric: a legacy *existing* entry with no saved
    reader counts as any reader, but a *candidate* with no reader matches only an existing entry
    with the same reader or none.

    The same folder under another reader is a different session (another reader could read the
    same files into different numbers). So is the same folder with another panel: it is another
    part of the video, which is why a folder that was split into panels is offered again as a
    whole-frame session when rescanned.
    """
    return (
        resolved(candidate.folder) == resolved(existing.folder)
        and (existing.reader is None or existing.reader == candidate.reader)
        and session_selector(candidate) == session_selector(existing)
        and existing.panel == candidate.panel
    )
