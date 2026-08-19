"""Canonical output column registry — single source of truth for export names."""

from __future__ import annotations

#: Ordered list of canonical column names used across all exporters.
CANONICAL_COLUMNS: list[str] = [
    # keys
    "session_id",
    "trial_id",
    "timepoint",
    "individual_id",
    "frame",
    "time_s",
    # kinematics
    "x_px",
    "y_px",
    "x_cm",
    "y_cm",
    "speed_cm_s",
    "speed_bl_s",
    "heading_rad",
    # zones
    "main_zone",
    "sec_zone",
    # metadata
    "treatment",
    "group_id",
    "trial_date",
]
