# ID correspondence between views (sub-project G)

**Status:** implemented
**Part of:** [the 3-D roadmap](2026-10-08-3d-roadmap.md). Builds on [the mode switch](2026-10-09-mode-switch-design.md) (sub-project E).

## Why

A 3-D project has two tracked views of the same fish. Fusion (D) cannot combine them until it
knows which fish in the top view is which fish in the side view, and nothing in the project says
which session is the top view and which is the side view, or which top session goes with which
side session. G records all three: the role of each session, the pairs, and the fish mapping.

## Sub-project order

| | Sub-project | Scope |
|---|---|---|
| E | Mode switch | Done |
| F | Panel split (layout i) | One video, two panels, two logical sessions. Creates the `ViewPair` for the two panels itself |
| **G** | **ID correspondence** (this spec) | View roles, pairing sessions (by regex or by hand), fish mapping, the Views step |
| D | Fusion | Reads `manifest.view_pairs` and each `fish_map` |
| B | 3-D metrics | |

G is built and tested against any two sessions, so it does not wait for F.

## Decisions

- **G owns the pair, not only the mapping.** A fish mapping hangs off a pair of sessions, so the
  pair record and the UI to create it belong here.
- **Roles are per session.** The user says which sessions are the top view and which are the side
  view.
- **Pairing by regex.** Two regexes, one for top sessions and one for side sessions, each with a
  `key` group. Sessions with an equal `key` become a pair. The regex runs on the session id. The
  user can always correct a pairing by hand.
- **"Same IDs" tick per pair.** If ticked, fish with the same label are the same fish. If not, the
  user matches them by hand.
- **Manual matching is visual.** A table with one dropdown per top-view fish, and two track plots
  with the selected fish highlighted.
- **Stable identities are required.** A pair with an identity-free session can exist but is flagged
  "cannot match fish: this session has no stable identities". Matching such fish by geometry belongs
  to D, if ever.
- **`mode.id_map` is removed.** It was reserved, unused, and a single project-wide dictionary cannot
  describe many pairs. Manifests that contain it still load (extra keys are ignored).
- **The step never blocks Next.** Computing is blocked in 3-D anyway. D will start requiring
  complete pairs.

## Design

1. **Data model** (`track2data/core/models.py`).
   - `SessionRef.view_role: Literal["top", "side"] | None = None`.
   - `ViewPair(top_session_id: str, side_session_id: str, same_ids: bool = False,
     fish_map: dict[str, str] = {}, auto: bool = False)`. `fish_map` maps a top-view label to a
     side-view label; a fish not in it is unmatched. `auto` marks pairs made by the pattern. A
     session belongs to at most one pair.
   - `PairingPatterns(top_regex: str = "", side_regex: str = "")`, stored as
     `ProjectMode.pairing` and edited through `modeChanged`.
   - `ProjectManifest.view_pairs: list[ViewPair] = []`.
   - Labels are `Session.identities_labels`, falling back to the 0-based index as text (the same
     fallback as `MappingRule.individual_match`).
   - Everything is hashed into `project_hash` through `model_dump`.
2. **Pure logic** (`track2data/views/pairing.py`, no Qt).
   - `pair_by_regex(sessions, top_regex, side_regex) -> PairingResult` with `pairs`, `unpaired_top`,
     `unpaired_side`, `ambiguous_keys` and `errors` (bad regex, missing `key` group). A key shared by
     more than one session on one side is reported as ambiguous and not paired.
   - `identity_map(top_labels, side_labels) -> tuple[dict[str, str], list[str]]` returns the map for
     the "same IDs" tick and the labels that differ.
   - `validate_fish_map(pair, top_labels, side_labels, identity_free) -> list[str]` reports
     duplicate side targets, unknown labels, a difference in fish counts, and the identity-free
     message above.
3. **Store** (`ui/store/project_store.py`). `update_view_role(session_id, role)`,
   `update_pairing(patterns)`, `apply_regex_pairing()` (replaces the auto-created pairs, keeps
   hand-made ones), `update_view_pair(pair)`, `remove_view_pair(top_id, side_id)`, and a
   `viewsChanged` signal wired into `_on_manifest_changed`. Removing a session removes its pairs
   and clears nothing else. All of this is for 3-D projects only; the calls are rejected in 2-D.
4. **The Views step** (`ui/views_screen.py`, 3-D only: page 10, belongs to the Sessions sidebar row, reached by Next/Back between Sessions and Calibration in 3-D projects).
   - *Roles and patterns.* A role selector per session and the two regex fields. Each field has an
     ⓘ popover in plain language (what `key` is, three worked examples such as `trial01_top`, and
     a live "this catches N sessions" line), plus a preview that lists unpaired sessions.
   - *Pairs.* One row per pair with the "same IDs" tick, a status (matched, needs matching,
     identity-free) and a manual re-pair option.
   - *Matching.* A table with one row per top-view fish and a dropdown for the side-view fish or
     "no match"; beside it two `TrajectoryView` plots with the selected fish highlighted.
5. **Navigation.** The sidebar and page lists are static today. Views is a new page (page 10, belongs to the
   Sessions sidebar row), shown only in 3-D projects; in 2-D it is hidden and skipped by Next and Back. `screen_flow(mode)` returns
   which variant of the Sessions-to-Calibration route to show. `stage_status` marks Views `empty`
   until every session has a role, `warning` while any pair needs matching or is identity-free,
   and `valid` when every pair has a complete map. It never returns `blocked`.
6. **Hand-off to D.** `manifest.view_pairs[i].fish_map` is the mapping between the two views.
   F creates the `ViewPair` for the two panels of one video.

## Testing

- Model: defaults, round trip, old manifest without the new fields, old manifest with `id_map`,
  hash changes with pairs.
- `pair_by_regex`: matching keys, unpaired on each side, ambiguous keys, bad regex, missing `key`.
- `identity_map` and `validate_fish_map`: equal labels, differing labels, duplicate targets,
  unknown labels, count mismatch, identity-free sessions.
- Store: role and pair updates, removing a session removes its pairs, rejection in 2-D,
  `viewsChanged`, dirty marking.
- Views step: popover text, live match count, role selector, "same IDs" tick filling the map,
  manual matching, status; navigation shows the step in 3-D and skips it in 2-D.
- Docs: CHANGELOG, a new decision row in `docs/dev/DECISIONS.md`, the user guide.

## Not in this cycle

Creating the pair for layout (i) (F), fusion (D), 3-D metrics (B), matching identity-free fish by
geometry, and an automatic guess of the fish mapping when labels differ.
