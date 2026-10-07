# Tier 0 Implementation Plan: scan, detect, confirm, persist

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user point Track2Data at a folder of tracker output, have the software detect which tracker wrote it, confirm or amend the choice in the UI, and have that reader used from then on. This tier builds the foundation and ships it for idtracker.ai (including folder-of-folders); the other trackers plug into it in Tiers 1 to 4.

**Architecture:** One read-only directory walk builds an immutable `ScanIndex`. Each registered reader's `discover` turns it into ranked `Detection`s. A Qt-free `ConfirmDraft` holds the user's choices, a thin modal dialog edits it, and the confirmed reader and options are saved on each `SessionRef` so the engine never re-detects. All new reader-contract features are additive, so existing and third-party readers keep working.

**Tech Stack:** Python 3.11+, pydantic v2, numpy, h5py, scipy, click, PySide6 (UI only), pytest, hypothesis, ruff, mypy. Run everything with `py -3.14 -m …`.

**Design:** [`2026-10-07-tracker-import-design.md`](2026-10-07-tracker-import-design.md). **Base:** pp3 (`2017cc8`), reconciled with `origin/main` after PR #100 (see *Integration with PR #100* below).

**Status of this plan.** Tasks for T0-1 to T0-3 are written to code level because they are implemented next. T0-4 to T0-9 give files, interfaces, tests and acceptance, and are expanded to code level in the PR that implements them, so the plan never describes code that the earlier PRs have already changed. Where merged code and this plan differ, the merged code is authoritative.

**Conventions for every task.** Strict TDD: failing test, see it fail for the stated reason, minimal code, see it pass, commit. Commit messages follow Conventional Commits and end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Before each commit run `py -3.14 -m ruff check .` and `py -3.14 -m mypy`. Never `pip install -e .` in this worktree: it would repoint the main checkout's editable install. Run pytest from the worktree root with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` so the OneDrive-synced tree stays clean.

---

## Integration with PR #100

The plan assumed pp3 was a strict superset of `main`. It was, until PR #100 merged 16 commits into `main` the day this work started: parallel session runs, the preprocessed-session cache, `SessionReader.probe`, the trajectory viewer and other GUI work, and the SCI-01 / SCI-02 metric fixes. pp3 conflicted with it in 13 files (not counting this work). The two were reconciled on their own branch (a merge commit, all tests green, CI's engine and GUI coverage floors held), and this work was then merged onto that. Three places needed more than a textual merge:

- **`probe` and the pickle-consent gate.** A probe opens the same trajectory file a read does, so it needs the same consent, and the same saved options. `SessionReader.probe`, `IDTrackerAiReader.probe` and `readers.probe_session` now take `allow_pickle` and `options` exactly as `read` does; the default `probe` hands each on to `read` only if the reader declares it. `probe_session` takes `reader=` like `read_session`. `ProjectStore` probes a session with the reader and options it saved, never by detection.
- **The preprocessed-session cache (D-019).** Its key was the detected reader, the folder fingerprint and the configs. It is now the entry's saved reader (detected only for an entry that saved none), its options, the fingerprint and the configs, because the same folder read at 25 fps and at 50 fps is two different sessions. A cache hit takes its `Session` from the cached result (a run needs it for the summary and the input hash) and stamps the entry's id on it, so a renamed session does not get another session's name. `Engine.preprocess_ref(ref)` is the cache-aware call for anything that has an entry (the trajectory viewer, `Engine.run`); `preprocess_folder(folder)` stays for callers without one.
- **SCI-01.** The tracker's own body length is now propagated in `apply_calibration_and_zones`, so the sensitivity sweep, which calls it directly, gets it too.

Two things to remember in T0-7: probes and scans share the single-thread `TaskRunner` pool with pipeline runs (D-018 lists it as not done), so a scan should not queue behind a run; and a parallel run (`n_workers > 1`) rebuilds its engine in spawned worker processes, where only built-in and entry-point readers are registered.

---

## File structure (all of Tier 0)

| Path | Responsibility | PR |
|---|---|---|
| `tests/real_samples/` (`__init__.py`, `conftest.py`, `fixtures.py`, `oracles.py`, `reference_readers.py`, `test_format_quirks.py`, `test_reader_contract.py`, `fixtures_manifest.json`, `README.md`) | The reader fixture-test suite: independent oracles, pinned fixtures, quirk and contract tests | T0-1 |
| `track2data/core/ids.py` | The one place that decides what a session is called | T0-2 |
| `track2data/readers/params.py` | `ReaderParameter`, `ProposedValue`, `resolve_options` | T0-3 |
| `track2data/readers/detection.py` | `Confidence`, `SessionCandidate`, `Detection` | T0-3 |
| `track2data/readers/base.py`, `track2data/readers/__init__.py` | Additive contract; `get_reader`, `reader_names`, `_call_read`, named `read_session` | T0-3 |
| `track2data/readers/index.py`, `peek.py`, `scan.py` | Read-only walk, header peeks, ranking | T0-4 |
| `track2data/core/models.py`, `track2data/api.py`, `track2data/exporters/{base,readme}.py`, `track2data/metrics/diagnostic.py` | Persisted reader, engine seam, provenance, D-5 | T0-5 |
| `track2data/readers/confirm.py`, `track2data/cli.py`, `track2data/__main__.py` | Qt-free `ConfirmDraft`; `scan`, `list-readers`, `add` | T0-6 |
| `ui/store/project_store.py`, `ui/store/task_runner.py`, `app/main_window.py` | Scan task, quiet failures, priority | T0-7 |
| `ui/dialogs/confirm_format_dialog.py`, `ui/widgets/parameter_form.py`, `ui/import_screen.py`, `ui/store/session_facts.py` | The confirm dialog and Sessions-screen wiring | T0-8 |
| `.claude/skills/run-track2data/driver.py`, `track2data/readers/recognise.py` | Driver verbs; recognise-only formats | T0-9 |

---

## PR T0-1: import the reader fixture-test suite

**Branch:** `test/real-sample-suite` · **Goal:** the supplied suite lives in `tests/real_samples/`, never downloads unless asked, caches outside the OneDrive-synced worktree, and reports 42 quirk tests passing and 80 contract tests XFAIL on the pp3 base.

**Source:** `C:\Users\marti\Downloads\t2d_reader_fixture_tests.zip` (sha256 `bf5c5d16…`, nine files).

### Task 1: Extract the suite into `tests/real_samples/`

**Files:**
- Create: `tests/real_samples/__init__.py`, `fixtures_manifest.json`, `README.md`, `oracles.py`, `reference_readers.py`, `test_format_quirks.py`, `test_reader_contract.py`
- Modify: `.gitattributes`

- [ ] **Step 1: Confirm the suite is absent (RED)**

Run: `PYTHONDONTWRITEBYTECODE=1 py -3.14 -m pytest tests/real_samples --collect-only -q -p no:cacheprovider`
Expected: error `file or directory not found: tests/real_samples`.

- [ ] **Step 2: Extract the files**

```bash
cd "<worktree>"
py -3.14 - <<'PY'
import pathlib
import zipfile

z = zipfile.ZipFile(r"C:\Users\marti\Downloads\t2d_reader_fixture_tests.zip")
root = "t2d_reader_fixture_tests/"
dest = pathlib.Path("tests/real_samples")
dest.mkdir(parents=True, exist_ok=True)
(dest / "__init__.py").write_text("", encoding="utf8")
mapping = {
    "fixtures_manifest.json": "fixtures_manifest.json",
    "README.md": "README.md",
    "tests/oracles.py": "oracles.py",
    "tests/reference_readers.py": "reference_readers.py",
    "tests/test_format_quirks.py": "test_format_quirks.py",
    "tests/test_reader_contract.py": "test_reader_contract.py",
    "tests/conftest.py": "_original_conftest.py",   # split in Task 2, then deleted
}
for member, target in mapping.items():
    (dest / target).write_bytes(z.read(root + member))
print(sorted(p.name for p in dest.iterdir()))
PY
```

Expected: the printed list contains the nine names above plus `__init__.py`.

- [ ] **Step 3: Keep the manifest's bytes stable**

Append to `.gitattributes`:

```
tests/real_samples/fixtures_manifest.json -text
```

- [ ] **Step 4: Do not commit yet**

The suite does not import until Tasks 2 and 3 are done.

### Task 2: Split `conftest.py` into `fixtures.py` and a collection-aware `conftest.py`

**Files:**
- Create: `tests/real_samples/fixtures.py`, `tests/real_samples/conftest.py`
- Delete: `tests/real_samples/_original_conftest.py`

The original `conftest.py` is imported by name (`from conftest import …`), which would collide with `tests/conftest.py`, and it inserts its own directory into `sys.path`. The helpers move to an importable module; only fixtures and collection rules stay in `conftest.py`.

- [ ] **Step 1: Write `tests/real_samples/fixtures.py`**

```python
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

import pytest

HERE = Path(__file__).resolve().parent
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

    Until the first real reader replaces the scaffolding readers, this still writes the sidecar
    that ``reference_readers.py`` reads. Task 3 of PR T0-3 adds the options path.
    """
    (folder / "video_info.json").write_text(json.dumps(info))
```

- [ ] **Step 2: Write `tests/real_samples/conftest.py`**

```python
"""Collection rules and the ``fx`` fixture for the real-sample suite.

The suite downloads about 70 MB, so it is opt-in: select it with ``-m quirk``,
``-m contract`` or ``-m real_sample``, or set ``T2D_REAL_SAMPLES=1``. Every test here is also
marked ``network`` so that CI (``-m "not network"``) and the default developer run skip it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.real_samples.fixtures import fetch

HERE = Path(__file__).resolve().parent
# A marker name that is not directly negated ("not real_sample") counts as opting in.
_SUITE_MARKERS = re.compile(r"(?<!not )\b(quirk|contract|real_sample)\b")


def _opted_in(config: pytest.Config) -> bool:
    if os.environ.get("T2D_REAL_SAMPLES") == "1":
        return True
    return bool(_SUITE_MARKERS.search(config.getoption("markexpr") or ""))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(
        reason="the real-sample suite downloads about 70 MB: run "
        "`pytest tests/real_samples -m quirk` (or -m contract), or set T2D_REAL_SAMPLES=1"
    )
    opted_in = _opted_in(config)
    for item in items:
        if HERE not in Path(str(item.path)).parents:
            continue
        item.add_marker(pytest.mark.network)
        item.add_marker(pytest.mark.real_sample)
        if not opted_in:
            item.add_marker(skip)


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("T2D_REFERENCE_READERS") == "1":
        from tests.real_samples import reference_readers  # noqa: F401  (registers on import)


@pytest.fixture(scope="session")
def fx() -> Callable[[str], Path]:
    """fx('name.ext') -> verified Path."""
    return fetch
```

- [ ] **Step 3: Delete the original**

Run: `git rm -f --cached tests/real_samples/_original_conftest.py 2>/dev/null; rm tests/real_samples/_original_conftest.py`

### Task 3: Repair imports, the PyTables guard, markers and ignores

**Files:**
- Modify: `tests/real_samples/oracles.py`, `test_format_quirks.py`, `test_reader_contract.py`, `reference_readers.py`, `README.md`, `pyproject.toml`, `.gitignore`

- [ ] **Step 1: Package-relative imports**

In `test_format_quirks.py` replace `import oracles as O` with `from tests.real_samples import oracles as O`.
In `test_reader_contract.py` replace `import oracles as O  # noqa: E402` with `from tests.real_samples import oracles as O  # noqa: E402` and replace `from conftest import build_folder, fetch, provide_video_info  # noqa: E402` with `from tests.real_samples.fixtures import build_folder, fetch, provide_video_info  # noqa: E402`.

- [ ] **Step 2: Skip, do not fail, when PyTables is missing**

In `oracles.py` add `import pytest` to the imports and change `read_dlc` so the `.h5` branch reads:

```python
    if path.suffix == ".h5":
        pytest.importorskip("tables", reason="the DLC .h5 oracle reads pandas HDF5 via PyTables")
        return pd.read_hdf(path, key="df_with_missing")
```

- [ ] **Step 3: Register markers and add PyTables to the dev extra**

In `pyproject.toml`, append to `markers = [...]`:

```toml
    "quirk: format-quirk test; parses raw fixture files, needs no Track2Data (tests/real_samples)",
    "contract: reader-contract test; runs against registered readers (tests/real_samples)",
    "real_sample: needs downloaded real tracker output (about 70 MB); opt in with -m quirk/contract/real_sample or T2D_REAL_SAMPLES=1",
```

and append to the `dev` list:

```toml
    "tables>=3.9",               # tests/real_samples/oracles.py reads DeepLabCut's pandas-HDF5
                                  # output through PyTables. Test-only ORACLE: the shipped reader
                                  # must not depend on it (decided at gate G-H5).
```

- [ ] **Step 4: Ignore the cache and relax style only where the suite is third-party code**

Append to `.gitignore`:

```
# Real-sample fixture cache (defaults to a local, unsynced directory; this is for other machines)
tests/real_samples/.fixture_cache/
```

Run `py -3.14 -m ruff check tests/real_samples --no-cache`. If it reports only `E501` or `B905` in the supplied files, add to `[tool.ruff.lint.per-file-ignores]`:

```toml
"tests/real_samples/**" = ["ANN", "S", "RUF012", "E501", "B905"]  # supplied suite; keep it close to the original
```

Fix anything else properly.

- [ ] **Step 5: Adapt the README run section**

Replace the "Run" block in `tests/real_samples/README.md` with:

```markdown
## Run

From the repository root, with Python 3.14 (the interpreter that has the dev dependencies):

```bash
py -3.14 -m pip install "tables>=3.9"          # once: the DLC .h5 oracle needs PyTables
py -3.14 -m pytest tests/real_samples -m quirk      # no Track2Data needed
py -3.14 -m pytest tests/real_samples -m contract   # reader contract; XFAIL until readers exist
```

The suite is opt-in and excluded from CI (every test is also marked `network`). Fixtures are
cached outside the worktree: set `T2D_FIXTURE_DIR` to override the location.
```

### Task 4: Run the suite and commit

- [ ] **Step 1: Quirk tests (GREEN)**

Run: `PYTHONDONTWRITEBYTECODE=1 py -3.14 -m pytest tests/real_samples -m quirk -q -p no:cacheprovider`
Expected: `42 passed` (the first run downloads about 70 MB into `%LOCALAPPDATA%\track2data\fixture_cache`; if the network is unreachable the tests report `skipped`, and the task is blocked until it is).

- [ ] **Step 2: Contract tests (XFAIL)**

Run: `PYTHONDONTWRITEBYTECODE=1 py -3.14 -m pytest tests/real_samples -m contract -q -p no:cacheprovider`
Expected: `80 xfailed`, 0 errors.

- [ ] **Step 3: Contract tests with the scaffolding readers**

Run: `T2D_REFERENCE_READERS=1 PYTHONDONTWRITEBYTECODE=1 py -3.14 -m pytest tests/real_samples -m contract -q -p no:cacheprovider`
Expected: `75 passed, 5 skipped` (the figures the suite reports; if different, record the real numbers in the commit message and README).

- [ ] **Step 4: The default run must not touch the suite**

Run: `PYTHONDONTWRITEBYTECODE=1 py -3.14 -m pytest tests/ -m "not r_parity and not network and not corpus_local" -q -p no:cacheprovider`
Expected: the same pass count as the baseline (1,936 + the 6 pin tests = 1,942), no downloads. Then run plain `py -3.14 -m pytest tests/real_samples -q -p no:cacheprovider` and expect every test `skipped` with the opt-in reason.

- [ ] **Step 5: Lint and commit**

```bash
py -3.14 -m ruff check . --no-cache && py -3.14 -m mypy
git add -A tests/real_samples pyproject.toml .gitignore .gitattributes
git commit -m "test(real-samples): import the reader fixture-test suite" -m "<what and why, the three figures from Steps 1 to 3>" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## PR T0-2: one place that names a session

**Branch:** `refactor/session-id` · **Goal:** `core/ids.py` is the only derivation of a session id. No behaviour change for existing folders. `SessionRef.session_id` rejects only path-hostile values.

### Task 1: The helpers

**Files:** Create `track2data/core/ids.py`, `tests/test_core/test_ids.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Session ids: one derivation, Windows-safe, unique, and unchanged for existing folders."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from track2data.core.ids import default_session_id, sanitise_session_id, uniquify


class TestDefaultSessionId:
    def test_a_directory_keeps_its_name_verbatim(self, tmp_path: Path) -> None:
        # Existing projects join metadata on this exact string; it must never change.
        for name in ["session_trial10_Segment1", "fish 3", "run.v2", "été", "a" * 200]:
            folder = tmp_path / name
            folder.mkdir()
            assert default_session_id(folder) == name

    def test_a_file_is_named_after_its_stem(self, tmp_path: Path) -> None:
        file = tmp_path / "trial01DLC_resnet50.h5"
        file.write_bytes(b"x")
        assert default_session_id(file) == "trial01DLC_resnet50"

    def test_a_file_stem_is_sanitised(self, tmp_path: Path) -> None:
        file = tmp_path / "a:b?.csv"
        file.write_bytes(b"x")
        assert default_session_id(file) == "a_b_"


class TestSanitise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ok name", "ok name"),
            ("a/b\\c", "a_b_c"),
            ('a:b*c?"d<e>f|g', "a_b_c__d_e_f_g"),
            ("trailing. ", "trailing"),
            ("CON", "CON_"),
            ("nul", "nul_"),
            ("com1", "com1_"),
            ("", "session"),
            ("...", "session"),
            ("a\x00b", "a_b"),
        ],
    )
    def test_known_cases(self, raw: str, expected: str) -> None:
        assert sanitise_session_id(raw) == expected

    def test_is_truncated(self) -> None:
        assert len(sanitise_session_id("x" * 500, max_len=120)) == 120

    @given(st.text())
    def test_never_empty_and_has_no_separators(self, raw: str) -> None:
        out = sanitise_session_id(raw)
        assert out
        assert not set(out) & set('/\\:*?"<>|\x00')

    @given(st.text())
    def test_is_idempotent(self, raw: str) -> None:
        once = sanitise_session_id(raw)
        assert sanitise_session_id(once) == once


class TestUniquify:
    def test_already_unique_is_unchanged(self) -> None:
        assert uniquify(["a", "b", "c"]) == ["a", "b", "c"]

    def test_duplicates_get_a_numbered_suffix_in_order(self) -> None:
        assert uniquify(["a", "a", "b", "a"]) == ["a", "a__2", "b", "a__3"]

    def test_taken_ids_are_respected(self) -> None:
        assert uniquify(["a", "b"], taken={"a"}) == ["a__2", "b"]

    def test_suffixes_do_not_collide_with_real_names(self) -> None:
        assert uniquify(["a", "a", "a__2"]) == ["a", "a__3", "a__2"]

    @given(st.lists(st.text(min_size=1, max_size=6), max_size=30))
    def test_result_is_unique_and_same_length(self, ids: list[str]) -> None:
        out = uniquify(ids)
        assert len(out) == len(ids)
        assert len(set(out)) == len(out)
```

- [ ] **Step 2: Run to verify RED**

Run: `py -3.14 -m pytest tests/test_core/test_ids.py -q -p no:cacheprovider`
Expected: collection error `ModuleNotFoundError: No module named 'track2data.core.ids'`.

- [ ] **Step 3: Implement `track2data/core/ids.py`**

```python
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


def default_session_id(path: Path) -> str:
    """The id a session gets when nothing else names it.

    A directory keeps its name; a file is named after its stem, sanitised.
    """
    path = Path(path)
    if path.is_dir():
        return path.name
    return sanitise_session_id(path.stem)


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
```

- [ ] **Step 4: Run to verify GREEN**

Run: `py -3.14 -m pytest tests/test_core/test_ids.py -q -p no:cacheprovider`
Expected: all pass. If a case from the tables above disagrees with the implementation, fix the implementation only when the test states the intended behaviour; otherwise correct the test and say why in the commit.

- [ ] **Step 5: Commit** `feat(core): add the single session-id derivation`.

### Task 2: Route the three derivations through it, and guard `SessionRef`

**Files:** Modify `ui/store/project_store.py` (the `session_id = folder.name` line in `add_session`), `track2data/readers/idtrackerai/normaliser.py:99`, `track2data/readers/idtrackerai_v5.py:122`, `track2data/core/models.py` (`SessionRef`); Test `tests/test_core/test_ids.py`

- [ ] **Step 1: Write the failing characterisation tests** (append to `tests/test_core/test_ids.py`)

```python
class TestDerivationsAgree:
    def test_both_idtracker_readers_use_the_helper(
        self, tiny_real_session: Path, tiny_v5_session: Path
    ) -> None:
        from track2data.readers import read_session

        for folder in (tiny_real_session, tiny_v5_session):
            assert read_session(folder).session_id == default_session_id(folder)

    def test_the_project_store_uses_the_helper(self, tiny_real_session: Path, tmp_path: Path) -> None:
        pytest.importorskip("PySide6")
        from ui.store.project_store import ProjectStore

        store = ProjectStore()
        store.new_project("p", tmp_path)
        store.add_session(tiny_real_session)
        assert store.manifest is not None
        assert [s.session_id for s in store.manifest.sessions] == [
            default_session_id(tiny_real_session)
        ]


class TestSessionRefGuard:
    @pytest.mark.parametrize("bad", ["", "a/b", "a\\b", "..", "a\x00b"])
    def test_path_hostile_ids_are_rejected(self, bad: str, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from track2data.core.models import SessionRef

        with pytest.raises(ValidationError):
            SessionRef(session_id=bad, folder=tmp_path, sha256="")

    def test_odd_but_safe_ids_still_load(self, tmp_path: Path) -> None:
        from track2data.core.models import SessionRef

        assert SessionRef(session_id="fish 3 (v2)", folder=tmp_path, sha256="").session_id
```

- [ ] **Step 2: Run to verify RED**

Run: `py -3.14 -m pytest tests/test_core/test_ids.py -q -p no:cacheprovider`
Expected: `TestSessionRefGuard` fails (`DID NOT RAISE`); `TestDerivationsAgree` passes already, because `folder.name` equals the helper for directories. That is the point of a characterisation test: it pins the behaviour before the refactor.

- [ ] **Step 3: Implement**

In `track2data/core/models.py` give `SessionRef` a validator:

```python
    @field_validator("session_id")
    @classmethod
    def _id_is_a_safe_path_segment(cls, value: str) -> str:
        """An id is used as a directory name; reject only what could escape it."""
        if not value or value in {".", ".."} or any(c in value for c in ("/", "\\", "\x00")):
            raise ValueError(f"unsafe session id: {value!r}")
        return value
```

(add `field_validator` to the pydantic import). Replace the three `folder.name` derivations with `default_session_id(folder)`, importing from `track2data.core.ids`.

- [ ] **Step 4: Run to verify GREEN, then the full default suite**

Run: `py -3.14 -m pytest tests/ -m "not r_parity and not network and not corpus_local" -q -p no:cacheprovider`
Expected: everything passes.

- [ ] **Step 5: Commit** `refactor(core): derive every session id through one helper`.

---

## PR T0-3: the additive reader contract

**Branch:** `feat/reader-contract` · **Goal:** readers can declare options, metadata and verification; a session can be read by *naming* the reader; a missing required option is a coded error, never a default. Existing readers and `cls().read(folder)` keep working. Scan and `discover` come in T0-4.

### Task 1: Options and detection types

**Files:** Create `track2data/readers/params.py`, `track2data/readers/detection.py`, `tests/test_readers/test_params.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Reader options: validation, defaults and the two coded errors."""

from __future__ import annotations

import pytest

from track2data.core.errors import ImportError_
from track2data.readers.params import ReaderParameter, resolve_options

PARAMS = (
    ReaderParameter(name="fps", label="Frame rate", kind="float", required=True, minimum=0.001),
    ReaderParameter(name="cutoff", label="Cutoff", kind="float", default=0.6, minimum=0, maximum=1),
    ReaderParameter(name="variant", label="Variant", kind="choice", default="raw",
                    choices=("raw", "filtered")),
    ReaderParameter(name="parts", label="Parts", kind="multichoice", choices=("a", "b", "c")),
    ReaderParameter(name="keep", label="Keep", kind="bool", default=True),
    ReaderParameter(name="n", label="N", kind="int", default=3),
)


def test_defaults_are_filled_and_given_values_win() -> None:
    out = resolve_options("t", PARAMS, {"fps": 30})
    assert out == {"fps": 30, "cutoff": 0.6, "variant": "raw", "parts": None, "keep": True, "n": 3}


def test_none_means_no_options() -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, None)
    assert err.value.code == "READER_OPTION_MISSING"


@pytest.mark.parametrize("given", [{}, {"fps": None}])
def test_a_missing_required_option_names_it_and_never_defaults(given: dict) -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, given)
    assert err.value.code == "READER_OPTION_MISSING"
    assert err.value.subject == "fps"
    assert err.value.remediation


@pytest.mark.parametrize(
    "given",
    [
        {"fps": 30, "nope": 1},                  # unknown name
        {"fps": "fast"},                         # wrong type
        {"fps": True},                           # bool is not a number
        {"fps": 0},                              # below minimum
        {"fps": 30, "cutoff": 2},                # above maximum
        {"fps": 30, "variant": "weird"},         # not a choice
        {"fps": 30, "parts": ["a", "z"]},        # not a subset of the choices
        {"fps": 30, "n": 2.5},                   # int expected
        {"fps": float("nan")},                   # not finite
    ],
)
def test_bad_values_are_invalid(given: dict) -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, given)
    assert err.value.code == "READER_OPTION_INVALID"
    assert err.value.remediation


def test_a_reader_without_parameters_accepts_no_options() -> None:
    assert resolve_options("t", (), None) == {}
    with pytest.raises(ImportError_) as err:
        resolve_options("t", (), {"fps": 30})
    assert err.value.code == "READER_OPTION_INVALID"
```

- [ ] **Step 2: Run to verify RED** (`ModuleNotFoundError: track2data.readers.params`).

- [ ] **Step 3: Implement `params.py`**

```python
"""Reader options: what a reader must be told because its files do not say.

Most tracker outputs record neither the frame rate nor the frame size (DeepLabCut, SLEAP,
Anipose), and several need a choice (which keypoint stands for the animal). A reader declares
these as ``parameters``; the confirm dialog renders them, the manifest stores the answers
(``SessionRef.reader_options``), and ``read(..., options=...)`` receives them.

A required option that is missing is an error and never a default: a made-up frame rate
silently corrupts every speed metric.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from track2data.core.errors import ImportError_

ParameterKind = Literal["int", "float", "str", "bool", "choice", "multichoice", "path"]
ValueSource = Literal["file", "video", "tool-default", "required", "user"]


class ReaderParameter(BaseModel):
    """One option a reader accepts."""

    name: str
    label: str
    kind: ParameterKind
    default: Any = None
    required: bool = False
    choices: tuple[str, ...] = ()
    help: str = ""
    #: "group": one value for every session in a scan group; "session": per-session column.
    scope: Literal["group", "session"] = "group"
    minimum: float | None = None
    maximum: float | None = None


class ProposedValue(BaseModel):
    """A value a detection proposes for a parameter, and where it came from."""

    value: Any = None
    source: ValueSource = "required"


def _invalid(reader: str, name: str, why: str) -> ImportError_:
    return ImportError_(
        f"Reader {reader!r}: option {name!r} {why}",
        code="READER_OPTION_INVALID",
        subject=name,
        remediation=f"Correct option {name!r} in the confirm dialog or with --option.",
    )


def _check(reader: str, spec: ReaderParameter, value: Any) -> Any:
    kind, name = spec.kind, spec.name
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise _invalid(reader, name, f"must be a number, got {value!r}")
        if kind == "int" and not float(value).is_integer():
            raise _invalid(reader, name, f"must be an integer, got {value!r}")
        if not math.isfinite(value):
            raise _invalid(reader, name, "must be finite")
        if spec.minimum is not None and value < spec.minimum:
            raise _invalid(reader, name, f"must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise _invalid(reader, name, f"must be at most {spec.maximum}")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise _invalid(reader, name, f"must be true or false, got {value!r}")
    elif kind == "str":
        if not isinstance(value, str):
            raise _invalid(reader, name, f"must be text, got {value!r}")
    elif kind == "choice":
        if value not in spec.choices:
            raise _invalid(reader, name, f"must be one of {list(spec.choices)}, got {value!r}")
    elif kind == "multichoice":
        if isinstance(value, str) or not isinstance(value, Sequence | set | frozenset):
            raise _invalid(reader, name, "must be a list of choices")
        extra = [v for v in value if v not in spec.choices]
        if extra:
            raise _invalid(reader, name, f"has unknown choices {extra}")
    elif kind == "path" and not isinstance(value, str | Path):
        raise _invalid(reader, name, f"must be a path, got {value!r}")
    return value


def resolve_options(
    reader: str,
    parameters: Sequence[ReaderParameter],
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate *options* against *parameters* and fill the declared defaults.

    Unknown names, wrong types and out-of-range values raise READER_OPTION_INVALID; a required
    option that is absent (or None) raises READER_OPTION_MISSING with its name as the subject.
    """
    given = dict(options or {})
    known = {p.name for p in parameters}
    unknown = sorted(set(given) - known)
    if unknown:
        raise _invalid(reader, ", ".join(unknown), "is not an option of this reader")
    out: dict[str, Any] = {}
    for spec in parameters:
        value = given.get(spec.name)
        if value is None:
            if spec.required:
                raise ImportError_(
                    f"Reader {reader!r} needs option {spec.name!r} ({spec.label}); "
                    "the files do not record it",
                    code="READER_OPTION_MISSING",
                    subject=spec.name,
                    remediation=f"Supply {spec.name!r} in the confirm dialog or with --option.",
                )
            out[spec.name] = spec.default
        else:
            out[spec.name] = _check(reader, spec, value)
    return out
```

- [ ] **Step 4: Run to verify GREEN.** If a parametrised case fails because Python's `isinstance(value, int | float)` treats `nan` as a number, the `isfinite` check above handles it.

- [ ] **Step 5: Write `track2data/readers/detection.py`** (types only; exercised from T0-4 on)

```python
"""What a scan reports: ranked detections with the evidence behind them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from track2data.readers.params import ProposedValue, ReaderParameter


class Confidence(IntEnum):
    """How sure a reader is. HIGH needs a structural marker, no negative marker, no rival."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True)
class SessionCandidate:
    """One session a reader found: where it is and which files belong to it."""

    session_id: str
    #: The session folder, or its primary file for single-file formats.
    source: Path
    files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Detection:
    """A reader's claim over part of a scanned tree."""

    reader: str
    display_name: str
    confidence: Confidence
    evidence: tuple[str, ...] = ()
    sessions: tuple[SessionCandidate, ...] = ()
    parameters: tuple[ReaderParameter, ...] = ()
    proposed: Mapping[str, ProposedValue] = field(default_factory=dict)
    verification: str = "synthetic_only"
```

- [ ] **Step 6: Commit** `feat(readers): add reader options and detection types`.

### Task 2: Contract metadata on `SessionReader`, `get_reader`, and a reader that can be named

**Files:** Modify `track2data/readers/base.py`, `track2data/readers/__init__.py`, `track2data/readers/idtrackerai/reader.py`, `track2data/readers/idtrackerai_v5.py`; Create `tests/test_readers/test_contract.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The additive reader contract: options, naming a reader, and staying backward compatible."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from track2data import readers
from track2data.core.errors import ImportError_
from track2data.core.models import Session
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter


def _session_from(folder: Path, name: str) -> Session:
    import numpy as np

    from track2data.core.models import VideoInfo

    return Session(
        session_id=folder.name, folder=folder, reader=name,
        video=VideoInfo(path=None, fps=10.0, n_frames=3, width_px=10, height_px=10),
        n_animals=1, trajectory_variant="with_gaps", has_stable_identities=True,
        raw_xy=np.zeros((3, 1, 2)),
    )


class LegacyReader(SessionReader):
    """Written against the original one-argument contract."""

    name = "legacy_test"
    priority = 0
    calls: ClassVar[list[tuple[tuple[Any, ...], dict[str, Any]]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "legacy.marker").exists()

    def read(self, folder: Path) -> Session:  # type: ignore[override]
        type(self).calls.append(((folder,), {}))
        return _session_from(folder, self.name)


class OptionReader(SessionReader):
    name = "option_test"
    priority = 0
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
        ReaderParameter(name="cutoff", label="Cutoff", kind="float", default=0.6),
    )
    seen: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "option.marker").exists()

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        type(self).seen.append(dict(options or {}))
        return _session_from(folder, self.name)


@pytest.fixture
def registered() -> Iterator[None]:
    LegacyReader.calls.clear()
    OptionReader.seen.clear()
    readers.register(LegacyReader)
    readers.register(OptionReader)
    yield
    for cls in (LegacyReader, OptionReader):
        readers._REGISTRY.remove(cls)


def test_defaults_describe_a_plain_reader() -> None:
    assert LegacyReader.parameters == ()
    assert LegacyReader.display_name == ""
    assert LegacyReader.verification == "synthetic_only"
    assert LegacyReader.coordinate_frame == "image_px"
    assert LegacyReader.provides_body_length is False


def test_builtin_idtracker_readers_declare_themselves_verified() -> None:
    for cls in (readers.IDTrackerAiReader, readers.IDTrackerAiV5Reader):
        assert cls.verification == "real_sample"
        assert cls.display_name
        assert cls.provides_body_length is True or cls is readers.IDTrackerAiV5Reader


def test_a_legacy_reader_still_detects_and_reads_with_one_argument(
    registered: None, tmp_path: Path
) -> None:
    (tmp_path / "legacy.marker").write_text("x")
    session = readers.read_session(tmp_path)
    assert session.reader == "legacy_test"
    assert LegacyReader.calls == [((tmp_path,), {})]


def test_options_reach_a_reader_that_declares_parameters(
    registered: None, tmp_path: Path
) -> None:
    readers.read_session(tmp_path, reader="option_test", options={"fps": 25})
    assert OptionReader.seen == [{"fps": 25, "cutoff": 0.6}]


def test_a_missing_required_option_is_a_coded_error_not_a_default(
    registered: None, tmp_path: Path
) -> None:
    with pytest.raises(ImportError_) as err:
        readers.read_session(tmp_path, reader="option_test")
    assert err.value.code == "READER_OPTION_MISSING"
    assert err.value.subject == "fps"
    assert OptionReader.seen == []


def test_options_for_a_reader_that_takes_none_are_rejected(
    registered: None, tmp_path: Path
) -> None:
    with pytest.raises(ImportError_) as err:
        readers.read_session(tmp_path, reader="legacy_test", options={"fps": 1})
    assert err.value.code == "READER_OPTION_INVALID"


def test_naming_a_reader_skips_detection(
    registered: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(folder: Path) -> None:
        raise AssertionError("detect_reader must not run when a reader is named")

    monkeypatch.setattr(readers, "detect_reader", boom)
    # No marker file exists, so detection would fail: naming the reader must not need it.
    assert readers.read_session(tmp_path, reader="legacy_test").reader == "legacy_test"


def test_get_reader_unknown_name_is_a_coded_error() -> None:
    with pytest.raises(ImportError_) as err:
        readers.get_reader("no_such_reader")
    assert err.value.code == "READER_UNKNOWN"
    assert err.value.subject == "no_such_reader"
    assert err.value.remediation


def test_reader_names_lists_the_registry_in_priority_order() -> None:
    names = readers.reader_names()
    assert names[:2] == ["idtrackerai", "idtrackerai_v5"]


def test_allow_pickle_is_still_forwarded_only_to_readers_that_declare_it(
    tiny_real_session: Path,
) -> None:
    # pp3's gate: a pickled trajectories.npy is refused unless the caller opts in.
    with pytest.raises(ImportError_) as err:
        readers.read_session(tiny_real_session, reader="idtrackerai")
    assert err.value.code == "IDT_PICKLE_REFUSED"
    assert readers.read_session(
        tiny_real_session, reader="idtrackerai", allow_pickle=True
    ).reader == "idtrackerai"
```

- [ ] **Step 2: Run to verify RED**

Run: `py -3.14 -m pytest tests/test_readers/test_contract.py -q -p no:cacheprovider`
Expected: failures such as `AttributeError: type object 'LegacyReader' has no attribute 'verification'` and `TypeError: read_session() got an unexpected keyword argument 'reader'`.

- [ ] **Step 3: Implement the base class additions** in `track2data/readers/base.py`

```python
from typing import ClassVar, Literal

from track2data.readers.params import ReaderParameter
```

and inside `SessionReader`, after `accepts_allow_pickle`:

```python
    #: Name shown in the confirm dialog ("DeepLabCut (CSV/H5)"). Empty falls back to ``name``.
    display_name: ClassVar[str] = ""
    #: Options the reader must be told because its files do not say (see readers/params.py).
    #: Empty means the reader takes none, and ``read`` is called without ``options``.
    parameters: ClassVar[tuple[ReaderParameter, ...]] = ()
    #: "real_sample": tested against real tracker output. "synthetic_only": built from the
    #: documented layout alone (DECISIONS D-012). Shown as a badge and recorded in provenance.
    verification: ClassVar[Literal["real_sample", "synthetic_only"]] = "synthetic_only"
    #: Whether coordinates are in the image's pixel frame (zones and the background image only
    #: make sense then) or in physical units, aligned or not, with that frame.
    coordinate_frame: ClassVar[Literal["image_px", "physical_aligned", "physical_unaligned"]] = (
        "image_px"
    )
    #: Whether the reader supplies per-animal body length (needed by the default calibration).
    provides_body_length: ClassVar[bool] = False
```

and extend the `read` docstring: "*folder* is the session folder, or its primary file for single-file formats; a folder holding several sessions raises `SESSION_AMBIGUOUS`. A reader that declares `parameters` also accepts a keyword-only `options` mapping; it is passed only to such readers."

- [ ] **Step 4: Implement the registry additions** in `track2data/readers/__init__.py`

```python
from collections.abc import Mapping
from typing import Any

from track2data.core.errors import ImportError_
from track2data.readers.params import resolve_options


def get_reader(name: str) -> type[SessionReader]:
    """Return the registered reader called *name*."""
    for cls in _REGISTRY:
        if cls.name == name:
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


def _call_read(
    cls: type[SessionReader],
    path: Path,
    *,
    allow_pickle: bool,
    options: Mapping[str, Any] | None,
) -> Session:
    """Call ``cls().read`` passing each keyword only to readers that declare it."""
    kwargs: dict[str, Any] = {}
    if cls.accepts_allow_pickle:
        kwargs["allow_pickle"] = allow_pickle
    # resolve_options also rejects options given to a reader that declares none.
    resolved = resolve_options(cls.name, cls.parameters, options)
    if cls.parameters:
        kwargs["options"] = resolved
    return cls().read(path, **kwargs)


def read_session(
    folder: Path,
    *,
    allow_pickle: bool = False,
    reader: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> Session:
    """Return a Session for *folder*, auto-detecting the reader unless one is named.

    ``reader`` names a registered reader and skips detection, which is how a confirmed choice
    is replayed. ``options`` are the reader's declared parameters. ``allow_pickle`` permits
    formats whose deserialisation executes code from the file; it and ``options`` are
    forwarded only to readers that declare them, so readers written against the original
    one-argument ``read(folder)`` keep working.
    """
    cls = get_reader(reader) if reader is not None else detect_reader(folder)
    if cls is None:
        raise ImportError_(
            f"No reader recognised the session folder: {folder}",
            code="NO_READER",
            subject=str(folder),
            remediation="Ensure the folder is a valid idtracker.ai output directory.",
        )
    return _call_read(cls, folder, allow_pickle=allow_pickle, options=options)
```

Also add `"get_reader"` and `"reader_names"` to `__all__`.

- [ ] **Step 5: Declare the built-ins.** In `IDTrackerAiReader` set `display_name = "idtracker.ai"`, `verification = "real_sample"`, `provides_body_length = True`. In `IDTrackerAiV5Reader` set `display_name = "idtracker.ai v5 (legacy)"`, `verification = "real_sample"`.

- [ ] **Step 6: Run to verify GREEN, then the whole default suite.** Expected: all pass; `tests/test_api.py` and `tests/test_ui/test_project_store.py` pass untouched, because their patches replace `read_session` wholesale.

- [ ] **Step 7: Commit** `feat(readers): let readers declare options and be read by name`.

### Task 3: The conformance test over every registered reader's fixtures

**Files:** Create `tests/test_readers/test_conformance.py`

- [ ] **Step 1: Write the test**

```python
"""Every shipped reader returns a well-formed Session and leaves its input untouched."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from track2data import readers


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(params=["idtrackerai", "idtrackerai_v5"])
def reader_and_folder(request: pytest.FixtureRequest) -> tuple[str, Path]:
    fixture = {"idtrackerai": "tiny_real_session", "idtrackerai_v5": "tiny_v5_session"}[
        request.param
    ]
    return request.param, request.getfixturevalue(fixture)


def test_session_is_well_formed(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    session = readers.read_session(folder, reader=name, allow_pickle=True)
    assert session.reader == name
    assert session.session_id
    assert session.raw_xy.dtype == np.float64
    assert session.raw_xy.ndim == 3
    assert session.raw_xy.shape[2] == 2
    assert not np.isinf(session.raw_xy).any()
    assert session.n_animals == session.raw_xy.shape[1]
    assert session.video.n_frames == session.raw_xy.shape[0]
    assert session.video.fps > 0
    assert session.video.width_px > 0
    assert session.video.height_px > 0


def test_reading_does_not_modify_the_input_folder(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    before = _tree_hash(folder)
    readers.read_session(folder, reader=name, allow_pickle=True)
    assert _tree_hash(folder) == before


def test_detect_agrees_with_naming_the_reader(reader_and_folder: tuple[str, Path]) -> None:
    name, folder = reader_and_folder
    assert readers.get_reader(name).detect(folder)
```

- [ ] **Step 2: Run.** Expected: the v5 case fails on `width_px > 0` if the legacy reader falls back to 0 (the known latent bug recorded in the design). If it does, mark exactly that assertion `xfail(strict=True)` for `idtrackerai_v5` with the reason "v5 reader falls back to 0 for missing frame size; fix after T0-3", and keep every other assertion live. Do not weaken the test for the unified reader.

- [ ] **Step 3: Commit** `test(readers): add a conformance test over the built-in readers`.

### Task 4: Thread options through the suite's two read call sites

**Files:** Modify `tests/real_samples/fixtures.py`, `tests/real_samples/test_reader_contract.py`

- [ ] **Step 1: Write the failing test** (`tests/test_readers/test_suite_options.py`)

```python
"""The real-sample suite hands options to readers at BOTH of its read call sites."""

from __future__ import annotations

from pathlib import Path

from tests.real_samples import fixtures


def test_provided_video_info_is_retrievable_as_options(tmp_path: Path) -> None:
    fixtures.provide_video_info(tmp_path, {"fps": 30.0, "width_px": 10, "height_px": 20})
    assert fixtures.options_for(tmp_path) == {"fps": 30.0, "width_px": 10, "height_px": 20}
    assert fixtures.options_for(tmp_path / "elsewhere") is None
```

- [ ] **Step 2: Run to verify RED** (`AttributeError: module … has no attribute 'options_for'`).

- [ ] **Step 3: Implement.** In `fixtures.py` add a module-level `_OPTIONS: dict[Path, dict] = {}`, have `provide_video_info` also record `_OPTIONS[folder.resolve()] = dict(info)` (it still writes the sidecar for the scaffolding readers), and add `options_for(folder)` returning `_OPTIONS.get(folder.resolve())`. Add a helper used by both call sites:

```python
def read_with_options(cls, folder):
    """Read *folder* with *cls*, passing the options a reader declares and nothing else."""
    from track2data import readers

    options = options_for(folder)
    return readers._call_read(
        cls, folder, allow_pickle=False, options=options if cls.parameters else None
    )
```

In `test_reader_contract.py` replace `registry.detect_reader(folder)().read(folder)` (the `loaded` fixture) and `cls().read(folder)` (in `_assert_clean_failure`) with `fixtures.read_with_options(cls, folder)`, importing `fixtures` from `tests.real_samples`.

- [ ] **Step 4: Run** the new test, then `T2D_REFERENCE_READERS=1 py -3.14 -m pytest tests/real_samples -m contract -q`. Expected: the same `75 passed, 5 skipped` as in T0-1, since the scaffolding readers declare no parameters and still read the sidecar.

- [ ] **Step 5: Commit** `test(real-samples): route options through both read call sites`.

### Task 5: Document the contract and the new error codes

**Files:** Modify `docs/USER_WORKFLOW.md` §6, `docs/TECHNICAL_SPEC.md` §12, `CHANGELOG.md`, `docs/tracker-formats/README.md`

- [ ] **Step 1:** Add rows to the `docs/USER_WORKFLOW.md` §6 error table for `READER_UNKNOWN`, `READER_NOT_AVAILABLE`, `READER_OPTION_MISSING` (subject = option name), `READER_OPTION_INVALID` and `SESSION_AMBIGUOUS`, each with its remediation text exactly as the code raises it. Add the capability-flag rule (`parameters`, `options`, `accepts_allow_pickle`) to the plug-in policy in `docs/TECHNICAL_SPEC.md` §12.2.
- [ ] **Step 2:** Add a `CHANGELOG.md` entry under `## [Unreleased]`, Added: readers can declare options and verification, and a session can be read by naming its reader.
- [ ] **Step 3:** Run `py -3.14 -m pytest tests/ -m "not r_parity and not network and not corpus_local" -q`, ruff and mypy. Commit `docs: document the reader contract additions`.

---

## PR T0-4: the read-only scan (built)

**Branch:** `feat/scan-core` · **Status:** implemented in `5ca75a6` and `e34170c`; this section records the design as built.

**What was built.**

- `readers/index.py`: `ScanBudget(max_entries=100_000, max_depth=4, max_seconds=30.0, max_peeks=2_000, peek_bytes=65_536)`; `IndexEntry(path, is_dir, size, cloud_only, depth)`; `ScanIndex` (`walk`, `dirs`, `entry`, `children`, `child`, `file_types`, plus `truncated`, `warnings`, `seconds`); `classify_attributes(attrs, is_dir=...)`, the Windows attribute rules as a pure function so Linux CI tests them; `build_index(roots, budget, progress, token, clock=...)`.
- `readers/peek.py`: `Peeker(budget, index)` with `head_bytes`, `text_lines` and `npy_header` (returns `NpyHeader(shape, dtype, fortran_order)` and never unpickles). Peeks for other containers (HDF5 signature, MAT variables, zip members, SQLite) are added with the first reader that needs them.
- `readers/detection.py` (T0-3) holds the types. `readers/discovery.py` holds `claim_sessions(index, accept)`, the breadth-first walk where a claimed folder is a leaf.
- `readers/scan.py`: `scan(roots, *, budget, progress, token) -> ScanResult` and the pure `scan_index(index, *, budget, token)`. `ScanResult(roots, groups, file_types, truncated, warnings, entries, seconds)`; `FormatGroup(detections)` with `.best`. Weaker claims inside a folder another reader is sure about are pruned, and session ids are made unique from their paths.
- `SessionReader.discover(index, peek)` has a default that wraps `detect` (MEDIUM confidence). Both idtracker.ai readers implement it. A session's own `trajectories/` subfolder, picked on its own, gives a LOW suggestion pointing at its parent.
- `IDTrackerAiReader.detect` now declines the v5 layout (a raw-array `trajectories.npy` beside a `video_object.npy`), so auto-detection reaches the v5 reader instead of failing with `IDT_FORMAT_AMBIGUOUS`. A raw array with no `video_object.npy` is still claimed, so reading it explains the problem instead of "no reader recognised the folder".
- `core/progress.py`: `Stage` gains `"scan"`.

**Deferred from the original outline**, until something needs it:

- `lenient_detection` (the "it is actually X" re-run): needed by the dialog's "Choose software…" path, so it arrives with T0-6 and T0-8.
- The HDF5, MAT, zip and SQLite peeks: they arrive with the first reader that uses each.
- The golden table over the suite's ten case folders: it arrives with the first real reader (T1-2), when there is something to expect.

**Verified.** 89 scan tests, including a property test that any tree scans deterministically with safe, unique ids. A mutation check shows the detect/discover agreement test fails without the v5 rule. On the real 70-session corpus one scan gives one HIGH group of 70 sessions (3,847 entries, 0.19 s for the walk and discovery). The default suite is 2,110 passed.

---

## PR T0-5: persist the reader (built)

**Branch:** `feat/persisted-reader` · **Status:** implemented in `15e2a39`, `9c272c6`, `d9cdd16` and the provenance commit that follows them; this section records the design as built.

**What was built.**

- `SessionRef` gains `reader: str | None`, `reader_options: dict[str, Any]`, `reader_chosen_by: Literal["detected", "user"] | None` and `reader_confidence: str | None` (the detection confidence, kept as text so a manifest does not depend on the enum). Manifest `schema_version` stays 1; `project_hash` changes once, because the new keys enter the hashed dump.
- `Engine.import_ref(ref) -> Session` (public, not `_import_ref`: the UI and CLI call it too). With `ref.reader is None` it calls exactly `self.import_session(ref.folder)`, the legacy shape the tests patch. Otherwise it calls `read_session(ref.folder, reader=ref.reader, options=ref.reader_options, allow_pickle=…)`. It ends with `session.model_copy(update={"session_id": ref.session_id})`. `import_sessions`, `_run_one_session`, the pre-flight summaries, `validate` and the CLI all go through it. `READER_UNKNOWN` becomes `READER_NOT_AVAILABLE`, with no fall-back to detection.
- `Engine.scan(roots, *, budget, progress, token)`: a static facade over `readers.scan.scan`. It needs no project, which is how a project gets its first sessions.
- `SessionProvenance` gains `source_software`, `reader_verification`, `reader_options`, `reader_chosen_by`, `detection_confidence`, `source_files`. `Engine.build_payload` fills them from the reader class (`find_reader`: display name and verification) and the manifest entry (who chose it, options, confidence); `source_files` is the session's `trajectory_source`.
- The README gets a "Source software provenance" section for any session whose reader is not idtracker.ai: software, reader, verification, how the reader was chosen, options, source file names (names only, never directories, because a README is meant to be shared), counts, identity status, calibration factor. A provenance with no reader, or an `idtrackerai*` reader, keeps the idtracker.ai section byte-for-byte. The new fields reach `manifest.json` through `asdict`; they carry no unit, so pp3's unit schema is not triggered.
- `readers/advisories.py`: `reader_advisories(summaries)` gives one plain-language warning per reader that was never checked against real output (it names the sessions), and one for `bodylength` calibration on sessions that carry no body length. `SessionSummary` gains `has_body_length` for that, taken from the data (`body_length_px is not None`) rather than from the reader's declared flag, so it is right for an idtracker.ai session that lacks the key too. `Engine.consistency_warnings()` returns them after the heterogeneity warnings, and `PROJECT_SUMMARY.md` records them in their own "Notes on the readers" section, apart from "Read before pooling these sessions": they say how the sessions were read, not that they disagree. Neither blocks `validate()` or a run.
- `readers.find_reader(name)` returns the registered class or `None`; `get_reader` raises `READER_UNKNOWN` through it.
- D-5 returns `not_assessed` when the reader never supplies identification quality, and its documentation says so.
- **After PR #100:** the cache key, `preprocess_ref` and the probe contract described in *Integration with PR #100* are part of this PR's behaviour. `tests/support/toy_reader.py` is the shared non-idtracker reader that the persisted-reader, provenance, advisory and cache tests use.

**Deviation from the outline.** The outline put the body-length advisory on the reader's `provides_body_length` flag. The flag remains a declaration for the dialog, but the advisory is driven by whether the session really has a body length: it is what decides whether calibration runs.

**Done when.** Legacy projects give byte-identical metrics (only `project_hash` differs), and a saved reader replays to exactly what detection produced.

**Verified.**

- A toy non-idtracker reader runs `Engine.run` end to end from its saved options (`tests/test_integration/test_non_idtracker_reader.py`): README, `manifest.json`, D-5, advisories and the project summary. Ten mutations of the new logic (the idtracker/other switch, the verified-reader skip, the calibration-mode test, the verification field, pipe escaping, name-only file listing, the body-length flag, both consistency surfaces, the "+N more" cut) are each caught by a test.
- **Legacy outputs, compared across trees.** The pp3 tip (`2017cc8`) and the T0-4 tree (`48610f5`) were extracted with `git archive` (no worktree, no install) and run from inside their own folders, each asserting that `track2data` was imported from there. All four ran over the same two fixture folders (`tiny_real`, `tiny_v5`), every metric selected, diagnostics included, `allow_pickle_trajectories` on, once under the default `bodylength` calibration and once under `scalar`. The pp3 tip cannot read `tiny_v5` (`IDT_FORMAT_AMBIGUOUS`, fixed in T0-4), so it is a baseline for `tiny_real` only. Result: every per-session CSV is byte-identical from pp3 and from T0-4 to now (4 files per session, both calibrations), and byte-identical between a project whose entries name no reader and the same project with persisted readers.
- **What does differ, all expected.** `codebook.csv`: only D-5's description (it now documents `not_assessed`). `PROJECT_SUMMARY.md`: the project hash and, for `tiny_v5` under `bodylength`, the new "Notes on the readers" entry saying its sessions carry no body length (true before, and reported only now: the calibration was skipped without a word). `sessions.csv` differs from the pp3 run only because the pp3 run could not read `tiny_v5`.
- **Re-checked against `main` after pp3 landed (#103).** The same comparison, with today's `main` as the
  baseline and the foundation head as the subject: every per-session CSV for `tiny_real` is byte-identical
  under both calibrations, and a project that saves its readers writes byte-identical files to one that
  detects them, for both layouts. `main` itself still cannot auto-detect `tiny_v5` (the
  `IDT_FORMAT_AMBIGUOUS` bug the scan work fixes), so `tiny_v5` has no baseline there.
- The permanent guard is `tests/test_integration/test_replayed_reader.py`: all CSVs of a detected run and a saved-reader run must match byte for byte, for both layouts and both calibration modes. Breaking the replay road (the project's pickle consent not forwarded; the wrong reader replayed) makes it fail.

---

## PR T0-6: confirm draft and CLI (built)

**Branch:** `feat/confirm-cli` · **Status:** implemented; this section records the design as built.

**What was built.**

- `readers/params.py`: `parse_value(spec, text)` and `parse_assignments(parameters, ["name=value", ...])` turn command-line text into typed values. Only the form is checked (a number is a number, a choice is one of the choices); ranges and requiredness stay with `resolve_options`. A malformed assignment, an unknown name or the same name twice is `READER_OPTION_INVALID`, so a typo is never ignored and "last one wins" never hides a mistake.
- `readers/confirm.py`: `ConfirmDraft(result, existing=...)`, Qt-free. It starts on the best reader of the first group with every session included and the options pre-filled from `Detection.proposed` (each value remembers where it came from). `select_group`, `select_reader` (only a reader that recognised the group; choosing another marks the choice as the user's and starts that reader's options afresh), `set_option` / `set_session_option` (shared or per-session, by the parameter's `scope`; `None` clears), `set_included`, `rename`. `rows` are `SessionRow`s with the original id as the stable handle. `problems()` lists everything between the user and "Add": `NOTHING_SELECTED`, `OPTION_MISSING`, `OPTION_INVALID` (by the reader's own validation), `ID_UNSAFE`, `ID_DUPLICATE` (against the other chosen sessions and against the project). A session already in the project under the same reader (or a legacy entry with none) is left out and flagged; the same folder under another reader is another session. `to_session_refs()` saves the reader, the options that were *given* (not the defaults), who chose it and the confidence.
- CLI: `track2data list-readers [--json]`, `track2data scan ROOT... [--max-depth N] [--json]`, `track2data add PROJECT ROOT... [--group N] [--reader NAME] [--option NAME=VALUE] [--exclude ID] [--rename OLD=NEW] [--max-depth N] [--yes] [--dry-run]`, and `track2data/__main__.py` so `python -m track2data` runs the code on the current path. `add` shows the suggestion, applies the amendments, refuses with the reader's own wording while a required option is missing, asks for confirmation (`--yes` skips it, `--dry-run` shows the plan), and writes the project only after that. Nothing recognised exits non-zero and lists the file types it did see, and says how to look deeper.

**Deferred.** `lenient_detection` (offering a reader that did *not* recognise the files, reusing the group's candidates) arrives with the first reader that needs it (Tier 1): with only idtracker.ai readers there is nothing meaningful to offer, and a forced reader on files it cannot read only moves the error.

**Verified.** 45 `ConfirmDraft` tests and 29 CLI tests; mutations of the draft (the dedupe rule, `chosen_by`, option reset on a reader change, defaults frozen into the entries, excluded sessions still added, duplicate and unsafe ids, per-session options) and of the commands (no confirmation, ignored flags, a dry run that writes, ...) are each caught.

---

## PR T0-7: the store and the task runner

**Branch:** `feat/store-scan` · **Expanded when T0-6 has merged.**

**Interfaces.** `ProjectStore.scan_folders(paths) -> task_id`, signal `scanFinished(task_id, object)`, `add_confirmed(refs)` (dedupe on resolved path plus reader plus selector option); a quiet-task set so scan and probe failures show in the log and per-row status instead of the generic "Pipeline run failed" modal; `TaskRunner.submit` and `submit_with_progress` take `priority=`. `add_session` stays byte-identical so the existing test seams keep working.

**Tests.** The scan result arrives as a value; cancel stops within one second through `store.tasks.taskCancelled`; a failing probe produces an inline message, not a modal; priority ordering against slow fake tasks.

---

## PR T0-8: the confirm dialog

**Branch:** `feat/confirm-dialog` · **Expanded when T0-7 has merged.**

**Interfaces.** `ui/widgets/parameter_form.py` (the field builder extracted from `metric_config_dialog._build_field`, with characterisation tests first and no copied event filter); `ui/dialogs/confirm_format_dialog.py` (`ConfirmFormatDialog`, opened with `open()`, no outside-click filter, OK disabled with a tooltip stating why); `ImportScreen` routes folder pick and drop through scan, accepts files as well as folders, shows the reader column from the manifest immediately, and offers "Re-detect"; `SessionFacts` gains `source_software` with a default so injected-facts tests still construct it. Docs: `docs/dev/UI_DESIGN.md` §6.2 and `docs/USER_WORKFLOW.md` Stage 2.

**Tests.** pytest-qt offscreen: a press outside the dialog does not close it; a combo selection works; OK adds `SessionRef`s carrying reader and options; the table shows the persisted reader after reopen. Existing drop and add tests that assert `store.add_session` directly are updated deliberately, as a failing-test-first step.

**Acceptance.** A scan of the 70-session corpus root and one Enter adds all 70 sessions.

---

## PR T0-9: driver verbs and recognise-only formats

**Branch:** `feat/driver-recognise` · **Expanded when T0-8 has merged.**

**Interfaces.** Driver verbs `scan`, `confirm`, `shot-dialog` and a `QFileDialog` guard in `.claude/skills/run-track2data/driver.py` (never `exec()`); `readers/recognise.py` with a table of `(name, display, signature, remediation)` for formats that are detected but cannot be read: `.slp`, DLC-3D until Tier 3, AnimalTA detailed, FlyTracker, MWT, DANNCE, FicTrac, and `trx.mat` until a sample is pinned.

**Tests.** A recognise-only fixture per table entry gives a MEDIUM detection whose remediation text is shown instead of "nothing found"; a smoke test of each driver verb.

---

## Self-review against the design

- **Flow and dialog (design 4.1):** T0-4 (scan), T0-6 (draft), T0-8 (dialog), T0-7 (store).
- **Scan (4.2):** T0-4. **Contract (4.3):** T0-3 now, `discover` in T0-4. **Persistence and engine seam (4.4):** T0-2, T0-5. **Provenance (4.5):** T0-5.
- **Options, scale and units (4.6), pose core (4.7), identity regimes (4.8), native units (4.9):** Tier 1 to 3 PRs; the options mechanism they need lands in T0-3.
- **Suite as acceptance harness:** T0-1 and T0-3 Task 4.
- **No placeholders in the code-level tasks (T0-1 to T0-3).** T0-4 to T0-9 are deliberately interface-level and are expanded in their own PRs; this is the one departure from a fully code-level plan, made so the plan does not describe code that earlier PRs will already have changed.
- **Type consistency.** `ReaderParameter`, `ProposedValue`, `resolve_options`, `Confidence`, `SessionCandidate`, `Detection`, `get_reader`, `reader_names`, `_call_read` and `read_session(path, *, allow_pickle, reader, options)` are defined once (T0-3) and used by name afterwards.
