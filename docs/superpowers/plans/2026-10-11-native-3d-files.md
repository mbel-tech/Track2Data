# Native 3-D Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read Anipose pose-3d CSV and DLC-3D files into sessions that carry an absolute `z` in the project's length unit, so IL-16, IL-17, GL-16 (and IL-15 once the user gives a water column) run on them.

**Architecture:** Two readers share `readers/native3d.py` (unit table, axis permutation, assembly). A native session has `has_pixel_frame = False`, `length_unit = 1.0`, `raw_z`; the pipeline lays `raw_z` out beside `xy` as `PreprocessedSession.z`; the water column (a `CalibrationConfig` field) derives `depth` after calibration. A native 3-D project is a `dimension == "2d"` project whose sessions come from native readers, so run units, stage flow and the Views/Fusion steps need no change (a ruling that refines the spec: `dimension "3d"` keeps meaning "top + side views to fuse").

**Tech Stack:** Python, pydantic v2, numpy/pandas, PySide6, pytest/pytest-qt, ruff, mypy (CI: mypy 2.4.0 + numpy 2.4.6).

**Spec:** `docs/3d-movement/2026-10-10-native-3d-files-design.md`. Builds on B1/B2: `track2data/metrics/geometry3d.py`, `track2data/metrics/availability.py`, `Engine.preprocess`/`run_units` in `track2data/api.py`.

## Global Constraints

- Reader ids `anipose` and `deeplabcut_3d`, `verification = "synthetic_only"`, class flag `provides_native_3d: ClassVar[bool] = True` (default False on `SessionReader`). The set of native reader names is the constant `NATIVE_3D_READERS = frozenset({"anipose", "deeplabcut_3d"})` in `track2data/readers/native3d.py`, which availability code uses without importing the registry.
- Options (`ReaderParameter`, in this order): `fps` (float, required), `unit` (choice `mm|cm|m|in`, required, Anipose proposes `mm` with source `tool-default`), `target_unit` (choice `mm|cm|m|in`, default `cm`), `keypoint`, `likelihood_cutoff` (Anipose only, applied to `_score`, default 0.0 = no cutoff; DLC-3D has no likelihood and no such option), `vertical_axis` (choice `x|y|z`, default `z`), `flip` (bool, default false), `keep_skeleton` (bool, default true).
- Unit factors to metres: mm 0.001, cm 0.01, m 1.0, in 0.0254; coordinate × factor(unit) / factor(target) = coordinate in `target_unit`.
- Session fields: `has_pixel_frame: bool = True`, `coordinate_unit: str | None = None`, `raw_z: np.ndarray | None = None` shape `(n_frames, n_animals)` float64; `PreprocessedSession.z` same rows as `xy`. Native sessions: `has_pixel_frame False`, `length_unit 1.0`, `video.width_px = video.height_px = 0`, `coordinate_unit = target_unit`, `raw_attrs["native_3d"]` = `{"source_unit","target_unit","vertical_axis","flip"}`.
- Missing values: Anipose NaN in x, y, z together; DLC-3D a row where x, y and z are all exactly 0 (a single 0 is a real coordinate).
- `CalibrationConfig.water_column: WaterColumn | None = None`, `WaterColumn(surface_z: float, floor_z: float)`, finite and `surface_z != floor_z` (either order allowed). Derived: `depth = (z - surface_z) / (floor_z - surface_z)`, `depth_height_cm = abs(floor_z - surface_z)`, outside [0, 1] -> NaN and `depth_outside_mask`/`depth_outside` (counted, never clipped).
- Reason strings, exactly: `NEEDS_WATER_COLUMN_REASON = "needs the water column (surface and floor z) on the Calibration page"`; for the project-mixing error codes `NATIVE_3D_MIXED` (message names both kinds and the session) and `NATIVE_3D_UNIT_MISMATCH` (names both target units).
- Native projects require `calibration.mode == "session"`, `length_unit_label == target_unit` and `length_unit_confirmed_by_user True`; the first native import sets them. `Engine.validate` blocks other modes.
- No existing output changes for sessions with `has_pixel_frame True`: existing suites stay green, `ruff check .` and CI-venv `mypy` clean, `-W error::RuntimeWarning` on the new tests.

## Review Focus

- A frame gap in the file (Anipose `fnum` skips, or rows missing) leaves `raw_z`, `xy` and the tracking intervals on the same rows, including bridged and separator rows (Task 1, Task 2).
- DLC-3D's `0 = missing` must not erase a real 0 coordinate: a row is missing only when x, y and z are all exactly 0 (Task 3).
- A wrong unit silently scales every speed: `unit` is required, never defaulted silently, and a missing one is an error naming the option (Task 2).
- A water column with the floor on the other side of the surface (reversed order) works; `surface_z == floor_z` or non-finite is refused (Task 1, Task 4).
- A native session in a pixel project, a pixel session in a native project, or a native session in a fused 3-D project is refused with the code above (Task 4); and no screen or metric crashes or invents an arena from `video.width_px = 0` (Task 5).

---

### Task 1: Core: `z`, water column, pipeline, geometry

**Files:**
- Modify: `track2data/core/models.py` (Session fields, `PreprocessedSession.z`, `WaterColumn`, `CalibrationConfig.water_column`), `track2data/preprocess/pipeline.py` (lay out `raw_z`), `track2data/metrics/binning.py` (`slice_psess` slices `z`), `track2data/metrics/geometry3d.py` (`positions_cm` uses `psess.z`), `track2data/api.py` (`Engine.preprocess` derives depth after calibration)
- Create: `track2data/calibration/water_column.py`
- Test: `tests/test_native3d/test_core.py` (new, with `__init__.py`)

**Interfaces:**
- Produces: `WaterColumn(BaseModel)`; `apply_water_column(psess: PreprocessedSession, wc: WaterColumn) -> PreprocessedSession` (returns `dataclasses.replace(...)` with `depth`, `depth_height_cm`, `depth_outside`, `depth_outside_mask` set; unchanged when `psess.z is None`); `geometry3d.positions_cm` returns Z from `psess.z` when set, else `depth * depth_height_cm`, `None` only when neither exists or `px_per_cm` is missing (and `depth_height_cm` is no longer required when `z` is set).

- [ ] **Step 1: Write failing tests** (names are the contract): `test_water_column_validation` (equal, NaN, inf refused; reversed order accepted); `test_apply_water_column_exact` (surface 0, floor 20, z = [0, 5, 20, 25, -1] gives depth [0, .25, 1, NaN, NaN], `depth_height_cm == 20`, outside mask [F,F,F,T,T], `depth_outside == 2`); `test_apply_water_column_reversed` (surface 20, floor 0 gives the same fractions for z = [20, 15, 0]); `test_pipeline_lays_out_z_with_xy` (a session with `tracking_intervals` that leave a gap: `psess.z.shape == psess.xy.shape[:2]`, NaN on separator rows, equal to `raw_z` on tracked rows; and the no-gap case equals `raw_z`); `test_slice_psess_slices_z`; `test_positions_cm_uses_z_without_depth` (xy 80,40 at `px_per_cm 8`, z 12 gives (10, 5, 12)); `test_positions_cm_none_without_z_or_depth`; `test_pixel_sessions_unchanged` (`z is None`, `has_pixel_frame True`).
- [ ] **Step 2: Run** `pytest tests/test_native3d/test_core.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the fields and `WaterColumn` (a `model_validator` for finite and unequal); in `pipeline.run` lay `raw_z` out with `lay_out(expansion, session.raw_z)` when an expansion exists, else copy; pass `z=` into `PreprocessedSession`; `slice_psess` slices `z` beside `depth` (grep `depth_outside_mask` for every site that copies depth-like arrays and add `z`); `Engine.preprocess` calls `apply_water_column` after calibration when `calibration.water_column` is set and `psess.z` exists; `positions_cm` as in Interfaces (keep the fused path byte-identical).
- [ ] **Step 4: Run** `pytest tests/test_native3d tests/test_metrics tests/test_preprocess tests/test_fusion tests/test_integration -q -W error::RuntimeWarning`, `ruff check .`, `mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(native3d): absolute z, water column and 3-D positions from z`.

### Task 2: Shared helpers and the Anipose reader

**Files:**
- Create: `track2data/readers/native3d.py`, `track2data/readers/anipose.py`
- Modify: `track2data/readers/base.py` (`provides_native_3d` flag), `track2data/readers/assemble.py` (`assemble_native_session`), `track2data/readers/__init__.py` (register)
- Test: `tests/test_readers/test_native3d.py`, `tests/test_readers/test_anipose.py` (new; synthetic files built in the tests, helper `write_anipose_csv(tmp_path, keypoints, frames, ...)` in `tests/test_readers/native3d_files.py`)

**Interfaces:**
- Produces in `native3d.py`: `NATIVE_3D_READERS`, `UNIT_FACTORS_M: dict[str, float]`, `convert_units(values: np.ndarray, unit: str, target: str) -> np.ndarray`, `horizontal_axes(vertical_axis: str) -> tuple[int, int]` (the two other axes, in file order), `native_parameters(unit_default: str | None) -> tuple[ReaderParameter, ...]` (the Global Constraints list), `reduce_native(xy3: np.ndarray, names: list[str], confidence: np.ndarray | None, *, keypoint: str | None, cutoff: float | None, vertical_axis: str, flip: bool) -> tuple[Reduction, np.ndarray]` (the Reduction from `reduce_keypoints(..., plane=horizontal_axes(...))` and the chosen keypoint's z `(F, A)`, negated when `flip`).
- Produces in `assemble.py`: `assemble_native_session(*, session_id, folder, reader, fps, raw_xy, raw_z, source_unit, target_unit, vertical_axis, flip, keypoints, tracking_intervals, trajectory_source, trajectory_format) -> Session` with the Session fields of Global Constraints and `DataValidationError(code="READER_OUTPUT_INVALID")` for bad shapes or fps.
- `AniposeReader(SessionReader)` with `name = "anipose"`, `provides_native_3d = True`, `coordinate_frame = "physical_unaligned"`, `detect`, `discover`, `read`; one animal, `identities_labels None`, `has_stable_identities True`.

- [ ] **Step 1: Write failing tests:** `test_convert_units_table` (mm to cm /10, m to cm x100, in to mm x25.4, same unit identity); `test_horizontal_axes` (z -> (0,1), y -> (0,2), x -> (1,2)); `test_anipose_detects_layout_and_rejects_near_misses` (a DLC 2-D file, a CSV with `_x/_y` but no `_z`, no `fnum`); `test_anipose_hyphenated_keypoint_names` (`l-base_x` splits from the right); `test_anipose_reads_exact_values` (3 keypoints, 5 frames, mm to cm: `raw_xy`, `raw_z` equal the hand values; `keypoints.xy.shape == (5,1,3,3)`); `test_anipose_nan_triple_is_missing`; `test_anipose_fnum_gap_gives_tracking_intervals` (fnum 0,1,2,5,6 -> intervals [(0,3),(5,7)] and `raw_z` length 5); `test_anipose_vertical_axis_and_flip` (vertical `y` makes `raw_xy` the x and z columns, `raw_z` the y column; flip negates `raw_z`); `test_anipose_keypoint_and_score_cutoff`; `test_anipose_requires_fps_and_unit` (each missing -> `READER_OPTION_*` error naming the option); `test_anipose_session_flags` (`has_pixel_frame False`, `length_unit 1.0`, `coordinate_unit == target`, `video.width_px == 0`, `raw_attrs["native_3d"]`); `test_anipose_registered_and_discovered` (scan a folder, a `Detection` with `reader == "anipose"`, `proposed["unit"].value == "mm"` and source `tool-default`).
- [ ] **Step 2: Run** `pytest tests/test_readers/test_native3d.py tests/test_readers/test_anipose.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the helpers, `assemble_native_session` and `AniposeReader` following `readers/deeplabcut.py` (`_files_in`, `discover` with the peeked header, `_build_session` shape); the file read uses pandas like `_read_table`; register after `DeepLabCutReader`; the `keep_skeleton` memory guard is `skeleton_fits` as for DLC.
- [ ] **Step 4: Run** `pytest tests/test_readers tests/real_samples -q -W error::RuntimeWarning` (the existing Anipose contract case may flip from XFAIL to run: if the fixture file is absent it stays skipped), `ruff check .`, `mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(readers): shared native 3-D helpers and the Anipose reader`.

### Task 3: The DLC-3D reader

**Files:**
- Create: `track2data/readers/deeplabcut_3d.py`
- Modify: `track2data/readers/__init__.py` (register)
- Test: `tests/test_readers/test_deeplabcut_3d.py` (new, uses the helper file writers in `tests/test_readers/native3d_files.py`, adding `write_dlc3d_csv`)

**Interfaces:**
- Consumes: Task 2's `native_parameters`, `reduce_native`, `assemble_native_session`.
- Produces: `DeepLabCut3DReader(SessionReader)` with `name = "deeplabcut_3d"`, `provides_native_3d = True`, `detect`/`discover`/`read`; header is three rows `scorer`, `bodyparts`, `coords` with `x, y, z` per body part; no `likelihood_cutoff` option (it is dropped from `parameters`).

- [ ] **Step 1: Write failing tests:** `test_detects_only_the_3d_header` (a 2-D DLC file with `likelihood` is not claimed, nor a header with `x, y` only; and `DeepLabCutReader` does not claim the 3-D file); `test_reads_exact_values_and_units`; `test_all_zero_row_is_missing_but_a_single_zero_is_real` (a keypoint row (0,0,0) is NaN; (0,5,3) keeps x=0); `test_vertical_axis_and_flip`; `test_requires_fps_and_unit`; `test_multi_frame_index_from_the_first_column` (the leading index column is the frame number, gaps give tracking intervals); `test_session_flags` as for Anipose.
- [ ] **Step 2: Run** `pytest tests/test_readers/test_deeplabcut_3d.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `DeepLabCut3DReader` reusing `deeplabcut._read_table`-style parsing for the header (three rows), then `reduce_native` and `assemble_native_session`; confirm `DeepLabCutReader.discover`/`detect` reject the 3-D header (its parser needs `likelihood`; if it can accept a 3-D header, tighten it and add the regression test).
- [ ] **Step 4: Run** `pytest tests/test_readers -q -W error::RuntimeWarning`, `ruff check .`, `mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(readers): DLC-3D reader`.

### Task 4: Project rules, availability and engine

**Files:**
- Modify: `track2data/readers/native3d.py` (`manifest_native_3d`), `track2data/metrics/availability.py`, `track2data/api.py` (`import_sessions`/`import_ref`, `validate`, `preprocess` calibration for native, run-time availability, `_resolve_px_per_cm`), `ui/store/project_store.py` (`add_session` path sets the first-import calibration, using the same Engine function)
- Test: `tests/test_native3d/test_project_rules.py`, extend `tests/test_metrics/test_availability.py`

**Interfaces:**
- Consumes: Task 1's `WaterColumn`/`psess.z`, Task 2's `NATIVE_3D_READERS`.
- Produces: `manifest_native_3d(manifest) -> bool` (any `SessionRef.reader in NATIVE_3D_READERS`); `Engine.register_native_import(session: Session) -> None` called by every import path (raises `ImportError_` codes `NATIVE_3D_MIXED` and `NATIVE_3D_UNIT_MISMATCH`; on the first native import sets `calibration.mode = "session"`, `length_unit_label = session.coordinate_unit`, `length_unit_confirmed_by_user = True`); availability for native projects: `manifest_view` returns `("top", water_column is not None)`; `manifest_depth_scale` reports the project as 3-D data (`dimension "3d"`, `has_depth True`, documented in its docstring: the name means "3-D data present" for native projects); IL-15 in a native project without a water column is unavailable with `NEEDS_WATER_COLUMN_REASON` (never the camera-view text); `Engine.validate` reports an error when a native project's calibration mode is not `session`; run time: a native unit's `has_depth` comes from `psess.z`, and the "3-D projects compute fused sessions only" guard in `compute_metrics` is unchanged for `dimension "3d"` and not applied to native sessions.

- [ ] **Step 1: Write failing tests:** `test_first_native_import_sets_calibration` (mode `session`, label equals target, confirmed); `test_second_import_with_other_target_is_refused` (`NATIVE_3D_UNIT_MISMATCH` naming both); `test_native_into_pixel_project_and_back_are_refused` (`NATIVE_3D_MIXED`, both directions); `test_native_refused_in_a_fused_3d_project`; `test_validate_requires_session_mode`; availability: `test_native_project_offers_the_three_3d_metrics` (IL-16, IL-17, GL-16 available at manifest level and per unit), `test_il15_needs_the_water_column_in_a_native_project` (reason text exactly `NEEDS_WATER_COLUMN_REASON` in `Engine.skipped_metrics`, `validate`, and the Metrics screen row) and `test_il15_available_with_the_water_column`; `test_2d_and_fused_projects_unchanged` (their reasons are the existing strings).
- [ ] **Step 2: Run** `pytest tests/test_native3d/test_project_rules.py tests/test_metrics/test_availability.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** by routing every availability caller through `availability.unavailable_reason` (the B2 single function; thread the native/water-column facts the same way `depth_scale` was threaded: grep `manifest_depth_scale` and `manifest_view` for every caller, including `Engine.skipped_metrics`, `validate`, `_view_selection_notes`, the CLI `list-metrics` and `ui/metrics_screen.py`).
- [ ] **Step 4: Run** `pytest tests/test_native3d tests/test_metrics tests/test_camera_view_gating.py tests/test_api.py tests/test_ui -q -W error::RuntimeWarning`, `ruff check .`, `mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(native3d): project rules, calibration and availability`.

### Task 5: No pixel frame: zones, arena, screens, Calibration page, CLI

**Files:**
- Modify: `track2data/metrics/derived.py` (IL-3/IL-14 arena fallback), `track2data/core/session_consistency.py`, `track2data/zones/io.py`, `ui/zones_screen.py`, `ui/preview_screen.py`, `ui/store/session_facts.py`, `ui/calibration_screen.py` (water column fields), `track2data/exporters/readme.py` ("Native 3-D source" block), `track2data/cli.py` (confirm the readers' options reach `t2d import --option`)
- Test: `tests/test_native3d/test_no_pixel_frame.py`, `tests/test_ui/test_calibration_water_column.py`

**Interfaces:**
- Consumes: Task 1's `Session.has_pixel_frame`/`coordinate_unit`, Task 4's `manifest_native_3d`.
- Produces: every consumer of `video.width_px`/`height_px` (grep: `session_consistency`, `derived`, `zones/io`, `zones_screen`, `preview_screen`, `session_facts`, `calibration_screen`) either skips or uses the data extent when `has_pixel_frame` is False; `derived` arena fallback `centre`/`radius` from the min/max of the finite `xy` with the warning text `"no pixel frame: the arena was taken from the extent of the tracked positions"`; the Zones screen shows a disabled notice `"This project's sessions have no pixel frame (native 3-D); zones are not available."`; the Calibration page shows the two water column fields (`surface z`, `floor z`, labelled with `length_unit_label`) only when `manifest_native_3d`, and writes `calibration.water_column` through the store (clearing it when either is empty; invalid values refused with the field named).

- [ ] **Step 1: Write failing tests:** `test_arena_fallback_uses_extent_with_warning` (xy spanning 0..10 gives centre (5,5), radius 5, the warning present, no `ZeroDivisionError`/NaN); `test_no_consumer_reads_zero_video_size` (a native session through `core.session_consistency` checks and `session_facts` produces no error and no frame-size complaint); `test_zones_screen_is_disabled_for_native` (pytest-qt; no ROI can be added); `test_calibration_fields_only_for_native_projects`; `test_water_column_fields_round_trip_through_the_store` (type values, `manifest.calibration.water_column` equals them; clear one -> `None`; equal values -> refused with the field named); `test_readme_native_block` (reader, file unit, project unit, vertical axis, flip, water column or its absence); `test_cli_import_options` (`t2d import --option unit=mm --option fps=100` on a synthetic Anipose file creates the session).
- [ ] **Step 2: Run** `pytest tests/test_native3d/test_no_pixel_frame.py tests/test_ui/test_calibration_water_column.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** each consumer guard (a small helper `Session.pixel_size_known` property = `has_pixel_frame and width_px > 0 and height_px > 0` keeps the checks one-line), the screens, the README block and the store setter; a pixel session's behaviour stays byte-identical.
- [ ] **Step 4: Run** `pytest tests/test_native3d tests/test_ui tests/test_metrics tests/test_zones tests/test_exporters -q -W error::RuntimeWarning`, `ruff check .`, `mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(native3d): no-pixel-frame handling, water column fields, README block`.

### Task 6: End to end, docs and full check

**Files:**
- Create: `tests/test_integration/test_native_3d.py`
- Modify: `CHANGELOG.md` (`### Added`), `docs/dev/DECISIONS.md` (new entry after the last: amends D-031 a second time), `docs/guide/USER_GUIDE.md` (the 3-D section: native files, units, vertical axis, water column, limits), `docs/tracker-formats/2026-10-07-tracker-import-design.md` and `animal_tracking_output_formats.md` (P5 status, DLC-3D entry), `docs/3d-movement/2026-10-10-native-3d-files-design.md` (status "implemented", a "Changes made during the build" section recording the 2-D-dimension ruling), `docs/3d-movement/2026-10-08-3d-roadmap.md` (A done), README reader list and counts
- Test: `tests/test_docs/test_guide.py`

- [ ] **Step 1: End-to-end tests** (synthetic Anipose file built in the test, a fish moving (3, 4, 12) mm per frame at 25 fps, 11 frames, unit `mm`, target `cm`): import through `Engine`, preprocess, run IL-16/IL-17/GL-16 with two files (two sessions) and assert exact values (10 steps x hypot(0.3, 0.4, 1.2) = 1.3 cm per step = 13 cm path, speed 1.3 cm x 25 fps = 32.5 cm/s; state this arithmetic in the test), IL-15 unavailable without and exact with a water column (including outside values counted), the 2-D metrics on the horizontal plane, a binned run, serial vs parallel agree, the same project with `vertical_axis="y"`; a pixel-frame (idtracker.ai/DLC 2-D) control project run unchanged (compare a sessions.csv header and a metric table with the existing expectations).
- [ ] **Step 2: Docs** written from the spec after verifying every id, option name, code and reason string in the code; state the limits (one animal per file, no z in the per-frame table, no mixing, board unit must be confirmed, no refraction correction, water column is entered not estimated).
- [ ] **Step 3: Run** `pytest tests/test_docs -q`, then the full `QT_QPA_PLATFORM=offscreen python -m pytest -q -x -W error::RuntimeWarning` (background, output to a file, poll), `ruff check .` and CI-venv `mypy`. Expected: all pass; report any segfault or abort at exit verbatim.
- [ ] **Step 4: Commit** `test: end-to-end native 3-D files` and `docs: describe native 3-D files`.
