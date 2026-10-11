# Deferred Minor Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the minor findings deferred during the 3-D metrics (B2) and native 3-D files (A) work.

**Architecture:** Four small, independent groups of fixes, each with its own tests: native readers, session/pipeline/engine guards, availability/CLI/docs wording, and metric tests/log noise. No behaviour change for pixel-frame sessions or for any existing metric value.

**Tech Stack:** Python, pydantic v2, numpy/pandas, PySide6, pytest/pytest-qt, ruff, mypy (CI: mypy 2.4.0 + numpy 2.4.6).

**Spec:** `docs/3d-movement/2026-10-10-native-3d-files-design.md` and `docs/3d-movement/2026-10-10-3d-metrics-design.md` (this plan changes no decision in them; every item below is a deferred minor from their reviews).

## Global Constraints

- No change to any metric value, exported file or `project_hash` for pixel-frame, fused 3-D or existing native projects (existing suites and the golden pixel README/hash tests stay green).
- Every new error uses an existing error class and carries `code`, `subject` and `remediation` like its neighbours.
- New tests are written first (RED recorded), `-W error::RuntimeWarning` clean; `ruff check .` and CI-venv mypy clean; keep lines <= 100 chars; `ruff format` is not enforced repo-wide, do not reformat whole files.
- Not in this plan (do not touch): GL-1/GL-16 counting a gap separator row as a frame (changes 2-D numbers), the `body_length_cm` vs GL-1 zero-length convention, IL-17's per-bin vertical-speed estimate, the Anipose real-sample contract case (fixture unreachable), regenerating guide screenshots.

## Review Focus

- A reader guard that raises where it used to silently continue must not break any file the readers accept today (the existing reader tests and `tests/real_samples` stay green).
- The new `t2d list-metrics` text must stay accurate for pixel projects and not become project-dependent (the command takes no project).
- A de-duplicated log warning must still report every skipped metric once per run, not drop information.
- Removing dead code (`Session.pixel_size_known`) must not leave a dangling doc or test reference.

---

### Task 1: Native readers

**Files:** Modify `track2data/readers/anipose.py`, `track2data/readers/deeplabcut_3d.py`, `track2data/readers/native3d.py`; Test `tests/test_readers/test_anipose.py`, `tests/test_readers/test_deeplabcut_3d.py`, `tests/test_readers/test_native3d.py`.

**Interfaces:**
- Produces: header detection that never reads a partial header line; `keypoint` choices that are never an empty set for scanned files that have keypoints; DLC-3D frame-index/value/decode errors with their own codes (`DLC3D_BAD_FRAME_INDEX`, `DLC3D_BAD_VALUE`, `DLC3D_UNREADABLE`) and text naming "DeepLabCut 3-D"; a duplicate DLC-3D `(bodypart, coord)` column raising `DataValidationError(code="DLC3D_DUPLICATE_COLUMN")`.

- [ ] **Step 1: Write failing tests:** `test_header_longer_than_the_peek_is_still_detected` (an Anipose and a DLC-3D header line > 64 KB: detected, no partial-line misparse); `test_keypoint_choices_are_the_union_when_files_share_none` (two scanned files with disjoint keypoints: the choices list the keypoints of every file, and reading a file with a keypoint it lacks raises the existing `READER_OPTION_INVALID` naming the choices); `test_dlc3d_frame_index_errors_say_deeplabcut_3d` (duplicate / negative / non-integer index: the new code and the text "DeepLabCut 3-D", not `DLC_*`); `test_dlc3d_duplicate_column_is_refused`; `test_a_2d_table_with_z_and_likelihood_is_not_claimed_by_dlc3d` (it is claimed by `deeplabcut`, not `deeplabcut_3d`).
- [ ] **Step 2: Run** `pytest tests/test_readers -k "peek or keypoint_choices or deeplabcut_3d or duplicate_column or likelihood" -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Read the whole first header line(s) (bounded at a generous cap, e.g. 8 MB, then treat as undetected with a one-line log) instead of a fixed 64 KB slice; for the keypoint choices use the union and keep the per-file read check; give `deeplabcut_3d.py` its own table reader errors instead of reusing the `DLC_*` ones (update the existing tests that pin `DLC_BAD_FRAME_INDEX` for the 3-D reader only); raise on duplicate `(bodypart, coord)`.
- [ ] **Step 4: Run** `pytest tests/test_readers tests/real_samples tests/test_scan -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(readers): native 3-D readers read whole headers, name their own errors, refuse duplicate columns`.

### Task 2: Session, pipeline and engine guards

**Files:** Modify `track2data/views/panels.py` (`keep_animals`), `track2data/fusion/fuse.py`, the identity-switch correction step in `track2data/preprocess/` (find `correct_switches`), `track2data/core/models.py` (`Session.pixel_size_known`), `track2data/cli.py` (`t2d add`), `ui/store/project_store.py` (`add_session`); Test `tests/test_native3d/test_guards.py` (new), plus the existing files named by the greps below.

**Interfaces:**
- Produces: `keep_animals` logs a `warning` (logger of that module) naming the session when it drops a `raw_z` whose shape does not match; the `fuse()` refusal message names the actual condition ("session <id> has no pixel frame (a native 3-D session has no views to fuse)"); `correct_switches` logs one `warning` per call and leaves `z` untouched when a session with `z` has more than one animal (the documented single-animal limit made visible); `Session.pixel_size_known` removed together with its references (grep first; `SessionFacts.pixel_size_known` stays); `t2d add` names the file whose read failed (`"<path>: <reason>"`) in its error and exit message; `ProjectStore.add_session` runs the same native mixing/unit pre-check as `add_confirmed` before listing a session when the reader can be resolved from the folder without a probe, otherwise keeps the post-probe check.

- [ ] **Step 1: Write failing tests:** `test_keep_animals_warns_when_dropping_a_mismatched_z` (caplog); `test_fuse_refusal_names_the_missing_pixel_frame`; `test_switch_correction_warns_for_multi_animal_z`; `test_t2d_add_names_the_unreadable_native_file` (a corrupt Anipose file in a batch with a good one: message contains the corrupt file's path); `test_add_session_refuses_a_mixed_native_folder_before_listing` (pytest-qt, offscreen); and a grep-based assertion test is not needed for the removed property (existing tests that referenced it are updated).
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement** each item as in Interfaces; keep pixel behaviour byte-identical; when removing `Session.pixel_size_known`, update tests/docs that mention it.
- [ ] **Step 4: Run** `pytest tests/test_native3d tests/test_views tests/test_fusion tests/test_ui tests/test_preprocess tests/test_cli* -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(native3d): session and engine guards for deferred minors`.

### Task 3: Availability, CLI and docs wording

**Files:** Modify `track2data/cli.py` (`list-metrics`, `t2d add` unit line), `track2data/metrics/availability.py` (water-column reason wording), `docs/METRICS_SPEC.md`, `docs/guide/USER_GUIDE.md` (only if it quotes changed text), `CHANGELOG.md`; Test `tests/test_cli/` or `tests/test_integration/test_end_to_end.py` (where the existing `list-metrics` test lives), `tests/test_native3d/test_project_rules.py`.

**Interfaces:**
- Produces: `NEEDS_WATER_COLUMN_REASON` keeps its text for the Metrics screen; the CLI (`t2d validate`/`run` skip lines) renders it with "Calibration page" replaced by "calibration settings (`calibration.water_column` in the project)" through a small `availability.reason_for_cli(reason: str) -> str` (identity for every other reason); `t2d list-metrics` gains one footer line stating that availability also depends on the project (3-D data, cm scale, pixel frame, number of animals) and pointing to `t2d validate`, with the VIEW column unchanged; `t2d add --yes` prints a `check: unit=mm (proposed by the reader; override with --option unit=...)` line for every proposed (not given) required option; `docs/METRICS_SPEC.md` gets an "Availability" note on the IL-3, IL-9, IL-10, IL-14 rows and on the group-metrics section for native 3-D projects, quoting `NEEDS_PIXEL_FRAME_REASON` and `NEEDS_SEVERAL_ANIMALS_REASON` exactly (import the constants in the test and assert the doc contains them).

- [ ] **Step 1: Write failing tests:** `test_reason_for_cli_rewrites_only_the_water_column_reason`; `test_cli_skip_line_for_il15_names_the_project_setting`; `test_list_metrics_footer_points_to_validate` (and the existing pixel rows/columns unchanged); `test_add_yes_prints_a_check_line_for_proposed_unit`; `test_metrics_spec_documents_native_unavailability` (doc contains both reason constants).
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; CHANGELOG `### Changed` entry.
- [ ] **Step 4: Run** `pytest tests/test_docs tests/test_native3d tests/test_metrics tests/test_integration/test_end_to_end.py -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(cli): clearer native 3-D availability wording and proposals`.

### Task 4: Metric tests and log noise

**Files:** Modify `track2data/api.py` (`compute_metrics` depth-scale skip warning), `track2data/metrics/geometry3d.py` (tests only), Test `tests/test_metrics/test_nnd_3d.py`, `tests/test_camera_view_gating.py`.

**Interfaces:**
- Produces: the per-session depth-scale skip warning is logged once per run per `(metric, reason)` with the count of sessions affected ("IL-16 skipped for 12 sessions: needs a cm scale ...") instead of once per metric per session; the README skip list and `skipped_metrics` are unchanged.

- [ ] **Step 1: Write failing tests:** `test_depth_scale_skip_warning_is_logged_once_per_run` (caplog: 3 sessions, one metric, one reason: exactly one record whose text contains "3 sessions"); `test_nnd3d_zero_animals_and_zero_frames_give_nan_without_warnings` (`-W error::RuntimeWarning`, columns present, `n_skipped_frames_3d == n_frames`).
- [ ] **Step 2: Run** the new tests. Expected: FAIL (first) / PASS or FAIL (second; if it passes keep it as a regression test).
- [ ] **Step 3: Implement** the log aggregation around the existing warning in `compute_metrics`.
- [ ] **Step 4: Run** `pytest tests/test_metrics tests/test_camera_view_gating.py tests/test_api.py -q -W error::RuntimeWarning`, then the full suite (`QT_QPA_PLATFORM=offscreen python -m pytest -q -W error::RuntimeWarning`, in the background with output to a file; report any segfault verbatim), ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(metrics): one skip warning per run; NND zero-size tests`.
