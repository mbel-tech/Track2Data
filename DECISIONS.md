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

### D-004 · `ProjectStore` implemented in `app/state.py` for Phase 1

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
