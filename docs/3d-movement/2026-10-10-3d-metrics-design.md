# 3-D metrics (sub-project B2)

**Status:** implemented 2026-10-10 (decision D-042); see "Changes made during the build" at the end
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on [fusion](2026-10-09-fusion-design.md) (D) and [running a 3-D project](2026-10-10-3d-run-design.md) (B1).

## Why

A fused session has the top view's x and y and a depth for every fish, but every metric except
IL-15 still measures in the top-view plane. B2 adds the three metrics asked for at the start of the
3-D work: 3-D path length, 3-D speed and 3-D nearest-neighbour distance. The 2-D versions stay and
keep running on the top view.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E, G, F, D, B1 | Mode switch, ID correspondence, panel split, fusion, running a 3-D project | Done |
| **B2** | **3-D metrics** (this spec) | IL-16, IL-17, GL-16; availability; documentation |
| A | Read 3-D tracker files | |

## Decisions

- **Three new metrics, next to the 2-D ones:** IL-16 3-D path length, IL-17 3-D speed, GL-16 3-D
  nearest-neighbour distance. IL-1, IL-2 and GL-1 are unchanged.
- **Coordinates in cm.** `X = x_px / px_per_cm`, `Y = y_px / px_per_cm` (the top view's scale),
  `Z = depth_fraction * depth_height_cm` (the tank height from the fusion settings). Distances are
  Euclidean in (X, Y, Z). The sign of Z does not matter.
- **The top view's cm scale is required, and the metrics say so.** Without it the 3-D metrics are
  unavailable and never produce a number. There is no estimate from the fusion (it would add an
  error that the outputs would not show).
- **Valid steps and frames need all three coordinates.** A step needs a valid x, y and depth at
  both ends. A frame for the nearest-neighbour distance needs a valid x, y and depth for every fish.
- **Existing conventions:** columns are emitted unconditionally (NaN when unavailable), body-length
  units use the animal's body length converted to cm through the same scale, identity rules are as
  for the 2-D counterparts (IL-16 and IL-17 need identities, GL-16 does not).

## Design

1. **IL-16, 3-D path length** (`track2data/metrics/individual.py`). Per animal, the sum of
   `||P[t+1] - P[t]||` over steps with finite `P` at both ends, where `P` is the (X, Y, Z) series.
   Columns: `session_id, metric_id, individual_id, path_length_3d_cm, path_length_3d_bl,
   n_valid_steps`. An animal with no valid step reports NaN (not 0). `path_length_3d_bl` divides
   by the animal's body length in cm (`body_length_px / px_per_cm`); NaN when the body length is
   unknown. `window_safe` (binned runs add nothing across bins beyond the per-bin sums).
2. **IL-17, 3-D speed** (`individual.py`). Horizontal speed `vh` is the pipeline's own
   `kinematics.speed_px_s / px_per_cm` (so IL-17 is consistent with IL-2). Vertical speed `vz` is
   the finite difference of `Z` with the same scheme as `preprocess/kinematics.py`
   (`compute_kinematics`; reuse its derivative helper rather than a second implementation). The 3-D
   speed per frame is `sqrt(vh^2 + vz^2)`, valid where both are finite. Columns:
   `session_id, metric_id, individual_id, mean_speed_3d_cm_s, median_speed_3d_cm_s,
   max_speed_3d_cm_s, mean_speed_3d_bl_s`. Always at least IL-2's cm/s for the same frames.
3. **GL-16, 3-D nearest-neighbour distance** (`track2data/metrics/group.py`). As GL-1 with 3-D
   points: per frame the kd-tree nearest-neighbour distance of every fish, the mean over fish; frames
   where any fish lacks x, y or depth are skipped and counted. Columns: `session_id, metric_id,
   mean_nnd_3d_cm, median_nnd_3d_cm, mean_nnd_3d_bl, n_skipped_frames_3d`. `_bl` uses the same body
   length convention as GL-1's `mean_nnd_bl`, converted to cm. One fish gives NaN.
4. **Availability** (`track2data/metrics/base.py`, `availability.py`, the Engine and the Metrics
   screen). A new class flag `requires_depth_scale: ClassVar[bool] = False`, True for the three.
   - 2-D project: unavailable, reason "needs a fused 3-D session".
   - 3-D project, manifest level (the Metrics screen, `validate`, notes): unavailable when the
     calibration mode is `bodylength` (no top-view scale), reason "needs a cm scale for the top view
     (use scalar or session calibration)"; otherwise available. Reuse the `manifest_view` helper
     style of B1.
   - Run time, per fused unit: skipped, with the reason in the run README, when the unit's
     `px_per_cm` is None or `depth_height_cm` is None (in practice scalar calibration with no
     `px_per_cm`; session calibration without a length unit blocks the whole run instead). `compute()` called directly on such a session returns NaN columns.
5. **Outputs and docs.** The new columns reach the metric tables, `all_sessions`, the README metric
   list, and `docs/METRICS_SPEC.md` (a section per metric with definition, formula, inputs,
   assumptions and warnings: depth comes from a side camera at right angles, no refraction or
   parallax correction, a wrong tank height scales every vertical distance); each metric carries a
   `MetricDocumentation` and a citation (standard kinematics; nearest-neighbour distance as GL-1).
   `docs/METRIC_REFERENCES.csv` and the reference-consistency tests are updated as the existing
   metrics require. The user guide and CHANGELOG describe them.
6. **2-D and old projects unchanged.** The metrics are not selectable in 2-D, no existing output
   changes, and a 2-D run is byte-identical, except that `codebook.csv` lists the whole registry and so gains rows for IL-16, IL-17 and GL-16.

## Testing

- Exact values on synthetic tracks: a diagonal movement with known X, Y and depth gives a known
  3-D length, speed and nearest-neighbour distance; IL-17 is at least IL-2's cm/s.
- NaN in x, y or depth (steps and frames dropped, counted), an animal with no valid step, one fish,
  unknown body length, unknown tank height, missing scale (NaN columns, no warnings: run with
  `-W error::RuntimeWarning`).
- Availability in 2-D, in 3-D under each calibration mode, and the per-unit run-time skip with its
  reason in the README; the Metrics screen rows.
- Binned runs for all three; a serial and parallel run agree.
- End to end on the physical test scene from the B1 tests (known 3-D path): exported values within
  tolerance.
- 2-D regression: existing suites, and a 2-D control run unchanged.
- Docs: CHANGELOG, a decision entry, the metrics spec, the references tests, the user guide.

## Not in this cycle

Vertical speed as its own metric, 3-D inter-individual distance and cohesion, estimating the top
view's scale from the fusion, a per-view scale, and depth-band zones.

## Changes made during the build

Where the build differs from the text above, the build is right.

- **Kinematics config route.** `PreprocessedSession` does not carry the `KinematicsCfg`. A new class
  flag `Metric.uses_kinematics_cfg` (True for IL-17) makes `Engine._effective_cfg` put the project's
  config under `cfg["kinematics"]`; IL-17 defaults to `KinematicsCfg()` without it.
- **IL-17 and the inequality.** `3-D speed >= IL-2` holds only over the frames where the vertical
  speed is finite (the forward-difference estimator gives none for the last frame; a depth segment
  shorter than the Savitzky-Golay window gives none). Frames without a vertical speed are left out of
  IL-17, never counted as 0. In a binned run `vz` is estimated inside each bin, so the estimator's edge
  frames can differ slightly from a whole-session run.
- **IL-16 and IL-1.** `IL-16 >= IL-1` holds over the steps where depth is also finite (`n_valid_steps`).
- **GL-16 and GL-1.** GL-16 skips frames where any fish lacks depth that GL-1 keeps, so the
  inequality holds only per frame where both are valid, not for the two means.
- **Skip reasons.** The three reasons are constants in `availability.py` (`NEEDS_FUSED_REASON`,
  `NEEDS_CM_MODE_REASON`, `NEEDS_CM_SCALE_REASON`). The manifest-level answer is optimistic (it
  catches a 2-D project, body-length calibration and, in scalar mode, a missing `px_per_cm`; a unit
  whose scale is missing anyway, as when `track2data run` carries on after its warning, is caught per
  unit at run time. Session calibration without a length unit never reaches the metrics: it raises
  CAL-SESSION-MISSING and the 3-D run refuses). A unit always has a tank
  height (`FusionSettings.tank_height_cm > 0`), so in practice the run-time skip is a missing
  `px_per_cm`. `validate`, the log and the Metrics screen name the cause that fired.
- **The Metrics screen refreshes** when the calibration or the mode changes, and its presets leave
  greyed-out rows unticked (a 2-D project's *All metrics* no longer ticks the 3-D metrics).
- **GL-16's skip count is `n_skipped_frames_3d`** (not `n_skipped_frames`): the merged group tables
  join GL-1 and GL-16 in one row, and a shared name would have been suffixed `_x`/`_y` when the counts
  differ. The codebook maps it to "frames".
- **`list-metrics`** prints "fused 3-D + cm scale" in the VIEW column of IL-16, IL-17 and GL-16.
- **Presets** leave every greyed-out row unticked, not only the 3-D ones: in a project whose sessions
  are all identity-free, *Standard locomotor* ticks nothing.
- **Metric counts** in the README and ROADMAP now say 54.

