"""Zone metrics (Z-1 Time-in-zone, Z-3 Zone-visit-count)."""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pandas as pd

from track2data.metrics.base import Metric, MetricDocumentation, MetricParameter

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
    "A", so it contributes zero transitions instead of two."""
    runs: list[tuple[str, int]] = []
    for val in col:
        name = str(val)
        if runs and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + 1)
        else:
            runs.append((name, 1))

    kept = [name for name, length in runs if length >= min_dwell_frames]

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
        citation=(
            "Walsh & Cummins 1976, Psychol. Bull. 83(3):482-504 (the "
            "open-field test, whose central measure is time spent in "
            "defined sub-regions)"
        ),
        citation_doi="10.1037/0033-2909.83.3.482",
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
        citation=(
            "Martin & Bateson 2007, Measuring Behaviour: An Introductory "
            "Guide, 3rd ed. (Cambridge University Press) -- frequency "
            "counting of discrete behavioural events"
        ),
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
        warnings=["Returns empty DataFrame when cfg is missing or incomplete"],
        citation=(
            "Area-normalised occupancy (observed time in a zone relative to "
            "that zone's share of the arena), the standard correction for "
            "comparing unequal-area regions of interest. No single "
            "originating work"
        ),
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

        if roi_areas is None or total_arena_area is None or total_arena_area == 0:
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
            "entering/leaving no-zone is ignored"
        ],
        citation=(
            "Fagen & Young 1978, 'Temporal patterns of behaviors', in "
            "Colgan (ed.) Quantitative Ethology, pp. 79-114 (Wiley) -- "
            "sequence and transition analysis of behavioural states"
        ),
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
        citation=(
            "Boundary-crossing event extraction underlying the event/state "
            "distinction in Martin & Bateson 2007, Measuring Behaviour, "
            "3rd ed. (Cambridge University Press)"
        ),
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
            "(rather than NaN) so results sort as 'latest possible'."
        ],
        citation=(
            "Bourin & Hascoët 2003, Eur. J. Pharmacol. 463(1-3):55-65 -- "
            "latency to first entry as a standard exploration/anxiety "
            "readout in the light/dark box test"
        ),
        citation_doi="10.1016/S0014-2999(03)01274-3",
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


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(TimeInZone)
_register(AreaCorrectedOccupancy)
_register(ZoneVisitCount)
_register(ZoneTransitions)
_register(Z5EntryExitEvents)
_register(Z6LatencyToFirstEntry)
