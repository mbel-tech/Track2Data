# SP5 — water-column semantics and geometry the model cannot express

Design note for findings 5, 7 and the smaller items of finding 9 of the 3-D data-path review.
Status: **draft for review**; nothing here is implemented. Based on `main` after #147, #150, #152
and #155 (SP1-SP4).

## 1. The water column also bounds z for IL-16, IL-17 and GL-16 (finding 5)

**Today.** `apply_water_column` writes `depth` and the outside mask, which only IL-15 reads. IL-16 and
GL-16 take `psess.z` through `geometry3d.positions_cm`; IL-17 takes `psess.z` through its own copy of
that rule (`individual.py` ~2013). A user who enters a water column to exclude out-of-tank artefacts
(reflections, a mis-triangulated keypoint) gets them out of IL-15 and still in the path length and
speed. Fused sessions already behave the other way: their Z is `depth * height`, which is NaN outside
the column.

**Decision (already made):** the column bounds z for every 3-D metric.

**Design.**
- One helper `geometry3d.vertical_cm(psess)` returns the vertical coordinate in cm: `psess.z` with the
  samples in `depth_outside_mask` set to NaN (native), or `depth * depth_height_cm` (fused). Both
  `positions_cm` and IL-17 call it, so the two rules cannot drift apart again.
- A sample outside the column is NaN, so a step touching it is dropped (the existing "a step needs all
  three coordinates" rule); nothing is clipped.
- With no water column the behaviour is unchanged (z is used as is).
- The exported `z_cm` column (SP2) stays the unmasked file coordinate: it is the data, not a metric
  input. The README states which samples the 3-D metrics dropped (`depth_outside` is already counted).
- The Calibration page text for the water column says it also excludes samples from path length and
  speed.

**Tests that change on purpose.** `test_il15_with_the_water_column_counts_the_outside_values` asserts
that the outside frames keep their 3-D path and speed (D-043's "z is absolute" reading). It becomes: IL-16
and IL-17 are computed without the two outside frames, and equal the no-column values when nothing is
outside. CHANGELOG notes the changed numbers for native projects that set a water column.

## 2. An inverted side view (finding 7)

**Today.** `FusionSettings` requires `surface_row < floor_row`. The depth formula
`(y - surface_row) / (floor_row - surface_row)` is already correct for either order; the validator is
the only thing refusing it, while the native `WaterColumn` accepts either order.

**Design.**
- Replace the validator with "floor_row must differ from surface_row". Keep `surface_row >= 0`.
- `fusion/align.py:108` computes the side's horizontal scale as `(floor_row - surface_row) /
  tank_height_cm`; with an inverted view that is negative and silently flips the agreement check's
  sign. Use the absolute value (the horizontal direction is already governed by `flip`).
- The Fusion dialog's summary line and README keep printing the two rows as entered.
- Tests: an inverted pair gives the mirror-image depth (`1 - d`) of the upright pair with the rows
  swapped, and the agreement RMS is unchanged.

## 3. Fusion dialog helper text (finding 7)

`horizontal_axis` and `flip` change only the view-agreement check and `suggest_offset`, never the
fused positions, but the dialog lays them out beside the surface and floor rows. Add one line of helper
text under them: "Used to check that the two views agree; does not change the fused positions."
(`ui/dialogs/fusion_dialog.py`.) The guide screenshots for that dialog are regenerated.

## 4. Native sessions that disagree on the vertical axis (finding 7)

**Today.** `CalibrationConfig.water_column` is one `(surface_z, floor_z)` pair for the project, entered
"on the file's own vertical axis" with a per-session `flip` compensation, but `vertical_axis` is only
recorded in provenance. Two native files read with different `vertical_axis` (or calibrated in separate
sessions with unrelated origins) share a column that means different things for each.

**Design.**
- `_native_rule` (the import rule that already refuses mixing and unit mismatches) also compares
  `vertical_axis`: a batch or project whose native sessions use different vertical axes is refused with
  a message naming them, like the unit rule. `flip` may differ (it is already compensated).
- Different origins cannot be detected from the files. The Calibration page says, next to the water
  column fields, that one surface and floor apply to every session, so they must share an origin.
- Test: adding a second file with another `vertical_axis` is refused before it is listed.

## 5. Smaller items from finding 9

- **`VideoInfo.n_frames` for a gappy file** (`readers/assemble.py:291`) is the row count. A file with
  `fnum` 0-199 and 400-599 reports 400 frames, 13.3 s, against a real 20.0 s. Set it to the span (last
  interval end) when intervals exist; the check that intervals cover the rows is kept on the row count.
  Consumers of `video.n_frames` are audited first (only `session_facts` is expected to read it); if
  another one assumes rows, this item is dropped from SP5 rather than widened.
- **Horizontal-plane handedness** (`native3d.horizontal_axes`) returns the two non-vertical axes in file
  order, so `vertical_axis="y"` gives `(x, z)`, which is mirrored relative to the right-handed `(z, x)`.
  Audit result: magnitude metrics are unaffected, but **IL-11's `mean_heading_rad` and the sign of
  `left_right_turn_bias` are mirrored** for `vertical_axis` of `x` or `y`. Fix: return the two axes in
  cyclic order after the vertical one (`z -> (x, y)`, `x -> (y, z)`, `y -> (z, x)`). `vertical_axis="z"`,
  the default, is unchanged. Not fixed here: `flip` negates the vertical axis, which also mirrors the
  view from above; that stays documented (Known Issues in SP6) rather than silently permuting a
  horizontal axis.
- **IL-15 token without a water column** is done in SP2.

## 6. Not doing: excluding the water column from the cache key

The review suggests dropping `calibration.water_column` from the preprocessing cache key because
`apply_water_column` is a post-hoc transform. The cache stores the object returned by `preprocess()`,
which already includes `apply_calibration_and_zones` (calibration, the water column and zones), so the
water column is part of what is cached. Removing it from the key would return stale depths after the
user changes the column. Splitting the cache before and after calibration is a larger change than the
cost it saves (a re-preprocess when the column changes), so SP5 leaves it as it is.

## 7. Order of work and risk

1. `vertical_cm` helper and the water-column masking (tests first; changes native numbers).
2. Inverted `FusionSettings` and the `align.py` sign.
3. `vertical_axis` rule in `_native_rule`.
4. `horizontal_axes` order (changes IL-11 / turn-bias signs for `vertical_axis` x or y).
5. `n_frames` span, if the audit allows.
6. Dialog and Calibration page text, README wording, CHANGELOG.

One PR per numbered group if the groups grow; the first two are independent of the rest.
