"""Session ids: the single place that decides what a session is called.

An id becomes a directory name (``out_dir/<session_id>/``), a key in the metadata join and a
column in every export, so it must be stable, unique and safe on Windows. Before this module
three places derived it independently (``project_store``, ``Normaliser``, the v5 reader) and
the engine relied on them agreeing.

Directories keep their name verbatim: existing projects already joined metadata on that string.
Anything derived (a file stem, an arena of a file) is sanitised.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Sequence
from pathlib import Path

_HOSTILE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}
_FALLBACK = "session"


def sanitise_session_id(raw: str, *, max_len: int = 120) -> str:
    """Make *raw* safe as a Windows file name. Never empty, idempotent."""
    text = unicodedata.normalize("NFC", raw)
    text = _HOSTILE.sub("_", text).rstrip(" .")[:max_len].rstrip(" .")
    if not text:
        return _FALLBACK
    if text.split(".")[0].upper() in _RESERVED:
        text = f"{text}_"
    return text


def default_session_id(path: Path, *, is_file: bool | None = None) -> str:
    """The id a session gets when nothing else names it.

    An existing file is named after its stem, sanitised. Anything else keeps its name
    verbatim, whether a directory or a path that is not on disk: that has always been the id,
    and tests and probes build sessions for folders that do not exist.

    ``is_file`` overrides the file-system check for callers that already know.
    """
    path = Path(path)
    if is_file is None:
        is_file = path.is_file()
    return sanitise_session_id(path.stem) if is_file else path.name


#: The run-root folder that stacks every session's tables (``exporters/pooled.py``); a
#: session of this name would write into it.
RESERVED_SESSION_IDS = ("all_sessions",)


def session_id_key(session_id: str) -> str:
    """The form under which two ids name the same output folder on Windows.

    Windows compares file names case-insensitively and drops trailing dots and spaces, so
    ``Trial1``, ``trial1`` and ``trial1.`` are one folder there.
    """
    return unicodedata.normalize("NFC", session_id).rstrip(" .").casefold()


def session_id_problems(ids: Sequence[str]) -> list[str]:
    """One sentence per id that collides with an earlier one or takes a reserved name."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    reserved = {session_id_key(r): r for r in RESERVED_SESSION_IDS}
    for sid in ids:
        key = session_id_key(sid)
        if key in reserved:
            problems.append(
                f"Session id {sid!r} is reserved: {reserved[key]!r} is the folder that "
                "stacks every session's tables. Rename the session."
            )
        elif key in seen:
            problems.append(
                f"Session ids {seen[key]!r} and {sid!r} collide: they name the same output "
                "folder on Windows (case, trailing dots and spaces are ignored there). Rename one."
            )
        else:
            seen[key] = sid
    return problems


def uniquify(ids: Sequence[str], taken: Collection[str] = ()) -> list[str]:
    """Return *ids* with later duplicates suffixed ``__2``, ``__3``, ... in order.

    The first holder of a name keeps it; names in *taken* are already used elsewhere, and the
    reserved names (:data:`RESERVED_SESSION_IDS`) are always taken. Names are compared the way
    Windows compares folder names (:func:`session_id_key`). A generated suffix never collides
    with a name that is present in *ids* or *taken*.
    """
    used = {session_id_key(t) for t in (*taken, *RESERVED_SESSION_IDS)}
    reserved = {session_id_key(i) for i in ids}
    out: list[str] = []
    counts: dict[str, int] = {}
    for item in ids:
        key = session_id_key(item)
        if key not in used:
            used.add(key)
            out.append(item)
            continue
        n = counts.get(key, 1)
        while True:
            n += 1
            candidate = f"{item}__{n}"
            ckey = session_id_key(candidate)
            if ckey not in used and ckey not in reserved:
                break
        counts[key] = n
        used.add(ckey)
        out.append(candidate)
    return out
