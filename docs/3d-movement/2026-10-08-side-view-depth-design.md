# Side-view depth: camera-view setting and IL-15

**Status:** approved 2026-10-08 (sub-project C of [the 3-D roadmap](2026-10-08-3d-roadmap.md))

## Why

Stacked secondary-level zones already give band occupancy, latency, visits, transitions and
dwell on a side view (Z-1 to Z-9). Missing: a way to say a recording *is* a side view
(ROADMAP Z-10's blocker), a continuous depth measure, and a guard so "depth" is never
computed from a top-down y axis.

## Decisions

- Depth runs 0 = water surface to 1 = tank floor. Height above the floor is `1 - value`.
- The metric is **IL-15**, not Z-10: exports bucket metrics by ID prefix and the UI by level.
  Z-10 is re-reserved for auto depth bands.
- Camera view is project-level. A per-session override arrives with sub-project D.
- Existing metrics are not gated by camera view in this cycle.

## Design

1. **Setting.** `ProjectManifest.scene: SceneConfig` with `camera_view: "unknown" | "top" |
   "side"` (default `unknown`). Top-level, not in `ZoneSet` (Zones Clear/Load/Import replaces
   it) nor `CalibrationConfig` (hashed into the cache key). Store: `update_scene()` and
   `sceneChanged`.
2. **Gating.** `Metric.valid_camera_views: frozenset | None` (None = any view; IL-15 =
   `{"side"}`). One predicate returns `{metric_id: reason}`; `Engine.skipped_metrics` merges
   identity and view reasons. `compute()` called directly with no water column still returns
   every column as NaN.
3. **Extent.** `zones/extent.py` pools min/max y over every main-level "+" ROI vertex. No
   usable zone gives NaN and a token (`none:no_main_zone`, `none:degenerate_zone`,
   `none:frame_size_mismatch`, `none:not_derived`), never the frame height.
4. **IL-15.** With `T`, `B` the surface and floor rows and `d = (y - T) / (B - T)` over frames
   inside `[T, B]`: `mean_depth_fraction`, `median_depth_fraction`, `sd_depth_fraction`
   (ddof 1), `mean_depth_cm` (NaN uncalibrated), `frac_outside_extent`, `depth_extent_source`.
   Out-of-extent frames are dropped and counted, never clipped.
5. **Zones canvas.** For every reader except idtracker.ai v6 the canvas was a blank 640x480
   scene and saved zones carried no frame size, so zones were not in video pixels. The scene
   is now sized from the session frame, and `source_*_px` is stamped only when the ZoneSet has
   no ROIs yet. This gives correct units, not a backdrop to draw on.
6. **UI.** A camera-view combo on the Calibration screen; a Zones-stage warning; one
   availability pass on the Metrics screen.
7. **Provenance.** `SessionProvenance.camera_view` and README rows, written only when declared
   or when IL-15 is computed.

## Not in this cycle

Auto depth bands, vertical speed, freezing-by-depth, typed surface/bottom rows, a depth plot,
any 3-D handling, gating IL-3/IL-14, and a Zones-canvas backdrop for non-idtracker.ai sessions.
