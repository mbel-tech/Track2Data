"""Metrics that are intrinsically not independent of each other (decision D-054).

Some measures are built from the same raw quantity (the positions' covariance, the
speed trace, the heading changes, the time in a zone). They will therefore move
together in almost any data set, and a test on each of them is not a test on separate
findings. This is a property of how they are defined, not of a particular data set, so
it is listed here once and shown wherever metrics are selected.

Picking several metrics from one group is allowed. The warning says what that means:
do not count them as independent pieces of evidence, and do not correct for multiple
testing as if they were unrelated; choose one per group as the primary outcome and
report the others as descriptive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelatedGroup:
    """Metrics that share variance, and why."""

    title: str
    ids: tuple[str, ...]
    why: str


CORRELATED_GROUPS: tuple[CorrelatedGroup, ...] = (
    CorrelatedGroup(
        "Group size",
        ("GL-2", "GL-4", "GL-6", "GL-10"),
        "convex hull area, mean inter-individual distance, cohesion and RMS spread all "
        "measure how spread out the group is, and rise and fall together",
    ),
    CorrelatedGroup(
        "Group size (3-D)",
        ("GL-18", "GL-19"),
        "inter-individual distance and cohesion are both built from the same pairwise "
        "distances (cohesion is the inverse of the mean distance)",
    ),
    CorrelatedGroup(
        "Group shape and size",
        ("GL-4", "GL-10", "GL-15"),
        "elongation, RMS spread and hull area all come from the covariance of the "
        "animals' positions; a larger group is also usually a more elongated one",
    ),
    CorrelatedGroup(
        "Neighbour distance",
        ("GL-1", "GL-13", "GL-16"),
        "the nearest-neighbour distance is the k = 1 row of the k-NN distances, and "
        "the k-th distances rise together with the group's size and density",
    ),
    CorrelatedGroup(
        "Group order",
        ("GL-3", "GL-8", "GL-11"),
        "polarisation and rotational order are computed from the same headings, and "
        "the order-state classification is defined from them",
    ),
    CorrelatedGroup(
        "Group speed",
        ("GL-5", "GL-7"),
        "centroid speed and the NN-matched speed are both averages of the animals' "
        "speeds, so they share the speed variance",
    ),
    CorrelatedGroup(
        "Movement amount",
        ("IL-1", "IL-2", "IL-4", "IL-6", "IL-7"),
        "path length, speed, activity, acceleration and freezing all come from the "
        "same speed trace (path length is speed integrated over time; freezing is a run "
        "of low speed)",
    ),
    CorrelatedGroup(
        "Movement amount (3-D)",
        ("IL-16", "IL-17", "IL-18"),
        "3-D path length and speed come from the same trace; vertical speed is one "
        "component of the 3-D speed",
    ),
    CorrelatedGroup(
        "Turning",
        ("IL-5", "IL-8", "IL-11"),
        "tortuosity, turn rate and the turn-bias in IL-11 are all built from the "
        "frame-to-frame changes of heading",
    ),
    CorrelatedGroup(
        "Position in the arena",
        ("IL-3", "IL-14"),
        "distance from the centre and distance to the wall are two views of the same "
        "position (almost mirror images in a round arena)",
    ),
    CorrelatedGroup(
        "Time in a zone",
        ("Z-1", "Z-2", "Z-8"),
        "area-corrected occupancy and the zone preference index are derived from the "
        "time spent in the zone",
    ),
    CorrelatedGroup(
        "Zone entries",
        ("Z-3", "Z-4", "Z-5", "Z-7"),
        "visit counts, transitions, entry/exit events and the transition matrix count "
        "the same crossings of zone borders",
    ),
)

_ADVICE = (
    "They share variance by construction, so do not treat them as independent "
    "findings; choose one as the primary outcome and report the others as descriptive."
)


def correlated_selection_notes(selected_ids: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """One note per group that has two or more of its metrics in *selected_ids*."""
    selected = set(selected_ids)
    notes: list[str] = []
    for group in CORRELATED_GROUPS:
        chosen = [mid for mid in group.ids if mid in selected]
        if len(chosen) >= 2:
            notes.append(f"{group.title}: {', '.join(chosen)} -- {group.why}. {_ADVICE}")
    return notes
