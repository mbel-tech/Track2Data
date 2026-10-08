# Glossary

**Applies to:** Track2Data v0.1.0 and later. Column names are the ones the exporter
writes; the authoritative per-column unit is in `codebook.csv`, shipped with every run.

Terms as this tool uses them, each with the exported column it corresponds to. Formal
definitions, formulas and citations are in
[`docs/METRICS_SPEC.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/METRICS_SPEC.md).

## The shape of a dataset

| Term | What it means here |
|---|---|
| **Session** | One tracked recording — one idtracker.ai output folder. Identified by `session_id`. The unit most analyses should treat as independent. |
| **Project** | A set of sessions plus the settings applied to all of them, saved as a `.t2d.json` file. |
| **Run** | One execution of a project, writing one output directory. Recorded in `manifest.json` (`run_metadata`: `app_version`, `project_hash`, `generated_at`, `metrics_computed`). |
| **Individual** | One tracked animal within a session, `individual_id`. Not comparable across sessions: identity 0 in two tanks is two different animals. |
| **Long table** | `metrics_long.csv` — one row per measured value: `session_id`, `individual_id`, `zone_name`, `metric_id`, `column`, `value`, `unit`. Start here for analysis. |
| **Wide tables** | `trial_activity_summary.csv` (session × animal), `group_dynamics_summary.csv` (session), `trial_summary_wide.csv` (everything side by side), `master_fish_by_frame.csv` (session × animal × frame). |
| **Codebook** | `codebook.csv` — one row per exported column with its unit, level, originating metric and DOI. |
| **Time bins** | Optional windows set on the Metrics screen. Summary tables gain `bin_index`, `bin_start_s`, `bin_end_s`; metrics that are not meaningful per window keep one row with empty bin columns. |

## Units and calibration

| Term | What it means here |
|---|---|
| **`*_px`** | Pixels. Always available. |
| **`*_cm`** | Physical units, written only when a pixels-per-unit scale (`px_per_cm`) is set. Empty columns mean no scale, not an error. |
| **`*_bl`** | Body lengths: `value_px / body_length_px`. Independent of `px_per_cm` and of the calibration mode, so it works when no physical scale exists — but needs a body length from the tracker. |
| **`*_pct`** | **A fraction in [0, 1], not a percentage.** `time_pct = 0.42` means 42 %. The names are kept for backward compatibility; `codebook.csv` states the real unit. |
| **Calibration mode** | `bodylength` (default), `scalar` (one px_per_cm for the project) or `session` (measured per session). Set on the Calibration screen. |
| **`length_calibration_rel_sd`** | In `sessions.csv`: the spread of the calibration clicks behind a session-mode scale. Above 5 % is warned about. `None` means no estimate (fewer than two clicks), never zero error. |

## Preprocessing

| Term | What it means here | Default |
|---|---|---|
| **Gap fill** | Short runs of missing positions filled by interpolation; `max_gap_frames` is the longest gap filled. Filled frames are flagged `was_interpolated` in `master_fish_by_frame`. | on, `max_gap_frames = 30` |
| **Jump replacement** | Physically implausible displacements detected (`sd_multiple`, `percentile` or `idtracker_velocity_threshold`) and replaced. | on, `sd_mult = 10.0`, `replacement = linear_interp` |
| **Smoothing** | Savitzky–Golay filter over the trajectory; `window` frames, polynomial `polyorder`. Under-smoothing inflates path length; over-smoothing suppresses speed. | on, `savgol`, `window = 5`, `polyorder = 2` |
| **Identity-switch correction** | Attempts to repair swapped identities between animals. Changes who is who, so it is off unless you turn it on, and it carries a risk warning in the UI. | **off** |
| **Coverage check** | `min_track_frames`, `max_pct_na_per_individual` — drops or flags individuals tracked too sparsely to measure. | `0`, `0.10` |

Every one of these is recorded in `manifest.json`. They are analysis choices, not neutral
cleanup: see [[Statistics and Pseudoreplication]] and `track2data sensitivity`.

## Tracking quality

| Term | What it means here |
|---|---|
| **Identity-free session** | A session tracked without stable identities. Metrics that follow an individual are not reported; zone occupancy (Z-1, Z-2, Z-8) is pooled over animals with no `individual_id`, and GL-7 gives a nearest-neighbour-matched speed. Flagged ⚠ on the Sessions screen. |
| **Interpolated vs measured** | `n_interpolated` / `frac_interpolated` count frames filled by gap filling; `frac_measured` is the share of used frames that came from the tracker. From D-11. |
| **Coverage (D-11)** | `n_frames_total`, `n_frames_used`, `frac_frames_used`, `n_jump_replaced`, `frac_jump_replaced`. The columns that tell a ratio from 200 frames apart from one from 20,000. |
| **Distortion index (D-16)** | `rms_displacement_px`, `frac_frames_altered`, `path_length_ratio`, `distortion_index` — how far preprocessing moved the trajectory it was given. |
| **Fragment** | A continuous stretch of frames the tracker assigned to one identity. `fragment_length_median` and friends are counted in **frames**; `certainty_mean` and D-14's certain-frame fraction describe how sure the tracker was. |
| **Identity stability (D-5)** | `identity_stability_status` — a categorical flag, not a number. |
| **Tracking accuracy (D-2)** | `estimated_accuracy`, the tracker's own estimate; `fraction_identified` and the D-3 `id_prob_*` columns describe the identity-probability distribution. |

## Behavioural vocabulary

| Term | Metric | Column |
|---|---|---|
| **Path length** | IL-1 | `path_length_px` / `_cm` / `_bl` — a *total*, so it scales with session duration |
| **Speed** | IL-2 | `mean_speed_*`, `median_speed_*`, `max_speed_*` |
| **Thigmotaxis** | IL-14, IL-3 | `mean_wall_distance_px`, `wall_contact_time_pct`; `time_in_centre_pct` |
| **Freezing / activity** | IL-4 | `active_fraction`, `freezing_fraction`, `threshold_px_s` |
| **Bout** | IL-7, Z-3 | A run of consecutive frames meeting a criterion. `min_bout_frames_used` and `bout_criterion_effective` record the criterion actually applied — report it |
| **Tortuosity** | IL-5 | `tortuosity` — path length ÷ net displacement |
| **Home base** | IL-9 | `home_base_time_pct`, `home_base_stable` |
| **Roaming entropy** | IL-10 | `roaming_entropy_normalised` (and a `_bits` form) |
| **Zone occupancy** | Z-1, Z-2 | `time_s`, `time_pct`; `area_corrected_occupancy` divides occupancy by zone area |
| **Jacobs' D** | Z-8 | `jacobs_d`, in [−1, 1]: preference corrected for how much of the arena the zone is |
| **NND / IID** | GL-1, GL-2 | `mean_nnd_px` / `_cm` / `_bl`; inter-individual distance — the usual cohesion measures |
| **Polarisation** | GL-3 | `mean_polarisation`, `median_polarisation`, in [0, 1]: 1 = everyone heading the same way |
| **Rotational order** | GL-8 | `mean_rotational_order` — milling around the group centre |
| **Order state** | GL-11 | `swarm_time_pct`, `milling_time_pct`, `polarised_time_pct` |
| **School area / shape** | GL-4, GL-10, GL-15 | convex hull area in `px^2`; group expansion; `mean_elongation_ratio` |
| **Cohesion index** | GL-6 | `cohesion_index` |

A **group-level (GL-\*) metric is one value per session**, not per animal — which is what
makes group metrics expensive in sample size. See [[Statistics and Pseudoreplication]].
