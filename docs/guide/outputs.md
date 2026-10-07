# Understanding the output files

Each session is written to `<out_dir>/<session_id>/`. Files differ by exporter; the tables are the
same.

| Table | One row per | Contents |
|---|---|---|
| `master_fish_by_frame` | session × animal × frame | `time_s`, `x_px`, `y_px`, `was_interpolated` (true where preprocessing filled a gap), `speed_px_s`, `heading_rad`, `main_zone`, `sec_zone`, plus calibrated and metadata columns |
| `trial_activity_summary` | session × animal | individual-level metrics, plus metadata |
| `group_dynamics_summary` | session | group-level metrics, plus metadata |
| `trial_summary_wide` | session × animal | all summary metrics side by side |

## Column naming

| Suffix | Meaning |
|---|---|
| `_px` | pixels |
| `_cm` | centimetres (only with a scale; otherwise empty) |
| `_bl` | body lengths (needs the tracker's body length; independent of the calibration mode and of any physical scale) |
| `_s` | per second |

## Things to know

- **Empty `*_cm` columns** mean no pixels-per-unit scale was set, not an error. Use `*_bl`, or set a
  scale on the [Calibration](03-calibration.md) screen.
- **Identity-free sessions** have no per-animal rows for metrics that follow an individual; zone
  occupancy (Z-1, Z-2, Z-8) is reported pooled over animals, without an `individual_id` column.
- **Time bins** (when set on the Metrics screen): summary tables have one row per animal *per bin*, with `bin_index`, `bin_start_s`, `bin_end_s`; `master_fish_by_frame` gets `bin_index`. Metrics that are not meaningful per window keep a single row with empty bin columns.
- **Missing positions** are empty values, never zeros.
- The README written next to the files records the settings and versions used, and the SHA-256 of
  each output, so a result can be traced and reproduced.

Definitions, formulas and references for every metric: [`docs/METRICS_SPEC.md`](../METRICS_SPEC.md).
