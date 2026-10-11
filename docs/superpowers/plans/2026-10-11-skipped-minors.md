# Skipped Minor Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the minors that the earlier deferred-minors plan deliberately skipped, and a few small parked ones, correcting two published counts and one inconsistency along the way.

**Architecture:** Three independent tasks: (1) group-metric count and convention fixes, (2) IL-17 vertical speed computed once on the whole series and sliced with the session, (3) small reader/CLI/wording robustness items. Corrections that change an exported number are listed in the CHANGELOG under `### Fixed`.

**Tech Stack:** Python, pydantic v2, numpy/pandas, PySide6, pytest/pytest-qt, ruff, mypy (CI: mypy 2.4.0 + numpy 2.4.6).

**Spec:** `docs/3d-movement/2026-10-10-3d-metrics-design.md` (IL-17, GL-16) and `docs/3d-movement/2026-10-10-native-3d-files-design.md`; the earlier plans `2026-10-11-deferred-minors.md` and `2026-10-11-native-3d-files.md` carry the decisions this plan builds on.

## Global Constraints

- The only exported numbers that may change: GL-1 and GL-16 `n_skipped_frames` / `n_skipped_frames_3d` for sessions that have unfilled gaps between tracking intervals (separator rows no longer counted), GL-16 `mean_nnd_3d_bl` only for sessions with a zero or non-finite per-animal body length, and IL-17 values at bin edges in binned runs (and only there). Every other metric value, exported file and `project_hash` stays identical (existing suites and the golden pixel README/hash tests stay green).
- A separator row (`PreprocessedSession.separator_mask`) is "not a frame" (see its docstring in `core/models.py`): it is never counted as a skipped frame.
- New tests are written first (RED recorded), `-W error::RuntimeWarning` clean; `ruff check .` and CI-venv mypy clean; lines <= 100 chars; do not reformat whole files.
- Not in this plan: the Anipose real-sample contract case (fixture host unreachable from here), rewriting commit trailers (needs a force-push of merged history), regenerating screenshots (checked separately), and new features.

## Review Focus

- A session with `separator_mask` None (every pixel session without tracking intervals) must produce byte-identical GL-1/GL-16 output.
- A sliced (windowed or binned) session must see the same vertical speed values as the whole-session series at the same frames; a session with no precomputed vertical speed (direct `compute()` calls) must still work.
- The CLI log formatter must keep rewriting the water-column reason when the root logger already has handlers, or document that it does not.

---

### Task 1: Group-metric counts and body-length convention

**Files:** Modify `track2data/metrics/group.py` (GL-1 `NearestNeighbourDistance`, GL-16), `CHANGELOG.md` (`### Fixed`), `docs/METRICS_SPEC.md` (GL-1 and GL-16 sections), the wiki page(s) under `docs/wiki/` that quote `n_skipped_frames` or the reanalysis guidance (follow the repo's wiki conventions: `scripts/check_wiki.py`, stamps); Test `tests/test_metrics/test_group.py`, `tests/test_metrics/test_nnd_3d.py`.

**Interfaces:**
- Produces: GL-1 and GL-16 skip counts that exclude separator rows (`n_skipped_frames` = frames, among real rows, with at least one NaN animal; the one-animal early return reports the number of real rows); GL-16 `mean_nnd_3d_bl` computed like GL-1's `mean_nnd_bl`: the nan-mean of the raw per-animal `body_length_in_px()` over `px_per_cm`, valid only when positive and finite.

- [ ] **Step 1: Write failing tests:** `test_gl1_does_not_count_a_separator_row_as_skipped` (3 frames + 1 separator row + 3 frames, two animals, all finite on real rows: `n_skipped_frames == 0`, mean unchanged); `test_gl1_counts_real_nan_rows_only` (separator plus one real NaN frame: 1); `test_gl1_one_animal_reports_real_rows` (separator excluded); the same three for GL-16 (`n_skipped_frames_3d`); `test_gl16_bl_matches_gl1_convention` (three animals with body lengths [10, 0, 20] px: GL-16 `mean_nnd_3d_bl` equals GL-16 `mean_nnd_3d_cm / (mean([10, 0, 20]) / px_per_cm)` exactly as GL-1's rule gives, and a zero-only or non-finite mean gives NaN with no warning); `test_sessions_without_separators_are_unchanged` (a session with `separator_mask None`: output equal to the old formula on a random fixture).
- [ ] **Step 2: Run** `pytest tests/test_metrics/test_group.py tests/test_metrics/test_nnd_3d.py -k "separator or convention or unchanged" -v -W error::RuntimeWarning`. Expected: FAIL.
- [ ] **Step 3: Implement** by skipping rows where `separator_mask` is true in both loops and in the early-return counts; align GL-16's bl rule; add the CHANGELOG `### Fixed` entries (both counts, and the GL-16 bl rule) and the METRICS_SPEC sentences; update the wiki page(s) if they quote the counts (`scripts/check_wiki.py` must stay clean).
- [ ] **Step 4: Run** `pytest tests/test_metrics tests/test_docs tests/test_integration -q -W error::RuntimeWarning`, `python scripts/check_wiki.py`, ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(metrics): separator rows are not frames in GL-1/GL-16 counts; GL-16 body length follows GL-1`.

### Task 2: IL-17 vertical speed from the whole series

**Files:** Modify `track2data/core/models.py` (`PreprocessedSession.z_speed`), `track2data/metrics/binning.py` (`slice_psess` slices it), `track2data/api.py` (compute it once per session before windows are cut, where `uses_kinematics_cfg` metrics are run: find `_effective_cfg` and `_compute_windowed`), `track2data/metrics/individual.py` (`Speed3D` uses it), `docs/METRICS_SPEC.md` (IL-17 binned note), `CHANGELOG.md`; Test `tests/test_metrics/test_speed_3d.py`, `tests/test_native3d/test_core.py`.

**Interfaces:**
- Produces: `PreprocessedSession.z_speed: np.ndarray | None = None`, shape `(n_frames, n_animals)`, the vertical speed in the project length unit per second computed by `compute_kinematics` on the whole-session Z with the manifest's `KinematicsCfg`; `metrics/geometry3d.py::vertical_speed(psess, kin_cfg) -> np.ndarray | None` (the single implementation: Z from `positions_cm`, derivative via `compute_kinematics`, `None` when there is no Z); `Speed3D` reads `psess.z_speed` when present and otherwise calls `vertical_speed` on its own slice (direct `compute()` calls keep working).

- [ ] **Step 1: Write failing tests:** `test_vertical_speed_helper_matches_the_estimator` (known Z series, default and forward-difference configs: equals `compute_kinematics` output / the existing Speed3D values); `test_binned_iL17_bins_are_slices_of_the_whole_series` (a non-constant-velocity Z track, `timepoint_minutes` giving several bins: each bin's `mean_speed_3d_cm_s` equals the mean of the whole-session per-frame 3-D speed over that bin's frames — the old per-bin re-estimate differs at the bin edges; assert equality to 1e-9 on a track where it used to differ); `test_slice_psess_slices_z_speed`; `test_speed3d_without_precomputed_z_speed_still_works`; `test_whole_session_iL17_is_unchanged` (an unbinned run: identical to the previous values).
- [ ] **Step 2: Run** `pytest tests/test_metrics/test_speed_3d.py tests/test_native3d/test_core.py -k "z_speed or whole_series or helper or unchanged or slices" -v -W error::RuntimeWarning`. Expected: FAIL.
- [ ] **Step 3: Implement** the field, the helper (move the vertical-speed code out of `Speed3D.compute` so there is one implementation), the slice, the once-per-session computation in the engine for sessions that have Z and a scale (only when a selected metric has `uses_kinematics_cfg`; fused and native alike), and the docs/CHANGELOG notes (IL-17 bin-edge values now match the whole-session estimate; unbinned values unchanged).
- [ ] **Step 4: Run** `pytest tests/test_metrics tests/test_native3d tests/test_integration tests/test_preprocess tests/test_fusion -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(metrics): IL-17 vertical speed is estimated once on the whole series`.

### Task 3: Reader, CLI and wording robustness

**Files:** Modify `track2data/readers/anipose.py`, `track2data/readers/deeplabcut_3d.py`, `track2data/readers/native3d.py`, `track2data/cli.py` (log formatter), `track2data/api.py` (the native-mixing refusal text); Test `tests/test_readers/test_anipose.py`, `tests/test_readers/test_deeplabcut_3d.py`, `tests/test_native3d/test_project_rules.py`, `tests/test_cli/` (where the `run` log test lives).

**Interfaces:**
- Produces: (1) a file whose header line is longer than the 8 MB cap raises, when read directly, `DataValidationError(code="HEADER_TOO_LONG")` naming the file and the cap instead of the generic "not an Anipose/DeepLabCut 3-D table" (detection stays False); (2) `discover()` of both readers adds a `SessionCandidate.warnings` entry for a file with a duplicate `(bodypart, coord)` column (`"duplicate column <name>: the file will be refused when read"`), as the 2-D reader does for its own problems; (3) the CLI log rewrite becomes a `logging.Formatter` subclass `_ReasonFormatter` wrapping the handler's existing formatter (no private `Formatter._fmt` access), and also applied to handlers already on the root logger when `cli()` starts; (4) the `NATIVE_3D_MIXED` text for a folder that is not a native file says `"'<id>' is not a native 3-D file (no native reader recognised it)"` when the ref has no reader, instead of `pixel-tracked`.

- [ ] **Step 1: Write failing tests:** `test_overlong_header_read_says_so` (both readers; 9 MB single line); `test_discover_warns_about_a_duplicate_column` (both readers); `test_cli_formatter_is_a_formatter_subclass_and_rewrites_the_reason` (no `_fmt` attribute access: assert via the public `format()` on a LogRecord, with the original format preserved) and `test_cli_rewrites_on_preinstalled_handlers` (root logger with a handler before `cli()` main runs in-process via `CliRunner`: the record's formatted output carries the CLI text); `test_undetected_folder_into_a_native_project_message` (assert the new wording, and the old `pixel-tracked` wording still used for a ref whose reader is a known pixel reader).
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; keep every existing code and message that other tests pin.
- [ ] **Step 4: Run** `pytest tests/test_readers tests/real_samples tests/test_scan tests/test_native3d tests/test_cli* tests/test_integration -q -W error::RuntimeWarning`, then the full suite (`QT_QPA_PLATFORM=offscreen python -m pytest -q -W error::RuntimeWarning`, in the background with output to a file; quote the summary line), ruff, mypy. Expected: PASS.
- [ ] **Step 5: Commit** `fix(native3d): clearer overlong-header, duplicate-column and mixing messages; CLI formatter without private access`.
