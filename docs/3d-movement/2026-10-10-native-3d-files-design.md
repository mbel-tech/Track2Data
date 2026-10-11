# Reading native 3-D tracker files (sub-project A)

**Status:** implemented 2026-10-11 (decision D-043). See "Changes made during the build" at the end.
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on [3-D metrics](2026-10-10-3d-metrics-design.md) (B2) and [running a 3-D project](2026-10-10-3d-run-design.md) (B1). Amends D-031 a second time (B2 was the first).

## Why

Fusion (D) builds a 3-D session from a top and a side recording. Some trackers deliver 3-D positions
directly: Anipose (`pose-3d` CSV) and DeepLabCut's 3-D triangulation (DLC-3D). Their coordinates are
in physical units (the calibration board's unit), have an absolute z axis, and have no pixel frame.
A adds readers for both and lets the 3-D metrics of B2 and IL-15 run on them.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E, G, F, D, B1, B2 | Mode switch, ID correspondence, panel split, fusion, running a 3-D project, 3-D metrics | Done |
| **A** | **Native 3-D files** (this spec) | Two readers; minimal native-unit handling; absolute `z`; IL-15 from a user-given water column |

## Decisions

- **Two readers, built from the published layouts** (`verification = "synthetic_only"`, D-012):
  `anipose` (pose-3d CSV) and `deeplabcut_3d`. There are no real sample files at hand for the DLC-3D
  layout. For Anipose the repo's published sample (`tests/real_samples/`) is used by the existing
  reader-contract case when the fixture is present; it is not required.
- **One animal per file.** Neither format carries an animal axis. Several animals are several files
  (several sessions), as for the other single-animal readers.
- **Units are converted when reading, to the project's length unit.** The reader takes `unit` (the
  file's unit: mm, cm, m, in; Anipose proposes mm, which the file does not state, so it is always
  confirmed) and `target_unit` (default cm). The first import sets the project's
  `calibration.length_unit_label` to `target_unit` and confirms it; later imports must use the same
  target (a different one is an error naming both). The `_cm` column suffix is unchanged and nominal,
  as it already is for a project calibrated in mm; the README states the real unit.
- **A native 3-D session has no pixel frame.** `Session.has_pixel_frame: bool = True` (False here),
  `Session.coordinate_unit: str | None = None` (the project unit it was converted to), and
  `length_unit = 1.0` (so the existing "session" calibration reads "1 coordinate unit = 1 project
  unit" with no new calibration path; it is confirmed automatically for these sessions).
- **Absolute `z`.** `Session.raw_z: np.ndarray | None` of shape `(n_frames, n_animals)` in the project
  unit, and the same array on `PreprocessedSession.z`. It is not smoothed or interpolated, like the
  fused `depth`. It follows the same rows as `xy` everywhere `depth` does (`slice_psess`, windows,
  gap rows).
- **Vertical axis.** The reader option `vertical_axis` (`x`, `y`, `z`; default `z`) with `flip`
  (default false) says which file axis is up. The other two axes are the horizontal plane that
  becomes `raw_xy`; `KeypointData.xy` keeps all three axes (D = 3).
- **Position from one keypoint,** as for the other pose readers (`reduce_keypoints`, with the
  likelihood cutoff applied to the Anipose `_score` or the DLC likelihood; never an average).
- **Water column for IL-15.** `calibration.water_column: WaterColumn | None` with `surface_z` and
  `floor_z` (project unit, finite, different). When set, a native 3-D session gets
  `depth = (z - surface_z) / (floor_z - surface_z)` (0 surface, 1 floor), `depth_height_cm =
  |floor_z - surface_z|`, positions outside [0, 1] become NaN and are counted
  (`depth_outside_mask`), never clipped. Without it IL-15 is unavailable with the reason "needs the
  water column (surface and floor z) on the Calibration page".
- **No mixing in a project.** A project holds either pixel sessions (including fused pairs) or native
  3-D sessions; importing the other kind is refused with an error naming both.
- **No Views or Fusion step** for native 3-D projects (nothing to pair or fuse).

## Design

1. **Readers** (`track2data/readers/anipose.py`, `deeplabcut_3d.py`, registered like the others).
   - Anipose detect: a CSV with `fnum` and at least one `<kp>_x/_y/_z` triple (suffixes split from
     the right, since keypoint names contain hyphens); `M_xx` and `center_*` columns are ignored.
     Missing is NaN in x, y and z together. `fnum` gives the frame index.
   - DLC-3D detect: the three-row header (`scorer`, `bodyparts`, `coords`) with `x`, `y`, `z`
     columns; 0 means missing. The frame index is the row number.
   - Options: `fps` (required, never defaulted), `unit`, `target_unit`, `keypoint`,
     `likelihood_cutoff`, `vertical_axis`, `flip`, `keep_skeleton`. The `keypoint` choices are filled
     from the scanned files as the DLC reader does.
   - Both finish through `assemble_session`, which gains a 3-axis path (axis permutation, flip,
     unit factor, `raw_z`, `has_pixel_frame = False`). `video` is a placeholder `VideoInfo` with the
     fps and the frame count, `width_px = height_px = 0` (never used when `has_pixel_frame` is false).
2. **Pipeline.** The preprocess step copies `raw_z` to `PreprocessedSession.z` row-aligned with `xy`,
   and derives `depth`, `depth_height_cm` and `depth_outside_mask` from the water column when set.
   `px_per_cm` comes from the confirmed `length_unit = 1.0`.
3. **Zones, background, arena.** For a session with `has_pixel_frame = False`: zones and the
   background image are disabled on their screens (with the reason), and the IL-3 and IL-14 arena
   fallback (`metrics/derived.py`) uses the data extent plus a warning instead of
   `video.width_px / height_px`.
4. **Metrics.** `geometry3d.positions_cm` takes Z from `psess.z` when it is set, otherwise
   `depth * depth_height_cm`; it returns None when neither exists, or when `px_per_cm` is missing.
   `availability.depth_scale_reason` and `view_unavailable_reason` treat "has z" as having 3-D data
   (today "has depth"); IL-15 keeps requiring `depth`. A native 3-D project's camera view is
   irrelevant: it is treated as `top` for view gating, and the 2-D metrics run on the horizontal plane.
5. **UI and CLI.** The confirm dialog renders the new options. The Calibration page shows the water
   column fields (surface z, floor z) for native 3-D projects only. The Metrics screen needs no new
   rows. `t2d import` takes the options with `--option` as for the other readers.
6. **Outputs and docs.** A z column group in the per-frame table is not added (z is not exported in
   this cycle except through the metrics); the run README gets a "Native 3-D source" block (reader,
   file unit, project unit, vertical axis, flip, water column or its absence). Docs: the tracker
   formats table and design (P5, plus a DLC-3D entry), the user guide, CHANGELOG, a decision entry, the roadmap row
   and D-031's amendment.

## Testing

- Readers on synthetic files: layout detection and rejection of near-misses, hyphenated keypoint
  names, NaN/0 as missing, `fnum` gaps, unit conversion (mm to cm, m to cm, in to mm), axis
  permutation and flip, keypoint choice and cutoff, required `fps`, the `target_unit` consistency rule.
- Session and pipeline: `raw_z`/`z` row alignment through gap rows and `slice_psess`, `has_pixel_frame`
  false disables zones and uses the data-extent arena fallback with a warning, a mixed project is
  refused, `length_unit = 1.0` calibration.
- Metrics end to end: a known 3-D track gives exact IL-16, IL-17 and GL-16 values with no water
  column; IL-15 unavailable with its reason without it, available with it (exact fractions, outside
  positions NaN and counted); 2-D metrics on the horizontal plane equal a hand computation; serial and
  parallel runs agree.
- Regression: pixel-frame projects (idtracker.ai, DLC 2-D, fused 3-D) unchanged: the existing suites
  and a 2-D control run.
- Docs: tests for the guide and reference consistency as the existing ones require.

## Not in this cycle

Mixed native and fused projects, several animals in one Anipose file, mm or m export suffixes, reading
the camera model or the reprojection error, a z column in the per-frame table, and a water column
estimated from the data.

## Changes made during the build

The design above is what was proposed; these rulings were made while building it and are what the
code does.

- **A native 3-D project is a `dimension "2d"` project** whose sessions come from native readers
  (`NATIVE_3D_READERS`). The spec's "No Views or Fusion step" holds, and no new dimension value was
  added: `"3d"` keeps meaning "top and side views to fuse", which avoids about thirty-five
  dimension-keyed sites. The mode banner and the Project screen therefore say 2-D (cosmetic).
- **Only the add entry point sets up calibration.** `Engine.set_up_native_import` (used by
  `track2data add` and the GUI's add; a batch is checked as a whole) sets mode `session`, label = target
  unit and confirmed. Import, validate and run are read-only on the manifest and only check; a native
  session in a non-session calibration mode raises `NATIVE_3D_NEEDS_SESSION_CALIBRATION` (also
  in validate); validate also reports an unconfirmed unit and a label that differs from the sessions'
  unit. `Engine.import_sessions` only checks.
- **`unit` and `fps` are required options.** Anipose proposes `mm` (source `tool-default`) but never
  defaults it; DLC-3D proposes nothing. `likelihood_cutoff` above 0 without `_score` columns for every
  keypoint is `READER_OPTION_INVALID`; DLC-3D has no such option.
- **Missing values.** Anipose: NaN in x, y, z together (a partly NaN triple counts as missing). DLC-3D:
  x, y, z all exactly 0 (or any non-finite). Anipose `fnum` gaps are kept as tracking intervals, not
  filled; unsorted `fnum` is sorted; duplicate, negative or non-integer `fnum` is `ANIPOSE_BAD_FRAME_INDEX`.
- **Units are converted in the reader**, on all three axes and with exact integer ratios, so the stored
  skeleton is in the project unit too (axes are neither permuted nor flipped there).
- **`fuse()` refuses native sessions** ("session <id> has no pixel frame (a native 3-D session has no views to fuse)"); mixing is
  `NATIVE_3D_MIXED` and a second target unit `NATIVE_3D_UNIT_MISMATCH`.
- **IL-17 reads `z`.** The first build left IL-17 on `depth * height`, so a native session without the
  water column got NaN; found by the end-to-end test and fixed. IL-15 outside values, and non-finite z,
  are NaN and counted.
- **GL-16 is not offered for native files** (one animal per file; the metric needs two in a session).
- **The unreadable-format notice for DLC-3D was narrowed** in `readers/recognise.py`: the single-animal
  tables the reader takes are no longer reported, while a multi-animal table (extra `individuals` header
  row) or one without full x, y, z triples is still named as one that cannot be read yet.
- **Metrics not offered in a native project** (one reason each, through `availability.unavailable_reason`):
  IL-3, IL-9, IL-10 and IL-14 (pixel-sized defaults would silently change with `target_unit`; the
  data-extent arena fallback is kept but not reachable in a run) and every group metric, GL-16 included
  (one animal per file).
- **The water column is on the file's axis.** For a session read with `flip`, `apply_water_column` negates
  both values, so the same physical fish gets the same depth with or without flip.
- **Provenance and outputs.** `calibration.water_column` is left out of the serialised manifest while it
  is None (and so out of `project_hash`, the cache key and `manifest.json`), and the provenance
  `native_3d` key only appears for a native session: a pixel project hashes, caches and serialises exactly
  as before (golden values from fc5b2fc). IL-15's `depth_extent_source` is `water_column` for native
  sessions. A replaced jump also blanks z.
- **UI.** Zones and background are disabled for native projects; the trajectories preview frames the data
  from its extent; the Calibration screen shows the **WATER COLUMN** group (Surface z, Floor z) for
  native projects only; the GUI add refuses a batch that would break the rules before listing it.
