# Panel split (sub-project F)

**Status:** implemented 2026-10-09 (decision D-039). Changes made during the build: the Panels section is
its own widget, `ui/widgets/panels_section.py`, embedded in the Views page and refreshed from it; it loads
the unpanelled session on the store's worker pool before opening the editor; the editor's flags are
*low*, *left out* and *no data*; no log warning is written for a fish left out of a panel (the editor
flag is the notice).
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on [the mode switch](2026-10-09-mode-switch-design.md) (E) and
[ID correspondence](2026-10-09-id-correspondence-design.md) (G).

## Why

A 3-D recording can be one video with the top view and the side view in two panels. Track2Data
reads tracker output; it does not track. So for the layout "One video, two panels" the project
needs to know which part of the frame each view occupies, and to turn one video into two sessions
(top and side) that G can pair and match, and D can later fuse.

## Two ways the data arrives

| | Case | What the user has | What F does |
|---|---|---|---|
| A | One tracker run on the whole frame | One session folder; its animals come from both panels | Splits it into two sessions, one per panel |
| B | Two tracker runs on the same video, each limited to one panel (for example by an ROI) | Two session folders that point at one video | Records each session's panel; nothing is filtered because the tracker already did it |

Two separately recorded videos (layout "Two videos") need nothing from F.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E | Mode switch | Done |
| G | ID correspondence | Done |
| **F** | **Panel split** (this spec) | `PanelRect`, applying a panel to a session, splitting a session, the panel editor, the Panels section on the Views page |
| D | Fusion | Reads `manifest.view_pairs`; needs per-view pixel scale (not F) |
| B | 3-D metrics | |

## Decisions

- **One idea covers both cases:** a session may have a *panel*, the rectangle of the video it covers.
  Reading a session with a panel keeps only the animals inside it.
- **Coordinates are panel-relative.** The panel's top-left becomes (0, 0) and the session's video size
  becomes the panel size. Zones are then drawn on one panel, and depth (IL-15) measures y inside the
  side panel. Cases A and B behave the same way.
- **Assignment by majority (case A).** An animal goes to the panel that holds most of its tracked
  positions. Positions outside the rectangle become NaN in that panel's session, because they belong
  to the other view. An animal with under 50% of its positions in a panel is left out of that panel's
  session, with a warning. The editor flags animals under 90% inside.
- **The panel is part of the session's identity.** The same folder with two different panels is two
  sessions, and the panel is part of the preprocessing cache key.
- **F-created pairs are hand-made.** The `ViewPair` for the two panels has `auto=False`, so
  re-applying a regex pattern (G) never removes it.
- **Changing a panel resets that session's pair map.** The animals in the session may change, so the
  pair's `fish_map` and `same_ids` are cleared; the pair itself stays.
- **Panels exist only for the layout "One video, two panels".**

## Design

1. **Model** (`track2data/core/models.py`).
   - `PanelRect(x: float, y: float, width: float, height: float)`; `x, y >= 0`, `width, height > 0`.
   - `SessionRef.panel: PanelRect | None = None`. Manifests without it load unchanged.
   - Session ids from a split are `<id>__top` and `<id>__side`; a collision gets a numeric suffix.
   - Duplicate detection (`_is_duplicate` and the session selector in `ui/store/project_store.py`)
     treats the same folder with a different panel as a different session.
2. **Applying a panel** (`track2data/views/panels.py`, no Qt).
   - `apply_panel(session: Session, panel: PanelRect) -> Session` returns a new session: animals
     assigned by majority and kept if at least 50% of their positions are inside; positions outside
     set to NaN; coordinates shifted by the panel origin; `video.width_px`/`height_px` set to the
     panel size; `n_animals`, `identities_labels`, colours, `id_probabilities` and `body_length_px`
     filtered together with the animals; `setup_points` and `roi_list` moved into panel coordinates.
     A panel larger than the video, or one that lies outside it, raises `ValueError`.
   - `panel_coverage(session, rect) -> list[AnimalCoverage]` gives, for each animal, the share of its
     positions inside the rectangle, for the editor and its flags.
   - Identity-free sessions have one slot per frame, so positions outside the panel become NaN and
     slots with no position left are dropped; the session stays identity-free.
   - It is applied where sessions are read: the engine (`track2data/api.py`) and the store's
     background probe, so previews, runs and the CLI all see the panel version, and
     `SessionFacts` describes the panel (size, animals, labels).
   - The zones backdrop (the tracker's background image) is cropped to the panel when drawn.
3. **Store** (`ui/store/project_store.py`).
   - `split_session_into_panels(session_id, top_rect, side_rect)` replaces the whole-frame session
     with `<id>__top` and `<id>__side` (same folder and reader settings, `panel` set, `view_role`
     set), and adds a `ViewPair(top, side, auto=False)`.
   - `set_session_panel(session_id, rect | None)` handles case B and clearing.
   - Both reject calls unless the project is 3-D with layout "One video, two panels"
     (`PANELS_ONLY_FOR_SINGLE_VIDEO`, a new constant) and emit `viewsChanged`.
   - Changing or clearing a panel clears `fish_map` and `same_ids` of the pair that holds the session.
4. **Panel editor** (`ui/dialogs/panel_dialog.py`).
   - Presets "Left | Right" and "Top | Bottom" with a split slider (default 50%); exact x, y, width and
     height fields for each panel; a choice of which panel is the top view.
   - Preview backdrop: the tracker's background image if there is one, otherwise the first video
     frame when the video file exists and `av` is installed, otherwise the tracks themselves, drawn
     as points. Two rectangles are drawn over it.
   - A per-fish table (case A) shows its panel, its share inside, and a flag under 90%.
   - OK is disabled when a rectangle is invalid or leaves a panel without animals.
   - "Set panel" (case B) opens the same editor with one rectangle.
5. **Views page.** A "Panels" section, shown only for the layout "One video, two panels": one row
   per session with its panel ("whole video" or the rectangle), and the buttons "Split into
   panels…", "Set panel…" and "Clear panel".
6. **Hand-off to D.** Every session already has its own video size and coordinates in panel
   pixels, so D reads two ordinary sessions plus `view_pairs`.

## Testing

- Model: defaults, validation, round trip, old manifests, project-hash dependence.
- `apply_panel`: shift and size, majority assignment, NaN outside, 50% cut-off, label and colour
  filtering, identity-free sessions, setup points and ROI move, invalid panel.
- `panel_coverage` values and the 90% flag.
- Store: split creates the two sessions and the hand-made pair, ids and collisions, duplicates,
  case B, clearing resets the pair map, rejection outside the single-video layout.
- Editor: presets, split slider, numeric fields, swap, OK disabled cases, per-fish table, backdrop
  fallback order (background image, video frame, tracks).
- Views page: the Panels section appears only for the single-video layout; button states.
- Engine and CLI: a panel session is read as the panel; the cache key changes with the panel.
- Docs: CHANGELOG, a decision row in `docs/dev/DECISIONS.md`, the user guide.

## Not in this cycle

Exporting cropped videos, per-view pixel-to-centimetre calibration (fusion and 3-D metrics need it),
automatic panel detection, more than two panels, rotated panels, and matching fish between the two
panels (that is G's matching table).
