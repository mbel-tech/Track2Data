# Panel Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a 3-D project with the layout "One video, two panels" give each session a panel (a rectangle of the video), split one whole-frame session into a top and a side session, and edit panels in a dialog on the Views page.

**Architecture:** `SessionRef.panel` (a `PanelRect`) is applied by a pure function (`track2data/views/panels.py`) at the single place a session is read (`Engine.import_ref`) and in the store's background probe, so previews, runs and the CLI all see panel-relative coordinates. The store gets two mutators (split and set/clear). A dialog with a preview defines the rectangles; a "Panels" section on the Views page opens it.

**Tech Stack:** Python 3.11+, numpy, pydantic v2, PySide6, pytest / pytest-qt, ruff.

**Spec:** `docs/3d-movement/2026-10-09-panel-split-design.md` (also read the G and E specs it builds on).

## Global Constraints

- `PanelRect(x, y, width, height)`: floats in whole-frame video pixels; `x, y >= 0`, `width, height > 0`. `SessionRef.panel` defaults to `None`; manifests without it load unchanged.
- Panels exist only for `mode.layout == "single_video_two_panels"`. Otherwise the new store calls raise `ValueError(PANELS_ONLY_FOR_SINGLE_VIDEO)` with `PANELS_ONLY_FOR_SINGLE_VIDEO = "Panels apply to the 'One video, two panels' layout only"`.
- Coordinates become panel-relative: panel top-left is (0, 0) and the session's `video.width_px`/`height_px` become the panel size (rounded to int).
- Assignment: an animal is kept in a panel when at least 50% of its valid positions are inside it (`MIN_COVERAGE = 0.5`); the editor flags animals under 90% (`LOW_COVERAGE = 0.9`). Positions outside the rectangle become NaN. An animal with no valid position has coverage 0 and is left out.
- Identity-free sessions (`has_stable_identities` False): outside positions become NaN and slots with no position left are dropped; no 50% rule.
- A panel that lies outside the video, or is larger than it, raises `ValueError` (video size 0 means unknown: no check).
- Split ids are `<id>__top` and `<id>__side` (collision: numeric suffix via the store's `uniquify`). The pair created by a split has `auto=False`; the two sessions get `view_role` top / side.
- Changing or clearing a panel clears `fish_map` and `same_ids` of the pair that holds the session; the pair stays.
- The same folder with a different panel is a different session; the panel is part of the preprocessing cache key.
- Signals to long-lived store signals use bound methods; lambdas capturing `self` on a widget's own children use `ui/widgets/weak_slot.py`. A rebuild of a page never calls the store's write methods.
- No change to any 2-D behaviour or to sessions without a panel; the existing suite must pass. Run `ruff check` on touched files before each commit.

## Review Focus

- A panel outside or larger than the video, or a video of unknown size, gives a clear error and no crash (Tasks 2, 4, 7).
- An animal with no valid positions is left out with coverage 0, never a divide-by-zero (Task 2).
- The same folder with two different panels is not a duplicate, the same panel twice is (Task 4).
- A split whose ids collide gets a numeric suffix; splitting a session that already has a panel is rejected (Task 4).
- Clearing or changing a panel after matching clears the map and keeps the pair; facts refresh (Task 4).
- Splitting an identity-free session works and the result stays identity-free; a panel with no animals disables OK (Tasks 2, 7).
- Zones drawn earlier in whole-frame pixels do not silently become wrong: the backdrop is cropped, and the guide states that zones are still one set per project (Tasks 5, 9).

---

## File Structure

- Modify `track2data/core/models.py`: `PanelRect`, `SessionRef.panel`, `PANELS_ONLY_FOR_SINGLE_VIDEO`.
- Create `track2data/views/panels.py`: `apply_panel`, `panel_coverage`, `AnimalCoverage`, `preset_rects`, thresholds.
- Modify `track2data/api.py`: `Engine.import_ref` applies the panel; `_cache_key` includes it.
- Modify `ui/store/project_store.py`: duplicate check, probe, `split_session_into_panels`, `set_session_panel`.
- Modify `ui/widgets/zone_canvas.py`, `ui/zones_screen.py`: cropped backdrop.
- Create `ui/widgets/panel_preview.py`: preview widget with the backdrop fallback.
- Create `ui/dialogs/panel_dialog.py`: the editor.
- Modify `ui/views_screen.py`: the Panels section.
- Docs: `CHANGELOG.md`, `docs/dev/DECISIONS.md`, `docs/guide/USER_GUIDE.md`, the F spec and roadmap.
- Tests: `tests/test_core/test_models.py`, `tests/test_views/test_panels.py` (new), `tests/test_core/test_panel_engine.py` (new), `tests/test_ui/test_project_store.py`, `tests/test_ui/test_zone_canvas.py`, `tests/test_ui/test_panel_preview.py` (new), `tests/test_ui/test_panel_dialog.py` (new), `tests/test_ui/test_views_screen.py`.

---

### Task 1: Model

**Files:**
- Modify: `track2data/core/models.py` (`SessionRef` ~line 236, constants beside `VIEWS_3D_ONLY`)
- Test: `tests/test_core/test_models.py`

**Interfaces:**
- Produces: `PanelRect(BaseModel)` with `x: float = 0.0`, `y: float = 0.0`, `width: float`, `height: float` (validators: `x, y >= 0`, `width, height > 0`); `SessionRef.panel: PanelRect | None = None`; `PANELS_ONLY_FOR_SINGLE_VIDEO` (exact text in Global Constraints).

- [ ] **Step 1: Write failing tests**: `test_panel_defaults_to_none`; `test_panel_rect_rejects_non_positive_size` and `_negative_origin` (`ValidationError`); `test_session_ref_with_panel_roundtrips_json`; `test_old_manifest_without_panel_loads`; `test_project_hash_depends_on_panel`.
- [ ] **Step 2: Run** `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_core/test_models.py -k panel -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the models and the constant.
- [ ] **Step 4: Run** `pytest tests/test_core -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): panel rectangle on a session`.

### Task 2: Applying a panel (Qt-free)

**Files:**
- Create: `track2data/views/panels.py`
- Test: `tests/test_views/test_panels.py` (new)

**Interfaces:**
- Consumes: `PanelRect`, `Session` (`raw_xy` shape `(n_frames, n_animals, 2)`, `video`, `identities_labels`, `identities_colors`, `id_probabilities`, `body_length_px`, `setup_points`, `roi_list`, `has_stable_identities`, `n_animals`).
- Produces: `MIN_COVERAGE = 0.5`, `LOW_COVERAGE = 0.9`; `AnimalCoverage` (frozen dataclass: `index: int`, `label: str`, `share_inside: float`, `n_valid: int`); `panel_coverage(session: Session, rect: PanelRect) -> list[AnimalCoverage]` (labels from `fish_labels`); `apply_panel(session: Session, rect: PanelRect) -> Session`; `preset_rects(preset: Literal["left_right", "top_bottom"], frame_width: float, frame_height: float, split: float = 0.5, first_is_top: bool = True) -> tuple[PanelRect, PanelRect]` returning `(top_rect, side_rect)`.

- [ ] **Step 1: Write failing tests** (synthetic `Session` built like existing tests in `tests/test_readers`/`tests/conftest.py`): shift and size (panel `x=100,y=50,w=200,h=100` on a 400x200 video: a point at (150, 80) becomes (50, 30), `video.width_px == 200`, `height_px == 100`); animals with share `>= 0.5` kept, others dropped, with `identities_labels`, `identities_colors`, `id_probabilities`, `body_length_px` filtered together and `n_animals` updated; positions outside become NaN for kept animals; an animal with no valid positions has `share_inside == 0.0` and is dropped; identity-free session drops all-NaN slots and keeps partial ones; `setup_points` (`{"a": [x, y]}`) and `roi_list` vertices shift by the origin; a panel outside the video and one larger than it raise `ValueError`; unknown video size (0) skips the check; per-animal extras not listed (`bbox_table`, `bbox_summary`, `identities_groups`) are set to `None` after a panel; `preset_rects("left_right", 400, 200, 0.5, True) == (PanelRect(0,0,200,200), PanelRect(200,0,200,200))`, `first_is_top=False` swaps them, `"top_bottom"` splits the height, and `split=0.3` gives widths 120 / 280.
- [ ] **Step 2: Run** `pytest tests/test_views/test_panels.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** with `Session.model_copy(update=...)`; look at the `Session` model for every per-animal field and handle each (filter if indexed by animal and listed above, else `None`).
- [ ] **Step 4: Run** `pytest tests/test_views -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(views): apply a panel to a session`.

### Task 3: Engine reads panel sessions

**Files:**
- Modify: `track2data/api.py` (`import_ref` ~line 425-470, `_cache_key` ~507-540)
- Test: `tests/test_core/test_panel_engine.py` (new)

**Interfaces:**
- Consumes: `apply_panel`, `SessionRef.panel`.
- Produces: `Engine.import_ref(ref)` returns the panel version when `ref.panel` is set (both the saved-reader and the auto-detect branches, after the video override); `_cache_key` includes `"panel": ref.panel.model_dump(mode="json") if ref.panel else None` in the hashed payload, so the key changes with the panel.

- [ ] **Step 1: Write failing tests** (reuse the fixtures of `tests/test_api.py` for a readable session): `import_ref` without a panel is unchanged; with a panel returns the shifted session of panel size; a panel outside the video raises `ValueError` through `import_ref`; `_cache_key` differs between no panel, panel A and panel B, and is equal for the same panel twice; `preprocess_ref` on a panel ref returns panel-relative `xy`.
- [ ] **Step 2: Run** `pytest tests/test_core/test_panel_engine.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Apply the panel last in `import_ref`; keep `session_id` handling as is.
- [ ] **Step 4: Run** `pytest tests/test_core tests/test_api.py tests/test_cli -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): read a session through its panel`.

### Task 4: Store: split, set panel, probe

**Files:**
- Modify: `ui/store/project_store.py` (`_is_duplicate` ~100, `_on_identity_probe_finished` ~790, new methods near `update_view_pair`)
- Test: `tests/test_ui/test_project_store.py`

**Interfaces:**
- Consumes: Tasks 1-3; G's `ViewPair`, `view_pairs`, `_require_3d`-style helpers; `uniquify`; `_submit_probe(session_id, folder)`.
- Produces: `ProjectStore.split_session_into_panels(session_id: str, top_rect: PanelRect, side_rect: PanelRect) -> tuple[str, str]` (returns the new top and side ids; replaces the session at its list position; raises `ValueError` for an unknown session, a session that already has a panel, or the wrong layout); `ProjectStore.set_session_panel(session_id: str, rect: PanelRect | None) -> None`. `_is_duplicate` also compares `panel`. The probe result is passed through `apply_panel` for a ref with a panel (a `ValueError` is logged with `append_log` and the unpanelled facts are kept).

- [ ] **Step 1: Write failing tests** (3-D project, layout single_video_two_panels): `split_session_into_panels` creates `s__top` / `s__side` with the same folder, reader and options, `panel` set, `view_role` top / side, a `ViewPair(top, side, auto=False)`, in the original's list position, and returns the ids; a taken id gets a numeric suffix; a second split of the same (already replaced) id raises; splitting a session that already has a panel raises; wrong layout or 2-D raises `ValueError` with the exact message; `set_session_panel` sets and clears, clears `fish_map` and `same_ids` of its pair but keeps the pair, re-probes (assert `_submit_probe` called, monkeypatched), and emits `sessionsChanged` and `viewsChanged`; `_is_duplicate`: same folder, different panel is not a duplicate, same panel is; a probe result for a ref with a panel yields facts of the panel size (monkeypatch the probe result with a synthetic session).
- [ ] **Step 2: Run** `pytest tests/test_ui/test_project_store.py -k "panel or split" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** following the `update_view_pair` / `apply_regex_pairing` patterns (single `model_copy`, emit once).
- [ ] **Step 4: Run** `pytest tests/test_ui/test_project_store.py tests/test_app_smoke.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(store): split a session into panels and set a session's panel`.

### Task 5: Cropped zones backdrop

**Files:**
- Modify: `ui/widgets/zone_canvas.py` (`load_session` ~256), `ui/zones_screen.py` (`_refresh_canvas` ~445)
- Test: `tests/test_ui/test_zone_canvas.py`

**Interfaces:**
- Consumes: `PanelRect`, `SessionRef.panel` from the manifest.
- Produces: `ZoneCanvas.load_session(background_image_path, setup_points, frame_size=None, crop: PanelRect | None = None)`: with `crop` the backdrop is `QImage.copy(x, y, w, h)` and the scene is the crop size; `ZonesScreen._refresh_canvas` passes the selected session's `panel`.

- [ ] **Step 1: Write failing tests**: a 400x200 test image with `crop=PanelRect(x=100,y=50,width=200,height=100)` gives a scene rect of 200x100 (assert `canvas.sceneRect()`); no crop leaves the existing behaviour; a crop beyond the image is clamped by Qt and does not raise; the zones screen passes the session's panel (monkeypatch the canvas and assert the call).
- [ ] **Step 2: Run** `pytest tests/test_ui/test_zone_canvas.py tests/test_ui/test_zones_screen.py -k "crop or panel" -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): crop the zones backdrop to a session's panel`.

### Task 6: Panel preview widget

**Files:**
- Create: `ui/widgets/panel_preview.py`
- Test: `tests/test_ui/test_panel_preview.py` (new)

**Interfaces:**
- Consumes: `track2data/readers/video_meta.py::extract_frame(video_path: Path, frame_index: int = 0) -> bytes | None` (image bytes or None).
- Produces: `PanelPreview(QGraphicsView)` with `set_source(frame_size: tuple[float, float], background_path: Path | None, video_path: Path | None, tracks: np.ndarray | None) -> None` choosing the backdrop in this order: the background image if it exists, else the first video frame (`extract_frame`, only if the video exists), else the tracks as points (`tracks` shape `(n_frames, n_animals, 2)`); `backdrop_kind -> Literal["image", "video", "tracks", "none"]`; `set_rects(top: PanelRect | None, side: PanelRect | None)` draws two labelled rectangles ("Top view", "Side view") over the scene; `rect_item_count -> int`.

- [ ] **Step 1: Write failing tests**: with a background image path `backdrop_kind == "image"`; without it but with a video path whose `extract_frame` is monkeypatched to return PNG bytes, `"video"`; with neither and tracks, `"tracks"` and the scene holds one item per plotted point group; with nothing `"none"` and the scene is the frame size; `set_rects` draws 2 rectangles, `set_rects(None, None)` removes them; an `extract_frame` that returns `None` or raises falls through to tracks.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_panel_preview.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): panel preview with backdrop fallback`.

### Task 7: Panel editor dialog

**Files:**
- Create: `ui/dialogs/panel_dialog.py`
- Test: `tests/test_ui/test_panel_dialog.py` (new)

**Interfaces:**
- Consumes: `Session` (the unpanelled session), `preset_rects`, `panel_coverage`, `AnimalCoverage`, `LOW_COVERAGE`, `MIN_COVERAGE`, `PanelPreview`.
- Produces: `PanelDialog(session: Session, mode: Literal["split", "single"], background_path: Path | None = None, parent: QWidget | None = None)`; attributes `_preset_combo` (items "Left | Right", "Top | Bottom", "Custom"), `_split_slider` (5..95, default 50), `_first_view_combo` (items "Top view", "Side view": what the left / top panel is; split mode only), spin boxes `_top_x, _top_y, _top_w, _top_h` and `_side_x, _side_y, _side_w, _side_h` (in single mode only the top set is used, labelled "Panel"), `_coverage_table` (columns "Fish", "Panel", "Inside", "Flag"; split mode only), `_preview` (`PanelPreview`), `_ok_button`; methods `result_rects() -> tuple[PanelRect, PanelRect]` (split) and `result_rect() -> PanelRect` (single).
- Behaviour: choosing a preset or moving the slider sets the spin boxes through `preset_rects`; editing a spin box switches the preset to "Custom"; the table is recomputed from the rectangles: each fish's panel is the one with the higher share, "Inside" is the share as a percentage, "Flag" is "low" under `LOW_COVERAGE` and "left out" under `MIN_COVERAGE`, "no data" when `n_valid == 0`; `_ok_button` is disabled when a rectangle is invalid (outside the frame) or when a panel keeps no animal (split mode) / the panel keeps no animal (single mode).

- [ ] **Step 1: Write failing tests** (synthetic session, two clusters of animals left and right of x=200 on a 400x200 frame): the default state is "Left | Right" at 50% with the exact rectangles; the slider at 30 changes the widths to 120 / 280; editing a spin box sets the preset to "Custom"; the first-view combo swapped gives the side rectangle on the left; the coverage table lists every fish with its panel and "Inside" text, flags a fish at 80% as "low" and one at 40% as "left out", and "no data" for an all-NaN fish; `_ok_button` is disabled when a panel is outside the frame and when one panel keeps no animal, enabled otherwise; single mode shows one rectangle and no table; `result_rects()` returns the rectangles shown; a rebuild never raises with an empty session (zero animals).
- [ ] **Step 2: Run** `pytest tests/test_ui/test_panel_dialog.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** (spin boxes with `blockSignals` while a preset fills them; connect child-widget signals with `weak_slot`).
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): panel editor dialog`.

### Task 8: Panels section on the Views page

**Files:**
- Modify: `ui/views_screen.py`
- Test: `tests/test_ui/test_views_screen.py`

**Interfaces:**
- Consumes: `PanelDialog`, `store.split_session_into_panels`, `store.set_session_panel`, `Engine.import_ref` (to load the unpanelled session for the dialog in a background task: `store.tasks.submit(...)`, result on `store.taskFinished`, stale results ignored like the matching panel).
- Produces on `ViewsScreen`: `_panels_box` (visible only when `mode.layout == "single_video_two_panels"`), `_panels_table` (columns "Session", "Panel": "whole video" or "x, y, w × h"), `_split_btn` ("Split into panels…"), `_set_panel_btn` ("Set panel…"), `_clear_panel_btn` ("Clear panel"); button states: split enabled when the selected session has no panel, set enabled for any selected session, clear enabled when it has a panel. Dialog result applies through the store; a rebuild never writes.

- [ ] **Step 1: Write failing tests** (monkeypatch `PanelDialog` with a stub that returns fixed rectangles, and the session loader): the box is hidden for layout "two_videos" and 2-D, shown for "single_video_two_panels"; the table lists sessions with their panel text; selecting a session sets the button states; accepting the split dialog calls `split_session_into_panels` once with the dialog's rectangles and the table shows the two new sessions; accepting "Set panel" calls `set_session_panel` with the rectangle; "Clear panel" calls `set_session_panel(id, None)`; cancelling a dialog writes nothing; a failed session load shows the error in a status label and does not raise; a rebuild does not call the store's write methods.
- [ ] **Step 2: Run** `pytest tests/test_ui/test_views_screen.py -k panel -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep `views_screen.py` readable: if the file would pass ~900 lines, move the Panels section into `ui/widgets/panels_section.py` and import it.
- [ ] **Step 4: Run** `pytest tests/test_ui -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): Panels section on the Views page`.

### Task 9: Docs and full check

**Files:**
- Modify: `CHANGELOG.md` (an `### Added` entry under Unreleased), `docs/dev/DECISIONS.md` (new decision after the last one, same format), `docs/guide/USER_GUIDE.md` (a `###` subsection "Panels (one video, two views)" inside the "2. Sessions" chapter next to the Views subsection; no new numbered chapter, no images; state the limitation that zones are still one set per project), `docs/3d-movement/2026-10-09-panel-split-design.md` (status "implemented"; record any design change made during the build), `docs/3d-movement/2026-10-08-3d-roadmap.md` (F row done).
- Test: `tests/test_docs/test_guide.py`

- [ ] **Step 1:** Write the text from the spec; verify each fact in the code first and document only what exists.
- [ ] **Step 2: Run** `pytest tests/test_docs -q`. Expected: PASS.
- [ ] **Step 3: Run** `QT_QPA_PLATFORM=offscreen python -m pytest -q -x` and `ruff check .`. Expected: all pass; report any segfault or abort at exit verbatim.
- [ ] **Step 4: Commit** `docs: describe panel split`.
