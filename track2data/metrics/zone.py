"""Zone metrics (Z-1 Time-in-zone, Z-3 Zone-visit-count)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd

from track2data.metrics.base import Metric, MetricDocumentation

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
    )

    def compute(
        self,
        session: object,
        cfg: dict | None = None,
    ) -> pd.DataFrame:
        """Count zone visits (rising edges) for every (zone, animal) pair.

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
            session_id, zone_name, individual_id, visit_count.
            Empty DataFrame when no zone arrays are present.
        """
        zone_arrays = _collect_zone_arrays(session)
        empty_cols = self.output_columns
        if not zone_arrays:
            return pd.DataFrame(columns=empty_cols)

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        # Accumulate visit counts per (zone, animal) across all zone arrays.
        # We sum rising-edge counts; if the same zone appears in both main and
        # sec arrays we still count entries independently.
        visit_counts: dict[tuple[str, int], int] = {}
        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]
                zone_names = [z for z in np.unique(col) if z != _EMPTY_ZONE_VALUE]
                for zone_name in zone_names:
                    in_zone: np.ndarray = col == zone_name  # bool (n_frames,)
                    # Rising edges: frame 0 if in_zone[0] is True, then each
                    # transition from False to True
                    visits = int(in_zone[0]) + int(np.sum(~in_zone[:-1] & in_zone[1:]))
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
    )

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
    )

    def compute(self, session: object, cfg: dict | None = None) -> pd.DataFrame:
        """Count zone-to-zone transitions for every (from_zone, to_zone, animal) triplet.

        Parameters
        ----------
        session:
            A ``PreprocessedSession`` instance.
        cfg:
            Unused; reserved for future configuration.

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

        session_id: str = session.session_id  # type: ignore[attr-defined]
        n_animals: int = session.n_animals  # type: ignore[attr-defined]

        # Accumulate transition counts: {(from_zone, to_zone, animal_idx): count}
        trans_counts: dict[tuple[str, str, int], int] = {}

        for arr in zone_arrays:
            for k in range(n_animals):
                col = arr[:, k]  # (n_frames,) object array
                for t in range(len(col) - 1):
                    from_z = col[t]
                    to_z = col[t + 1]
                    # Only count transitions between named (non-empty) zones
                    if (
                        from_z != _EMPTY_ZONE_VALUE
                        and to_z != _EMPTY_ZONE_VALUE
                        and from_z != to_z
                    ):
                        key = (str(from_z), str(to_z), k)
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


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.metrics import register as _register  # noqa: E402

_register(TimeInZone)
_register(AreaCorrectedOccupancy)
_register(ZoneVisitCount)
_register(ZoneTransitions)
