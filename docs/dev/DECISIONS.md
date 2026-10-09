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

### D-010 · Metadata join excludes `individual_id` and `session_id` — SUPERSEDED by D-025

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
itself is untouched (see the second addendum: it is no longer registered).

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

**Addendum (offline prep):** a conservative `looks_like_v4()` heuristic now makes
`read_session`/`probe_session` raise `V4_NOT_SUPPORTED` rather than `NO_READER`;
`detect()` still returns False and no entry point is added. The inspector script and
`docs/IDTRACKERAI_V4_SAMPLES.md` exist so real samples can be gathered.

**Second addendum (pp3 and #101 reconciled):** the class is not registered as a
built-in any more. Its `detect()` is always False, so registering it could never
select it, and a registered class whose only behaviour is to raise is worse than an
absent one. The module keeps the class (a test pins `detect() is False`) and
`looks_like_v4`, which `read_session` and `probe_session` use to raise
`V4_NOT_SUPPORTED`.

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

**Addendum (scan lane):** a third lane, `scan`, carries the read-only scan that precedes
adding sessions (D-027). It reports progress on `scanProgress`, ends on `scanFinished`,
`scanFailed` or `scanCancelled`, and never touches the generic or probe signals, so a failed
or cancelled scan is shown inline by the confirm dialog rather than as the pipeline-failure
modal, and a long scan neither waits for a run nor delays a probe. `ProjectStore.scan_folders`
submits it with a cancel check and drops its result if the project changes meanwhile.

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

---

### D-025 · Per-animal metadata (supersedes D-010)

**Decision:** When the mapping gives `individual_id`, the join becomes
per-animal. `metadata/join.py` groups a session's rows by normalised animal key
(`1`, `1.0` and `" 1 "` are the same animal); a repeated animal is a conflict
(the first row is kept), several animals per session are not. Fields constant
across the session's rows are session-level (`JoinResult.matched`, applied to
every frame); everything else is per-animal (`matched_individuals`, applied only
to frames with an `individual_id` column, NaN for an animal without a row).
Keys are matched to animals per loaded session (`resolve_animal`): by the
validator's identity label (case-insensitive) or, with no labels or with
`MappingRule.individual_match="index"`, by 0-based position.
`MappingRule.extra_columns` carries further columns by name; a metadata column
never overwrites a column the frame already has, and names the engine writes
itself are refused at mapping time. Identity-free sessions get no per-animal
values (a row index there is a detection slot).

**Rationale:** D-010 rejected this only because no call site needed it; the
Metadata screen now does, and per-animal covariates (weight, sex) were the main
thing users had to join by hand. The hazard D-010 named (an `individual_id` from
metadata overwriting the real index) is avoided because the metadata key is
never written to `individual_id`; it only selects which animal's values to use.

**Trade-offs:** With default labels `1..N` and a CSV counting from 0, "label"
mode matches the wrong animals silently, so the screen names the mode and the
guide says when to use each. A column constant across a session is treated as
session-level, so for an animal without a row it is still set from the session.
Unmatched animals and keys are logged once per session, not per frame.

---

## Phase 6 — Importing output from other trackers

The design is in `docs/tracker-formats/`; these are the decisions the first tier built.

### D-026 · The reader a session was added with is saved, replayed, and never silently replaced

**Decision:** `SessionRef` records `reader` (a registered reader's `name`),
`reader_options` (what the user gave it), `reader_chosen_by` (`detected` or `user`)
and `reader_confidence`. `Engine.import_ref` replays exactly that reader with those
options; an entry that records none (every project saved before this) is detected as
before. A saved reader that is not registered here fails with `READER_NOT_AVAILABLE`
and is **never** replaced by auto-detection. The preprocessed-session cache (D-019)
is keyed by the saved reader and its options, and a session probe (D-018) uses them.
The session id comes from the manifest entry, not from the reader.

**Rationale:** Another reader can turn the same files into different numbers, so
"fall back to whichever reader detects it" would change a project's results with no
warning, on the machine that happens to lack a plug-in. The user confirmed the
software once; the project should not ask a heuristic again. Reader `name`s are
therefore manifest API and are frozen once released.

**Alternative considered:** Detect on every use (the previous behaviour). Rejected:
it is slower on a folder of folders, and it cannot work for formats that need options
the files do not record.

**Trade-offs:** The manifest stays `schema_version=1` (the fields are additive), but
`project_hash()` changes once for every project. A project opened where a plug-in is
missing cannot run that session until the plug-in is installed or the session is
removed and added again.

---

### D-027 · Scanning is read-only, bounded, and never unpickles

**Decision:** `track2data scan`, `Engine.scan` and the confirm dialog look at a folder
with one `os.scandir` walk into an immutable `ScanIndex`; each reader's `discover`
is a pure function of that index. The only code that opens a file is `Peeker`, and it
reads headers only (head bytes, CSV header rows, a `.npy` header through
`np.lib.format`); it never unpickles and never writes. Folders a reader has claimed
are not looked into again, and the walk stops at a budget (100,000 entries, 30 s,
4 levels by default) with `truncated=True` rather than raising. Files that exist
only in the cloud (OneDrive placeholders) are never opened, because opening one
downloads it.

**Rationale:** The user points at a folder and expects an answer in a second, from
folders that may hold gigabytes, sit on a sync client, or have been sent by someone
else (SECURITY.md). Detection must therefore be cheap, side-effect free and safe
by construction rather than by care.

**Trade-offs:** A reader cannot decide from file *contents* beyond a header. A tree
nested deeper than four levels needs `--max-depth` (the CLI says so when it finds
nothing).

---

### D-028 · What the files do not record is asked for as an option, not read from a sidecar

**Decision:** Most trackers record neither the frame rate nor the frame size
(DeepLabCut, SLEAP, Anipose, AnimalTA, Ctrax). A reader declares them as
`ReaderParameter`s; the confirm dialog or `--option NAME=VALUE` supplies them; they
are saved on the session and passed to `read(..., options=...)`. A required option
that is missing is `READER_OPTION_MISSING` and **never** a default. Nothing is
written into the input folder (FR-IMP-5). Where a file or a neighbouring file does
record a value, the dialog is pre-filled and says where it came from.

**Rationale:** A made-up frame rate silently scales every speed, acceleration and
path-length metric. A sidecar file in the input folder would modify data the user
considers read-only and would not travel with the project.

**Alternative considered:** Default to 30 fps with a warning. Rejected for the reason
above.

---

### D-029 · Amends D-012: text readers may ship unverified, binary containers need a real sample

**Decision:** D-012 refuses to implement a format "with no real fixture". For
importers of other trackers, a reader for a **text or CSV** layout that is documented
in enough detail may ship before a real sample is found, provided it declares
`verification = "synthetic_only"`: the confirm dialog shows an "unverified" badge,
`list-readers` says so, the export's provenance records it, and a pre-flight warning
repeats it. A reader for a **binary container** (HDF5, MAT, NPZ, SQLite) needs a real
sample, because its layout cannot be guessed from documentation. A reader is
`real_sample` only when a pinned real file is part of its test suite.

**Rationale:** A wrong CSV parser fails loudly on the first row; a wrong HDF5
dataset path or axis order can produce plausible, wrong numbers. The label puts the
residual risk in front of the person who can check it against their own tracker.

---

### D-030 · D-5 says "not assessed" for a tracker that reports no identification quality

**Decision:** The identity-stability diagnostic (D-5) used to treat a missing
`fraction_identified` as 0.0, so every session from a tracker that does not report one
read "weak". A reader that never supplies it (`provides_identification_quality =
False`) now gets `not_assessed`. Separately, the pre-flight note about body-length
calibration is driven by whether the session actually carries a body length, not by
the reader's declared flag.

**Rationale:** "Weak" is a claim about the tracking; for these trackers nothing was
measured. Driving the note from the data keeps it right for an idtracker.ai session
whose trajectory lacks the key.

---

### D-031 · Accepted for the tiers not yet built (pose, native units, fragments, 3-D)

**Status:** accepted; not implemented. The reasoning is in
`docs/tracker-formats/2026-10-07-tracker-import-design.md` §4.6-4.9.

**Decision:** *Pose.* One keypoint (the user's choice; default the best-covered)
drives the metrics; the full skeleton is kept on the session, stored only, and no
metric consumes it. The animal's position is never the mean of the visible
keypoints, which jitters whenever the visible set changes. *Units.* A source with no
pixel frame (Anipose, ToxTrac RealSpace without its pixel twin) gets a native-unit
mode; a scale a tool applied (TRex `cm_per_pixel`, ToxTrac RealSpace) only rebuilds
true pixels and is never presented as a physical unit without the user's confirmation,
and a factor of exactly 1.0 or a default arena counts as uncalibrated. *Fragments.*
A tracker whose identities are track fragments (Ctrax) keeps every fragment as its own
slot and is flagged identity-free; keeping only the N longest is an opt-in. *3-D.*
Metrics use a chosen 2-D plane (default x, y); z is kept.

**Rationale:** These are the places where a reader could report plausible but wrong
physical quantities. Recording them before the readers exist keeps each reader's
review about the format, not about re-deciding the policy.

---

### D-032 · One row-to-frame timeline; zone events and latency follow it

**Decision:** Which video frame a stored trajectory row is comes from one place,
`PreprocessedSession.timeline()` (built on `core/timeline.py`): the per-frame table,
time bins and the zone events all use it, and a window cut from a session carries its
rows' original frames. Z-5 reports the original `frame` and `t_s = frame / fps`, as the
per-frame table does. Z-6 keeps its meaning, time since the start of tracked observation,
but says where that is (`origin_frame`) and counts time omitted between tracking intervals
as elapsed time. Each unbroken stretch of video is read on its own: no exit is invented
where observation stops, the first observed frame in a zone after a gap is an enter flagged
`after_gap`, and Z-9 drops a visit that began in a gap. Malformed or non-reconciling
intervals fall back to the row position with a logged warning, and an array that already
spans the whole timeline is not expanded twice.

**Rationale:** Two clocks for one observation made event logs disagree with the trajectory
by the tracking start (40 s in the reported case) and by every omitted span. Redefining
latency as absolute video time would have silently changed a published meaning, so the
origin is explicit instead. Z-4 and Z-7 still count a transition between the last zone of
one interval and the first of the next; that is a known limit, not yet addressed.

---

### D-033 · The quality grid separates choice from failure and counts crossings by frame

**Decision:** D-5 keeps its `identity_stability_status` values and adds
`identity_free_reason` (`declared`, `low_identification`, `unknown`, `not_applicable`) and
`identified_fraction`; the user's Identity-free tick counts as `declared`. The Preview grid
leaves `declared` and `not_applicable` unjudged and flags the others. D-8 keeps
`crossing_frame_fraction` (a share of fragment duration, which falls as the group grows)
and adds `crossing_unique_frame_fraction` (frames with a crossing over tracked frames); the
grid uses the new one with the limits that were already written for a share of frames.

**Rationale:** `identity_free` meant both "tracked without identities on purpose" and
"identification failed", so a 10 % identification session read Good. Adding fields rather
than changing existing values keeps every consumer of the old columns working.

---

### D-034 · No usable data is NaN, not zero (IL-1, IL-7)

**Decision:** IL-1 reports NaN when an animal has no valid pair of consecutive positions,
and IL-7 reports NaN count and durations when it has no usable speed. Valid data with no
movement or no qualifying bout stays 0, and the mean duration with zero observed bouts keeps
its historical 0.

**Rationale:** An empty sum is 0.0, which reads as "did not move" for an animal that was
never tracked; if tracking failures differ by condition, that biases group comparisons.

---

### D-035 · Gaps between tracking intervals: real time, a separator, optional bridging

**Decision:** A session stored as tracking intervals is put on real elapsed time before any
temporal step. Each unobserved stretch becomes either rows (bridged: one per missing frame,
a straight line between the animal's last and next observed positions) or a single all-NaN
separator row, so no step reads two intervals as adjacent frames. Bridging is off by default
(`GapFillCfg.across_tracking_intervals`), limited to `max_cross_interval_gap_s` (30 s) counted in
real missing frames, requires stable identities (and no identity-free override) and an observed
anchor on both sides per animal, never extrapolates, and is refused outright when the rebuilt arrays
would exceed 50 million cells. The tracker's own `Session` stays compact; the processed session
carries `frame_index`, `tracked_mask`, `separator_mask` and row-aligned raw positions and
identification probabilities. Inserted rows are `was_interpolated`, `in_tracking_interval = false`,
and have NaN confidence; separators are never exported. Distance, speed, activity and zone time
include estimated frames, which D-11 counts and Z-5 flags (`estimated`).

**Rationale:** The compact array made the move between two stationary stretches look like
~1,060 px/s, and every derivative (smoothing, speed, acceleration) inherited it. Rebuilding only the
gaps the user chose keeps memory bounded, keeps an estimate visibly an estimate, and leaves a
contiguous session byte-for-byte on its old path.

---

### D-036 · Camera view is a project setting; depth is IL-15, measured against the main zones

**Status:** accepted; implemented. Design: `docs/3d-movement/2026-10-08-side-view-depth-design.md`
(sub-project C of `docs/3d-movement/2026-10-08-3d-roadmap.md`). The unmerged
`feat/native-units` branch also numbered a decision D-032, which `main` has since used for
something else, so that branch needs renumbering when it lands. It does not change D-031: 3-D
data still reduces to a chosen plane.

**Decision:** *Setting.* `ProjectManifest.scene.camera_view` is `unknown` (default), `top` or
`side`, declared once on the Calibration screen. It is top-level, not inside `ZoneSet` (the Zones
screen replaces that object on Clear/Load/Import) nor `CalibrationConfig` (hashed into the
preprocessing cache key, which a view never changes). *Gate.* A metric names the views it is
meaningful for in `Metric.valid_camera_views` (a set; `None` = any). A metric the view rules out
is greyed, skipped with a reason that reaches the run README, and never silently computed on the
wrong axis. *Existing metrics are deliberately not gated:* IL-3 and IL-14 assume a top-down view,
but gating them would change what existing projects get. *IL-15, not Z-10.* Exports bucket
metrics by ID prefix and the UI by level, so an individual-level metric must be IL-xx; Z-10 is
re-reserved for auto depth bands. *Depth.* 0 = water surface, 1 = tank floor. The water column is
the vertical span of every main-level "+" zone pooled (not per animal like IL-3), and when there
is none the values are empty with a stated reason, never the video frame. Frames outside the
column are dropped and counted, never clipped. *Zones canvas.* The blank Zones canvas is the size
of the video frame, and the first zone saved records it (`source_*_px`); a zone set that already
holds zones is never stamped.

**Rationale:** Without a declared view, "depth" on a top-down recording would be computed from a
meaningless y axis and look plausible. Clipping would manufacture "at the surface" and "at the
floor" occupancy out of reflections and tracker noise. The canvas fix is here because depth is
only right if the zones are in the video's own pixels, which they were not for any tracker but
idtracker.ai.

**Unverified:** that an idtracker.ai session's `background.png` has the video's pixel size. The
Zones canvas for an idtracker.ai session is sized from that image, while the frame size the zone
set now records comes from the session. IL-3, IL-14, IL-15 and every zone metric already rested on
the two agreeing. The only idtracker.ai sessions in the repository are synthetic (`tests/conftest.py`
writes a placeholder PNG), so this could not be checked; check it on a real session before relying
on it, and if they differ, the recorded size would hide the discrepancy.

---

### D-037 · Project mode (2D or 3D) is a project setting, locked once sessions exist, and 3-D does not compute yet

**Status:** accepted; implemented. Design: `docs/3d-movement/2026-10-09-mode-switch-design.md`
(sub-project E of `docs/3d-movement/2026-10-08-3d-roadmap.md`). It does not change D-031 or D-036.

**Decision:** *Setting.* `ProjectManifest.mode` holds `dimension` (`2d` default, or `3d`), `layout`
(`single_video_two_panels` or `two_videos`; set if and only if the dimension is 3-D) and `id_map`.
It is separate from `scene`: `scene.camera_view` stays what one camera sees, and D gives each view
its own through `Engine.camera_view_for(session)`. Manifests without a `mode` key load as 2-D. *Lock.*
The mode cannot change while the project has any session ("Remove all sessions to change the
mode"); removing them unlocks it, because panel splits and ID maps built on a mode would otherwise
go stale. *No 3-D compute.* Until fusion (D) and 3-D metrics (B) exist, a 3-D project can be set up,
have sessions added and be saved, but nothing computes: Processing, Preview and Export are blocked
with "3-D fusion is not available yet". The gate is `Engine.require_computable()` and it covers
every compute entry point, including `compute_metrics` and the `sensitivity` command, not only
the screens, so the CLI and API cannot produce 2-D numbers for a 3-D project. *id_map.* Reserved
for sub-project G (ID correspondence between views); E never reads or writes it. (G replaced it by
`view_pairs` and `mode.pairing`; see D-038.) *Order.* E, then F
(panel split) and G in either order, then D, then B.

**Rationale:** Fusion, ID correspondence and 3-D metrics all need to know the dimension and the
recording layout first, and need it fixed before sessions exist. Running the 2-D pipeline on a
3-D project would give plausible but wrong results, so refusing at the engine is safer than
hiding buttons.

### D-038 · ID correspondence between views: G owns the pair record, pairing is by regex, and the Views page never blocks

**Status:** accepted; implemented. Design: `docs/3d-movement/2026-10-09-id-correspondence-design.md`
(sub-project G of `docs/3d-movement/2026-10-08-3d-roadmap.md`). Replaces the reserved `id_map` of D-037.

**Decision:** *Ownership.* G owns the pair record and the fish mapping: `ProjectManifest.view_pairs`
holds `ViewPair(top_session_id, side_session_id, same_ids, fish_map, auto)` and `SessionRef.view_role`
is `top`, `side` or unset. `mode.id_map` is removed (a manifest that still contains it loads, the key
is ignored) and replaced by `view_pairs` plus `mode.pairing` (`PairingPatterns`, a top and a side
regex, both empty by default). *Pairing.* Two regexes, searched in the session id, each with a `key`
group; sessions with an equal key pair up. An empty `key` means no match, and a key shared by several
sessions on one side is ambiguous and not paired. A session belongs to at most one pair. *Same IDs.*
A per-pair tick says fish with the same label are the same fish; otherwise the user matches by hand.
`fish_map` is the single authority (what D reads); `same_ids` only says the map was derived from equal
labels. While it is set the map is re-derived when new labels arrive; the tick is disabled until both
sessions' labels are known; any hand edit of the map clears it.
*Identity-free.* A session without stable identities cannot be matched; the pair is flagged "cannot
match fish: this session has no stable identities" (matching by geometry is not done). *auto.*
Applying the pattern again keeps the pairs it made earlier (`auto=True`) that it still produces, with
their matching, removes the ones it no longer produces, and never touches hand-made ones. A user change
to a pair (ticking or unticking Same IDs, editing the map) makes it hand-made (`auto=False`). *Navigation.* Views is page 10, belongs to the Sessions sidebar row, shows only in 3-D
and is reached by Next and Back between Sessions and Calibration; `PAGE_NAMES` keeps its ten entries.
*Gate.* Pairs never block Next (3-D cannot compute anyway); the Views status is never `blocked`.
*Status.* The Views status (`stage_status`) is manifest-only (roles, pairs, identity-free flags, a
non-empty map means matched) and drives the Sessions row: in 3-D that row shows the worse of the
Sessions and Views statuses. The page validates fish maps strictly (duplicate, unknown labels, counts)
against the sessions' labels.

**Rationale:** A fish mapping hangs off a pair of sessions, and one project-wide dictionary cannot
describe many pairs, so the pair record and its UI belong with the mapping. Regex pairing scales to
many trials, and the manual path covers names that follow no rule. Keeping hand-made pairs out of
re-pairing means a correction is never silently undone. Fusion (D) will be the stage that requires
complete pairs.
