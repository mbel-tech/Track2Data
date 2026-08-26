"""Zone metrics (Z-1 Time-in-zone, Z-3 Zone-visit-count)."""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pandas as pd

from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter
from track2data.metrics.references import (
    BAKEMAN_GOTTMAN_1997,
    BOURIN_HASCOET_2003,
    HALL_1934,
    JACOBS_1974,
    KRAUSE_RUXTON_2002,
    MARTIN_BATESON_2007,
    SIBLY_1990,
    WALSH_CUMMINS_1976,
)

# ── helpers ────────────────────────────────────────────────────────────────────

_EMPTY_ZONE_VALUE = ""


def _collect_zone_arrays(psess: object) -> list[np.ndarray]:
    """Return non-None zone arrays from a PreprocessedSession."""
    arrays: list[np.ndarray] = []
    main = getattr(psess, "main_zone", None)
    sec = getattr(psess, "sec_zone", None)
    if main is not None:
        arrays.append(main)
    if sec is not None:
        arrays.append(sec)
    return arrays


def _run_lengths(mask: np.ndarray) -> list[int]:
    """Run-length encode consecutive True runs in a 1-D boolean mask --
    used to debounce boundary flicker via a minimum-run-length cutoff
    (Z-3's min_visit_frames, Z-4/Z-6's min_dwell_frames)."""
    lengths: list[int] = []
    current = 0
    for val in mask:
        if val:
            current += 1
        else:
            if current > 0:
                lengths.append(current)
            current = 0
    if current > 0:
        lengths.append(current)
    return lengths


def _true_run_spans(mask: np.ndarray, min_length: int) -> list[tuple[int, int]]:
    """Return (start, end) index pairs -- end exclusive -- for each run
    of consecutive True values in mask at least min_length long. Used
    by Z-5 to debounce a brief in-zone flicker away entirely (no
    enter/exit events at all) rather than merely shortening it."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, val in enumerate(mask):
        if val and start is None:
            start = i
        elif not val and start is not None:
            if i - start >= min_length:
                spans.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_length:
        spans.append((start, len(mask)))
    return spans


def _debounced_zone_sequence(col: np.ndarray, min_dwell_frames: int) -> list[str]:
    """Run-length encode a per-frame zone-name column, drop any run
    shorter than min_dwell_frames, then collapse whatever consecutive
    duplicate zone names that leaves behind into one entry -- e.g.
    A(9), B(2), A(9) with min_dwell_frames=3 drops the 2-frame B
    flicker and merges the two A runs either side of it into a single
    "A", so it contributes zero transitions instead of two.

    Runs of the empty-zone sentinel are never dropped, however short.
    Dropping one splices the zones on either side of it into adjacent
    entries, so a brief tracking dropout between two non-adjacent zones
    would be reported as a direct crossing -- meaning a higher
    min_dwell_frames could *raise* the transition count it exists to
    lower. An empty run is a gap in knowledge, not a flicker to smooth
    over, so it stays and keeps the two stays apart.
    """
    runs: list[tuple[str, int]] = []
    for val in col:
        name = str(val)
        if runs and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + 1)
        else:
            runs.append((name, 1))

    kept = [
        name
        for name, length in runs
        if length >= min_dwell_frames or name == _EMPTY_ZONE_VALUE
    ]

    sequence: list[str] = []
    for name in kept:
        if not sequence or sequence[-1] != name:
            sequence.append(name)
    return sequence


# ── Z-1: Time in each zone ────────────────────────────────────────────────────


class TimeInZone(Metric):
    """Z-1 — Fraction and duration each animal spends in every named zone."""

    id = "Z-1"
    name = "time_in_zone"
    label = "Time in zone"
    level = "zone"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "time_s",
        "time_pct",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Duration and proportion of the session that each animal spends "
            "inside each named zone."
        ),
        formula_plain=(
            "time_s[k, z] = count(zone[t, k] == z) / fps; "
            "time_pct[k, z] = time_s[k, z] / (n_frames / fps)"
        ),
        inputs=["PreprocessedSession.main_zone", "PreprocessedSession.sec_zone"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings."],
        warnings=["Empty-string values are treated as 'not in any zone'."],
        primary_reference=WALSH_CUMMINS_1976,
        supporting_references=[HALL_1934],
    )

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute time-in-zone for every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Unused; reserved for future configuration.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) with columns:
            session_id, zone_name, individual_id, time_s, time_pct.
            Empty DataFrame when no zone arrays are present.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_frames: int = session.n_frames  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]
        fps: float = session.fps  # type: ignore[attr-defined]
        total_duration_s = n_frames / fps

        # Accumulate frame counts: {(zone_name, animal_idx): frame_count}
        counts: dict[tuple[str, int], int] = {}
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                for zone_name in np.unique(col):
                    if zone_name == _EMPTY_ZONE_VALUE:
                        continue
                    n = int(np.sum(col == zone_name))
                    key = (zone_name, k)
                    counts[key] = counts.get(key, 0) + n

        if not counts:
            return pd.DataFrame(columns=empty_cols)

        rows = []
        for (zone_name, animal_idx), frame_count in counts.items():
            time_s = frame_count / fps
            time_pct = time_s / total_duration_s
            rows.append(
                {
                    "session_id": session_id,
                    "zone_name": zone_name,
                    "individual_id": animal_idx,
                    "time_s": time_s,
                    "time_pct": time_pct,
                }
            )

        return pd.DataFrame(rows, columns=self.output_columns)


# ── Z-3: Zone visit count ─────────────────────────────────────────────────────


class ZoneVisitCount(Metric):
    """Z-3 — Number of discrete visits each animal makes to each zone."""

    id = "Z-3"
    name = "zone_visit_count"
    label = "Zone visit count"
    level = "zone"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "visit_count",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Number of discrete visits (entry events) each animal makes to each "
            "named zone during the session."
        ),
        formula_plain=(
            "visit_count[k, z] = number of rising-edge transitions "
            "(False→True) in the boolean mask [zone[t, k] == z]"
        ),
        inputs=["PreprocessedSession.main_zone", "PreprocessedSession.sec_zone"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings."],
        warnings=["A single continuous stay counts as one visit regardless of duration."],
        primary_reference=MARTIN_BATESON_2007,
        supporting_references=[BAKEMAN_GOTTMAN_1997],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_visit_frames",
            label="Minimum visit length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help=(
                "Debounces boundary flicker: a run of consecutive frames inside "
                "a zone shorter than this doesn't count as a visit."
            ),
        ),
    ]

    def compute(
        self,
        session: object,
        cfg: dict | None = None,
    ) -> pd.DataFrame:
        """Count zone visits (runs of consecutive in-zone frames) for
        every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Optional dict. ``cfg['min_visit_frames']`` (default 1) sets the
            minimum run length that counts as a visit -- shorter runs are
            debounced away rather than counted.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) with columns:
            session_id, zone_name, individual_id, visit_count.
            Empty DataFrame when no zone arrays are present.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        min_visit_frames = 1
        if cfg is not None and "min_visit_frames" in cfg:
            min_visit_frames = int(cfg["min_visit_frames"])

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        # Accumulate visit counts per (zone, animal) across all zone arrays.
        # We sum qualifying-run counts; if the same zone appears in both main
        # and sec arrays we still count entries independently.
        visit_counts: dict[tuple[str, int], int] = {}
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                zone_names = [z for z in np.unique(col) if z != _EMPTY_ZONE_VALUE]
                for zone_name in zone_names:
                    in_zone: np.ndarray = col == zone_name  # bool (n_frames,)
                    visits = sum(
                        1 for length in _run_lengths(in_zone) if length >= min_visit_frames
                    )
                    key = (zone_name, k)
                    visit_counts[key] = visit_counts.get(key, 0) + visits

        if not visit_counts:
            return pd.DataFrame(columns=empty_cols)

        rows = [
            {
                "session_id": session_id,
                "zone_name": zone_name,
                "individual_id": animal_idx,
                "visit_count": count,
            }
            for (zone_name, animal_idx), count in visit_counts.items()
        ]
        return pd.DataFrame(rows, columns=self.output_columns)


# ── Z-2: AreaCorrectedOccupancy ───────────────────────────────────────────────


class AreaCorrectedOccupancy(Metric):
    """Z-2 — Area-corrected occupancy = time_pct / (roi_area / total_arena_area)."""

    id = "Z-2"
    name = "area_corrected_occupancy"
    label = "Area-Corrected Occupancy"
    level = "zone"
    priority = "primary"
    requires_identity = False
    # Z-8 (Jacobs' D) is a bias-corrected, bounded [-1, +1] form of the
    # same use-vs-availability idea; this raw ratio stays unbounded and
    # asymmetric, so it can't be meaningfully averaged across animals or
    # compared across arena designs. Z-2 keeps computing exactly what it
    # always has -- no existing project's numbers move -- but the tool
    # now says which statistic is the better one. See METRICS_SPEC.md.
    superseded_by: ClassVar[str | None] = "Z-8"
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "area_corrected_occupancy",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Area-corrected occupancy normalises the time fraction spent in a zone "
            "by the fractional area of that zone relative to the total arena area. "
            "A value of 1.0 means the animal occupies the zone in proportion to its area; "
            ">1 means over-representation."
        ),
        formula_plain=(
            "area_corrected_occupancy = time_pct / (roi_area / total_arena_area); "
            "requires cfg['roi_areas'] (dict of zone_name → area) and "
            "cfg['total_arena_area']"
        ),
        inputs=["PreprocessedSession.main_zone", "PreprocessedSession.sec_zone"],
        assumptions=[
            "Zone arrays are pre-assigned object arrays of zone-name strings",
            "roi_areas and total_arena_area must be provided in cfg",
        ],
        warnings=[
            "Returns empty DataFrame when cfg is missing or incomplete",
            "This ratio is unbounded and asymmetric (over- and "
            "under-representation are not on comparable scales), so it "
            "cannot be meaningfully averaged across animals or compared "
            "across arena designs -- see Z-8 (Jacobs' D) for a bounded "
            "[-1, +1] alternative built on the same zone-area data",
        ],
        citation=(
            "Area-normalised occupancy (observed time in a zone relative to "
            "that zone's share of the arena), the standard correction for "
            "comparing unequal-area regions of interest. No single "
            "originating work"
        ),
        supporting_references=[JACOBS_1974, KRAUSE_RUXTON_2002],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="roi_areas", label="Zone areas", kind="float", derived=True,
            help="Derived per session from the project's own zone geometry.",
        ),
        MetricParameter(
            name="total_arena_area", label="Total arena area", kind="float",
            derived=True, unit="px²",
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute area-corrected occupancy for every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Must contain ``roi_areas`` (dict zone_name → float) and
            ``total_arena_area`` (float).  If absent, returns empty DataFrame.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) with area-corrected occupancy.
            Empty DataFrame (with correct columns) when cfg is missing.
        """
        empty_cols = self.output_columns
        empty_df = pd.DataFrame(columns=empty_cols)

        # Require both zone arrays and cfg with area info
        zone_arrays = _collect_zone_arrays(session)
        if not zone_arrays:
            return empty_df

        if cfg is None:
            return empty_df

        roi_areas: dict[str, float] | None = cfg.get("roi_areas")
        total_arena_area: float | None = cfg.get("total_arena_area")

        # `<= 0`, not `== 0`. roi_areas holds SIGNED areas ("-" exclusion
        # polygons subtract), so a zone set whose exclusions outweigh
        # their parent yields a negative total -- which sailed past an
        # equality check and exported negative occupancy fractions that
        # look like real measurements.
        if roi_areas is None or total_arena_area is None or total_arena_area <= 0:
            return empty_df

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_frames: int = session.n_frames  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]
        fps: float = session.fps  # type: ignore[attr-defined]
        total_duration_s = n_frames / fps

        # Compute time_pct per (zone, animal) — same logic as Z-1
        counts: dict[tuple[str, int], int] = {}
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                for zone_name in np.unique(col):
                    if zone_name == _EMPTY_ZONE_VALUE:
                        continue
                    n = int(np.sum(col == zone_name))
                    key = (zone_name, k)
                    counts[key] = counts.get(key, 0) + n

        if not counts:
            return empty_df

        rows = []
        for (zone_name, animal_idx), frame_count in counts.items():
            roi_area = roi_areas.get(zone_name)
            if roi_area is None or roi_area == 0:
                continue
            time_s = frame_count / fps
            time_pct = time_s / total_duration_s
            area_fraction = roi_area / total_arena_area
            aco = time_pct / area_fraction

            rows.append(
                {
                    "session_id": session_id,
                    "zone_name": zone_name,
                    "individual_id": animal_idx,
                    "area_corrected_occupancy": aco,
                }
            )

        if not rows:
            return empty_df

        return pd.DataFrame(rows, columns=empty_cols)


# ── Z-4: ZoneTransitions ─────────────────────────────────────────────────────


class ZoneTransitions(Metric):
    """Z-4 — Zone-to-zone transition counts per individual."""

    id = "Z-4"
    name = "zone_transitions"
    label = "Zone Transitions"
    level = "zone"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "from_zone",
        "to_zone",
        "individual_id",
        "transition_count",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Counts every discrete transition from one named zone to another for each "
            "individual.  Transitions from/to the empty zone (no zone) are excluded."
        ),
        formula_plain=(
            "for each consecutive frame pair (t, t+1): if zone[t,k] != zone[t+1,k] "
            "and both are non-empty, count += 1 for (from=zone[t,k], to=zone[t+1,k])"
        ),
        inputs=["PreprocessedSession.main_zone", "PreprocessedSession.sec_zone"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings"],
        warnings=[
            "Only named zone-to-zone transitions are counted; "
            "entering/leaving no-zone is ignored",
            "Collapses the full transition sequence to a scalar count per "
            "zone pair; see Z-7 for the full transition matrix and "
            "sequence entropy computed from this same run-length-encoded "
            "data",
        ],
        # Not Fagen & Young 1978 ('Temporal patterns of behaviors', in
        # Colgan ed., Quantitative Ethology, Wiley) -- real work, but with
        # no Crossref record or DOI, so a reader of this citation cannot
        # resolve it. Bakeman & Gottman 1997 covers transition-matrix and
        # sequential analysis directly and is DOI-bearing.
        primary_reference=BAKEMAN_GOTTMAN_1997,
        supporting_references=[MARTIN_BATESON_2007],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_dwell_frames",
            label="Minimum dwell length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help=(
                "Debounces boundary flicker: a zone visit shorter than this is "
                "dropped, merging the transitions either side of it into one "
                "continuous stay rather than two flicker transitions."
            ),
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Count zone-to-zone transitions for every (from_zone, to_zone, animal) triplet.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Optional dict. ``cfg['min_dwell_frames']`` (default 1) sets the
            minimum run length a zone visit must last to count -- shorter
            visits are debounced away before transitions are counted, so a
            brief flicker into a zone and back out doesn't register as two
            transitions.

        Returns
        -------
        pd.DataFrame
            One row per (from_zone, to_zone, individual_id) with transition_count.
            Empty DataFrame when no zone arrays are present or no transitions occur.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        min_dwell_frames = 1
        if cfg is not None and "min_dwell_frames" in cfg:
            min_dwell_frames = int(cfg["min_dwell_frames"])

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        # Accumulate transition counts: {(from_zone, to_zone, animal_idx): count}
        trans_counts: dict[tuple[str, str, int], int] = {}

        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]  # (n_frames,) object array
                sequence = _debounced_zone_sequence(col, min_dwell_frames)
                for from_z, to_z in pairwise(sequence):
                    # Only count transitions between named (non-empty) zones
                    if from_z != _EMPTY_ZONE_VALUE and to_z != _EMPTY_ZONE_VALUE:
                        key = (from_z, to_z, k)
                        trans_counts[key] = trans_counts.get(key, 0) + 1

        if not trans_counts:
            return pd.DataFrame(columns=empty_cols)

        rows = [
            {
                "session_id": session_id,
                "from_zone": from_z,
                "to_zone": to_z,
                "individual_id": animal_idx,
                "transition_count": count,
            }
            for (from_z, to_z, animal_idx), count in trans_counts.items()
        ]
        return pd.DataFrame(rows, columns=empty_cols)


# ── Z-5: Entry / exit event log ───────────────────────────────────────────────


class Z5EntryExitEvents(Metric):
    """Z-5 — Event log of zone entry/exit timestamps for each animal.

    ``Metric.level`` only allows "individual" / "group" / "zone" / "diagnostic"
    (see ``track2data/metrics/base.py``) — "event" is not a supported value —
    so this metric declares ``level = "zone"`` even though its output is an
    event log rather than a per-(zone, individual) summary row.
    """

    id = "Z-5"
    name = "zone_entry_exit_events"
    label = "Zone Entry/Exit Events"
    level = "zone"
    priority = "optional"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "event",
        "t_s",
        "frame",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Event log of every zone entry and exit for each animal: one row "
            "per rising or falling edge in the zone-membership series."
        ),
        formula_plain=(
            "enter at frame t when in_zone[t] and (t == 0 or not in_zone[t-1]); "
            "exit at frame t when not in_zone[t] and in_zone[t-1]; t_s = frame / fps"
        ),
        inputs=["Z-1 zone-membership series"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings."],
        warnings=[
            "An animal already inside a zone at frame 0 gets an 'enter' event at "
            "frame 0 with no preceding 'exit'.",
            "An animal still inside a zone at the final frame gets an 'enter' "
            "event with no matching 'exit' event.",
        ],
        primary_reference=MARTIN_BATESON_2007,
        supporting_references=[SIBLY_1990],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_dwell_frames",
            label="Minimum dwell length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help=(
                "Debounces boundary flicker: a run inside a zone shorter than "
                "this produces no enter/exit events at all."
            ),
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Emit one row per zone entry/exit edge for every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Optional dict. ``cfg['min_dwell_frames']`` (default 1) is the
            minimum run length inside a zone that produces an enter/exit
            pair -- a shorter run is debounced away entirely, as if the
            animal never entered.

        Returns
        -------
        pd.DataFrame
            One row per event with columns: session_id, zone_name,
            individual_id, event ("enter"/"exit"), t_s, frame.
            Empty DataFrame when no zone arrays are present.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        min_dwell_frames = 1
        if cfg is not None and "min_dwell_frames" in cfg:
            min_dwell_frames = int(cfg["min_dwell_frames"])

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]
        fps: float = session.fps  # type: ignore[attr-defined]

        rows: list[dict[str, object]] = []
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                zone_names = [z for z in np.unique(col) if z != _EMPTY_ZONE_VALUE]
                for zone_name in zone_names:
                    in_zone: np.ndarray = col == zone_name
                    spans = _true_run_spans(in_zone, min_dwell_frames)
                    enter_frames = [start for start, _end in spans]
                    exit_frames = [
                        end for _start, end in spans if end < len(in_zone)
                    ]
                    for frame in enter_frames:
                        rows.append(
                            {
                                "session_id": session_id,
                                "zone_name": zone_name,
                                "individual_id": k,
                                "event": "enter",
                                "t_s": frame / fps,
                                "frame": frame,
                            }
                        )
                    for frame in exit_frames:
                        rows.append(
                            {
                                "session_id": session_id,
                                "zone_name": zone_name,
                                "individual_id": k,
                                "event": "exit",
                                "t_s": frame / fps,
                                "frame": frame,
                            }
                        )

        if not rows:
            return pd.DataFrame(columns=empty_cols)

        df = pd.DataFrame(rows, columns=empty_cols)
        return df.sort_values(["individual_id", "zone_name", "frame"]).reset_index(drop=True)


# ── Z-6: Latency to first entry ───────────────────────────────────────────────


class Z6LatencyToFirstEntry(Metric):
    """Z-6 — Time of each animal's first entry into each named zone."""

    id = "Z-6"
    name = "latency_to_first_entry"
    label = "Latency to First Entry"
    level = "zone"
    priority = "optional"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "first_entry_t_s",
    ]
    documentation = MetricDocumentation(
        definition=("Time (in seconds) of each animal's first entry into each named zone."),
        formula_plain=(
            "first_entry_t_s[k, z] = min(t_s) over Z-5 'enter' events for "
            "(zone_name == z, individual_id == k); inf if the animal never enters"
        ),
        inputs=["Z-5 event log"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings."],
        warnings=[
            "NaN when the individual never enters the zone is encoded as inf "
            "(rather than NaN) so results sort as 'latest possible'.",
            "The source paradigm is rodent (mouse light/dark box) and gives "
            "no censoring convention of its own for a never-entering animal; "
            "the inf encoding above is this tool's own deliberate choice, "
            "not something the citation specifies.",
        ],
        primary_reference=BOURIN_HASCOET_2003,
        supporting_references=[MARTIN_BATESON_2007],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_dwell_frames",
            label="Minimum dwell length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help=(
                "Forwarded to Z-5: debounces boundary flicker so a run "
                "inside a zone shorter than this doesn't count as the "
                "first entry."
            ),
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute the first-entry latency for every (zone, animal) pair.

        Internally reuses ``Z5EntryExitEvents.compute()`` as the event-log
        subroutine (per METRICS_SPEC.md Z-6 "Inputs: Z-5 event log") rather
        than re-deriving rising edges.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Unused; reserved for future configuration.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) — the full grid of every
            zone seen by any animal times every animal — with
            first_entry_t_s == inf for pairs that never had an enter event.
            Empty DataFrame when no zone arrays are present.
        """
        empty_cols = self.output_columns
        zone_arrays = _collect_zone_arrays(session)
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        events = Z5EntryExitEvents().compute(session, cfg)
        enters = events[events["event"] == "enter"]

        zone_names = sorted(enters["zone_name"].unique().tolist())
        if not zone_names:
            return pd.DataFrame(columns=empty_cols)

        rows = []
        for zone_name in zone_names:
            for k in range(n_animals):
                match = enters[
                    (enters["zone_name"] == zone_name) & (enters["individual_id"] == k)
                ]
                first_entry_t_s = float(match["t_s"].min()) if len(match) > 0 else float("inf")
                rows.append(
                    {
                        "session_id": session_id,
                        "zone_name": zone_name,
                        "individual_id": k,
                        "first_entry_t_s": first_entry_t_s,
                    }
                )

        return pd.DataFrame(rows, columns=empty_cols)


# ── Z-7: Zone transition matrix & sequence entropy ───────────────────────────


class ZoneTransitionMatrix(Metric):
    """Z-7 — Full zone-to-zone transition-probability matrix and the
    Shannon entropy of the transition sequence, per individual.

    Same run-length-encoded, debounced zone sequence Z-4 already
    builds; where Z-4 collapses it to one scalar count per zone pair,
    this exposes the full matrix (row-normalised into conditional
    probabilities) plus a single entropy value per individual.
    """

    id = "Z-7"
    name = "zone_transition_matrix"
    label = "Zone Transition Matrix & Sequence Entropy"
    level = "zone"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "individual_id",
        "from_zone",
        "to_zone",
        "transition_count",
        "transition_probability",
        "sequence_entropy_bits",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Full zone-to-zone transition-probability matrix per individual "
            "(same debounced zone sequence as Z-4), plus the Shannon entropy "
            "of that individual's transition distribution -- a single number "
            "summarising how predictable the zone-to-zone sequence is. Z-4's "
            "scalar transition count is one cell of this same matrix."
        ),
        formula_plain=(
            "Same debounced zone sequence as Z-4; "
            "transition_probability[a,b] = count(a->b) / sum_b' count(a->b') "
            "(row-normalised, i.e. P(next=b | current=a)); "
            "sequence_entropy_bits = -sum(p_ij * log2(p_ij)) over all observed "
            "transitions (a,b), p_ij = count(a,b) / total_transitions -- the "
            "joint distribution's entropy, not the row-normalised one, so it "
            "reflects both how many distinct transitions occur and how evenly "
            "used they are"
        ),
        inputs=["PreprocessedSession.main_zone", "PreprocessedSession.sec_zone"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings"],
        warnings=[
            "Only named zone-to-zone transitions are counted; entering/leaving "
            "no-zone is ignored, same as Z-4",
            "sequence_entropy_bits is repeated on every row for a given "
            "individual (it is one scalar per individual, broadcast across "
            "the matrix rows for long-format consistency)",
            "Undefined (NaN) for an individual with zero qualifying transitions",
        ],
        primary_reference=BAKEMAN_GOTTMAN_1997,
        supporting_references=[MARTIN_BATESON_2007],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_dwell_frames",
            label="Minimum dwell length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help=(
                "Debounces boundary flicker: a zone visit shorter than this is "
                "dropped, merging the transitions either side of it into one "
                "continuous stay rather than two flicker transitions. Same "
                "parameter as Z-4."
            ),
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute the zone transition matrix and sequence entropy for
        every individual.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Optional dict. ``cfg['min_dwell_frames']`` (default 1), same as Z-4.

        Returns
        -------
        pd.DataFrame
            One row per (individual_id, from_zone, to_zone) with
            transition_count, transition_probability, and
            sequence_entropy_bits. Empty when no zone arrays are present
            or no individual has any qualifying transition.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        min_dwell_frames = 1
        if cfg is not None and "min_dwell_frames" in cfg:
            min_dwell_frames = int(cfg["min_dwell_frames"])

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        rows: list[dict] = []
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                sequence = _debounced_zone_sequence(col, min_dwell_frames)

                trans_counts: dict[tuple[str, str], int] = {}
                for from_z, to_z in pairwise(sequence):
                    if from_z != _EMPTY_ZONE_VALUE and to_z != _EMPTY_ZONE_VALUE:
                        key = (from_z, to_z)
                        trans_counts[key] = trans_counts.get(key, 0) + 1

                if not trans_counts:
                    continue

                totals_by_from: dict[str, int] = {}
                for (from_z, _to_z), count in trans_counts.items():
                    totals_by_from[from_z] = totals_by_from.get(from_z, 0) + count

                total_transitions = sum(trans_counts.values())
                entropy_bits = -sum(
                    (count / total_transitions) * np.log2(count / total_transitions)
                    for count in trans_counts.values()
                )

                for (from_z, to_z), count in trans_counts.items():
                    rows.append(
                        {
                            "session_id": session_id,
                            "individual_id": k,
                            "from_zone": from_z,
                            "to_zone": to_z,
                            "transition_count": count,
                            "transition_probability": count / totals_by_from[from_z],
                            "sequence_entropy_bits": float(entropy_bits),
                        }
                    )

        if not rows:
            return pd.DataFrame(columns=empty_cols)

        return pd.DataFrame(rows, columns=empty_cols)


# ── Z-8: Zone preference index (Jacobs' D) ────────────────────────────────────


class ZonePreferenceIndex(Metric):
    """Z-8 — Availability-corrected zone preference index (Jacobs' D).

    Bounded [-1, +1] replacement for Z-2's unbounded area-corrected
    ratio. Z-2 is kept (see its ``superseded_by``) for output
    compatibility with existing projects; this is the better statistic
    for new analyses -- it is bias-corrected and can be meaningfully
    averaged across animals or compared across arena designs, which
    Z-2's raw ratio cannot.
    """

    id = "Z-8"
    name = "zone_preference_index"
    label = "Zone Preference Index (Jacobs' D)"
    level = "zone"
    priority = "primary"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "jacobs_d",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Availability-corrected preference index for each zone: how much "
            "more (or less) time an animal spends in a zone than expected from "
            "that zone's share of the total arena area, on a bounded [-1, +1] "
            "scale. 0 = time matches area share exactly; +1 = maximal "
            "preference; -1 = maximal avoidance."
        ),
        formula_plain=(
            "r = observed time_pct in the zone (same computation as Z-1); "
            "p = roi_area / total_arena_area (same derivation as Z-2); "
            "jacobs_d = (r - p) / (r + p - 2*r*p), or 0 when r == p == 0"
        ),
        inputs=[
            "PreprocessedSession.main_zone",
            "PreprocessedSession.sec_zone",
            "cfg['roi_areas'] (derived per session, see metrics/derived.py)",
            "cfg['total_arena_area'] (derived per session)",
        ],
        assumptions=[
            "Zone arrays are pre-assigned object arrays of zone-name strings",
            "roi_areas and total_arena_area are supplied in cfg (derived, "
            "same as Z-2 -- never user-typed)",
        ],
        warnings=["Returns empty DataFrame when cfg is missing or incomplete"],
        primary_reference=JACOBS_1974,
        supporting_references=[KRAUSE_RUXTON_2002],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="roi_areas", label="Zone areas", kind="float", derived=True,
            help="Derived per session from the project's own zone geometry (shared with Z-2).",
        ),
        MetricParameter(
            name="total_arena_area", label="Total arena area", kind="float",
            derived=True, unit="px²",
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute Jacobs' D for every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Must contain ``roi_areas`` (dict zone_name -> float) and
            ``total_arena_area`` (float), both derived per session --
            identical inputs to Z-2.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) with jacobs_d.
            Empty DataFrame when cfg is missing/incomplete or no zone
            arrays are present.
        """
        empty_cols = self.output_columns
        if not cfg or "roi_areas" not in cfg or "total_arena_area" not in cfg:
            return pd.DataFrame(columns=empty_cols)

        roi_areas: dict[str, float] = cfg["roi_areas"]
        total_arena_area: float = cfg["total_arena_area"]
        if not roi_areas or total_arena_area <= 0:
            return pd.DataFrame(columns=empty_cols)

        zone_arrays = _collect_zone_arrays(session)
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_frames: int = session.n_frames  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]
        total_duration_frames = n_frames

        counts: dict[tuple[str, int], int] = {}
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                for zone_name in np.unique(col):
                    if zone_name == _EMPTY_ZONE_VALUE or zone_name not in roi_areas:
                        continue
                    n = int(np.sum(col == zone_name))
                    key = (str(zone_name), k)
                    counts[key] = counts.get(key, 0) + n

        if not counts:
            return pd.DataFrame(columns=empty_cols)

        rows = []
        for (zone_name, animal_idx), frame_count in counts.items():
            r = frame_count / total_duration_frames
            p = roi_areas[zone_name] / total_arena_area
            denom = r + p - 2 * r * p
            jacobs_d = 0.0 if denom == 0 else (r - p) / denom
            rows.append(
                {
                    "session_id": session_id,
                    "zone_name": zone_name,
                    "individual_id": animal_idx,
                    "jacobs_d": jacobs_d,
                }
            )

        return pd.DataFrame(rows, columns=empty_cols)


# ── Z-9: Zone dwell-time distribution ─────────────────────────────────────────


class ZoneDwellTimeDistribution(Metric):
    """Z-9 — Distribution of individual visit durations per zone.

    Z-1 (total time) and Z-3 (visit count) cannot separate "one long
    visit" from "many brief ones" -- a distinction that carries most
    of the anxiety-phenotype signal in light/dark and novel-tank
    assays. Pairs Z-5's enter/exit events into visits and summarises
    their durations.
    """

    id = "Z-9"
    name = "zone_dwell_time_distribution"
    label = "Zone Dwell-Time Distribution"
    level = "zone"
    priority = "optional"
    requires_identity = False
    output_columns: ClassVar[list[str]] = [
        "session_id",
        "zone_name",
        "individual_id",
        "n_visits",
        "mean_dwell_s",
        "median_dwell_s",
        "max_dwell_s",
    ]
    documentation = MetricDocumentation(
        definition=(
            "Mean, median, and maximum duration of each animal's visits to "
            "each named zone, from the same enter/exit event log as Z-5."
        ),
        formula_plain=(
            "Pair each 'enter' event with its next 'exit' event (same zone, "
            "individual) from the Z-5 event log; dwell_s = exit.t_s - enter.t_s; "
            "mean/median/max computed over all paired visits. A visit still "
            "open at the final frame (Z-5's unmatched 'enter') is excluded, "
            "not counted as an open-ended visit."
        ),
        inputs=["Z-5 event log"],
        assumptions=["Zone arrays are pre-assigned object arrays of zone-name strings."],
        warnings=[
            "An animal's final, still-open visit at session end is excluded "
            "from these statistics (its true duration is unknown)",
            "Undefined (no row) for a (zone, animal) pair with zero completed visits",
        ],
        primary_reference=SIBLY_1990,
        supporting_references=[BOURIN_HASCOET_2003],
    )
    parameters: ClassVar[list[MetricParameter]] = [
        MetricParameter(
            name="min_dwell_frames",
            label="Minimum dwell length",
            kind="int",
            default=1,
            minimum=1,
            unit="frames",
            help="Forwarded to Z-5: debounces boundary flicker, same as Z-5/Z-6.",
        ),
    ]

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Compute dwell-time distribution statistics for every (zone, animal) pair.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Optional dict. ``cfg['min_dwell_frames']`` (default 1), forwarded to Z-5.

        Returns
        -------
        pd.DataFrame
            One row per (zone_name, individual_id) with n_visits,
            mean_dwell_s, median_dwell_s, max_dwell_s. Empty DataFrame
            when no zone arrays are present or no visit completes.
        """
        empty_cols = self.output_columns
        events_df = Z5EntryExitEvents().compute(session, cfg)
        if events_df.empty:
            return pd.DataFrame(columns=empty_cols)

        rows = []
        grouped = events_df.groupby(["zone_name", "individual_id"], sort=False)
        for (zone_name, animal_idx), group in grouped:
            group = group.sort_values("frame")
            durations: list[float] = []
            pending_enter_t: float | None = None
            for _, event_row in group.iterrows():
                if event_row["event"] == "enter":
                    pending_enter_t = float(event_row["t_s"])
                elif event_row["event"] == "exit" and pending_enter_t is not None:
                    durations.append(float(event_row["t_s"]) - pending_enter_t)
                    pending_enter_t = None
            # A trailing pending_enter_t (visit still open at session end) is
            # deliberately dropped -- its true duration is unknown.

            if not durations:
                continue

            arr = np.asarray(durations, dtype=np.float64)
            rows.append(
                {
                    "session_id": session.session_id,  # type: ignore[attr-defined]
                    "zone_name": zone_name,
                    "individual_id": animal_idx,
                    "n_visits": len(durations),
                    "mean_dwell_s": float(arr.mean()),
                    "median_dwell_s": float(np.median(arr)),
                    "max_dwell_s": float(arr.max()),
                }
            )

        if not rows:
            return pd.DataFrame(columns=empty_cols)

        return pd.DataFrame(rows, columns=empty_cols)


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(TimeInZone)
_register(AreaCorrectedOccupancy)
_register(ZoneVisitCount)
_register(ZoneTransitions)
_register(Z5EntryExitEvents)
_register(Z6LatencyToFirstEntry)
_register(ZoneTransitionMatrix)
_register(ZonePreferenceIndex)
_register(ZoneDwellTimeDistribution)
