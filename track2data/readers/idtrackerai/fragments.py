"""
Loader for idtracker.ai's preprocessing/list_of_fragments.json.

A Fragment is idtracker.ai's own unit of continuous identity: a maximal run
of frames believed to belong to the same animal (or the same crossing).
Fragment boundaries are the *only* frames where an identity swap is
physically possible -- everything preprocess/identity_switch.py currently
reasons about frame-by-frame, this data answers directly and authoritatively.

The on-disk schema is undocumented -- fragment_idtrackerai.md's
__getstate__ entry is four words ("Helper for pickle."), no field list.
Everything below is derived empirically against a 70-session real corpus.
Confirmed top-level schema, identical across all 70 sessions:

    n_animals: int
    fragments: list[dict]           -- see FRAGMENT_ALWAYS_PRESENT below
    id_images_file_paths: list[str]
    id_to_exclusive_roi: list[int]  -- -1 per identity when exclusive_rois=False
    accumulable_individual_fragments: list[int]      -- fragment identifiers
    not_accumulable_individual_fragments: list[int]  -- fragment identifiers

Per-fragment keys are SPARSE (verified: only 10 of 27 observed keys are
present on every fragment). Any consumer of this module's output must use
``.get()`` throughout, never direct indexing -- see FRAGMENT_ALWAYS_PRESENT
for the keys that are safe to assume.

Defensive parsing rules (each grounded in a real observation, not caution
theatre):
  1. Optional keys may be absent (e.g. 'identity' missing on ~34% of
     fragments in the sampled session) -- always .get(), never fragment[k].
  2. Unknown keys exist and aren't in any of the four official fragment
     docs (observed: 'zero_identity_assigned_by_P2', 'P1_below_random') --
     preserved verbatim rather than dropped, same policy as
     normaliser.py's raw_attrs for the trajectory dict.
  3. 'certainty' is NOT a probability -- observed negative
     (-0.0069). Never assert it's in [0, 1].
  4. 'identity' is 1-based (fragment_idtrackerai.md: "From 1 to n_animals"),
     matching Session.identities_labels' 1-based-looking default naming,
     but NOT api.py's 0-based individual_id -- an off-by-one trap at any
     join between this data and the trajectory-derived tables.
     'temporary_id' is 0-based, unlike 'identity'.
  5. 'end_frame' is exclusive: fragment identifier 0 has start_frame=0,
     end_frame=7 with exactly 7 images.
  6. 'episodes' format is undocumented (observed [[0], [7]] for a 7-image
     fragment) -- do not depend on its structure.
  7. 'coexisting_individual_fragments' is never serialised -- the one
     exclusion the docs state explicitly (ListOfFragments.md: "which is
     not saved in the JSON file"). Reconstruct from start_frame/end_frame
     overlap if ever needed; not attempted here.
  8. Centroids are not on disk, only start_position/end_position.
  9. Missing preprocessing/ folder (or missing list_of_fragments.json
     specifically) degrades to None, exactly like every other custom
     artefact in this reader -- fragment data is a bonus, never a
     requirement for a session to import.

Do not build on: number_of_crossing_blobs / number_of_individual_blobs
(deprecated since 6.0.0 in favour of ListOfFragments.get_stats(), which
this module does not attempt to replicate) or single_global_fragment() /
no_global_fragment() (deprecated in favour of len(...) == 1 / == 0).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

#: Fragment keys observed present on every fragment in the real corpus.
#: Everything else is optional and must be accessed with .get().
FRAGMENT_ALWAYS_PRESENT: frozenset[str] = frozenset({
    "identifier",
    "start_frame",
    "end_frame",
    "images",
    "episodes",
    "is_an_individual",
    "frame_by_frame_velocity",
    "start_position",
    "end_position",
    "P1_vector",
})


def load_fragments(folder: Path) -> dict[str, Any] | None:
    """
    Load preprocessing/list_of_fragments.json.

    Returns None when the file is absent or unparseable -- opportunistic,
    like every other custom-artefact loader in this reader. Never raises.

    Returns
    -------
    dict with (at least, when present in the source file):
        n_animals: int | None
        fragments: list[dict]  -- verbatim parsed fragment dicts; see the
                                   module docstring for which keys are safe
                                   to assume present
        id_to_exclusive_roi: list[int] | None
        accumulable_individual_fragments: list[int] | None
        not_accumulable_individual_fragments: list[int] | None
    """
    path = Path(folder) / "preprocessing" / "list_of_fragments.json"
    if not path.exists() or path.name.startswith("._"):
        return None

    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        logger.warning("Could not parse list_of_fragments.json at %s: %s", path, exc)
        return None

    if not isinstance(raw, dict) or "fragments" not in raw:
        logger.warning(
            "list_of_fragments.json at %s doesn't have the expected shape "
            "(missing top-level 'fragments' key).",
            path,
        )
        return None

    fragments = raw.get("fragments")
    if not isinstance(fragments, list):
        return None

    return {
        "n_animals": raw.get("n_animals"),
        "fragments": fragments,
        "id_to_exclusive_roi": raw.get("id_to_exclusive_roi"),
        "accumulable_individual_fragments": raw.get("accumulable_individual_fragments"),
        "not_accumulable_individual_fragments": raw.get(
            "not_accumulable_individual_fragments"
        ),
    }


def individual_fragments(fragments_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only the fragments where is_an_individual is True.

    A crossing fragment has is_an_individual=False by construction
    (fragment_idtrackerai.md: "belong to the same animal or to the same
    crossing"); treat a missing key as NOT individual (conservative --
    an ambiguous fragment should not be trusted for identity-switch
    boundaries or body-length sampling).
    """
    return [f for f in fragments_data["fragments"] if f.get("is_an_individual") is True]


def fragment_swap_boundaries(fragments_data: dict[str, Any]) -> set[int]:
    """
    Return the set of frame numbers where an identity swap is physically
    possible: the end_frame of every individual fragment that is not
    identity_is_fixed.

    This is the authoritative, exact replacement for
    preprocess/identity_switch.py's current whole-recording geometric
    search -- see the format-alignment plan's Fase 6d for the full
    fragment-aware corrector this feeds into.
    """
    boundaries: set[int] = set()
    for frag in individual_fragments(fragments_data):
        if frag.get("identity_is_fixed") is True:
            continue
        end_frame = frag.get("end_frame")
        if isinstance(end_frame, int):
            boundaries.add(end_frame)
    return boundaries


def crossing_frame_mask(fragments_data: dict[str, Any], n_frames: int) -> np.ndarray:
    """
    Return a session-wide ``(n_frames,)`` bool array, True for every frame
    covered by at least one crossing fragment (``is_an_individual is
    False``).

    This is session-wide, not per-animal: a crossing fragment merges two or
    more animals into one blob, so it cannot be attributed to a single
    trajectory column without the blob layer (preprocessing/list_of_blobs.pickle,
    not read by this reader). Even at this coarser granularity it is a
    useful gap classifier -- verified on a real session, 65.1% of frames
    with at least one animal's position missing coincide with an active
    crossing fragment, matching the correlation measured independently at
    the (unread) blob level.

    Used by preprocess/gap_fill.py to distinguish "occluded by a
    conspecific" (this animal is present, its path passes through the
    crossing) from "not detected at all" (no crossing fragment active,
    interpolation is on weaker footing) when reporting which kind of gap
    was filled.
    """
    mask = np.zeros(n_frames, dtype=bool)
    for frag in fragments_data.get("fragments", []):
        if frag.get("is_an_individual") is not False:
            continue
        start, end = frag.get("start_frame"), frag.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        mask[max(0, start):min(end, n_frames)] = True
    return mask
