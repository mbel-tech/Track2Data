# Metrics screen + MetricInfoDialog: full redesign

**Status:** Draft — awaiting user review
**Date:** 2026-08-21
**Relates to:** issue #26, `docs/UI_DESIGN.md` §5.6/§6.10, `docs/METRICS_SPEC.md` §6, `CONTRIBUTING.md` §7

## 1. Background

Issue #26 shipped a deliberately minimal `MetricInfoDialog`: a shared
"Metric info…" button below a `QListWidget`-based tab set, opening a
plain-text dump of whichever metric is `currentItem()`. That was a
conscious simplification to avoid a `QListWidget.setItemWidget()`
covering the item's native checkbox — a real risk with that widget.

`docs/UI_DESIGN.md` (§5.6, §6.10) and `docs/METRICS_SPEC.md` §6 still
describe a considerably richer target that was never built: a
`QTableWidget` with per-row ⓘ/⚙ columns, a `MetricInfoDialog` built
from a `Metric` instance (not an id string), a copy-citation button,
Escape/outside-click close, an icon-visibility rule, and
identity-aware/zone-tab graying. Per `CONTRIBUTING.md` §7 ("the spec
is the contract; code that diverges from spec is a bug"), this
divergence needs reconciling.

This document specs the **full implementation** path (as opposed to
the cheaper "just update the docs" path), per the decision to invest
in the richer design now.

### Investigation findings that shaped this design

- `Session.has_stable_identities` ([track2data/core/models.py:45](../../../track2data/core/models.py)) only
  exists on the fully-loaded `Session` object a reader produces. The
  persisted `SessionRef` ([models.py:175](../../../track2data/core/models.py)) that Stage 6 actually holds
  carries only `session_id` / `folder` / `sha256` — **no identity
  status reaches the Metrics screen today**, at all, for any project.
- The ⚙ per-metric config icon points at Screen 6.3
  (`docs/UI_DESIGN.md` §6.11), which does not exist as a screen, a
  `Metric` config schema, or any per-metric parameter concept anywhere
  in the codebase. There is nothing real for it to open.
- `ui/metrics_screen.py`'s row source (`_INDIVIDUAL_METRICS` /
  `_GROUP_METRICS` / `_ZONE_METRICS`, hardcoded lists) does not use
  `metrics.registry.list_for_level(...)` as the spec requires — a
  second, independent divergence from the same file.
- `ProjectStore.add_session()` ([ui/store/project_store.py:182](../../../ui/store/project_store.py)) never
  invokes a reader at all — it registers a `SessionRef` with
  `sha256=""` and stops. No reader/identity plumbing exists at import
  time to build on.
- `ui/store/task_runner.py`'s `TaskRunner` already exists precisely to
  run `Engine`/reader calls off the GUI thread (used today by
  validate/run/preview). The identity probe should reuse it rather
  than invent new concurrency.

## 2. Scoping decisions (already made, not open questions)

| Question | Decision |
|---|---|
| Identity-aware graying data source | **Add a cached probe**: extend `SessionRef` with `has_stable_identities`, populated by a reader read at import time, cached from then on. |
| ⚙ per-metric config icon | **Stub it**: keep the column in the table shape, clickable, but every click shows a "Not yet implemented" message — no real config UI exists to open, but the affordance is present. *(Revised from the original "omit entirely" decision.)* |
| Row source | **Switch to `metrics.registry.list_for_level(...)`** now, replacing the hardcoded id lists. |

## 3. Goals (in scope for this work)

1. `ui/metrics_screen.py`: replace each tab's `QListWidget` with a
   `QTableWidget` (columns: `include` checkbox, `metric_id`,
   `metric_name`, `info` ⓘ, `config` ⚙), rows sourced from
   `metrics.registry.list_for_level(level)`.
2. `MetricInfoDialog(metric: type[Metric], parent=None)` — constructor
   takes the `Metric` class/instance, not a bare id string.
3. Per-row ⓘ click opens `MetricInfoDialog` for that row directly (no
   more shared button + `currentItem()`).
4. ⓘ hidden when `documentation.formula_plain is None and
   documentation.citation is None` (spec §6.5).
5. "Copy citation" footer button on the dialog (clipboard write of
   citation + DOI), enabled only when a citation exists.
6. Dialog closes on ✕ button, `Escape`, and click-outside.
7. Individual tab: IL-* rows greyed when every session in the project
   has `has_stable_identities is False`.
8. Zone tab disabled when `manifest.zones.rois` is empty.
9. `SessionRef.has_stable_identities: bool | None = None`, populated by
   a background probe (via `TaskRunner`) when a session is added.
10. Every row's ⚙ is present and clickable, but wired to a stub handler
    (`QMessageBox.information(..., "Not yet implemented")`) rather than
    any real per-metric config UI.
11. `docs/UI_DESIGN.md` and `docs/METRICS_SPEC.md` updated to match
    what actually ships (⚙ column present but documented as a stub,
    stating the all-sessions-identity-free graying rule precisely).

## 4. Non-goals / explicitly deferred

These are named in the docs today but are **not** part of this change,
and will still not exist once this work lands:

- **Screen 6.3 (Per-Metric Advanced Configuration)** and any
  `Metric` config-schema concept. The ⚙ column stays in the table
  (see Goals #10) but is a stub — every click shows a "Not yet
  implemented" message, regardless of which metric's row it's on.
  No config screen, no config schema, no per-metric parameters.
- **`SessionRef.sha256` is still never computed** at
  `ProjectStore.add_session()` time. Pre-existing gap, unrelated to
  this change, not touched here.
- **Zone overlap policy** (`METRICS_SPEC.md` §8, open question 2) —
  untouched.
- **Per-metric config** (`METRICS_SPEC.md` §8, open question 3) —
  untouched.
- **Registry-driven population for the config table** — moot, since
  Screen 6.3 doesn't exist (see above).
- No change to `Engine.import_sessions()` / the heavier
  processing-screen import flow — the identity probe added here is a
  separate, lighter-weight path specific to populating
  `SessionRef.has_stable_identities` at add-time.

## 5. Design

### 5.1 Data model + import-time identity probe

```python
# track2data/core/models.py
class SessionRef(BaseModel):
    session_id: str
    folder: Path
    sha256: str
    has_stable_identities: bool | None = None   # NEW — None = not yet probed / probe failed
```

`ProjectStore.add_session(folder)`:
1. Registers the `SessionRef` immediately (as today), so the UI shows
   the session right away.
2. Submits a background probe task via `self._tasks.submit(...)`:
   `read_session(folder)` off the GUI thread, reusing the reader
   auto-detection already used by `Engine.import_session`.
3. On success, replaces that one `SessionRef` in
   `manifest.sessions` (`model_copy`, matching the immutable-manifest
   pattern already used by every other `update_*` method) with
   `has_stable_identities` set from the probed `Session`, then emits
   `sessionsChanged`.
4. On failure (bad folder, unsupported reader, exception), leaves
   `has_stable_identities=None` and appends a run-log line via
   `self.append_log(...)` — the session stays in the project;
   graying just treats it as unknown, not identity-free.

This needs a `task_id -> session_id` map inside `ProjectStore` (a
plain `dict[str, str]`, alongside the existing `_tasks`/`_run_results`
attributes) so `taskFinished` can be routed back to the right
`SessionRef`, mirroring how `ProcessingScreen` already tracks its own
`_current_task_id`.

### 5.2 `ui/metrics_screen.py`

- `_make_list` → `_make_table(level: str) -> QTableWidget`, populated
  from `metrics.registry.list_for_level(level)` sorted by `id`.
- Column 0: `QTableWidgetItem` with `ItemIsUserCheckable`, matching
  today's checkbox behavior — this lives in its own column now, so it
  never conflicts with a cell widget the way `QListWidget.setItemWidget`
  would have.
- Column 3: a small `QPushButton("ⓘ")` via `setCellWidget`, connected
  per-row to open `MetricInfoDialog(metric_cls, self)`; omitted
  (empty cell) when the visibility rule says to hide it.
- Column 4: a small `QPushButton("⚙")` via `setCellWidget` on every
  row (no visibility rule — always present, since there's no per-metric
  "has config" concept to gate it on), connected to a stub slot:
  `QMessageBox.information(self, "Not yet implemented", "Per-metric
  configuration isn't available yet.")`. Not disabled — it's clickable,
  it just has nothing real behind it yet.
- `_show_metric_info` and `self._info_btn` are removed — no shared
  button anymore.
- Individual tab rows: for each `IL-*` row, grey it out
  (`setFlags(... & ~Qt.ItemFlag.ItemIsEnabled)` + tooltip) when
  `all(not s.has_stable_identities for s in manifest.sessions if
  s.has_stable_identities is not None)` **and** at least one session
  has a non-`None` probe result. (If every session is still unprobed,
  don't grey — treat as unknown, not identity-free.)
- Zone tab: `self._tabs.setTabEnabled(zone_index, bool(manifest.zones.rois))`.
- `_checked_ids` / `_apply` / `_load_from_store` keep their current
  shape, adapted to read from `QTableWidget` rows instead of
  `QListWidget` items.

### 5.3 `MetricInfoDialog`

- Constructor: `__init__(self, metric_cls: type[Metric], parent=None)`
  — looks up nothing; the caller already has the class from the
  registry-driven row.
- Footer gains a "Copy citation" `QPushButton` next to "Close",
  `.setEnabled(doc.citation is not None)`, wired to
  `QApplication.clipboard().setText(f"{doc.citation} (DOI:
  {doc.citation_doi})" if doc.citation_doi else doc.citation)`.
- `keyPressEvent`: call `super()` (Qt's default `QDialog` behavior
  already closes on Escape via `reject()` — verify this isn't
  swallowed by the `QTextEdit` child stealing focus; add an explicit
  override only if needed).
- Outside-click close: give the dialog a semi-transparent parent
  overlay widget and a `mousePressEvent` on it that calls
  `self.reject()` when the click lands outside `self.geometry()`.

### 5.4 Docs reconciliation

- `docs/UI_DESIGN.md` §6.10: keep the `config` column in the widget
  list, but add a note that it is a stub in v1 ("clicking ⚙ shows a
  'Not yet implemented' message; Screen 6.3 does not exist yet");
  state the graying rule as "all sessions in the project have
  `has_stable_identities is False`" (not "identity-free sessions",
  which was ambiguous about per-session vs. project-wide).
- `docs/METRICS_SPEC.md` §6.1/§6.2: same stub note next to the `⚙`
  glyph in the ASCII diagram and click-behaviour text.

## 6. Error handling

- Reader failures during the identity probe never surface as a modal
  error — they're not user-initiated actions, just a background
  enrichment. Logged via `append_log`, surfaced only as "unknown"
  (not greyed) in the UI.
- `MetricInfoDialog` for a metric with no `Metric.get(...)` hit still
  shows today's graceful "No documentation available" message — this
  behavior is unaffected by the constructor signature change, since
  registry-driven rows can no longer reference an unregistered id in
  the first place (the whole point of switching row sources).

## 7. Testing

- `tests/test_ui/test_metric_info_dialog.py`: every existing test
  constructs `MetricInfoDialog("IL-1")` etc. — **all of these need
  rewriting** to pass `metrics.get("IL-1")` (a `type[Metric]`) instead
  of the bare string. The "unknown metric id" test
  (`test_dialog_handles_unknown_metric_id_gracefully`) no longer
  applies in its current form once the caller only ever passes real
  registered classes; keep an equivalent test at the dialog level by
  passing a metric class with no matching registry entry, or drop it
  if that path becomes unreachable — decide during implementation.
- The three `_show_metric_info`/`_info_btn` tests in the same file
  (`test_info_button_...`) test behavior being removed entirely; they
  get replaced with per-row-ⓘ-click tests against the new
  `QTableWidget`.
- **No `tests/test_ui/test_metrics_screen.py` exists today** — new
  tests are needed from scratch for: registry-driven row population,
  the ⓘ visibility rule, identity graying (all-sessions-false vs.
  mixed vs. all-unprobed), and zone-tab disabling.
- **No `tests/test_ui/test_project_store.py` exists today** — new
  tests needed for the background identity probe: success path
  (`has_stable_identities` populated), failure path (stays `None`,
  session not removed), and the `sessionsChanged` re-emission.

## 8. Left to do (explicit)

This document is a design, not an implementation. Nothing above is
built yet. In order:

1. [ ] `SessionRef.has_stable_identities` field + migration-free
   backward compatibility check against an existing saved manifest.
2. [ ] `ProjectStore.add_session` background probe + `task_id ->
   session_id` tracking + `sessionsChanged` re-emission on probe
   completion.
3. [ ] `ui/metrics_screen.py` `QTableWidget` rewrite (registry-driven
   rows, checkbox column, per-row ⓘ, identity graying, zone-tab
   disable).
4. [ ] `MetricInfoDialog` constructor change to take a `Metric` class,
   plus copy-citation button and Escape/outside-click close.
5. [ ] ⚙ stub column: present on every row, clicking it shows a
   "Not yet implemented" message — no real config UI.
6. [ ] Rewrite `tests/test_ui/test_metric_info_dialog.py` for the new
   constructor and remove the shared-button tests.
7. [ ] New `tests/test_ui/test_metrics_screen.py` (include a test for
   the ⚙ stub message).
8. [ ] New tests for the `ProjectStore` identity probe.
9. [ ] Update `docs/UI_DESIGN.md` §6.10 and `docs/METRICS_SPEC.md` §6
   to match what actually ships (⚙ column kept but marked as a stub,
   precise graying rule).
10. [ ] Confirm no other caller of `MetricInfoDialog(metric_id: str)`
    exists outside `ui/metrics_screen.py` before changing the
    constructor (a repo-wide check, not yet done as part of this
    design pass).

Explicitly **not** on this list, and not expected to exist after it:
Screen 6.3, any real `Metric` config schema behind the ⚙ stub,
`SessionRef.sha256` computation, zone-overlap policy.
