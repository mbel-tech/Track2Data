# Backlog Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the twelve highest value-for-effort items left open after the v0.3.0 audit of every plan, design doc and roadmap.

**Architecture:** Twelve mostly independent tasks, each with its own tests and commit. Small fixes first (view gating, zones backdrop, panel-aware duplicates), then interoperability (xarray adapter, `probe_video`, `lenient_detection`, DLC `.h5`), then docs, small features and metrics, then one task that is blocked on a design decision (multi-animal Anipose). No change to any existing metric value for projects that do not opt in.

**Tech Stack:** Python 3.11+ (dev env: `py -3.14`), pydantic v2, numpy/pandas, h5py, PySide6, pytest/pytest-qt, ruff, mypy (CI: mypy 2.4.0 + numpy 2.4.6).

**Spec:** the audit in this session's transcript, plus the design docs each task names: `docs/3d-movement/2026-10-08-side-view-depth-design.md`, `docs/3d-movement/2026-10-09-panel-split-design.md`, `docs/3d-movement/2026-10-10-3d-metrics-design.md`, `docs/3d-movement/2026-10-10-native-3d-files-design.md`, `docs/tracker-formats/2026-10-07-tracker-import-design.md`, `docs/tracker-formats/2026-10-08-tier-1-implementation-plan.md`, `docs/tracker-formats/2026-10-08-tier-2-implementation-plan.md`, `docs/INTEROPERABILITY.md`, `docs/ENGINE_DESIGN.md`.

## Global Constraints

- Test command is `py -3.14 -m pytest <path> -q -W error::RuntimeWarning`; lint is `ruff check .` (line length 100, `ruff format` not enforced repo-wide, do not reformat whole files); types are `mypy` on `track2data` only, CI venv.
- No change to any metric value, exported file or `project_hash` for pixel-frame, fused 3-D or existing native projects. The golden tests `tests/test_native3d/test_pixel_unchanged.py` (pinned `GOLDEN_HASH`, `GOLDEN_JSON_SHA`), `tests/test_native3d/test_no_pixel_frame.py` and the golden README tests stay green.
- Every new error uses an existing error class and carries `code`, `subject` and `remediation` like its neighbours.
- New tests are written first and the RED run is recorded. Optional dependencies missing from `py -3.14` (`tables`, `av`, `xarray`) are handled with `pytest.importorskip`; any new dependency goes into its extra and into `dev` in `pyproject.toml` with the usual inline comment.
- Adding or removing a registered metric must update, in the same commit: `docs/METRIC_REFERENCES.csv` (via `scripts/generate_metric_references.py`), `docs/METRICS_SPEC.md` (a `#### <ID> — …` section, §3 taxonomy, §4.5 identity-free table, §5 implementation map), and the four prose counts pinned by `tests/test_metric_references_consistency.py::test_metric_counts_stated_in_the_docs_match_the_registry` (`track2data/metrics/base.py` "N of M today", the METRICS_SPEC "N of the M metrics" sentence, `README.md:7`, `docs/dev/ROADMAP.md:29`).
- Each behaviour change gets a `docs/dev/DECISIONS.md` entry (check the highest existing D-number first; D-044 was the last seen) and a `CHANGELOG.md` `[Unreleased]` line.
- Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Commit after each task; push only to the existing remote, never create one.
- Not in this plan (do not touch): the statistics module, GPU, cloud sync, plug-in marketplace, `qasync`, Z-10 depth bands and depth-band zones, manual identity-swap correction, TRex/ToxTrac/AnimalTA readers, video scrubbing, vectorised group metrics, code signing, the idtracker.ai v4 reader, SLEAP `.slp`/CSV variants, rewriting commit trailers.

## Review Focus

- **IL-3/IL-14 gate must keep legacy projects working:** a project whose `camera_view` is `"unknown"` or `"top"`, and every fused or native session, must still run IL-3 and IL-14 with unchanged values.
- **DLC `.h5` must never unpickle at scan time** and must not be claimed twice: the SLEAP reader refuses `df_with_missing`, and `tests/real_samples/test_detection_matrix.py` expects exactly one claimant per real file; a `.csv` and `.h5` pair counts as one session.
- **A video frame whose size differs from `(width_px, height_px)` must never become a zones backdrop**, otherwise zone coordinates are stamped in the wrong pixel space.
- **Panel split then rescan:** rescanning a folder whose whole-frame session was split into panels must offer it again, while a true duplicate (same folder, reader, session selector, panel) is still left out.
- **Metrics with NaN-skipping frames on fragment-heavy files:** the new advisory must be silent for a `SessionSummary` built without the new field, and the xarray adapter must handle separator rows, unobserved rows and a missing `px_per_cm`.

---

### Task 0: Tag v0.3.0 (user-run, before anything else is merged)

**Files:** none.

- [ ] **Step 1:** Confirm the `CI passed` check is green on `a392f93` (`gh run list --branch main --limit 3`).
- [ ] **Step 2:** The user runs `git tag -a v0.3.0 a392f93c155c676104dbeb7256bea2d2e7d603ff -m "Release 0.3.0" && git push origin v0.3.0`. Tagging that exact commit keeps this plan's later changes out of the release. `release.yml` triggers on the tag; PyPI and Zenodo may still be unconfigured (`docs/dev/RELEASING.md`), so a PyPI job failure is possible and is not caused by this plan.
- This step is the user's decision. Do not run it without an explicit yes.

### Task 1: Gate IL-3 and IL-14 for side views

**Files:**
- Modify: `track2data/metrics/individual.py` (IL-3 `CentreDistance` L256, IL-14 `WallDistanceThigmotaxis` L1480)
- Modify: `ui/metrics_screen.py` (`PRESETS` "Thigmotaxis & space use", L54-59)
- Modify: `docs/dev/DECISIONS.md` (new entry superseding the "existing metrics are not gated" line of D-036), `docs/3d-movement/2026-10-08-side-view-depth-design.md` (L18, L26), `docs/3d-movement/2026-10-08-3d-roadmap.md:31`, `docs/guide/USER_GUIDE.md` (~L434-440), `docs/METRICS_SPEC.md` (IL-3, IL-14 "Required preprocessing" row and assumption line), `CHANGELOG.md`
- Test: `tests/test_metrics/test_availability.py`, `tests/test_camera_view_gating.py`, `tests/test_ui/test_metrics_screen.py`, `tests/test_integration/test_side_view_depth.py`

**Interfaces:**
- Produces: `CentreDistance.valid_camera_views` and `WallDistanceThigmotaxis.valid_camera_views`, both `frozenset({"top", "unknown"})`. Nothing else changes: `view_unavailable_reason` in `track2data/metrics/availability.py` already reads the attribute, and the CLI VIEW column renders "not set or top-down" automatically.

- [ ] **Step 1: Write failing tests**
  - `test_il3_and_il14_declare_top_and_unknown_views` (registry lookup, asserts both sets equal `frozenset({"top","unknown"})`).
  - `test_il3_and_il14_are_unavailable_on_a_declared_side_view` (via `unavailable_reason(cls, "side")` is not None and mentions "top-down").
  - `test_il3_and_il14_stay_available_for_top_unknown_fused_and_native_sessions` (parametrize `"top"`, `"unknown"`, and `camera_view_for_psess` of a fused psess).
  - UI: `test_thigmotaxis_preset_leaves_greyed_side_view_rows_unticked` in `tests/test_ui/test_metrics_screen.py` using `_set_view(store, "side")`.
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_metrics/test_availability.py tests/test_camera_view_gating.py tests/test_ui/test_metrics_screen.py -k "il3 or il14 or thigmotaxis" -q`. Expected: FAIL.
- [ ] **Step 3:** Add `valid_camera_views: ClassVar[frozenset[CameraView] | None] = frozenset({"top", "unknown"})` to both classes. The set must include `"unknown"`, or every legacy project loses both metrics. Native projects keep their existing `PIXEL_FRAME_METRIC_IDS` reason because that check runs first.
- [ ] **Step 4:** Rewrite the stale prose listed under Files (the USER_GUIDE paragraph "Declaring a view does not switch off any existing metric" is now false). Run the full `tests/test_metrics tests/test_ui/test_metrics_screen.py tests/test_native3d tests/test_integration -q -W error::RuntimeWarning`, `ruff check .`, mypy. Expected: PASS, golden hashes unchanged.
- [ ] **Step 5:** Commit `feat(metrics): gate IL-3 and IL-14 to top-down and unset camera views`.

### Task 2: Zones canvas video-frame backdrop

**Files:**
- Modify: `ui/zones_screen.py` (`_refresh_canvas`, ~L475-490), `ui/widgets/zone_canvas.py` (`ZoneCanvas.load_session`, ~L255-320)
- Modify: `ui/widgets/panel_preview.py` (extract the existing `_video_frame` static method into a shared helper)
- Modify: `track2data/readers/video_meta.py` (new `extract_frame_rgb(video_path, frame_index=0) -> tuple[bytes, int, int] | None` returning the bytes with the frame's own decoded `(width, height)` from the `av` frame; `extract_frame` becomes a thin wrapper that returns only the bytes, so its callers and mocks are unchanged)
- Create: `ui/widgets/video_frame.py` holding `decode_first_frame(video_path: Path | None, width_px: int, height_px: int) -> QImage | None`
- Test: `tests/test_ui/test_zones_screen.py`, `tests/test_ui/test_zone_canvas.py`, `tests/test_ui/test_panel_preview.py`, `tests/test_readers/test_video_meta.py`

**Interfaces:**
- Produces: `decode_first_frame(...)` returning `None` unless the path exists, `extract_frame_rgb(path, 0)` returns a frame whose **reported `(width, height)` equals `(width_px, height_px)`** and `len(data) == w * h * 3`. A byte-length check alone is not enough: a rotated or transposed frame (1080x1920 against a declared 1920x1080) has the same `w * h * 3`, so the decoded dimensions are the guard and the length is only a sanity check. `ZoneCanvas.load_session(background_image_path, setup_points, frame_size=None, crop=None, video_path: Path | None = None)` falls back to `decode_first_frame` only when the backdrop image is missing and `crop is None`.
- Consumes: `SessionFacts.video_path` (already filled), `track2data.readers.video_meta.extract_frame`.

- [ ] **Step 1: Write failing tests** (monkeypatch `extract_frame_rgb` (and `extract_frame` for the preserved `PanelPreview` path) as `tests/test_ui/test_panel_preview.py` does):
  - `test_zone_canvas_uses_the_video_first_frame_when_there_is_no_background_image`
  - `test_a_video_frame_of_the_wrong_size_is_rejected_and_the_canvas_stays_blank`
  - `test_a_transposed_frame_with_the_same_byte_count_is_rejected` (mock `extract_frame_rgb` to return `(bytes(1920*1080*3), 1080, 1920)` against a declared 1920x1080)
  - `test_extract_frame_rgb_reports_the_decoded_frame_size` (in `tests/test_readers/test_video_meta.py`, `av` mocked as `TestExtractFrame*` does)
  - `test_a_cropped_panel_never_falls_back_to_the_video_frame`
  - `test_zones_screen_passes_the_session_video_path_to_the_canvas`
  - `test_panel_preview_still_reports_backdrop_kind_video` (refactor guard).
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_ui/test_zones_screen.py tests/test_ui/test_zone_canvas.py tests/test_ui/test_panel_preview.py -q`. Expected: FAIL on the new tests.
- [ ] **Step 3:** Implement `extract_frame_rgb`, then the helper by moving `PanelPreview._video_frame` logic and swapping its length-only check for the decoded-size check (so `PanelPreview` gets the stricter guard too), have `PanelPreview` call it, add the `video_path` parameter to `ZoneCanvas.load_session`, and pass `facts.video_path` from `ZonesScreen._refresh_canvas`. The decoded-size check is the guard in Review Focus; the first saved zone stamps `source_*_px`, so a wrong-size frame must be refused, not scaled.
- [ ] **Step 4:** Run the three test files plus `tests/test_api.py -k preview_frame`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): show the video's first frame behind the zones canvas`.

### Task 3: Panel-aware `_already_added`

**Files:**
- Modify: `track2data/readers/confirm.py` (`ConfirmDraft.__init__` L83-88, `_already_added` L311-316)
- Modify: `ui/store/project_store.py` (`_is_duplicate` L105-121 reuses the shared helper)
- Create: `track2data/core/session_identity.py` with `same_session_part(a: SessionRef, b: SessionRef) -> bool`
- Test: `tests/test_readers/test_confirm.py` (class `TestSessions`), `tests/test_ui/test_project_store.py`, `tests/test_ui/test_import_screen.py`

**Interfaces:**
- Produces: `same_session_part(candidate: SessionRef, existing: SessionRef) -> bool`, deliberately **not symmetric**, copying `project_store._is_duplicate` exactly: same resolved folder; `existing.reader is None or existing.reader == candidate.reader` (only the *existing* ref's `None` is a wildcard, a candidate with `reader=None` matches only an existing ref that also has none or the same name); session-scope option values equal; and `existing.panel == candidate.panel`. It lives in `track2data/core` so `confirm.py` and `project_store.py` both import it without the circular import that importing `find_reader` into `confirm.py` would cause. The session-scope option selector currently lives in `project_store._selector`; move it with the helper and pass the reader's parameters in rather than importing `find_reader` at module level.
- Candidate refs from the dialog are `panel=None`; existing refs with a `panel` therefore no longer block them.

- [ ] **Step 1: Write failing tests**
  - `test_a_whole_frame_candidate_is_offered_again_after_the_folder_was_split_into_panels` (existing `SessionRef` with `panel=PanelRect(...)`, candidate `panel=None`, `already_added is False`).
  - `test_a_true_duplicate_is_still_left_out` (same folder, reader, selector, panel).
  - `test_project_store_and_confirm_agree_on_what_a_duplicate_is` (a fixed truth table written out as data, not derived from the implementation: existing reader `None`/`"a"` x candidate reader `None`/`"a"`/`"b"` x panel equal/different, run through both code paths; the asymmetric cases (existing `"a"` with candidate `None`) are listed explicitly as not duplicates).
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_readers/test_confirm.py tests/test_ui/test_project_store.py -k "panel or duplicate" -q`. Expected: FAIL.
- [ ] **Step 3:** Implement the shared helper, make `ConfirmDraft` keep its existing list as `SessionRef`s rather than `(folder, reader)` tuples, and make `_is_duplicate` delegate. Keep the legacy rule above and do not make it symmetric.
- [ ] **Step 4:** Run `tests/test_readers tests/test_ui/test_project_store.py tests/test_ui/test_import_screen.py tests/test_ui/test_panel_dialog.py -q`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `fix(import): a split folder is not "already in the project" when rescanned`.

### Task 4: `movement` / xarray adapter

**Files:**
- Create: `track2data/interop/__init__.py`, `track2data/interop/movement.py`
- Modify: `pyproject.toml` (new extra `xarray = ["xarray>=2023.1"]`, also added to `dev` with an inline comment), `docs/INTEROPERABILITY.md` (replace the "Planned" section L53-125 and the status row L134), `docs/dev/DECISIONS.md`, `CHANGELOG.md`
- Test: `tests/test_interop/test_movement.py` (new directory with `__init__.py`)

**Interfaces:**
- Produces: `to_movement_dataset(psess: PreprocessedSession, *, include_separator_rows: bool = False) -> "xarray.Dataset"`. Lazy `import xarray` inside the function, raising an `ImportError_` with `code="XARRAY_MISSING"` and remediation `pip install track2data[xarray]`. Dataset dims `("time", "individuals", "keypoints", "space")`; `position` from `psess.xy[..., None, :]`; `time` from `psess.timeline()` divided by `psess.fps`, not `np.arange` (the documented snippet is wrong for gappy files); `individuals` from `session.identities_labels` else `0..n-1` as strings; `keypoints` from the session's keypoint selection, else `["centroid"]`; `space` `["x","y"]` or `["x","y","z"]` when `psess.z` is present. Rows where `psess.separator_mask` is true are dropped unless `include_separator_rows`; rows with `tracked_mask` false stay as NaN. Identity confidence goes in a separately named variable `identity_confidence`, never as `confidence` (it is identity confidence, not pose confidence, per `docs/INTEROPERABILITY.md` L83-89). Attrs: `fps`, `source_software` from `session.source_software`, `reader_verification`, `length_unit` (`"px"` when `px_per_cm` is None), `px_per_cm`.
- Not an exporter: `ExportPayload` has no `xy` array, so this does not register in `track2data/exporters`.

- [ ] **Step 1: Write failing tests** (all with `xarray = pytest.importorskip("xarray")` except the first):
  - `test_a_missing_xarray_raises_a_coded_error` (monkeypatch `sys.modules["xarray"] = None`).
  - `test_dims_and_shapes_for_a_two_animal_session`
  - `test_time_follows_the_timeline_across_a_tracking_gap`
  - `test_separator_rows_are_dropped_by_default_and_kept_on_request`
  - `test_identity_confidence_is_not_called_confidence`
  - `test_a_native_3d_session_gets_a_z_space_coordinate`
  - `test_attrs_carry_source_software_and_unit`
- [ ] **Step 2:** Install the extra in the dev env (`py -3.14 -m pip install "xarray>=2023.1"`; ask the user first if pip install is not already approved), then run `py -3.14 -m pytest tests/test_interop -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `to_movement_dataset`. Verify the native z attribute name on `PreprocessedSession` (`grep -n "z:" track2data/core/models.py` near L938) before using it.
- [ ] **Step 4:** Rewrite the INTEROPERABILITY section as "Using the `movement` package" with the real call, and flip the status row to supported. Run `tests/test_interop tests/test_docs -q`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat(interop): export a PreprocessedSession as a movement-style xarray Dataset`.

### Task 5: `probe_video`

**Files:**
- Modify: `track2data/readers/video_meta.py` (add `probe_video` beside `extract_frame`)
- Modify: `track2data/readers/confirm.py` (`ConfirmDraft._enter` L294-309, new `ConfirmDraft.prefill_from_video(path: Path) -> None`), `ui/dialogs/confirm_format_dialog.py` (a "Read from video…" button next to the DLC/SLEAP fps and size fields), `ui/widgets/reader_options_form.py` (`_NOTES` already knows source `"video"`)
- Modify: `docs/tracker-formats/2026-10-08-tier-1-implementation-plan.md` (mark T1-1 `probe_video` built), `CHANGELOG.md`
- Test: `tests/test_readers/test_video_meta.py`, `tests/test_readers/test_confirm.py`, `tests/test_ui/test_confirm_format_dialog.py`

**Interfaces:**
- Produces: `probe_video(video_path: Path) -> VideoProbe | None` where `VideoProbe` is a frozen dataclass `(fps: float, width_px: int, height_px: int, n_frames: int | None)`; returns `None` when `av` is missing, the file is unreadable, fps or size is not positive. Never raises. `prefill_from_video` sets `fps`, `width_px`, `height_px` on the draft with source `"video"` (`ValueSource` in `track2data/readers/params.py:24`).
- The scan must never open videos (it is header-peek only), so probing happens at dialog time on a user-chosen video, never inside `discover`.

- [ ] **Step 1: Write failing tests** (mock `av` through `sys.modules` exactly as `TestExtractFrame*` does):
  - `test_probe_video_without_av_returns_none`, `test_probe_video_of_a_missing_file_returns_none`
  - `test_probe_video_reads_fps_and_size_from_the_first_video_stream`
  - `test_a_zero_fps_or_zero_size_stream_returns_none`
  - `test_prefill_from_video_sets_values_with_source_video_and_leaves_user_values_alone`
  - `test_the_read_from_video_button_is_disabled_when_no_reader_needs_fps_or_size`
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_readers/test_video_meta.py tests/test_readers/test_confirm.py tests/test_ui/test_confirm_format_dialog.py -k probe -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Frame count comes from `stream.frames` when positive, else `None`. Only fill fields the user has not typed (`source != "user"`).
- [ ] **Step 4:** Run the same files in full, plus `tests/test_readers/test_conformance.py`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat(import): read fps and frame size from a chosen video for DLC and SLEAP`.

(Task 5 edits `ConfirmDraft._enter` and the confirm dialog, which Task 3 also touches: start it after Task 3 has landed.)

### Task 6: `lenient_detection` ("choose software…" re-run)

**Depends on:** Task 3 and Task 5. Tasks 3, 5 and 6 all edit `readers/confirm.py` (`ConfirmDraft`) and `ui/dialogs/confirm_format_dialog.py`; run them in that order on one line of branches, not in parallel, or the three will conflict.

**Files:**
- Modify: `track2data/readers/scan.py` (`ScanResult` keeps the `ScanIndex`; new `lenient_scan(result: ScanResult, reader_name: str) -> FormatGroup | None`), `track2data/readers/confirm.py` (`ConfirmDraft.offer_reader(name: str) -> bool`), `track2data/cli.py` (`add --reader` falls through to it), `ui/dialogs/confirm_format_dialog.py` (`_show_nothing_recognised` L212 gains a "Choose software…" combo)
- Modify: `track2data/readers/base.py` (optional `SessionReader.discover_lenient(cls, index, peek) -> list[Detection]`, default returns `[]`)
- Modify: `docs/tracker-formats/2026-10-07-tier-0-implementation-plan.md` (T0-4/T0-6 deferred notes), `CHANGELOG.md`
- Test: `tests/test_readers/test_scan.py`, `tests/test_readers/test_confirm.py`, `tests/test_ui/test_confirm_format_dialog.py`, `tests/test_cli`

**Interfaces:**
- Produces: `lenient_scan` re-runs one reader's `discover_lenient` on the retained index and returns a group with `Confidence.LOW`; `ConfirmDraft.select_reader` accepts a reader that did not detect only through `offer_reader`, so an unrelated forced reader still errors with the existing "No reader … recognised these sessions" message. Readers that implement `discover_lenient` in this task: `deeplabcut` and `sleap_analysis` (accept a file by extension and a loosened header check, still refusing what `read` cannot parse). Other readers return `[]`.
- Memory: the retained `ScanIndex` is dropped when the dialog closes; do not store it on the manifest.

- [ ] **Step 1: Write failing tests**
  - `test_a_scan_result_keeps_its_index_until_released`
  - `test_lenient_scan_offers_a_reader_that_did_not_detect_at_low_confidence`
  - `test_lenient_scan_of_an_unrelated_reader_returns_none`
  - `test_offer_reader_then_select_reader_succeeds_and_other_names_still_raise`
  - `test_the_empty_state_dialog_lists_readers_that_can_try_leniently` and `test_choosing_one_populates_the_session_rows`
  - `test_cli_add_with_reader_retries_leniently_on_a_header_mismatch`
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_readers/test_scan.py tests/test_readers/test_confirm.py tests/test_ui/test_confirm_format_dialog.py -k "lenient or offer_reader" -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. A lenient candidate still goes through `read`, so a wrong guess fails with the reader's normal coded error instead of producing a session.
- [ ] **Step 4:** Run `tests/test_readers tests/test_ui/test_confirm_format_dialog.py tests/test_cli tests/test_scan -q`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat(import): let the user force a reader on files no reader recognised`.

### Task 7: DeepLabCut `.h5` reader

**Files:**
- Create: `track2data/readers/deeplabcut_h5.py`, `tests/support/dlc.py::write_dlc_h5`, `tests/test_readers/test_deeplabcut_h5.py`
- Modify: `track2data/readers/deeplabcut.py` (share `_build_session`, `_Header`, `_Table`; `discover` dedupes a `.csv`/`.h5` pair by stem), `track2data/readers/__init__.py` (register, L47-55), `track2data/readers/peek.py` (`Peeker.hdf5_root` exposes the `df_with_missing` group marker)
- Modify: `tests/real_samples/test_detection_matrix.py:23` (`dlc_single_animal_h5` expects the new reader), `tests/real_samples/test_reader_contract.py:73` (the XFAIL case should now pass), `docs/tracker-formats/README.md:59`, `docs/INTEROPERABILITY.md:139`, `docs/dev/DECISIONS.md` (the G-H5 record), `CHANGELOG.md`
- Test: as above plus `tests/test_readers/test_sleap_analysis.py` (the "DLC h5 is not claimed by SLEAP" test must keep passing)

**Interfaces:**
- Produces: `class DeepLabCutH5Reader(SessionReader)` with `name = "deeplabcut_h5"`, the same `parameters` as `DeepLabCutReader`, `verification = "real_sample"` only if the EPM fixture contract case passes, otherwise `"synthetic_only"`. Decoding yields the same `(_Header, _Table)` the CSV path builds, so both formats go through one `_build_session` (the oracle equivalence).
- G-H5 decision, made by the spike in Step 1 and recorded in DECISIONS: **(a)** h5py reads the pandas `table` compound dataset and a restricted unpickler decodes the pickled column labels (deny every global except numpy array reconstruction, cap each attribute's size). **(b)** only if (a) cannot decode the real EPM file: an optional `hdf` extra with `tables`, behind the pickle-consent gate (`accepts_allow_pickle = True`). Either way the scan itself never unpickles (`peek.py` docstring rule) and the shipped reader does not import `tables` at module level.
- The maDLC stitched `_el.h5` (root group `tracks`) has no fixture and an unverified layout: it stays refused with a remediation message in this task.

- [ ] **Step 1 (spike, no production code):** Read `DLC_single-mouse_EPM.predictions.h5` (manifest `tests/real_samples/fixtures_manifest.json`; single key `df_with_missing`, shape (18485, 24), 8 bodyparts) with plain h5py, and with a restricted unpickler for the column attributes. Record which of (a) or (b) works, with the evidence, as a DECISIONS entry. Commit the entry alone.
- [ ] **Step 2: Write failing tests**
  - `test_dlc_h5_matches_the_csv_reader_on_the_same_pose` (write the same `random_pose` as CSV and h5; the sessions' `raw_xy` are equal).
  - `test_an_h5_and_csv_pair_is_one_session`
  - `test_scan_never_unpickles` (monkeypatch `pickle.loads` / `pickle.Unpickler` to raise; scanning a DLC h5 must not call them).
  - `test_a_hostile_pickled_label_is_refused_with_a_coded_error`
  - `test_sleap_and_dlc_h5_never_both_claim_a_file`
  - `test_the_epm_real_sample_is_read_to_18485_frames` (`real_sample` marker; skips only when the fixture file is absent. It must run without `tables`: it reads with the shipped h5py path and asserts the shape and bodypart count recorded in the Step 1 spike (18485 frames, 8 bodyparts). The separate test `test_the_epm_real_sample_matches_the_pytables_oracle` is the one that uses `pytest.importorskip("tables")`, to cross-check values.)
  - `test_a_tracks_group_h5_is_refused_with_a_remediation` (maDLC `_el.h5` layout).
- [ ] **Step 3:** Run `py -3.14 -m pytest tests/test_readers/test_deeplabcut_h5.py tests/test_readers/test_sleap_analysis.py -q`. Expected: new tests FAIL, existing SLEAP tests PASS.
- [ ] **Step 4:** Implement per the G-H5 outcome. Errors: `DLCH5_UNREADABLE`, `DLCH5_LABELS_REFUSED`, `DLCH5_LAYOUT_UNSUPPORTED`, each with `subject` and `remediation`.
- [ ] **Step 5:** Run `tests/test_readers tests/test_scan tests/real_samples -q` (real-sample tests skip when fixtures are absent), `tests/test_readers/test_conformance.py`, ruff, mypy. Expected: PASS and the `dlc_single_animal_h5` contract case no longer XFAILs. Check that the run did not skip the real-sample reader test: with the fixture present and `tables` absent it must still execute (`-rs` shows the skip reasons).
- [ ] **Step 6:** Commit `feat(readers): DeepLabCut .h5 predictions`.

### Task 8: Fix the stale docs

**Depends on:** Tasks 1-7 and 9-11, including Task 6 (it closes the tier-0 deferred notes this task would otherwise leave open). Task 8 runs last of all the code tasks and re-measures every number, so it never blocks them.

**Files:**
- Modify: `docs/dev/ROADMAP.md` (L3-4 status and date; L34 "~1760 passing"; M5 checklist L52 onward: first tag and branch protection are done, L80 "not yet applied" is false; reserved-ID table L106-125: D-11 is Metric Input Provenance, D-12 is Fragment Quality Scores, GL-16 is 3-D NND, so reassign their old proposals to unused IDs D-17, D-18 and GL-20, and keep GL-17 reserved; L157 screen count), `docs/INTEROPERABILITY.md` (add `anipose` and `deeplabcut_3d` rows, keep `trx.mat` "synthetic only"), `docs/tracker-formats/README.md` (L61, L121, L129 `trx.mat` is built, synthetic only), `docs/tracker-formats/2026-10-08-tier-2-implementation-plan.md` (L9, L44-49), `docs/IDTRACKERAI_FORMAT_ANALYSIS.md` (§3 gap table L177-207: re-check each row against `track2data/readers/idtrackerai/*` and mark done rows)
- Modify: the `- [ ]` boxes in `docs/superpowers/plans/2026-10-09-*.md`, `2026-10-10-*.md`, `2026-10-11-*.md` and `docs/tracker-formats/2026-10-07-tier-0-implementation-plan.md` (all currently unticked, 339 boxes). A box is ticked only after it is checked against the repository: the task's commit (`git log --oneline --grep`), its named test (`grep -rn "def <test name>" tests`) or file exists, or the `[0.3.0]` section of `CHANGELOG.md` records the feature. A box that cannot be verified stays `- [ ]` with a one-line `Status:` note under its task (not shipped, deferred, or superseded and by what). The tier-0 deferred items (T0-4, T0-6) are ticked only if Task 6 shipped them. This plan's own boxes are ticked by the executor as it goes
- Modify: `docs/dev/DECISIONS.md` only if a numbering fix needs a note
- Test: `tests/test_docs_tracker_formats.py` (pins sha256 of research files and README rows; run it before and after), `tests/test_metric_references_consistency.py`, `tests/test_docs`

- [ ] **Step 1:** Re-measure: `py -3.14 -m pytest --collect-only -q` (tail) for the test count, `len(track2data.metrics._registry)` for the metric count, and write the numbers into ROADMAP as "collected", not "passing".
- [ ] **Step 2:** Edit the files above, plan by plan, writing the verification evidence (commit subject or test name) in the commit message for the ticked set. Do not edit files that `tests/test_docs_tracker_formats.py` hashes (the research files); change only the README rows it keeps in step.
- [ ] **Step 3:** Run `py -3.14 -m pytest tests/test_docs_tracker_formats.py tests/test_metric_references_consistency.py tests/test_docs -q`. Expected: PASS.
- [ ] **Step 4:** Commit `docs: bring the roadmap, interoperability table and shipped plans up to date`.

### Task 9: Multi-sheet Excel metadata

**Files:**
- Modify: `track2data/metadata/loader.py` (`load`, L45-46), `track2data/core/models.py` (`MetadataSource` L701 gains `sheet: str | None = None`), `track2data/api.py:327` (`_metadata_join` passes the sheet), `ui/metadata_screen.py` (file filter, preview through `load`, a sheet combo shown only for workbooks with several sheets; L175-210 and L336), `ui/store/project_store.py:1229` (`update_metadata_source`)
- Modify: `docs/ENGINE_DESIGN.md` §6.2 L386-391, `docs/guide/USER_GUIDE.md` L526-559, `docs/dev/DECISIONS.md`, `CHANGELOG.md`
- Test: `tests/test_metadata/test_schema.py`, `tests/test_ui/test_metadata_screen.py`

**Interfaces:**
- Produces: `load(path: Path, sheet: str | None = None) -> pd.DataFrame` (`None` keeps today's behaviour, first sheet), and `list_sheets(path: Path) -> list[str]` (`[]` for CSV). A sheet name that is absent raises `ValueError` with the available names in the message. The new `MetadataSource.sheet` defaults to `None` so existing manifests load unchanged. A plain pydantic field would serialise as `"sheet": null` and change `project_hash` (a `model_dump` of the whole manifest) for every project that has a metadata source, so `MetadataSource` gets a wrap `model_serializer` that omits `sheet` when it is `None`; `project_hash` and the saved JSON are then byte-identical until a sheet is chosen.

- [ ] **Step 1: Write failing tests** (workbooks built with openpyxl, already in the `export` extra and `dev`):
  - `test_load_xlsx_defaults_to_the_first_sheet`, `test_load_xlsx_reads_a_named_sheet`, `test_an_unknown_sheet_name_lists_the_available_ones`, `test_list_sheets_of_a_csv_is_empty`
  - `test_a_manifest_without_a_sheet_keeps_its_hash` (a manifest that **has** a `MetadataSource`, hash and `model_dump_json` compared with the values computed before the change; the pinned golden projects have no metadata source, so they alone would not catch this) and `test_a_chosen_sheet_is_saved_and_changes_the_hash`
  - UI: `test_loading_an_xlsx_previews_it_and_offers_a_sheet_choice`, `test_choosing_a_second_sheet_persists_it_on_the_store`, `test_reopened_project_restores_the_chosen_sheet`
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_metadata tests/test_ui/test_metadata_screen.py -k "sheet or xlsx" -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. `.xls` stays declared but unsupported by openpyxl: raise a clear `ValueError` instead of the current silent failure.
- [ ] **Step 4:** Run `tests/test_metadata tests/test_ui/test_metadata_screen.py tests/test_core -q`, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat(metadata): choose a sheet from an Excel metadata workbook`.

### Task 10: Fragmentation pre-flight advisory

**Files:**
- Modify: `track2data/core/session_consistency.py` (`SessionSummary` gains `nan_slot_fraction: float | None = None`, computed in `from_session` from `session.raw_xy`; default means "never warn"), `track2data/readers/advisories.py` (new `_fragmented(summaries)` in the `reader_advisories` chain and the module docstring), `track2data/api.py` (also surface the advisories in `validation_issues` as non-blocking notes so they appear before the run, not only in the run README, ~L2808)
- Modify: `docs/tracker-formats/2026-10-08-tier-2-implementation-plan.md` ("Left for follow-up" section), `CHANGELOG.md`
- Test: `tests/test_readers/test_advisories.py`, `tests/test_core/test_session_consistency.py`, `tests/test_api.py`

**Interfaces:**
- Produces: advisory text naming the affected sessions (using `_listed`), saying that group metrics skip frames with any NaN and that most slots are empty, and pointing to the Ctrax `top_n` option. Threshold: warn when `nan_slot_fraction >= 0.5` on a session with `n_animals > 1`; the constant is named `FRAGMENTED_NAN_FRACTION` in `advisories.py`.

- [ ] **Step 1: Write failing tests**
  - `test_a_fragment_heavy_session_gets_an_advisory_that_names_top_n`
  - `test_a_summary_built_without_the_new_field_never_warns`
  - `test_a_single_animal_session_never_warns`
  - `test_many_fragmented_sessions_are_truncated_with_plus_n_more`
  - `test_from_session_computes_the_nan_slot_fraction` and `test_validation_notes_include_the_fragmentation_advisory`
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_readers/test_advisories.py tests/test_core/test_session_consistency.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Existing `SessionSummary(...)` constructors in `tests/test_readers/test_advisories.py:65`, `tests/test_api.py:1966`, `tests/test_core/test_session_consistency.py:31`, `tests/test_exporters/test_depth_columns.py:292`, `tests/test_issue_batch.py:86` are keyword-based, so the defaulted field keeps them valid.
- [ ] **Step 4:** Run `tests/test_readers tests/test_core tests/test_api.py tests/test_integration -q`, ruff, mypy. Expected: PASS, run READMEs of existing golden tests unchanged.
- [ ] **Step 5:** Commit `feat(readers): warn before a run when group metrics will see mostly-empty slots`.

### Task 11: Standalone 3-D metrics (IL-18, GL-18, GL-19)

**Depends on:** Task 1 only (both edit `ui/metrics_screen.py` presets and the metric docs). This task changes the registered count from 54 to 57 and must update the four pinned prose counts itself, because `test_metric_counts_stated_in_the_docs_match_the_registry` fails otherwise; Task 8 then runs after it and re-measures, it is not a prerequisite.

**Files:**
- Modify: `track2data/metrics/individual.py` (new `VerticalSpeed3D`, registered after `Speed3D`), `track2data/metrics/group.py` (new `InterIndividualDistance3D`, `GroupCohesion3D`, registered after `NearestNeighbourDistance3D`), `track2data/metrics/references.py` only if a needed reference is missing
- Modify: `docs/METRICS_SPEC.md`, `docs/METRIC_REFERENCES.csv` (regenerate), `docs/dev/ROADMAP.md`, `README.md`, `track2data/metrics/base.py` (counts comment), `docs/guide/USER_GUIDE.md` (~L636, L745-790), `track2data/exporters/readme.py:214`, `docs/dev/DECISIONS.md`, `CHANGELOG.md`
- Test: `tests/test_metrics/test_vertical_speed_3d.py`, `tests/test_metrics/test_iid_3d.py`, `tests/test_metrics/test_cohesion_3d.py`, `tests/test_native3d/test_gating.py`, `tests/test_integration/test_3d_metrics.py`, `tests/test_ui/test_metrics_screen.py` (the All-metrics preset counts at ~L860-872 change), `tests/test_metric_references_consistency.py`

**Interfaces:**
- IDs: **IL-18** vertical speed, **GL-18** 3-D inter-individual distance, **GL-19** 3-D cohesion. These IDs were confirmed never used; GL-17 (repeatability), D-11, D-12 and GL-16 must not be reused.
- `VerticalSpeed3D` (id `IL-18`): copy `Speed3D`; `requires_depth_scale = True`, `uses_kinematics_cfg = True`, `requires_identity = True`; reads `session.z_speed` with the same fallback to `geometry3d.vertical_speed(psess, cfg["kinematics"])`. Columns: `session_id, metric_id, individual_id, mean_vertical_speed_cm_s, median_vertical_speed_cm_s, max_vertical_speed_cm_s, mean_vertical_speed_bl_s`. `vertical_speed` is unsigned (|vz|), so no signed mean is offered; a climb/dive split is out of scope.
- `InterIndividualDistance3D` (id `GL-18`): `level = "group"`, `requires_identity = False`, `requires_depth_scale = True`. Uses `geometry3d.positions_cm`, `session.counted_rows()`, skips frames with any NaN, `scipy.spatial.distance.pdist` on the `(k, 3)` array. Columns: `mean_iid_3d_cm, median_iid_3d_cm, mean_iid_3d_bl, n_skipped_frames_3d, frac_frames_used_3d`, same body-length convention as GL-16.
- `GroupCohesion3D` (id `GL-19`): as GL-6 with `cohesion_source` in `{"nnd", "iid"}`; output `cohesion_index_3d = 1 / mean_3d_distance_cm`. Both group metrics are unavailable for native projects automatically (the existing group-level rule).
- Each class carries a `MetricDocumentation` with `primary_reference` and `supporting_references` (`KRAUSE_RUXTON_2002`, `MILLER_GERLAI_2007`, `DELCOURT_PONCIN_2012` for the group metrics, as GL-2 and GL-6 do; IL-18 as IL-17).

- [ ] **Step 1: Write failing tests**, in the style of `tests/test_metrics/test_speed_3d.py` and `tests/test_metrics/test_nnd_3d.py` (`_fused(pos_cm, body_length_cm, kcfg)` helpers):
  - IL-18: `test_a_constant_vertical_ramp_gives_the_ramp_speed`, `test_horizontal_motion_gives_zero`, `test_it_uses_session_z_speed_when_present`, `test_it_is_unavailable_without_a_depth_scale`, `test_it_is_registered_with_requires_depth_scale`, binning via `bin_windows`/`slice_psess`.
  - GL-18: `test_two_fish_at_known_3d_separation`, `test_three_fish_mean_pairwise`, `test_frames_with_a_nan_are_skipped_and_counted`, `test_single_animal_session_is_refused`.
  - GL-19: `test_cohesion_is_the_reciprocal_of_the_mean_distance_for_both_sources`, `test_an_unknown_cohesion_source_is_refused`.
  - Gating: `test_the_new_group_metrics_are_unavailable_for_native_projects`, and the existing registry/exporter/output-schema contract tests run unchanged against the new IDs.
- [ ] **Step 2:** Run `py -3.14 -m pytest tests/test_metrics -k "vertical_speed_3d or iid_3d or cohesion_3d" -q`. Expected: FAIL (classes missing).
- [ ] **Step 3:** Implement the three metrics and register them.
- [ ] **Step 4:** Regenerate `docs/METRIC_REFERENCES.csv` with `scripts/generate_metric_references.py`, add the three METRICS_SPEC sections, update every pinned count (54 becomes 57; `base.py` "N of M today" per its own formula), update the preset counts in `tests/test_ui/test_metrics_screen.py`.
- [ ] **Step 5:** Run `py -3.14 -m pytest tests/test_metrics tests/test_metric_references_consistency.py tests/test_exporters tests/test_native3d tests/test_integration tests/test_ui/test_metrics_screen.py -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS; golden pixel hashes unchanged because pixel-frame projects never select the new IDs.
- [ ] **Step 6:** Commit `feat(metrics): vertical speed (IL-18), 3-D inter-individual distance (GL-18) and 3-D cohesion (GL-19)`.

### Task 12: Several animals in one Anipose file (blocked on a design decision)

**Do not start until the user chooses the file layout.** No doc, fixture or reader specifies a multi-animal Anipose layout: a real pose-3d CSV has no animal axis (`docs/3d-movement/2026-10-10-native-3d-files-design.md` L26 states "one animal per file" and lists this as "Not in this cycle"; `readers/anipose.py` hard-codes `A = 1`).

**Decision needed (ask the user, with a recommendation):** (a) a column prefix per animal, `<animal>_<keypoint>_x|y|z`; (b) several rows per `fnum` distinguished by an `animal` or `track` column; (c) keep one animal per file and add a "combine files into one session" import step instead. Without a real sample the reader would be `verification = "synthetic_only"` under any option.

**Files (once decided):**
- Modify: `track2data/readers/anipose.py` (`_parse_header`, `_read_table`, `_build_session` L273-314, the hard-coded `[:, None, ...]`), `track2data/readers/native3d.py` (`native_parameters` gains `individuals`; `reduce_native` already handles `A`), `track2data/readers/assemble.py` (`assemble_native_session` identities), `track2data/metrics/availability.py` (the group-metric rule at ~L194-196 becomes per-session `n_animals`, and `NEEDS_SEVERAL_ANIMALS_REASON` text changes), `track2data/metrics/group.py` (GL-16 assumptions text ~L227), `track2data/core/models.py:938` (the `PreprocessedSession.z` comment: identity-switch correction never touches z, so multi-animal z needs `preprocess/z_axis.py` to be safe), `docs/3d-movement/2026-10-10-native-3d-files-design.md`, `docs/dev/DECISIONS.md`, `CHANGELOG.md`
- Test: `tests/test_readers/test_anipose.py` (helper `write_anipose_csv` in `tests/test_readers/native3d_files.py` gains an animals argument), `tests/test_native3d/test_gating.py`, `tests/test_integration/test_native_3d.py`

- [ ] **Step 1:** Ask the user which layout, record the choice in DECISIONS, commit that entry alone.
- [ ] **Step 2:** Write failing tests for the chosen layout: `test_two_animals_in_one_file_become_two_slots_in_one_session`, `test_group_metrics_are_offered_for_a_native_session_with_several_animals`, `test_group_metrics_stay_unavailable_for_a_one_animal_native_session`, `test_identity_switch_correction_leaves_native_z_aligned_with_xy`, `test_a_single_animal_file_still_reads_exactly_as_before` (pixel and single-animal native goldens unchanged).
- [ ] **Step 3:** Run them, expect FAIL; implement; run `tests/test_readers tests/test_native3d tests/test_integration tests/test_preprocess -q -W error::RuntimeWarning`, ruff, mypy. Expected: PASS.
- [ ] **Step 4:** Commit `feat(readers): several animals in one Anipose file`.

---

## Execution order and dependencies

1. Task 0 (user), then Tasks 1, 2, 3 (small, independent of each other).
2. Tasks 3, 5 and 6 share `readers/confirm.py` and the confirm dialog, so they land strictly in the order 3, 5, 6.
3. Tasks 4, 7, 9, 10 are independent of each other and of the 3-5-6 line; 5 and 7 both touch reader parameters, so land 5 before 7.
4. Task 11 after Task 1, then Task 8 last of all (counts and statuses must be final; Task 8 does not block 11).
5. Task 12 only after the layout decision.

Suggested branches: one per task from `main`, merged through PRs so `CI passed` gates each.
