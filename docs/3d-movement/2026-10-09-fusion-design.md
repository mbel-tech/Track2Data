# Fusion of top and side views (sub-project D)

**Status:** draft 2026-10-09, awaiting review
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on the mode switch (E), [ID correspondence](2026-10-09-id-correspondence-design.md) (G), [panel split](2026-10-09-panel-split-design.md) (F) and the depth convention of [side-view depth](2026-10-08-side-view-depth-design.md) (C).

## Why

A 3-D project has paired top and side sessions (G) whose positions are in each view's own pixels
(F). Nothing yet turns a pair into one recording that knows both where a fish is on the floor and
how deep it is. D does that, for two cameras at right angles, and shows the user whether the pair
fits together. D does not compute metrics; B does.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E, G, F | Mode switch, ID correspondence, panel split | Done |
| **D** | **Fusion** (this spec) | Fusion settings per pair, the fusion logic, `Engine.fuse_pair`, the Fusion panel and dialog on the Views page |
| B | 3-D metrics | Reads the fused sessions; decides which metrics run in 3-D; lifts the 3-D compute block |

## Decisions

- **Geometry: two cameras at right angles.** The side view's horizontal axis follows one top-view
  axis (x or y, optionally flipped). No camera calibration or triangulation.
- **The result is an ordinary top-view session plus a depth array.** Existing 2-D code works on it
  unchanged; B reads `depth`.
- **Sync: same frame rate and a whole-frame offset.** Frame rates that differ beyond 0.1% are
  refused. For the layout "One video, two panels" the offset is 0 and fixed.
- **Water column per pair.** The user gives the side-view surface row, floor row and the tank
  height in cm. Depth is `(y_side - surface) / (floor - surface)`, 0 = surface, 1 = floor
  (the IL-15 convention). Positions outside [0, 1] become NaN and are counted, never clipped.
- **The side view's scale comes from the tank height:** `(floor - surface) / tank_height_cm`
  pixels per cm. The top view's scale is its normal calibration.
- **Agreement check, not extra data.** Both views are converted to cm; the side horizontal
  position is compared with the chosen top-view axis; the median difference is removed (the two
  views have no common origin) and the RMS of the rest is reported in cm.
- **Only matched fish are fused,** those in the pair's `fish_map`. The rest are listed in the
  report.
- **Fusion is computed on demand and cached,** never stored in the project file. 3-D compute stays
  blocked until B (`Engine.require_computable()` is unchanged).

## Design

1. **Model** (`track2data/core/models.py`).
   - `FusionSettings(frame_offset: int = 0, horizontal_axis: Literal["x", "y"] = "x",
     flip: bool = False, surface_row: float, floor_row: float, tank_height_cm: float)`.
     Valid when `0 <= surface_row < floor_row` and `tank_height_cm > 0`; finite numbers only.
   - `ViewPair.fusion: FusionSettings | None = None`. Manifests without it load unchanged; it is
     hashed into `project_hash` through `model_dump`.
   - `PreprocessedSession.depth: np.ndarray | None = None`, shape `(n_frames, n_animals)`.
   - `FusionReport` (dataclass): `overlap_frames`, `top_frames`, `side_frames`, `fused_labels`,
     `unmatched_top`, `unmatched_side`, `n_outside_column`, `agreement_rms_cm` (overall and per
     fish; `None` with `agreement_skipped` giving the reason), `agreement_warning: bool`,
     `suggested_offset: int | None`.
   - `FusedSession` (dataclass): `psess: PreprocessedSession` (top view, matched fish, `depth`
     set), `report`, `session_id = "<top>+<side>"`.
2. **Fusion logic** (`track2data/fusion/`, no Qt).
   - `fuse(top: PreprocessedSession, side: PreprocessedSession, pair: ViewPair, *,
     same_video: bool) -> FusedSession`. Raises `FusionError(message)` when: the pair has no
     settings; the `fish_map` is empty or invalid (`validate_fish_map`); a session is
     identity-free; frame rates differ by more than 0.1%; the settings are invalid; the overlap
     is empty. `same_video` forces the offset to 0.
   - Alignment is on video frame numbers (`timeline()`), side frame = top frame + offset; only
     the overlap is kept, and the fused session's frame index is the top view's.
   - Depth, drop count and the side scale as in Decisions. Agreement needs the top view's
     `px_per_cm`; without it `agreement_skipped = "top view not calibrated"` and depth is still
     computed. The warning is set when the overall RMS exceeds 10% of the pooled range of the
     top-view axis, in cm.
   - `suggest_offset(top, side, pair, window_s=5.0) -> int | None` scans lags in ±window, scores
     each by the pooled agreement RMS over the matched fish, and returns the best lag when it
     beats lag 0 by a clear margin (at least 20% lower RMS), else `None`.
3. **Engine** (`track2data/api.py`). `fuse_pair(pair) -> FusedSession` preprocesses both sessions
   through `preprocess_ref` (so each view's own pipeline and calibration apply), decides
   `same_video` from the layout, and caches the result under a key that includes both sessions'
   cache keys and the pair's `FusionSettings`. `fuse_all()` fuses every pair with settings and
   returns the results and the errors. `require_computable()` is unchanged.
4. **Store** (`ui/store/project_store.py`). `update_fusion(top_id, side_id, settings | None)`
   replaces the pair's settings and emits `viewsChanged`; rejected unless the project is 3-D and
   the pair exists. Changing a pair's `fish_map` or either session's panel keeps the settings (the
   water column does not depend on the matching).
5. **Views page.** A Fusion panel for the selected pair with a status line: "setup needed",
   "ready" with overlap, fused fish and dropped positions, "agreement warning: RMS x cm", or the
   `FusionError` text. A "Set up fusion…" button opens `FusionDialog`
   (`ui/dialogs/fusion_dialog.py`): the side-view backdrop (the panel preview) with two draggable
   horizontal lines for the surface and floor, typed fields for both rows, the tank height, the
   axis, flip and the offset (hidden and fixed at 0 for one video), a "Suggest offset" button, and
   a live summary from the same `fuse` call. The fusion runs in a background task and stale
   results are ignored. `stage_status` for Views gains a warning while a pair has no fusion
   settings; it still never returns `blocked`.
6. **Hand-off to B.** B calls `Engine.fuse_all()`; each `FusedSession.psess` carries `xy` (top
   view, panel pixels), `depth`, the top view's calibration and zones, and `px_per_cm`. The side
   scale is `(floor - surface) / tank_height_cm` from the pair's settings.

## Testing

- Model: defaults, validation (surface < floor, positive height, finite), round trip, old
  manifests, hash dependence.
- Fusion logic on synthetic orthogonal tracks with a known offset, scale and depth: exact depth,
  drop counting, agreement RMS near 0 for consistent tracks and large for a mismatched fish,
  unmatched fish listed, the axis and flip options, the uncalibrated case, every `FusionError`.
- `suggest_offset` recovers a known lag and returns `None` for lag 0 and for noise.
- Engine: `fuse_pair` result, the cache key changes with the settings and not otherwise,
  `fuse_all` collects errors, compute remains blocked.
- Store: `update_fusion` signals, rejection outside 3-D or for a missing pair, settings survive
  re-matching.
- Views page and dialog: status text per state, the lines and fields stay in sync, the offset
  control is hidden for one video, the summary updates, stale results ignored, nothing is written on
  rebuild.
- Docs: CHANGELOG, a decision row in `docs/dev/DECISIONS.md`, the user guide, the roadmap row.

## Not in this cycle

3-D metrics and lifting the compute block (B), camera calibration and triangulation, non-right-angle
cameras, fusion across different frame rates, automatic detection of the water column, a z axis in
the exports, and several offsets for one pair.
