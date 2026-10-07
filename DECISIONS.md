# Track2Data — Implementation Decisions

This file records every non-obvious implementation decision made during
development. New decisions are appended in the phase they were made.
Each entry states what was decided, why, and the alternative considered.

---

## Phase 1 — App Shell

### D-001 · `ui/` and `app/` placed at repository root

**Decision:** Both `app/` (entry point + shell) and `ui/` (wizard pages)
live at the repository root, not inside the `track2data/` engine package.

**Rationale:** `TECHNICAL_SPEC.md §4` explicitly states:
> "`ui/` lives outside `track2data/` deliberately so that the engine
> remains a clean, UI-free `pip install track2data` library."

Placing PySide6 code inside `track2data/` would make a bare
`pip install track2data` drag in PySide6, violating the clean
engine-vs-GUI separation and the `[ui]` extra model.

**Alternative considered:** Put `app/` and `ui/` inside `track2data/`
as `track2data/app/` and `track2data/ui/`. Rejected because it embeds
PySide6 in the engine package.

---

### D-002 · Separate top-level `core/` and `models/` directories NOT created

**Decision:** The proposed structure listed `core/__init__.py` and
`models/__init__.py` at the top level. These directories are **not**
created.

**Rationale:** `track2data/core/models.py` already contains fully
implemented Pydantic v2 models (`ProjectManifest`, `Session`,
`PreprocessConfig`, `MetricSelection`, etc.) with 200+ passing tests.
Creating shadow top-level `core/` and `models/` directories would
fragment the canonical data model and break all existing tests.

The engine package (`track2data/`) is the single source of truth for
all data models.

---

### D-003 · No `qasync` in Phase 1 (or any v1.0 phase)

**Decision:** `qasync` is not used anywhere in v1.0.

**Rationale:** `TECHNICAL_SPEC.md §3.3` defers `qasync` to v1.1.
`ROADMAP.md` lists it explicitly in "Out of MVP". QThreadPool
(I/O-bound tasks) + ProcessPoolExecutor (CPU-bound preprocessing and
metrics) cover all async needs for v1.0 without the added complexity
of async/await bridging in Qt.

---

### D-004 · `ProjectStore` implemented in `app/state.py` for Phase 1 — CLOSED

**Decision:** `ProjectStore` (QObject with signals) lives in
`app/state.py` for Phase 1.

**Rationale:** The user's Phase 1 structure specifies `app/state.py`.
The spec (`UI_DESIGN.md §4`) describes `ProjectStore` as a
`ui/store/project_store.py` component, but that split is a Phase 3
(M3) detail. For Phase 1, placing it in `app/state.py` keeps things
simple and matches the proposed layout.

**Future:** Will be refactored to `ui/store/project_store.py` +
`ui/store/task_runner.py` in Phase 3 when the full signal surface is
wired to actual engine calls.

**Closed (issue #27, M3):** `ProjectStore` now lives in
`ui/store/project_store.py`, moved as its own isolated commit once
`ui/store/task_runner.py` existed for it to own and forward signals
from — deliberately *not* bundled with the new `tasks`/`run_results`
wiring, so a regression is trivially `git bisect`-able to "the move"
vs. "the wiring". `app/state.py` keeps a deprecated re-export
(`from ui.store.project_store import ProjectStore`) rather than being
deleted outright, since `app/main_window.py` and pre-existing tests
still import from the old path; verified as a genuine re-export (not
a duplicate class) by an identity check
(`test_app_state_is_a_genuine_reexport_not_a_duplicate`). All
pre-existing `ProjectStore` tests in `test_app_smoke.py` pass
unmodified — the proof the move itself preserved behavior.

---

### D-005 · 10 placeholder screens, 7 sidebar stages

**Decision:** The `QStackedWidget` holds 10 placeholder pages (matching
the 10 screen files); the `WizardSidebar` shows 7 stages (matching PRD
§14). Sidebar clicks jump to each stage's first page; Back/Next toolbar
buttons navigate linearly through all 10 pages.

**Mapping (stage → first page index):**

| Stage | Label | First page |
|---|---|---|
| 0 | Project | 0 |
| 1 | Sessions | 1 |
| 2 | Calibration | 2 |
| 3 | Zones | 3 |
| 4 | Metadata | 4 |
| 5 | Preprocessing & Metrics | 5 |
| 6 | Preview & Export | 8 |

Sub-screens 6 (Metrics), 7 (Processing), and 9 (Export) are reached
via the Next button from their parent stage screens.

---

### D-006 · Screen files flat in `ui/` (not in `ui/pages/`)

**Decision:** All screen widgets live directly in `ui/*.py`, not in a
`ui/pages/` subdirectory.

**Rationale:** The Phase 1 target structure specifies flat `ui/*.py`.
`TECHNICAL_SPEC §4` and `ROADMAP M3` mention `ui/pages/` but that
subdirectory is a Phase 3 refinement. The flat layout is specified
explicitly in the Phase 1 instruction and is preserved.

---

### D-007 · GUI launched via `track2data-gui` console script

**Decision:** The desktop GUI is launched as `track2data-gui` (a
`pyproject.toml` console script pointing to `app.main:main`). The
existing `track2data` script remains the headless CLI.

**Rationale:** Keeps the CLI and GUI entry points cleanly separated.
Users who install only `track2data` (engine only) get the CLI. Users
who install `track2data[ui]` additionally get `track2data-gui`.

---

### D-008 · `PySide6>=6.6` added as `[ui]` optional dependency

**Decision:** PySide6 is declared under `[project.optional-dependencies]
ui = ["PySide6>=6.6"]`. Engine tests do not require PySide6; UI smoke
tests guard with `pytest.importorskip("PySide6")`.

**Rationale:** TECHNICAL_SPEC §10.1: "the engine is importable without
PySide6 so headless / notebook users have a small install."

---

### D-009 · `pytest-qt` added to `[dev]` extras

**Decision:** `pytest-qt>=4.0` added to the `dev` optional dependency
group so UI tests can create `QApplication` instances safely.

**Rationale:** pytest-qt handles `QApplication` lifecycle and headless
display configuration, preventing test suite crashes on CI without a
display server.

---

## Phase 2 — Metadata + remaining metrics (M2)

### D-010 · Metadata join excludes `individual_id` and `session_id`

**Decision:** `Engine._metadata_fields_for()` never merges a
metadata-sourced `individual_id` or `session_id` value into
`build_fish_by_frame()` or metric result frames, even when the user's
`MappingRule` maps a column (e.g. `fish_id`) to canonical
`individual_id`.

**Rationale:** `metadata.join.match()` matches at the **session**
level only (`match(session_ids: list[str], df, rule)` — no per-individual
key). So `JoinResult.matched[session_id]` is a single dict of field
values broadcast to *every* row of that session. If `individual_id`
were included, every row would get the *same* constant value,
silently overwriting the real per-row fish index
(`0..n_animals-1`, assigned in `build_fish_by_frame()` from
trajectory shape) that every downstream metric and export depends on.
That's not a missing feature — it's active data corruption disguised
as a metadata attribute. Excluding `session_id` too is defensive: it
should already equal the session being merged into given how `match()`
works, but there's no reason to let a mapped column silently override
an identifier this central.

**Alternative considered:** Support genuine per-individual metadata
(e.g. real per-fish IDs from ear-tag records) by extending `match()`
to accept `(session_id, individual_id)` composite keys. Rejected for
now — no current call site needs it, and `CANONICAL` already reserves
`individual_id` for this future use per `ENGINE_DESIGN.md §8.1`
("individual_id where applicable"). Revisit if per-individual metadata
becomes a real requirement; until then, the exclusion is the safe
default.

### D-011 · Metadata join is loaded once per `Engine` instance and cached

**Decision:** `Engine._metadata_join` is a `functools.cached_property`,
not recomputed per session.

**Rationale:** `run_all()` constructs one `Engine` and calls
`run_session()` once per manifest session; the same metadata file,
mapping, and join result apply to all of them. Recomputing per call
would re-read and re-parse the metadata file for every session for no
benefit. The cache is invalidated only by constructing a new `Engine`
(manifests are otherwise treated as immutable within an Engine's
lifetime, matching how `self._manifest` itself is never mutated
in-place elsewhere in this class).

### D-012 · `identity_free.py` deleted; `idtrackerai_v4` entry point removed

**Decision:** `track2data/metrics/identity_free.py` (a 4-line stub —
docstring plus `from __future__ import annotations`, no code) is
deleted, along with its lazy-import line in
`metrics/__init__.py::_load_builtins()`. Separately, the
`idtrackerai_v4` entry in `[project.entry-points."track2data.readers"]`
is removed from `pyproject.toml`; the `IDTrackerAiV4Reader` class
itself is untouched and still registered as a built-in directly in
`readers/__init__.py`.

**Rationale (metrics):** GL-7 ("NN-Matched Speed" — identity-free speed
via greedy nearest-neighbour assignment) was already fully implemented,
tested, and registered as `NNMatchedSpeed` in `metrics/group.py`. The
stub file was never filled in; nothing pointed to it. Moving the
already-working GL-7 implementation into `identity_free.py` for the
sake of the filename matching the metric's category would be pure
churn — re-wiring imports and registration order for zero functional
change — for a class that works correctly where it already lives.
Deleting dead placeholder code is safer than shuffling working code to
satisfy a naming expectation nothing else depends on.

**Rationale (idtrackerai_v4):** `IDTrackerAiV4Reader.detect()` is
hardcoded to return `False` unconditionally ("disabled until
implemented" per its own comment), so `detect_reader()` can never
select it — the `NotImplementedError` in `read()` is unreachable in
normal operation. Advertising it as a *live* entry point (as opposed
to the built-in registration every reader already gets in
`readers/__init__.py`, entry points or not) misleads anything that
enumerates `track2data.readers` externally into thinking it's a
working reader.

**Alternative considered:** Implement real v4 support instead of just
hiding the gap. Rejected for now: there is no idtracker.ai v4 sample
data anywhere in this repo to validate against (the 70-session
`Checked sessions GOT/` corpus is v6.0.13) — implementing format
support with no real fixture to test against would be speculation, not
engineering. Revisit if v4 sample data becomes available; re-add the
entry-point line at that point, not before.

### D-013 · `core/parallel.py` and `cache/store.py` stay unwired for now — CLOSED

**Decision:** `Engine.run_all()` continues to loop over sessions
sequentially rather than calling `core/parallel.map_sessions()`.
`cache/store.CacheStore` continues to be reachable only via
`track2data cache clear`, not from anywhere in the actual
import → preprocess → metrics → export pipeline. Both modules are
fully implemented and tested; neither is being deleted or considered
dead code — they're deferred because what they'd plug into isn't
ready for them yet, not because parallel execution or caching are bad
ideas.

**Rationale (parallel):** `run_all()` currently calls
`run_session(sess, out_dir, ...)` for *every* session with the *same*
`out_dir` — each session's output files silently overwrite the
previous session's (tracked as #2, "run_all silently overwrites output
when a manifest has 2+ sessions"; #19 covers the proper fix, giving
each session its own output subdirectory). Wiring in
`ProcessPoolExecutor`-based parallelism on top of a loop that already
destroys all but the last session's output the moment it goes multi-
session would be worse than useless — N workers would race to
overwrite the same files instead of one process doing it sequentially
and predictably. The output-collision bug is a correctness prerequisite
for parallelism to mean anything, not a detail to patch as a side
effect of this decision; #19 needs its own fix and its own tests.
Once that lands, `map_sessions()` should map over session *folder
paths* (cheap to pickle, re-imported fresh inside each worker) rather
than already-imported `Session` objects (which carry large in-memory
NumPy trajectory arrays) — worth re-litigating at that point, along
with the Windows `spawn`-vs-`fork` re-import cost this codebase hasn't
measured yet.

**Rationale (cache):** `CacheStore.put()`/`.get()` operate on a single
flat `pd.DataFrame`, keyed by `(reader_name, folder_hash,
config_hash)`. `PreprocessedSession` — the thing worth caching, per the
PRD's "iterative re-analysis using cached intermediates" use case — is
not a DataFrame: it's a dataclass carrying `xy`, a `KinematicsArrays`
(three more arrays), optional `main_zone`/`sec_zone` arrays, and a
`PreprocessReport`. Wiring `CacheStore` into `Engine.preprocess()`
needs a real serialization contract between that shape and something
Parquet-representable (or extending `CacheStore` to cache pickled
dataclasses directly, sidestepping Parquet) — an API design question,
not a missing function call. Deferred until that's designed
deliberately, with its own tests, rather than improvised here.


**Closed (critical-issues audit):** the cache is wired in by D-019 and parallel runs by D-020.

---

## Phase 3 — GUI wiring (M3)

### D-014 · `Engine.run()` accepts `n_workers` but only implements `n_workers=1` — CLOSED

**Decision:** `Engine.run(out_dir, exporters=None, *, progress=None,
n_workers=1)` accepts an `n_workers` parameter (per issue #19's
design) but only the sequential path is implemented. Passing
`n_workers > 1` logs a warning and runs sequentially anyway rather
than raising or silently ignoring the request.

**Rationale:** D-013 named the per-session `out_dir` collision as the
prerequisite blocker for reconsidering `core/parallel.map_sessions`.
`Engine.run()` (this decision's own change) fixes exactly that
prerequisite — each session now writes to `out_dir/<session_id>/`. But
actually wiring `ProcessPoolExecutor` correctly still needs: a
`ProgressCallback` that's picklable across the process boundary (a
bound method or closure capturing Qt objects is not), `map_sessions`
mapping over session *folder paths* rather than already-imported
`Session` objects per D-013's own note, and real testing of Windows
`spawn` semantics against this specific pipeline. That's substantially
more risk than the rest of this change combined. Accepting the
parameter now (rather than adding it later, which would be a breaking
signature change for `TaskRunner` and anything else that calls
`Engine.run()`) costs nothing; implementing parallel execution behind
it is deferred to its own properly-tested change.

**Alternative considered:** Omit `n_workers` entirely until parallel
execution is actually implemented. Rejected — issue #19 specifies it
as part of `Engine.run()`'s signature, and `ui/store/task_runner.py`
(issue #20) is being built immediately after this and will call
`Engine.run()`; adding the parameter now avoids a second signature
change once parallel execution does land.


**Closed (critical-issues audit):** `n_workers > 1` now runs in a spawn process pool; see D-020.

---

## Phase 4 — Critical-issues audit

### D-015 · Body-length normalisation is computed in pixel space

**Decision:** `*_bl` metric columns are `value_px / body_length_px[k]`
and no longer depend on `px_per_cm`. `PreprocessedSession.body_length_px`
is set by body-length calibration; `body_length_in_px()` falls back to
`body_length_cm * px_per_cm` for sessions that only carry physical units.
`body_length_cm` keeps its legacy behaviour (pixel values in bodylength
mode) so existing consumers do not change.

**Rationale:** Body Length mode is the recommended mode and leaves
`px_per_cm` unset, so nesting `_bl` under `px_per_cm is not None` made
every `_bl` column NaN. The old tests built sessions with both values,
a combination no calibration path produces, and hid the defect.

**Alternative considered:** Rename `body_length_cm` to pixels outright.
Rejected for now — it touches exporters and the public `Session` contract;
revisit in a separate change.

---

### D-016 · Zone metrics on identity-free sessions: pool occupancy, gate sequences

**Decision:** Z-1, Z-2 and Z-8 set `pools_when_identity_free`; for an
identity-free session `Engine.compute_metrics` runs them on
`metrics.zone.pooled_view()` (all slots stacked into one track) and drops
`individual_id`. Z-3, Z-4, Z-5, Z-6, Z-7 and Z-9 become
`requires_identity = True` and are skipped by the existing gate.

**Rationale:** On such a session the row index is a detection slot, so
anything built from visits, events or sequences per slot is an artefact
of slot swaps. ROADMAP had planned to pool Z-3, Z-5 and Z-9 too, but
visit counts, events and dwell times are sequence-based, not occupancy,
so pooling them would still publish artefacts. Pure occupancy is exact
under pooling.

**Alternative considered:** Pool every zone metric (the earlier ROADMAP
plan). Rejected for the reason above.

---

### D-017 · Parameter screens auto-commit; no Apply buttons

**Decision:** `ui/widgets/autocommit.py::AutoCommit` debounces widget
changes (200 ms) into the screen's commit method. Screens expose
`flush()`; `MainWindow._go_to_page` and `_action_validate` call it on the
outgoing screen. Screens populate from the store when built and suppress
triggers while populating. Commits use `model_copy` on the current config
and are skipped when nothing changed.

**Rationale:** An unclicked Apply button silently dropped edits. A
dirty-bar ("Apply / Discard") was the alternative, but every setting here
is cheap and reversible, so saving continuously is simpler and safer.

**Alternative considered:** Warn on leave with Apply/Discard. Rejected as
more friction for no safety gain.

---

### D-018 · Cheap session probe via `SessionReader.probe()`

**Decision:** `SessionReader.probe(folder)` (default: `read()`) returns the
facts the GUI shows. The unified idtracker.ai reader overrides it to skip
bbox tables, matching results, inconsistent frames, fragments and the
log. `ProjectStore` probes through `readers.probe_session` on import and on
project open.

**Rationale:** The trajectory payload is still read: `has_stable_identities`
falls back to NaN coverage, so identity status needs it, and the pickled
`.npy` payload cannot be memory-mapped. Skipping the other artefacts is the
safe saving; a payload-free probe would need format-specific work and a
different identity heuristic.

**Not done:** probes still share the single-thread `TaskRunner` pool with
pipeline runs.

---

### D-019 · Preprocessed sessions are cached as pickled dataclasses (closes D-013's cache half)

**Decision:** `CacheStore` gets `get_object`/`put_object` (atomic pickle,
`.pkl`). `Engine` caches the whole `PreprocessedSession` after
preprocess + calibration + zones, keyed by reader name, a folder
fingerprint (relative path, size, mtime of every file) and a hash of the
preprocess, calibration and zone configs plus a schema number and app
version. It is opt-in via `Engine(cache_dir=...)`; the GUI passes
`<project>/.t2d_cache`. A cache hit skips import, preprocessing,
calibration and zone assignment.

**Rationale:** D-013 left a choice of Parquet or a pickled dataclass; the
dataclass holds ragged arrays, zone object arrays and a nested pydantic
`Session`, which Parquet would force into an invented schema. The folder
is fingerprinted rather than hashed because reading gigabytes to decide
whether to read them defeats the point.

**Trade-offs:** mtime/size can miss an edit that preserves both (rare);
bump `Engine._CACHE_SCHEMA` when `PreprocessedSession` changes. Metrics
and exports are still recomputed on every run. Pickles are only loaded from
the project's own cache directory.

**Alternative considered:** Parquet per array. Rejected for the schema
cost above.

---

### D-020 · Parallel session runs and in-session cancellation (closes D-013/D-014's parallel half)

**Decision:** `Engine.run(n_workers=N>1)` uses a `ProcessPoolExecutor` with
the `spawn` context on every OS. Workers receive only the manifest JSON, a
session index, the output directory, exporter names and the cache path;
they rebuild an `Engine`, send `ProgressEvent`s through a `multiprocessing`
queue and read a shared cancel `Event`. The calling process drains the
queue and invokes the caller's `progress` callback, so Qt closures never
cross the process boundary. A worker that is cancelled returns `None`
(custom exceptions do not reliably unpickle). Results come back in manifest
order. Default stays `n_workers=1`.

Cancellation is a separate `cancel_check: Callable[[], None]` argument, not
extra progress events: existing tests and the GUI bar rely on progress being
sparse and stage-boundary only. The engine calls it between sessions,
preprocessing steps and metrics; in a parallel run the parent polls it and
sets the workers' flag. `TaskRunner.submit_with_progress(fn, cancel_check=True)`
passes the task's token.

**Trade-offs:** start-up per worker is roughly 0.6 s (imports), so small
sessions get slower; the benefit is for sessions taking many seconds each.
Not yet benchmarked on the real corpus. Memory is per-worker. A step inside
one numpy/shapely call still cannot be interrupted. `Engine` now holds the
run's `cancel_check` on the instance for the duration of `run()`, so one
Engine must not run two `run()` calls concurrently.

**Alternative considered:** Threads. Rejected: the metrics and shapely loops
hold the GIL.

---

### D-021 · Stage status is computed from the manifest; only required pages gate Next

**Decision:** `ui/store/stage_status.py::compute_stage_statuses` derives a
status per page from the manifest (and whether results exist). `MainWindow`
recomputes it on every store change, paints the sidebar and enables Next
only if `next_blocker()` is None. Required pages are Project, Sessions and
Metrics (when empty); a `blocked` page (invalid calibration) always blocks.
Sidebar clicks stay ungated.

**Rationale:** Zones, metadata and export targets are optional, and result
pages are produced by running; gating them would trap users. Keeping the
rules in a Qt-free function makes them unit-testable.

**Alternative considered:** Gate sidebar clicks too. Rejected: users need
to jump back to fix a problem shown by a badge.

---

### D-022 · Trajectory viewer is drawn with Qt graphics items, not pyqtgraph

**Decision:** `ui/widgets/trajectory_view.py` renders trails, markers, zones
and the heatmap with `QGraphicsView`, the same stack as the zone canvas.
No plotting dependency is added.

**Rationale:** The audit proposed pyqtgraph. The viewer needs paths over an
image with a scrubber, which graphics items already do, and a new
dependency would also need PyInstaller hidden-import work on three
platforms. Trails are strided to at most 1500 points each.

**Trade-off:** no built-in axes, ROI tools or GPU acceleration. If time
series plots (e.g. speed vs time with a live filter preview) are added
later, pyqtgraph can be reconsidered for those alone.

---

## Phase 5 — Open items after the critical-issues audit

### D-023 · Task lanes: probes get their own pool and their own signals

**Decision:** `TaskRunner` owns one single-thread pool per lane (`run`, `probe`).
Probe-lane tasks emit `probeFinished/probeFailed/probeCancelled` and none of the
generic `task*` signals. `cancel_all(lane=...)` can target one lane; the Cancel
button, Processing and Export screens pass `lane="run"`. A task whose token is
already cancelled never starts. `shutdown()` waits on both pools against one
deadline.

**Rationale:** Extends D-003. A separate pool alone was not enough: the main
window listens to the generic signals to enable Cancel and to show a modal
failure dialog, so a probe finishing during a run would have disabled Cancel
mid-run. Using different signals fixes that without touching the main window.

**Trade-offs:** probes still do not poll their token while running (a probe is a
single reader call), so cancelling only stops probes that have not started yet.
Run and probe lanes can read the same session files concurrently; both are
read-only and only the run lane writes the cache.

---

### D-024 · Timepoint binning by slicing, with whole-session config resolution

**Decision:** Binning is done in the engine, not in metrics. `metrics/binning.py`
cuts the session into windows of true video time (`bin_index = floor(time_s /
bin_length)`, empty bins skipped, partial last bin keeps its real end) and
`Engine.compute_metrics` runs each metric on a sliced copy of the
`PreprocessedSession`, then stacks the results with `bin_index`, `bin_start_s`,
`bin_end_s`. `Metric.resolve_for_windows(session, cfg)` lets a metric resolve
data-derived config (IL-4/IL-7 threshold, bout criterion for IL-7 and Z-3/4/5)
on the whole session once; `Metric.window_safe = False` (IL-5, IL-9) keeps a
metric whole-session with NaN bin columns; diagnostics are never binned.

**Rationale:** The alternative, giving every metric a time range, touches 40
metrics. Slicing works because metrics only read per-frame arrays plus fps and
calibration. Without whole-session resolution a data-driven threshold would
differ per window and per-bin values would not be comparable (a one-bin run
would also not equal the unbinned run; a test pins that).

**Names:** the columns are `bin_*`, not `timepoint`, because `timepoint` is a
canonical metadata field (metadata/schema.py) and the two must coexist.

**Trade-offs:** diff-based metrics lose one step per bin edge; Z-6 is a latency
from bin start; `timepoint_minutes` became a float so tests and short sessions
can use sub-minute bins. Binning multiplies metric time by the number of bins
only for the slicing overhead, not for the computation itself.
