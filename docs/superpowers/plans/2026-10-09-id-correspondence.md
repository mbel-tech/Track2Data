# ID Correspondence Between Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a 3-D project say which sessions are the top view and which the side view, pair them (by regex or by hand), and match the fish between the two views, in a new Views page.

**Architecture:** New manifest fields (`SessionRef.view_role`, `ProjectManifest.view_pairs`, `ProjectMode.pairing`) edited only through `ProjectStore`. A Qt-free module (`track2data/views/pairing.py`) holds the regex pairing and the fish-map checks. The Views page is an 11th stack page that belongs to the Sessions sidebar row, reached by Next/Back only in 3-D through a pure route function, so no existing page or stage index changes.

**Tech Stack:** Python 3.11+, pydantic v2, PySide6, pytest / pytest-qt, ruff.

**Spec:** `docs/3d-movement/2026-10-09-id-correspondence-design.md` (also read `docs/3d-movement/2026-10-09-mode-switch-design.md`, which this builds on).

## Global Constraints

- Defaults: `SessionRef.view_role=None`; `ViewPair.same_ids=False`, `fish_map={}`, `auto=False`; `PairingPatterns` both `""`; `ProjectManifest.view_pairs=[]`. Manifests without any of these must load unchanged.
- `mode.id_map` is removed from `ProjectMode`. A manifest that still contains `"id_map"` must load (extra keys are ignored).
- View roles are exactly `"top"` and `"side"`. A fish map maps a top-view label to a side-view label; a top fish not in it is unmatched.
- A session belongs to at most one pair. A pair's top session has role `top` and its side session has role `side`.
- Fish labels are `Session.identities_labels` (as `SessionFacts.identities_labels`), falling back to `str(index)` for index `0..n_animals-1`.
- Messages (exact): `"cannot match fish: this session has no stable identities"`; `"duplicate side fish: <label>"`; `"unknown top fish: <label>"`; `"unknown side fish: <label>"`; `"<n_top> top fish vs <n_side> side fish"`; roles/pairs rejected outside 3-D with `VIEWS_3D_ONLY = "Views apply to 3-D projects only"`.
- The Views page is page index `10`, belongs to sidebar stage `1` (Sessions), and is shown only in 3-D. Existing page indices `0..9` and `STAGES` do not change.
- Views stage status is never `blocked`.
- Signals connected to long-lived store signals use bound methods; lambdas capturing `self` on a widget's own children use `ui/widgets/weak_slot.py`.
- No change to any 2-D behaviour; the existing suite must pass. Run `ruff check` on touched files before each commit.

## Review Focus

- A manifest with `mode.id_map` and without the new fields loads (Task 1 test).
- A regex that is invalid, has no `key` group, or yields a duplicate key on one side is reported and pairs nothing wrongly (Task 2 tests).
- Removing a session, or changing its role, drops its pairs; a session cannot be in two pairs (Task 3 tests).
- In 2-D, Next/Back never lands on page 10; on page 10 the footer does not say "Done" and the Run button stays visible (Task 5 tests).
- A pair with an identity-free session is flagged and never auto-matched; ticking "same IDs" with differing label sets matches only the shared labels (Tasks 2 and 7 tests).
- A session whose facts are not probed yet, or that has no `identities_labels`, does not crash the Views page (Tasks 7 and 8 tests).

---

## File Structure

- Modify `track2data/core/models.py`: `ViewPair`, `PairingPatterns`, `SessionRef.view_role`, `ProjectMode.pairing`, remove `id_map`, `ProjectManifest.view_pairs`.
- Create `track2data/views/__init__.py`, `track2data/views/pairing.py`: pure logic.
- Modify `ui/store/project_store.py`: role / pairing / pair methods, `viewsChanged`, pruning in `update_sessions`.
- Modify `ui/store/stage_status.py`: 11 pages, Views status.
- Modify `ui/store/screen_flow.py`: `page_route`, `next_page`, `prev_page`.
- Modify `app/navigation.py`: `VIEWS_PAGE`, `PAGE_TO_STAGE`.
- Modify `app/main_window.py`: add the page, route-based Next/Back, footer fixes.
- Create `ui/views_screen.py`: the Views page. Create `ui/widgets/regex_help.py`: the help popover.
- Modify `ui/widgets/trajectory_view.py`: `set_highlight`.
- Modify `CHANGELOG.md`, `docs/dev/DECISIONS.md`, `docs/guide/USER_GUIDE.md`, the two spec/roadmap docs.
- Tests: `tests/test_core/test_models.py`, `tests/test_views/test_pairing.py` (new, with `__init__.py`), `tests/test_ui/test_project_store.py`, `tests/test_ui/test_stage_status.py`, `tests/test_ui/test_screen_flow.py`, `tests/test_app_smoke.py`, `tests/test_ui/test_views_screen.py` (new), `tests/test_ui/test_trajectory_view.py`.

---

### Task 1: Manifest fields

**Files:**
- Modify: `track2data/core/models.py` (`SessionRef` ~515, `ProjectMode` ~418, `ProjectManifest` ~620)
- Test: `tests/test_core/test_models.py`

**Interfaces:**
- Produces: `ViewPair(top_session_id: str, side_session_id: str, same_ids: bool=False, fish_map: dict[str,str]={}, auto: bool=False)` (validator: the two ids differ); `PairingPatterns(top_regex: str="", side_regex: str="")`; `ViewRole = Literal["top","side"]`; `SessionRef.view_role: ViewRole | None = None`; `ProjectMode.pairing: PairingPatterns = PairingPatterns()` (no `id_map`); `ProjectManifest.view_pairs: list[ViewPair] = []`; `VIEWS_3D_ONLY` constant.

- [ ] **Step 1: Write failing tests**: `test_view_defaults` (all defaults above); `test_view_pair_rejects_same_session`; `test_old_manifest_with_id_map_loads` (a manifest dict whose `mode` has `"id_map": {"a": "b"}` validates and `mode` has no `id_map` attribute); `test_manifest_without_view_fields_loads`; `test_views_roundtrip_json` (a manifest with roles, patterns and a pair survives `model_validate_json(model_dump_json())`); `test_project_hash_depends_on_pairs`. Update the existing E test that uses `id_map` (`test_mode_roundtrip_keeps_id_map`) to use `pairing` instead.
- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_core/test_models.py -k "view or pair or mode" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the models; grep the repo for other `id_map` uses (code and tests) and update them.
- [ ] **Step 4: Run** `pytest tests/test_core -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): view roles, view pairs and pairing patterns in the manifest`.

### Task 2: Pairing logic (Qt-free)

**Files:**
- Create: `track2data/views/__init__.py`, `track2data/views/pairing.py`
- Test: `tests/test_views/__init__.py`, `tests/test_views/test_pairing.py`

**Interfaces:**
- Produces:
  - `fish_labels(identities_labels: Sequence[str] | None, n_animals: int) -> list[str]`
  - `PairingResult` (frozen dataclass): `pairs: list[tuple[str, str]]` (top id, side id), `top_ids: list[str]`, `side_ids: list[str]`, `unpaired_top: list[str]`, `unpaired_side: list[str]`, `ambiguous_keys: list[str]`, `both_roles: list[str]`, `errors: list[str]`
  - `pair_by_regex(session_ids: Sequence[str], top_regex: str, side_regex: str) -> PairingResult`
  - `identity_map(top_labels: Sequence[str], side_labels: Sequence[str]) -> tuple[dict[str, str], list[str]]` (map of labels present in both views, and the sorted labels present in only one)
  - `validate_fish_map(fish_map: Mapping[str, str], top_labels, side_labels, *, top_identity_free: bool, side_identity_free: bool) -> list[str]`

- [ ] **Step 1: Write failing tests** (exact values): ids `["t1_top","t1_side","t2_top","t2_side","x"]` with `(?P<key>.+)_top$` / `(?P<key>.+)_side$` give `pairs == [("t1_top","t1_side"),("t2_top","t2_side")]`, `unpaired_top == []`, `unpaired_side == []`; a lone `t3_top` is in `unpaired_top`; two top sessions with the same key land in `ambiguous_keys` and are not paired; a session matching both regexes is in `both_roles` and not paired; an invalid regex and a regex without a `key` group each add one entry to `errors` and pair nothing; empty regex strings are "not set" and give an empty result with no error. `fish_labels(None, 3) == ["0","1","2"]`; `fish_labels(["a","b"], 2) == ["a","b"]`. `identity_map(["a","b"],["b","c"]) == ({"b":"b"}, ["a","c"])`. `validate_fish_map({"a":"x","b":"x"}, ["a","b"], ["x"], ...)` contains `"duplicate side fish: x"` and `"2 top fish vs 1 side fish"`; unknown labels give `"unknown top fish: z"` / `"unknown side fish: z"`; identity-free on either side gives exactly `"cannot match fish: this session has no stable identities"` once; a valid full map gives `[]`.
- [ ] **Step 2: Run** `pytest tests/test_views -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** with `re.search` on the session id; a session matching `top_regex` is a top candidate, matching `side_regex` a side candidate; pair on equal `key` group; keep result lists in input order.
- [ ] **Step 4: Run** `pytest tests/test_views -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(views): regex pairing and fish-map checks`.

### Task 3: Store

**Files:**
- Modify: `ui/store/project_store.py` (signals ~129-143 and the signal tuple ~190; `update_sessions` ~447; new methods after `update_mode`)
- Test: `tests/test_ui/test_project_store.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `ProjectStore.viewsChanged = Signal()` (also wired into `_on_manifest_changed`); `update_view_role(session_id: str, role: ViewRole | None) -> None`; `update_pairing(patterns: PairingPatterns) -> None`; `apply_regex_pairing() -> PairingResult`; `update_view_pair(pair: ViewPair) -> None` (upsert by `(top_session_id, side_session_id)`); `remove_view_pair(top_session_id: str, side_session_id: str) -> None`. All raise `ValueError(VIEWS_3D_ONLY)` unless `mode.dimension == "3d"`; `update_view_pair` raises `ValueError` for an unknown session, a wrong role, or a session already in another pair.

- [ ] **Step 1: Write failing tests** (3-D store with sessions added via `update_sessions`): role update emits `viewsChanged` and marks dirty; rejected in 2-D with the exact message; changing a session's role drops pairs containing it; `update_view_pair` upserts and rejects an unknown session / wrong role / second pair for one session; `remove_view_pair`; removing a session through `update_sessions` drops its pairs but keeps the other pairs and roles; `apply_regex_pairing` sets roles of matched sessions, adds pairs with `auto=True`, keeps an existing pair's `same_ids`/`fish_map` when its two sessions pair again, removes `auto` pairs that no longer match, and leaves hand-made (`auto=False`) pairs alone; `update_pairing` stores the patterns without applying them.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_project_store.py -k "view or pair" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** following the `update_mode` pattern (`model_copy(update=...)`, emit once).
- [ ] **Step 4: Run** `pytest tests/test_ui/test_project_store.py tests/test_app_smoke.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(store): view roles, pairing and view pairs`.

### Task 4: Stage status for the Views page

**Files:**
- Modify: `ui/store/stage_status.py` (`PAGE_NAMES`, the page constants, `compute_stage_statuses`, `stage_summaries` if it indexes pages)
- Test: `tests/test_ui/test_stage_status.py`

**Interfaces:**
- Produces: `compute_stage_statuses` returns 11 entries; `_VIEWS = 10`; `PAGE_NAMES[10] == "Views"`. Views status: 2-D or no project → `StageInfo("empty")`; 3-D with no sessions → `empty` "Add sessions first."; any session without a role → `empty` "Choose a view (top or side) for every session."; any session unpaired, any pair with neither `same_ids` nor a non-empty `fish_map`, or any pair with an identity-free session (`SessionRef.is_identity_free()`) → `warning` with a one-line message naming the first problem; otherwise `valid`. Never `blocked`.

- [ ] **Step 1: Write failing tests**: length is 11 for a manifest and for `None`; each branch above (build manifests with `SessionRef(view_role=...)` and `ViewPair`); 2-D manifest Views is `empty`; `next_blocker(statuses, 10)` is `None` for every Views status. Update the existing tests that assume 10 pages (`range(10)`, page parametrisation).
- [ ] **Step 2: Run** `pytest tests/test_ui/test_stage_status.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The `None` and fresh-list constructions use 10 trailing entries now.
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS (fix other tests that assume 10 pages).
- [ ] **Step 5: Commit** `feat(ui): Views page status`.

### Task 5: Route and navigation

**Files:**
- Modify: `ui/store/screen_flow.py`, `app/navigation.py`, `app/main_window.py` (page list ~135-150; `_go_to_page`, `_go_back`, `_go_next`, `_update_next_action`, `_refresh_footer_labels`, `_refresh_stage_status` if it assumes page counts)
- Create: `ui/views_screen.py` (skeleton)
- Test: `tests/test_ui/test_screen_flow.py`, `tests/test_app_smoke.py`

**Interfaces:**
- Produces: in `app/navigation.py` `VIEWS_PAGE = 10` and `PAGE_TO_STAGE` gains a final entry `1`; in `ui/store/screen_flow.py` `page_route(mode: ProjectMode) -> list[int]` (2-D: `0..9`; 3-D: `[0,1,10,2,3,4,5,6,7,8,9]`), `next_page(mode, page) -> int | None`, `prev_page(mode, page) -> int | None` (`None` at the ends, and for a page not in the route); `ViewsScreen(store, parent=None)` (QWidget with a `PageTitle` "Views" and a one-line lead).

- [ ] **Step 1: Write failing tests**: route lists above; `next_page`/`prev_page` for 2-D and 3-D including `next_page(2d, 1) == 2`, `next_page(3d, 1) == 10`, `next_page(3d, 10) == 2`, `prev_page(3d, 2) == 10`, `prev_page(3d, 1) == 0`, `prev_page(3d, 0) is None`, `next_page(2d, 10) is None`; smoke: `len(PAGE_TO_STAGE) == 11`, the main window stack has 11 pages with `ViewsScreen` last, Next from Sessions in a 3-D project goes to page 10 and then Calibration, Back from Calibration returns to page 10, in a 2-D project Next from Sessions goes to Calibration; on page 10 the Next button text is not "Done" and the Run button is not hidden; the sidebar highlights Sessions on page 10. Update the two existing smoke tests that assert 10 pages and the one-to-one mapping.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_screen_flow.py tests/test_app_smoke.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `_go_next`/`_go_back` use the route functions with `self._store.manifest.mode`; `_update_next_action` enables Next when `next_page(...) is not None`; the footer's "Done" shows when there is no next page and the page is not 8 (Export dataset); `_btn_run.setVisible(page not in (8, 9))`. Footer labels name the neighbouring routed page's stage through `PAGE_TO_STAGE` (on page 10, Back reads "← Sessions" and Next reads "Next: Calibration →"). Add `ViewsScreen` as the last stack page and make `modeChanged` refresh the footer.
- [ ] **Step 4: Run** `pytest tests/test_ui tests/test_app_smoke.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): route the Views page in 3-D projects`.

### Task 6: Views page, part 1: roles, patterns, help bubble

**Files:**
- Modify: `ui/views_screen.py`
- Create: `ui/widgets/regex_help.py`
- Test: `tests/test_ui/test_views_screen.py` (new)

**Interfaces:**
- Consumes: store methods (Task 3), `pair_by_regex` (Task 2).
- Produces on `ViewsScreen`: `_role_table` (QTableWidget, one row per session, column 1 a `QComboBox` with items `"(not set)"`, `"Top"`, `"Side"`), `_top_regex_edit`, `_side_regex_edit` (`QLineEdit`), `_top_help_btn`, `_side_help_btn` (`QToolButton`, text `ⓘ`), `_match_label` (`QLabel`: `"Top pattern catches <n> sessions · side pattern catches <m> sessions"`), `_unpaired_label` (lists unpaired and ambiguous sessions, empty when none), `_apply_btn` (`"Pair by pattern"`); `RegexHelpPopover(parent)` in `ui/widgets/regex_help.py` with module constant `REGEX_HELP_TEXT` containing the substrings `(?P<key>`, `(?P<key>.+)_top$`, `trial01_top` and a sentence saying sessions with the same key are paired. Pattern edits commit through `AutoCommit` to `store.update_pairing`; role combos call `store.update_view_role`; `_apply_btn` calls `store.apply_regex_pairing`. All widgets rebuild from the store on `projectChanged`, `sessionsChanged`, `modeChanged`, `viewsChanged` without writing back (use `AutoCommit.suppressed()` and block signals).

- [ ] **Step 1: Write failing tests** (3-D store with four sessions `t1_top`, `t1_side`, `t2_top`, `t2_side`): role combos reflect and set roles; typing the two patterns updates `_match_label` live to "catches 2 sessions · … 2 sessions" before any commit; an invalid or key-less pattern shows a message in `_match_label`'s sibling error label and does not raise; `_apply_btn` creates the two pairs and sets roles; `_unpaired_label` lists a lone `t3_top`; clicking `_top_help_btn` shows the popover and `REGEX_HELP_TEXT` contains the required substrings; rebuilding from the store does not call `update_view_role`/`update_pairing` (wrap and assert no calls); with no sessions the page shows an empty-state line.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_views_screen.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Follow the layout and object-name conventions of `ui/project_screen.py` and `ui/calibration_screen.py`; plain-language help text (no regex jargon beyond the one `key` example).
- [ ] **Step 4: Run** `pytest tests/test_ui/test_views_screen.py tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): Views page roles and pairing patterns`.

### Task 7: Views page, part 2: the pair list

**Files:**
- Modify: `ui/views_screen.py`
- Test: `tests/test_ui/test_views_screen.py`

**Interfaces:**
- Consumes: `identity_map`, `validate_fish_map`, `fish_labels`, `store.session_facts(session_id) -> SessionFacts | None`, `update_view_pair`, `remove_view_pair`.
- Produces on `ViewsScreen`: `_pairs_table` (columns: top session, side session, "Same IDs" checkbox, status, a Remove button), `_current_pair` property → `tuple[str, str] | None` (selected row), `pairSelected = Signal(object)` (emits the `(top_id, side_id)` tuple or `None`), manual-pair widgets `_manual_top_combo`, `_manual_side_combo` (sessions with that role not already in a pair) and `_manual_add_btn` ("Add pair"). Status text per row: `"Matched"` when `same_ids` or `fish_map` is non-empty and `validate_fish_map` returns `[]`; otherwise the first message from `validate_fish_map`, or `"Needs matching"` when the map is empty and `same_ids` is off. Ticking "Same IDs" sets `same_ids=True` and `fish_map` to the shared-label map from `identity_map`; unticking sets `same_ids=False` and keeps the map. Labels come from `fish_labels(facts.identities_labels if facts else None, facts.n_animals if facts else 0)`.

- [ ] **Step 1: Write failing tests**: a pair row appears with "Needs matching"; ticking "Same IDs" with equal label sets fills `fish_map` as identity and shows "Matched"; with label sets `["a","b"]` vs `["b","c"]` it maps only `b` (`fish_map == {"b":"b"}`), the status is `"Matched"` (fish seen in only one view are allowed to stay unmatched) and the status tooltip lists the unmatched fish `a` and `c`; an identity-free session shows exactly `"cannot match fish: this session has no stable identities"` and the tick does nothing for it; unticking keeps the map; Remove deletes the pair; manual add pairs a free top session with a free side session and the combos exclude already-paired sessions; selecting a row emits `pairSelected` with the tuple; sessions with no facts yet do not crash (status "Needs matching").
- [ ] **Step 2: Run** `pytest tests/test_ui/test_views_screen.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Refresh the facts-dependent status on `sessionFactsChanged` as well.
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): Views page pair list and same-IDs tick`.

### Task 8: Views page, part 3: manual matching with plots

**Files:**
- Modify: `ui/widgets/trajectory_view.py` (add `set_highlight`), `ui/views_screen.py`
- Test: `tests/test_ui/test_trajectory_view.py`, `tests/test_ui/test_views_screen.py`

**Interfaces:**
- Consumes: `load_trajectory_data(manifest, session_id, cache_dir) -> TrajectoryData` from `ui/preview_screen.py` and `store.tasks.submit(fn) -> task_id` / `store.taskFinished` (follow `PreviewScreen._load_trajectories` and `_on_traj_task_finished`).
- Produces: `TrajectoryView.set_highlight(animal: int | None) -> None` and property `highlighted_animal -> int | None`: the highlighted animal's trail is drawn with a pen at least twice as thick and its marker larger; every other animal is drawn thinner at reduced opacity; `None` restores the normal look. On `ViewsScreen`: `_match_table` (rows = top fish; column 0 the top label, column 1 a `QComboBox` with `"(no match)"` plus every side label), `_match_issues` (`QLabel` listing `validate_fish_map` messages, empty when none), `_top_plot`, `_side_plot` (`TrajectoryView`), `_match_status` (`QLabel`, loading text). Selecting a pair row (Task 7's `pairSelected`) loads both sessions' trajectories in the background and fills the table; choosing a combo item writes `fish_map` through `update_view_pair`; selecting a table row calls `set_highlight(row)` on the top plot and `set_highlight(index of its mapped side label)` (or `None`) on the side plot. A side fish already used by another top fish is marked in the other combos' items but stays selectable; the duplicate is reported in `_match_issues`.

- [ ] **Step 1: Write failing tests**: `set_highlight(1)` makes `highlighted_animal == 1`, `set_highlight(None)` restores `None`, and the highlighted trail's pen width is greater than the others' (read the scene items; keep this focused); on the Views page, selecting a pair fills `_match_table` with one row per top label and the right combo selection from `fish_map`; choosing a side label writes the map; choosing "(no match)" removes the key; two top fish mapped to one side fish shows `"duplicate side fish: <label>"` in `_match_issues`; selecting a table row highlights the mapped fish in both plots (monkeypatch `load_trajectory_data` to return synthetic `TrajectoryData` so no files are read); identity-free pair shows the flag text and disables the table; a pair whose session facts are missing shows an empty table and no crash.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_trajectory_view.py tests/test_ui/test_views_screen.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep highlight drawing inside `_redraw` using the existing per-animal loop; do not change defaults when no highlight is set.
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): manual fish matching with highlighted track plots`.

### Task 9: Docs and full check

**Files:**
- Modify: `CHANGELOG.md` (an `### Added` entry under Unreleased), `docs/dev/DECISIONS.md` (new `D-038`, same format as D-037), `docs/guide/USER_GUIDE.md` (a short "Views (3-D projects)" section after Sessions: roles, the two patterns with the ⓘ help, the "Same IDs" tick, manual matching; note that 3-D projects still cannot be run), `docs/3d-movement/2026-10-09-id-correspondence-design.md` (status "implemented"; add the `ViewPair.auto` field and "a session belongs to at most one pair" to its Design item 1; replace "ordered after Sessions" wording by "page 10, belongs to the Sessions sidebar row"), `docs/3d-movement/2026-10-09-mode-switch-design.md` and D-037 (`id_map` replaced by `pairing` and `view_pairs`), `docs/3d-movement/2026-10-08-3d-roadmap.md` (G row: done).
- Test: `tests/test_docs/test_guide.py`

- [ ] **Step 1:** Write the doc text from the spec; verify facts in the code first and document only what exists.
- [ ] **Step 2: Run** `pytest tests/test_docs -q`. Expected: PASS.
- [ ] **Step 3: Run** `QT_QPA_PLATFORM=offscreen python -m pytest -q -x` and `ruff check .`. Expected: all pass; report any segfault or abort at exit verbatim.
- [ ] **Step 4: Commit** `docs: describe ID correspondence between views`.
