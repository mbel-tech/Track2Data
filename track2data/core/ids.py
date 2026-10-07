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


def uniquify(ids: Sequence[str], taken: Collection[str] = ()) -> list[str]:
    """Return *ids* with later duplicates suffixed ``__2``, ``__3``, ... in order.

    The first holder of a name keeps it; names in *taken* are already used elsewhere.
    A generated suffix never collides with a name that is present in *ids* or *taken*.
    """
    used = set(taken)
    reserved = set(ids)
    out: list[str] = []
    counts: dict[str, int] = {}
    for item in ids:
        if item not in used:
            used.add(item)
            out.append(item)
            continue
        n = counts.get(item, 1)
        while True:
            n += 1
            candidate = f"{item}__{n}"
            if candidate not in used and candidate not in reserved:
                break
        counts[item] = n
        used.add(candidate)
        out.append(candidate)
    return out
