# Running a 3-D project (sub-project B1)

**Status:** implemented 2026-10-10 (see "Changes made during the build" at the end)
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on the mode switch (E), [panel split](2026-10-09-panel-split-design.md) (F), [ID correspondence](2026-10-09-id-correspondence-design.md) (G) and [fusion](2026-10-09-fusion-design.md) (D). Supersedes the "no 3-D compute" part of D-037.

## Why

A 3-D project can be set up, paired and fused, but Processing, Preview and Export are blocked.
B1 lets a 3-D project run: each fused pair goes through the existing pipeline, vertical position
(IL-15) is taken from the real depth, and the depth is exported. The new 3-D metrics (3-D speed,
path length, neighbour distance) are B2.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E, G, F, D | Mode switch, ID correspondence, panel split, fusion | Done |
| **B1** | **Run a 3-D project** (this spec) | Run units, the gate, IL-15 from depth, depth in the exports, UI and CLI |
| B2 | 3-D metrics | 3-D speed, path length, neighbour distance; unit conventions for 3-D distances |
| A | Read 3-D tracker files | |

## Decisions

- **One fused session per pair.** In a 3-D project a run walks *run units*: one per fusable pair,
  with the id `<top>+<side>` and the output folder `out_dir/<top>+<side>/`.
- **Everything else is skipped, with a reason.** Sessions in no fusable pair (no pair, no fusion
  settings, a fusion error) are not computed. Each skip and its reason is listed in the run
  README, `sessions.csv` and the Processing screen. If no pair is fusable the run refuses.
- **No plausible-but-wrong numbers (D-037 stays true in spirit).** In a 3-D project
  `compute_metrics` accepts only a fused session (one with a depth array). A top-view-only
  session is refused.
- **IL-15 reads the depth array on a fused session.** Zones are not involved. Same columns as
  today; `mean_depth_cm` is the depth fraction times the fusion's tank height;
  `depth_extent_source` is `"fusion"`. IL-15 is available for a fused session whatever the
  project's camera-view setting is. For a plain side-view session nothing changes.
- **Top-view metrics run unchanged.** Zones remain one set per project and apply to the top
  view (per-view zones and depth-band zones are not in this cycle).
- **Depth is exported.** The per-frame tables get `depth_fraction` and `depth_cm`.
- **2-D is unchanged,** including every output byte.

## Design

1. **Run units** (`track2data/api.py`).
   - `Engine.run_units() -> RunPlan` with `units: list[RunUnit]` and `skipped: list[SkippedSession]`
     (`session_id`, `reason`). In a 2-D project one unit per `SessionRef`, no skips. In a 3-D
     project one unit per pair that has fusion settings and fuses without a `FusionError`
     (checked with `Engine.fuse_pair`); every other session, and every pair with a problem, is
     skipped with the `FusionError` text or "not in a pair" / "pair has no fusion settings".
   - `RunUnit` is either a session ref or a pair (`kind: "session" | "pair"`, `unit_id`,
     `ref` or `pair`). `_run` iterates `run_units().units`; the output folder is
     `out_dir / unit_id`. `_run_one_session` becomes `_run_one_unit`: a pair unit gets its
     `PreprocessedSession` from `Engine.fuse_pair(pair).psess` instead of `import_ref` +
     `preprocess`; everything after that (metrics, payload, export, result) is the same code.
   - Parallel workers rebuild the engine from the manifest as today and receive the unit; a pair
     unit fuses in the worker. Results come back in plan order.
   - Fused sessions are not written to the preprocessing cache (their inputs are). `run_units()` fuses each pair once to check it; a serial run reuses that result, a parallel worker fuses again (fusion is cheap next to the metrics).
2. **The gate.** `Engine.require_computable()` raises `ValueError(reason)` in a 3-D project when
   `run_units().units` is empty; the reason names the first problems (for example "no pair is
   ready to fuse: top-1+side-1: no fusion settings for this pair"). `MODE_3D_BLOCK_REASON`
   stays as the text for a 3-D project with no sessions or pairs at all. In a 3-D project
   `compute_metrics(psess)` raises `ValueError("3-D projects compute fused sessions only")` when
   `psess.depth is None`. `run_session(session)` is 2-D only: in 3-D it raises with
   "use run() for a 3-D project".
3. **IL-15** (`track2data/metrics/individual.py`, `metrics/availability.py`, `zones/extent.py`
   untouched). `VerticalPosition.compute` uses `psess.depth` when present: per animal, the mean,
   median and SD (ddof 1) of the depth fraction over valid samples, `mean_depth_cm =
   mean * psess.depth_height_cm` (NaN when unknown), `frac_outside_extent` from
   `psess.depth_outside` (the fusion's count over the animal's valid side positions), and
   `depth_extent_source = "fusion"`. `PreprocessedSession` gains `depth_height_cm: float | None`
   and `depth_outside: np.ndarray | None` (per animal), set by `fuse`. The camera-view gate
   passes a metric that declares `valid_camera_views` when the session carries a depth array
   and the metric also declares `uses_depth = True` (IL-15 only); other metrics are gated as
   today. Engine `camera_view_for(session)` returns `"top"` for a fused session.
4. **Exports** (`track2data/exporters/`). When `psess.depth` is set the per-frame table gets
   `depth_fraction` and `depth_cm` (cm = fraction * `depth_height_cm`, NaN when unknown),
   aligned with the position columns; csv_long, csv_wide, feather and excel all carry them.
   `sessions.csv` and the session README add: the unit kind, the top and side session ids, the
   fusion settings (offset, axis, flip, rows, tank height), overlap frames, fish fused and left
   out, positions outside the water column, the agreement RMS, its warning flag and skip
   reason. The run-level README and `sessions.csv` list skipped sessions with reasons. For
   2-D runs none of the new columns or rows appear.
5. **UI and CLI.**
   - `stage_status`: Processing, Preview and Export are `blocked` in a 3-D project only when
     `run_units().units` is empty, with that reason (the manifest-only status helper uses a
     cheap check: at least one pair with fusion settings; the full fusability check runs in the
     Processing setup check and at run time, so a pair that fails to fuse is reported there).
   - The Processing setup check lists the units that will run and the sessions that will be
     skipped with their reasons (warning, not a problem), and blocks Start when none will run.
   - Preview and the trajectory view show the fused unit's top-view tracks with its id.
   - `track2data validate` reports unfusable pairs; `run` works on 3-D projects; the
     `sensitivity` command keeps refusing 3-D projects ("not supported for 3-D projects yet").
6. **Hand-off to B2.** B2 adds metrics that read `psess.depth` together with `psess.xy`; the
   cm scale for depth is `psess.depth_height_cm` (cm per unit fraction) and for the plane
   `psess.px_per_cm`.

## Testing

- Run plan: 2-D one unit per session; 3-D units, skips and reasons for every skip class (no
  pair, no settings, fps mismatch, unreadable session); empty plan refusal text.
- Gate on every entry point (`run`, `compute_metrics`, `run_session`, `export`, CLI, UI status).
- End to end: a synthetic 3-D project built from the physical scene used to review fusion
  (known depth), run serially and with two workers; exported depth columns and IL-15 values
  match; both modes give identical files.
- IL-15: fused path, NaN gaps, all-NaN animal, unknown tank height, side-view path unchanged.
- Exporters: columns present only with depth, aligned with positions, all four formats; 2-D
  outputs byte-identical to the previous release's fixtures.
- UI: status, setup check lists, Preview of a fused unit, nothing written on rebuild.
- Docs: CHANGELOG, a decision entry, the user guide, the roadmap.

## Not in this cycle

3-D speed, path length and neighbour distance (B2), depth-band zones and per-view zones, several
offsets per pair, a camera-view setting per session, reading 3-D tracker files (A), and
`sensitivity` for 3-D projects.

## Changes made during the build

Where the build differs from the text above, the build is right.

- **Skipped sessions are not rows of `sessions.csv`.** They go to a new `skipped.csv`
  (`session_id,reason`) and a "Skipped sessions" section of `PROJECT_SUMMARY.md`, both written only
  when something was skipped. `sessions.csv` has one row per run unit, and for a 3-D run the 18
  `FusionRunInfo` fields (`unit_kind`, `top_session_id`, `side_session_id`, the fusion settings, the
  report counts, the agreement fields and `side_trajectory_sha256`, the checksum of the side
  session's trajectory file). The per-unit README has a "## 3-D fusion" section and `manifest.json` has
  `run_metadata.fusion`.
- **The GUI's plan keeps `fused=None`; a serial run fuses again.** `RunPlanWatcher`
  (`ui/store/run_plan.py`, `ProjectStore.run_plan`) builds the plan on the store's worker pool and drops
  the fusion arrays so the GUI does not hold them; `Engine.run(plan=...)` then fuses each unit itself.
  A plan that still carries its fusion results (the CLI) is reused.
- **The plan is built on the worker pool** (like the Fusion section), never on the GUI thread; stale
  results are ignored, and `TaskRunner.closed` stops resubmission while the window closes.
- **Workers fuse their own pair by index.** A parallel worker receives the manifest JSON, the unit
  kind and the unit's index into `manifest.view_pairs` (a pair unit) or `manifest.sessions` (a
  session unit), builds that one `RunUnit` and fuses the pair; it does not rebuild the plan, and no
  array is pickled.
- **Skip reason and view helper names.** An unpaired session's reason is "not in a fusable pair" and a
  pair without settings gives "pair t+s: no fusion settings for this pair" (not "not in a pair" /
  "pair has no fusion settings"). The fused session's view comes from `Engine.camera_view_for_psess`
  (`"top"` when the session has a depth), not from `camera_view_for(session)`, which still takes a
  plain `Session`.
- **`frac_outside_extent` reads `depth_outside_mask`,** so a time bin counts its own outside samples;
  `depth_outside` is that mask's sum over the session.
- **Frame jumps get a separator row.** `fuse` inserts one NaN separator row (with `separator_mask` and
  `tracked_mask` set, the 2-D convention of `preprocess/timeline_expand.py`) on every per-row array
  where the kept frames jump, so path length and the other frame-to-frame metrics never bridge a gap;
  separator rows are never exported. A fusion without jumps is unchanged.
- **Metadata.** A unit carries the TOP session's metadata (looked up by the unit id among the
  manifest's pairs, never by splitting it on `+`); per-animal metadata matches by the top session's
  label, or by its index through `PreprocessedSession.source_animal_index`.
- **Pre-flight checks read the sessions that run.** In 3-D the consistency report summarises the top
  session of each pair with fusion settings, and session calibration checks both sessions of such pairs.
- **Run records.** `PROJECT_SUMMARY.md` says "Units processed (fused pairs): N of M; K sessions
  skipped" in 3-D; the pooled `all_sessions/manifest.json` carries each unit's `run_metadata.fusion`;
  the unit README says its preprocessing steps are the top session's.
- **`depth_outside_mask` was added** (per frame and animal) beside `depth_outside`, so IL-15 counts the
  outside positions of a time window, not only of the whole session.
- **`validate()` stays blocking-only.** The notes about unfusable pairs and unpaired sessions come from
  `Engine.validation_issues()` (`(blocking, notes)`); `track2data validate` prints both.
- **`manifest_view`** (`track2data/metrics/availability.py`) is the manifest-level availability helper:
  the view and whether the project can carry depth, so the screens that have no session in hand
  (metric lists, the setup check) agree with the run.
- **`export()` uses a cheap check** (at least one pair has fusion settings) before it runs the
  plan, rather than fusing every pair twice.
- **`side_trajectory_sha256`** was added to the provenance: the session checksum and the staleness
  check describe the top session only.
- **Block text.** `MODE_3D_BLOCK_REASON` is "Pair and fuse a top and a side session first", used when
  nothing can be run and no pair has settings. `SENSITIVITY_3D_REFUSAL` is "sensitivity is not supported
  for 3-D projects yet".

### Known limits

- All fused data of a plan is recomputed on every run (the plan, the Preview of a unit, a serial run
  from the GUI); nothing fused is cached.
- `csv_wide` has no per-frame table, so it carries no depth columns.
- Zones are one set applied to the top view; no 3-D speed, path length or neighbour distance (B2);
  `sensitivity` refuses 3-D projects.
