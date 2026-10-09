# 2D / 3D project mode (sub-project E)

**Status:** draft 2026-10-09, awaiting review
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). E is the entry point for the 3-D
sub-projects F, G, D and B below.

## Why

A project cannot say whether it is 2-D or 3-D, or how a 3-D recording was made. Everything
downstream (panel split, ID correspondence, fusion, 3-D metrics) needs that fact first, and
needs it fixed before sessions exist.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| **E** | **Mode switch and routing** (this spec) | `mode` in the manifest, Project-screen UI, locking, stage status, 3-D compute blocked |
| F | Panel split (layout i) | Define the two panels of one video; one tracking run per panel; two logical sessions |
| G | ID correspondence (layouts i and ii) | Map fish X in the top view to fish Y in the side view. Auto-match where IDs agree, manual correction in the UI otherwise. Own cycle, right after E |
| D | Fusion | Frame sync, then one 3-D track per fish from top x/y and side depth |
| B | 3-D metrics | 3-D speed, path length, vertical position, neighbour distance. Amends D-031 |

F and G are independent of each other. Order: E, F and G, D, B.

## Decisions

- Mode is project-level, in a new `ProjectManifest.mode`, not in `scene`. `scene.camera_view` stays
  "what one camera sees"; D gives each view its own through `Engine.camera_view_for(session)`.
- The mode is locked once the project has a session. Removing every session unlocks it.
- A 3-D project cannot run the pipeline or export until D and B exist. Sessions can still be added
  and the project saved.
- ID correspondence is not built here. E reserves its place in the file (`mode.id_map`) only.

## Design

1. **Model.** `ProjectMode` in `core/models.py`:
   - `dimension: "2d" | "3d"` (default `"2d"`)
   - `layout: None | "single_video_two_panels" | "two_videos"` (default `None`)
   - `id_map: dict[str, str]` (default `{}`, reserved for G, never read or written in E)

   A validator requires `layout` to be set if and only if `dimension == "3d"`. Existing manifests
   have no `mode` key and load as 2-D unchanged. `ProjectManifest.mode: ProjectMode` is hashed into
   `project_hash`.
2. **Store.** `ProjectStore.update_mode(mode)` raises `ValueError` when `manifest.sessions` is
   non-empty, then emits a new `modeChanged` signal (same pattern as `sceneChanged`). A read-only
   helper `mode_locked` returns the reason string or `None`.
3. **Project screen.** An "Analysis type" radio group (2D / 3D). Choosing 3D reveals a second group:
   "One video, two panels (top and side in one frame)" and "Two videos (top and side tracked
   separately)", each with a one-line help text. Both can be set at create time or later while
   unlocked. Once locked the controls are disabled with "Remove all sessions to change the mode".
4. **Stage status.** `compute_stage_statuses` marks Sessions `blocked` with "Choose a 3-D layout"
   when `dimension == "3d"` and `layout is None`. In a 3-D project, Processing and Export are
   `blocked` with "3-D fusion is not available yet". 2-D projects are unchanged.
5. **Routing.** A pure `screen_flow(mode)` returns which Sessions-step variant to show. In E every
   mode returns the existing 2-D Sessions screen. F and G replace the 3-D entries without touching
   other screens. Calibration, Zones and Metrics show a one-line banner in 3-D: "3-D mode: this
   screen applies to the 2-D tracks only until fusion is available". Metrics offers 2-D-valid
   metrics only.
6. **Provenance.** Exports are blocked in 3-D, so no README or manifest change in E.

## Testing

- Model: round-trip, default, validator (3-D without layout, 2-D with layout), old manifest loads.
- Store: `update_mode` rejected with sessions, allowed after they are removed, signal emitted.
- UI: radio visibility, lock state and message, stage statuses (Sessions, Processing, Export).
- Existing 2-D tests pass unchanged.
- Docs: CHANGELOG entry, new row in `docs/dev/DECISIONS.md`, user guide Project section.

## Not in this cycle

Panel definition and cropping (F), ID correspondence logic or UI (G), frame sync and fusion (D),
3-D metrics (B), reading native 3-D tracker files (roadmap A), per-session camera views.
