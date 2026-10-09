# 2D / 3D Project Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a locked-once-used 2D/3D project mode (with a 3-D layout choice) to the manifest, store and Project screen, and block all computing in 3-D projects until fusion exists.

**Architecture:** A new `ProjectMode` pydantic model on `ProjectManifest.mode`, edited only through `ProjectStore.update_mode` (rejected while sessions exist) which emits a new `modeChanged` signal. Stage status, screen banners and a single `Engine` gate read the mode; nothing else changes for 2-D projects.

**Tech Stack:** Python 3.11+, pydantic v2, PySide6, pytest / pytest-qt, ruff.

**Spec:** `docs/3d-movement/2026-10-09-mode-switch-design.md`

## Global Constraints

- Defaults: `dimension="2d"`, `layout=None`, `id_map={}`. A manifest without a `mode` key must load unchanged.
- `layout` is set if and only if `dimension == "3d"`; values are exactly `"single_video_two_panels"` and `"two_videos"`.
- `mode.id_map` is reserved for sub-project G. E never reads or writes it, but it must round-trip through save and load.
- Lock rule: mode cannot change while `manifest.sessions` is non-empty. Lock message: `"Remove all sessions to change the mode"`.
- 3-D compute-block message (exact): `"3-D fusion is not available yet"`. Sessions-blocked message (exact): `"Choose a 3-D layout"`.
- Screen banner text (exact): `"3-D mode: this screen applies to the 2-D tracks only until fusion is available"`.
- Radio labels (exact): `"2D"`, `"3D"`, `"One video, two panels (top and side in one frame)"`, `"Two videos (top and side tracked separately)"`.
- No change to any 2-D behaviour; the existing suite must pass unchanged.
- Run `ruff check` and `ruff format --check` on touched files before each commit.

## Review Focus

- Old project file with no `mode` key loads as 2-D (Task 1 test).
- Switching 3D to 2D must clear the layout, or the validator rejects the result (Task 3 test).
- A saved 3-D project that already has sessions opens locked (Task 3 test).
- Removing the last session through `update_sessions([])` unlocks the mode (Task 3 test).
- Opening a project syncs the radio buttons from the manifest without writing back to it (Task 5 test).
- A 3-D manifest driven headlessly (`Engine.run`, `run_all`, `export`) is refused, not silently run as 2-D (Task 2 test).

---

## File Structure

- Modify `track2data/core/models.py`: `ProjectMode`, `ProjectManifest.mode`, `MODE_3D_BLOCK_REASON`.
- Modify `track2data/api.py`: one gate used by every compute entry point.
- Modify `ui/store/project_store.py`: `modeChanged`, `update_mode`, `mode_locked`, `new_project(mode=)`.
- Create `ui/store/screen_flow.py`: pure `screen_flow(mode)`.
- Modify `ui/store/stage_status.py`: Sessions / Processing / Preview / Export rules for 3-D.
- Create `ui/widgets/mode_banner.py`: `ModeBanner` label.
- Modify `ui/project_screen.py`: radio groups.
- Modify `ui/calibration_screen.py`, `ui/zones_screen.py`, `ui/metrics_screen.py`: add the banner.
- Modify `ui/processing_screen.py`, `ui/export_screen.py`: disable run/export with the reason.
- Modify `app/main_window.py`: refresh stage status on `modeChanged`.
- Modify `CHANGELOG.md`, `docs/dev/DECISIONS.md`, `docs/guide/USER_GUIDE.md`.
- Tests: `tests/test_core/test_models.py`, `tests/test_core/test_mode_gate.py` (new), `tests/test_ui/test_project_store.py`, `tests/test_ui/test_stage_status.py`, `tests/test_ui/test_screen_flow.py` (new), `tests/test_ui/test_project_screen.py` (new), `tests/test_ui/test_mode_banner.py` (new).

---

### Task 1: ProjectMode model and manifest field

**Files:**
- Modify: `track2data/core/models.py` (next to `SceneConfig`, ~line 400; field on `ProjectManifest`, ~line 577)
- Test: `tests/test_core/test_models.py`

**Interfaces:**
- Produces: `ProjectMode(dimension: Literal["2d","3d"]="2d", layout: Literal["single_video_two_panels","two_videos"] | None=None, id_map: dict[str,str]={})`; `ProjectManifest.mode: ProjectMode = ProjectMode()`; module constant `MODE_3D_BLOCK_REASON = "3-D fusion is not available yet"`.

- [ ] **Step 1: Write failing tests** in `tests/test_core/test_models.py`:
  - `test_mode_defaults_to_2d`: `ProjectManifest(...).mode == ProjectMode()`, `.dimension == "2d"`, `.layout is None`, `.id_map == {}`.
  - `test_mode_3d_requires_layout`: `ProjectMode(dimension="3d")` raises `ValidationError`.
  - `test_mode_2d_rejects_layout`: `ProjectMode(dimension="2d", layout="two_videos")` raises `ValidationError`.
  - `test_mode_roundtrip_keeps_id_map`: dump and re-validate a manifest with `ProjectMode(dimension="3d", layout="two_videos", id_map={"a": "b"})`; equal afterwards.
  - `test_old_manifest_without_mode_loads`: `ProjectManifest.model_validate` of a manifest dict (from `model_dump(exclude={"mode"})`) gives `.mode == ProjectMode()`.
  - `test_project_hash_depends_on_mode`: hash with `ProjectMode()` differs from hash with a 3-D mode.
- [ ] **Step 2: Run** `pytest tests/test_core/test_models.py -k mode -v`. Expected: FAIL (`ProjectMode` not defined).
- [ ] **Step 3: Implement** `ProjectMode` as a `BaseModel` with a `model_validator(mode="after")` enforcing the layout rule (raise `ValueError`), add `ProjectManifest.mode`, and define `MODE_3D_BLOCK_REASON`. Fields are included in `project_hash` automatically via `model_dump`.
- [ ] **Step 4: Run** the same command plus `pytest tests/test_core -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): add ProjectMode to the manifest`.

### Task 2: Engine refuses 3-D projects

**Files:**
- Modify: `track2data/api.py` (`Engine.validate` ~1924, `run` ~1393, `run_session` ~1341, `run_all` ~1897, `export` ~1309)
- Test: `tests/test_core/test_mode_gate.py` (new)

**Interfaces:**
- Consumes: `ProjectMode`, `MODE_3D_BLOCK_REASON` (Task 1).
- Produces: `Engine.validate()` includes `MODE_3D_BLOCK_REASON` as an issue when `manifest.mode.dimension == "3d"`; `Engine.run`, `run_session`, `run_all` and `export` raise `ValueError(MODE_3D_BLOCK_REASON)` before doing any work. 2-D behaviour unchanged.

- [ ] **Step 1: Write failing tests** (build a minimal manifest as in `tests/test_api.py`, reuse its fixtures): `test_validate_reports_3d_block`, and one test per entry point asserting `pytest.raises(ValueError, match="3-D fusion is not available yet")`. Add `test_2d_validate_has_no_mode_issue`.
- [ ] **Step 2: Run** `pytest tests/test_core/test_mode_gate.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** a private `Engine._require_computable()` that raises, call it first in each entry point (before any I/O or cache access), and prepend the reason to `validate()`'s list.
- [ ] **Step 4: Run** `pytest tests/test_core/test_mode_gate.py tests/test_api.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): refuse to compute 3-D projects until fusion exists`.

### Task 3: Store: modeChanged, update_mode, lock

**Files:**
- Modify: `ui/store/project_store.py` (signals ~129-143, `__init__` signal list ~190, `update_scene` ~417, `new_project` ~331)
- Test: `tests/test_ui/test_project_store.py`

**Interfaces:**
- Consumes: `ProjectMode`.
- Produces: `ProjectStore.modeChanged = Signal()` (also wired to `_on_manifest_changed`); `ProjectStore.update_mode(mode: ProjectMode) -> None` (raises `ValueError(MODE_LOCK_REASON)` when sessions exist; no-op without a project); `ProjectStore.mode_locked -> str | None` (property: lock message or None); `ProjectStore.new_project(name, directory, mode: ProjectMode | None = None)`; module constant `MODE_LOCK_REASON = "Remove all sessions to change the mode"`.

- [ ] **Step 1: Write failing tests** (use the file's `store` fixture):
  - `test_update_mode_sets_mode_and_emits`: `qtbot.waitSignal(store.modeChanged)`; manifest `.mode.layout == "two_videos"` after.
  - `test_update_mode_rejected_with_sessions`: add a `SessionRef` via `store.update_sessions`, expect `ValueError` and unchanged mode.
  - `test_mode_locked_message_and_unlock`: `mode_locked` is the exact message with a session, `None` after `store.update_sessions([])`.
  - `test_switch_3d_to_2d_clears_layout`: update to 3-D then `ProjectMode()`; layout is `None`.
  - `test_new_project_accepts_mode`: `new_project("p", tmp_path, ProjectMode(dimension="3d", layout="two_videos"))` stores it.
  - `test_saved_3d_project_with_sessions_opens_locked`: save, reopen via `open_project`, `mode_locked` is the message.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_project_store.py -k mode -v`. Expected: FAIL.
- [ ] **Step 3: Implement** following the `update_scene` pattern (`model_copy(update={"mode": mode})`, emit `modeChanged`).
- [ ] **Step 4: Run** `pytest tests/test_ui/test_project_store.py tests/test_app_smoke.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(store): lockable project mode with modeChanged`.

### Task 4: Stage status and screen_flow

**Files:**
- Modify: `ui/store/stage_status.py` (`compute_stage_statuses`)
- Create: `ui/store/screen_flow.py`
- Modify: `app/main_window.py` (add `self._store.modeChanged` to the refresh tuple ~line 196)
- Test: `tests/test_ui/test_stage_status.py`, `tests/test_ui/test_screen_flow.py` (new)

**Interfaces:**
- Consumes: `ProjectMode`, `MODE_3D_BLOCK_REASON`.
- Produces: `screen_flow(mode: ProjectMode) -> Literal["standard"]`, the seam F and G replace per layout; in E it returns `"standard"` for every mode.

- [ ] **Step 1: Write failing tests** in `test_stage_status.py` with `_manifest(mode=ProjectMode(dimension="3d", layout="two_videos"))`:
  - `test_3d_processing_preview_export_blocked`: statuses at `PROC`, `PREVIEW`, `EXPORT` are `"blocked"` and the messages equal `"3-D fusion is not available yet"`.
  - `test_2d_stage_statuses_unchanged`: existing behaviour (default manifest has no blocked result pages).
  - `test_3d_sessions_status_with_layout_is_normal`: Sessions status for a 3-D project with a layout and no sessions is still `"empty"`.
  - `test_blocked_sessions_message_constant`: add `SESSIONS_NEEDS_LAYOUT = "Choose a 3-D layout"` to `stage_status.py` and assert it is exposed (the state is unreachable through the validator, so it guards hand-edited files loaded with `model_construct`); test with `ProjectManifest.model_construct`-style manifest where `mode.layout is None` and `dimension == "3d"`, expecting Sessions `"blocked"`.
  - In `test_screen_flow.py`: `screen_flow` returns `"standard"` for 2-D and for both 3-D layouts.
- [ ] **Step 2: Run** the two files. Expected: FAIL.
- [ ] **Step 3: Implement** the rules in `compute_stage_statuses`; blocked results pages replace the `ran` result for 3-D.
- [ ] **Step 4: Run** `pytest tests/test_ui/test_stage_status.py tests/test_ui/test_screen_flow.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): 3-D stage status and screen_flow seam`.

### Task 5: Project screen: mode controls

**Files:**
- Modify: `ui/project_screen.py`
- Test: `tests/test_ui/test_project_screen.py` (new; `pytest.importorskip("PySide6")`, use `qtbot`)

**Interfaces:**
- Consumes: `ProjectStore.update_mode`, `mode_locked`, `modeChanged`, `new_project(..., mode=)`.
- Produces: attributes `_dim_2d`, `_dim_3d` (`QRadioButton`), `_layout_single`, `_layout_two` (`QRadioButton`), `_lock_label` (`QLabel`), `_layout_box` (`QWidget`, visible only for 3-D). Labels as in Global Constraints.

- [ ] **Step 1: Write failing tests** (screen over a real `ProjectStore` with a project):
  - `test_layout_group_visible_only_for_3d`.
  - `test_choosing_3d_with_layout_updates_store`: click `_dim_3d` then `_layout_two`; `store.manifest.mode == ProjectMode(dimension="3d", layout="two_videos")`. Choosing 3D alone must not write an invalid mode: until a layout is picked the store keeps the previous mode.
  - `test_switching_back_to_2d_clears_layout`.
  - `test_locked_with_sessions`: after adding a session the four radios are disabled and `_lock_label` shows the lock message; removing sessions re-enables them.
  - `test_opening_project_syncs_radios_without_writing`: load a 3-D manifest via `store.open_project`; radios show it and `modeChanged` was not emitted by the screen.
  - `test_create_project_uses_chosen_mode`: with 3D + single-video selected and a name and directory, `_create_project` makes a project whose mode matches. Choosing 3D without a layout before Create shows a `QMessageBox.warning` (monkeypatch) and creates nothing.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_project_screen.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement**: "Analysis type" `QButtonGroup` pair, layout group with one-line help labels, a `_sync_from_store` slot connected to `projectChanged`, `modeChanged` and `sessionsChanged` that sets radios with signals blocked and applies the lock; the radio handlers call `store.update_mode`. Create passes the selected mode (3D requires a layout).
- [ ] **Step 4: Run** `pytest tests/test_ui/test_project_screen.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): 2D/3D mode controls on the Project screen`.

### Task 6: Banners and disabled run/export in 3-D

**Files:**
- Create: `ui/widgets/mode_banner.py`
- Modify: `ui/calibration_screen.py`, `ui/zones_screen.py`, `ui/metrics_screen.py` (insert under the `PageTitle`/lead in the root layout)
- Modify: `ui/processing_screen.py` (run button state in `_on_project_changed` ~404, and the re-enable sites ~450, ~489), `ui/export_screen.py` (`_update_export_enabled` ~311)
- Test: `tests/test_ui/test_mode_banner.py` (new), plus additions to `tests/test_ui/test_processing_screen.py` and `tests/test_ui/test_export_screen.py`

**Interfaces:**
- Consumes: `ProjectStore.modeChanged`, `projectChanged`.
- Produces: `ModeBanner(store, parent=None)` (`QLabel`, hidden for 2-D, shows the exact banner text for 3-D, tracks the store).

- [ ] **Step 1: Write failing tests**: `test_banner_hidden_in_2d`, `test_banner_visible_in_3d_with_exact_text`, `test_banner_updates_on_mode_change` (use `isHidden()`, not `isVisible()`); in the processing test file, `test_run_button_disabled_in_3d` (also after a task finishes, so the re-enable sites must honour it) and `test_start_run_refuses_3d` (reports the `Engine.validate` issue via the existing warning path); in the export test file, `test_export_button_disabled_in_3d`.
- [ ] **Step 2: Run** the three test files. Expected: FAIL.
- [ ] **Step 3: Implement** `ModeBanner`; add one to each of the three screens; in Processing and Export add a small helper that returns whether compute is allowed (`manifest.mode.dimension != "3d"`) and fold it into every place the buttons are enabled; show `MODE_3D_BLOCK_REASON` in each screen's status label while blocked.
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): 3-D banners and disabled run/export`.

### Task 7: Docs and full check

**Files:**
- Modify: `CHANGELOG.md` (under `## [Unreleased]`, an `### Added` entry), `docs/dev/DECISIONS.md` (new `D-037`, same format as D-036), `docs/guide/USER_GUIDE.md` (Project section, a "2D or 3D" note under **Notes** explaining the choice, the lock, and that 3-D computing is not available yet), `docs/3d-movement/2026-10-09-mode-switch-design.md` (status line: "implemented")
- Test: `tests/test_docs/test_guide.py`

- [ ] **Step 1:** Write the CHANGELOG, D-037 and guide text from the spec's Decisions section.
- [ ] **Step 2: Run** `pytest tests/test_docs -q`. Expected: PASS (fix anchors/links if it fails).
- [ ] **Step 3: Run** `pytest -q -x` and `ruff check . && ruff format --check .`. Expected: all pass.
- [ ] **Step 4: Commit** `docs: describe the 2D/3D project mode`.
