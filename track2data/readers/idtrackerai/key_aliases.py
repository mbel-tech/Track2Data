"""
Known key renames across idtracker.ai versions.

When a future release renames an existing key, add the mapping here:
    NEW_NAME: OLD_NAME

The normaliser applies these before processing so the rest of the code
always sees the canonical (latest) name.
"""

from __future__ import annotations

# Maps canonical_name → list[old_names] in descending version order.
KEY_ALIASES: dict[str, list[str]] = {
    # No renames known yet; extend as idtracker.ai evolves.
}

#: The 17 keys that belong to the official idtracker.ai trajectory dict.
KNOWN_TRAJECTORY_KEYS: frozenset[str] = frozenset({
    "trajectories",
    "id_probabilities",
    "version",
    "height",
    "width",
    "video_paths",
    "frames_per_second",
    "body_length",
    "estimated_accuracy",
    "fraction_identified",
    "areas",
    "setup_points",
    "identities_labels",
    "identities_groups",
    "length_unit",
    "silhouette_score",
    "fragment_connectivity",
})

QUALITY_KEYS: frozenset[str] = frozenset({
    "estimated_accuracy",
    "fraction_identified",
    "silhouette_score",
    "fragment_connectivity",
})
