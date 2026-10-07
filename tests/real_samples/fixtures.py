"""Fixture download, verification and session-folder helpers for the real-sample suite.

Fixtures are not stored in the repository. They are downloaded on first use from the URLs in
``fixtures_manifest.json``, verified against a pinned SHA-256, and cached outside the worktree
(this tree is OneDrive-synced, and ``.gitignore`` does not stop OneDrive uploading 70 MB).

Environment variables
---------------------
T2D_FIXTURE_DIR          cache directory. Default: ``%LOCALAPPDATA%\\track2data\\fixture_cache``
                         on Windows, ``$XDG_CACHE_HOME/track2data/fixture_cache`` elsewhere.
T2D_FIXTURES_OFFLINE=1   never touch the network; skip tests whose fixture is not cached.
T2D_REAL_SAMPLES=1       run the suite without naming one of its markers in ``-m``.
T2D_REFERENCE_READERS=1  register the test-only reference readers (reference_readers.py);
                         leave unset when testing your own readers.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
#: Options recorded per resolved session folder by ``provide_video_info``.
_OPTIONS: dict[Path, dict[str, Any]] = {}
MANIFEST = json.loads((HERE / "fixtures_manifest.json").read_text(encoding="utf8"))["files"]
OFFLINE = os.environ.get("T2D_FIXTURES_OFFLINE") == "1"


def default_cache_dir() -> Path:
    """Where fixtures are cached: never inside the (synced) worktree by default."""
    override = os.environ.get("T2D_FIXTURE_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "track2data" / "fixture_cache"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "track2data" / "fixture_cache"


CACHE = default_cache_dir()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(name: str) -> Path:
    """Return the cached, hash-verified path of fixture *name* (its upstream basename)."""
    if name not in MANIFEST:
        raise KeyError(f"{name} is not in fixtures_manifest.json")
    entry = MANIFEST[name]
    path = CACHE / name
    if not path.exists():
        if OFFLINE:
            pytest.skip(f"fixture {name} not cached and T2D_FIXTURES_OFFLINE=1")
        CACHE.mkdir(parents=True, exist_ok=True)
        try:
            request = urllib.request.Request(
                entry["url"], headers={"User-Agent": "t2d-reader-fixture-tests"}
            )
            data = urllib.request.urlopen(request, timeout=120).read()
        except Exception as exc:  # a network failure is not a test failure
            pytest.skip(f"cannot download {name}: {exc}")
        path.write_bytes(data)
    digest = _sha256(path)
    assert digest == entry["sha256"], (
        f"{name}: sha256 {digest[:12]}... != pinned {entry['sha256'][:12]}... "
        "(upstream file changed or cache is corrupt)"
    )
    return path


def build_folder(root: Path, names: list[str], unzip: str | None = None) -> Path:
    """Copy fixtures into a fresh folder, as a tracker would have written them."""
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(fetch(name), root / name)
    if unzip:
        with zipfile.ZipFile(root / unzip) as archive:
            for member in archive.namelist():
                if member.endswith(".npz"):
                    (root / Path(member).name).write_bytes(archive.read(member))
        (root / unzip).unlink()
    return root


def provide_video_info(folder: Path, info: dict) -> None:
    """THE one place that supplies metadata a format does not record.

    ``Session.video`` requires fps, width_px and height_px, but most tracker outputs record none
    or only some of them. The mechanism is a reader *option* (collected in the confirm dialog,
    saved on the SessionRef, passed to ``read``). Writing a sidecar into the input folder is
    rejected: readers must not modify it (FR-IMP-5).

    The values are recorded as options for ``read_with_options``. While the scaffolding readers
    in ``reference_readers.py`` still exist, a sidecar is also written for them (they predate
    options); it disappears with the last of them.
    """
    _OPTIONS[Path(folder).resolve()] = dict(info)
    (folder / "video_info.json").write_text(json.dumps(info))


def options_for(folder: Path) -> dict[str, Any] | None:
    """The options recorded for *folder* by ``provide_video_info``, if any."""
    return _OPTIONS.get(Path(folder).resolve())


def copy_options(src: Path, dst: Path) -> None:
    """Carry the recorded options over to a copy of a session folder.

    The damaged-file tests read a copy; without its options a reader that needs fps would stop
    at READER_OPTION_MISSING and never open the damaged file.
    """
    options = options_for(src)
    if options is not None:
        _OPTIONS[Path(dst).resolve()] = dict(options)


def read_with_options(cls: Any, folder: Path) -> Any:
    """Read *folder* with reader class *cls*, handing it the recorded options.

    Options go only to readers that declare parameters. Readers that do not (the scaffolding
    readers read a sidecar instead) are called exactly as the original contract says.
    """
    from track2data import readers

    return readers._call_read(
        cls,
        folder,
        allow_pickle=False,
        options=options_for(folder) if cls.parameters else None,
    )
