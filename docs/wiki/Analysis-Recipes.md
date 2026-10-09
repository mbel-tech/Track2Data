# Analysis recipes

**Applies to:** Track2Data v0.1.0 and later. Column names are as exported; check
`codebook.csv` for units.

Four worked designs, from a finished export to a fitted model. Each one names the metrics to
tick on the **Metrics** screen, the columns they produce, the model the design calls for, and
the mistake that specific design invites. They are starting points for common assays, not
recommendations for your experiment.

Runnable versions of the loading and modelling code ship with the repo:
[`examples/analysis/analyse.R`](https://github.com/mbel-tech/Track2Data/blob/main/examples/analysis/analyse.R)
and
[`examples/analysis/analyse.py`](https://github.com/mbel-tech/Track2Data/blob/main/examples/analysis/analyse.py).
The statistical reasoning behind the random-effects structure used throughout is in
[[Statistics and Pseudoreplication]].

## Loading the export (all recipes start here)

`metrics_long.csv` is one row per value: `session_id`, `individual_id`, `zone_name`,
`metric_id`, `column`, `value`, `unit`. Reshape the rows you need and nothing else.

```r
library(dplyr); library(tidyr); library(readr)

run <- "out"
long     <- list.files(run, "^metrics_long\\.csv$", recursive = TRUE, full.names = TRUE) |>
            Filter(f = \(f) basename(dirname(f)) != "all_sessions") |>  # see the note below
            lapply(read_csv, show_col_types = FALSE) |> bind_rows()
sessions <- read_csv(file.path(run, "sessions.csv"), show_col_types = FALSE)
codebook <- read_csv(file.path(run, "codebook.csv"), show_col_types = FALSE)

# Per-individual metrics, excluding zone rows and the provenance diagnostic.
individual <- long |>
  filter(is.na(zone_name), !is.na(individual_id), metric_id != "D-11") |>
  select(session_id, individual_id, column, value) |>
  pivot_wider(names_from = column, values_from = value)

# Coverage, to weight or exclude by.
quality <- long |> filter(metric_id == "D-11") |>
  select(session_id, individual_id, column, value) |>
  pivot_wider(names_from = column, values_from = value)
```

**Read the session folders or `all_sessions/`, never both.** A run with two or more sessions also writes
`all_sessions/metrics_long.csv`, which is the same rows stacked. A recursive search for `metrics_long.csv` finds it
as well, so the code above skips it; without that filter every value is counted twice. If you would rather read
one file, `read_csv(file.path(run, "all_sessions", "metrics_long.csv"))` gives the same table, but only exists
for runs with two or more sessions.

Join your treatment labels from the metadata you supplied on the **Metadata** screen (they
travel through to every table), or from `sessions.csv` if the treatment is per session.

---

## Recipe 1 — Open-field thigmotaxis

**Question.** Do treated animals spend more time near the wall?

**Metrics to select.** Z-1 (time in each zone), Z-8 (Jacobs' D), IL-14 (wall-distance
thigmotaxis), IL-3 (distance from arena centre). Draw `wall` and `centre` zones on the
**Zones** screen, or use IL-3/IL-14, which need no zones.

**Columns.** `time_pct` and `time_s` per `zone_name` (Z-1); `jacobs_d` (Z-8);
`wall_contact_time_pct`, `mean_wall_distance_px` (IL-14); `time_in_centre_pct`,
`mean_centre_distance` (IL-3).

```r
wall <- long |>
  filter(metric_id == "Z-1", zone_name == "wall", column == "time_pct") |>
  select(session_id, individual_id, wall_time = value) |>
  inner_join(filter(quality, frac_frames_used >= 0.80) |>
               select(session_id, individual_id), by = c("session_id", "individual_id")) |>
  left_join(treatments, by = "session_id")

# A fraction in [0, 1]: beta, not Gaussian.
glmmTMB::glmmTMB(wall_time ~ treatment + (1 | session_id),
                 family = glmmTMB::beta_family(), data = wall)
```

**The trap.** `time_pct` is a fraction, and zone occupancy sums to 1 across zones — so wall
and centre time are not two independent outcomes, they are one. Pick the zone you
pre-registered, or use `jacobs_d`, which is already corrected for how much of the arena each
zone occupies. Zone fractions also depend on where you drew the boundary: keep the zone
definition identical across sessions, and check the resolution warning if you reused zones
drawn on a different image size.

---

## Recipe 2 — Shoaling cohesion across a treatment

**Question.** Does the treatment change how tightly the group swims together?

**Metrics to select.** GL-1 (NND), GL-2 (IID), GL-3 (polarisation), GL-6 (cohesion index);
optionally GL-4 (hull area), GL-10 (group spread), GL-11 (order state).

**Columns.** `mean_nnd_px` / `_cm` / `_bl`, `mean_iid_*`, `mean_polarisation`,
`cohesion_index`, `mean_hull_area_px2`, `mean_group_spread_*`, `polarised_time_pct`,
`milling_time_pct`, `swarm_time_pct`.

```r
group <- long |>
  filter(metric_id %in% c("GL-1", "GL-3", "GL-6"),
         column %in% c("mean_nnd_bl", "mean_polarisation", "cohesion_index")) |>
  select(session_id, column, value) |>
  pivot_wider(names_from = column, values_from = value) |>
  left_join(select(sessions, session_id, n_animals, fps, duration_s), by = "session_id") |>
  left_join(treatments, by = "session_id")

stopifnot(dplyr::n_distinct(group$n_animals) == 1)   # see below
lm(mean_nnd_bl ~ treatment, data = group)            # n = sessions, not animals
```

**The trap.** These are **one value per session**. A tank of eight fish is one observation,
so the design needs replicate tanks; with four tanks per treatment you have *n* = 4. Group
size is the second trap: NND falls as animals are added, for geometric reasons alone, so an
unmatched group size will look like a treatment effect. Match group size, or model
`n_animals` explicitly and expect to defend it. Prefer `mean_nnd_bl` to `mean_nnd_cm` when
body size differs between groups — distance in body lengths is the comparable quantity.

---

## Recipe 3 — Activity and freezing

**Question.** Does the treatment change how much animals move, and how their freezing is
organised in time?

**Metrics to select.** IL-4 (activity / freezing fraction), IL-7 (freezing-bout statistics),
IL-2 (speed), IL-1 (path length).

**Columns.** `active_fraction`, `freezing_fraction`, `threshold_px_s` (IL-4);
`freezing_bout_count`, `mean_freezing_duration_s`, `total_freezing_duration_s`,
`min_bout_frames_used`, `bout_criterion_effective` (IL-7); `mean_speed_cm_s`,
`median_speed_cm_s`, `max_speed_cm_s` (IL-2); `path_length_cm` (IL-1).

```r
act <- individual |>
  left_join(select(sessions, session_id, duration_s), by = "session_id") |>
  left_join(treatments, by = "session_id")

# A rate: model it directly.
lme4::lmer(mean_speed_cm_s ~ treatment + (1 | session_id), data = act)

# A count: exposure offset, not a ratio.
glmmTMB::glmmTMB(freezing_bout_count ~ treatment + offset(log(duration_s)) + (1 | session_id),
                 family = glmmTMB::nbinom2, data = act)
```

**The trap.** "Freezing" is a threshold decision, not an observation: IL-4 reports the speed
threshold it used (`threshold_px_s`), and IL-7 reports the minimum bout length actually
applied (`min_bout_frames_used`, `bout_criterion_effective`). Both must be reported, and both
must be identical across the groups you compare. Smoothing matters more here than for any
other family — a wider window suppresses the small displacements that decide whether a frame
counts as freezing — so check `track2data sensitivity` before publishing a bout result.
`path_length_cm` is a total: use speed, or an offset.

---

## Recipe 4 — Habituation over time within a session

**Question.** Does activity decline across the session, and does the treatment change the
slope?

**Setup.** Set **time bins** on the Metrics screen (for example 60 s). Summary tables then
carry one row per animal per bin, with `bin_index`, `bin_start_s`, `bin_end_s`.

**Metrics to select.** IL-2, IL-1, IL-4, plus Z-1 if the question is zone use over time.

```r
bins <- read_csv(file.path(run, "tiny_session", "trial_activity_summary.csv"),
                 show_col_types = FALSE) |>
  filter(!is.na(bin_index)) |>
  left_join(treatments, by = "session_id")

lme4::lmer(mean_speed_cm_s ~ treatment * bin_index + (1 | session_id/individual_id),
           data = bins)
```

**The trap.** Bins are repeated measures within a session, not extra sessions — the random
structure has to keep both levels, and bins are autocorrelated, so a residual correlation
structure (`glmmTMB` with `ar1(...)`, or `nlme::lme(correlation = corAR1())`) is often the
honest model. Metrics that are not meaningful per window keep a single row with empty bin
columns; filter on `!is.na(bin_index)` rather than assuming every row is binned. Short bins
make every per-bin ratio noisy: check `n_frames_used` per bin before reading a trend.

---

## Before you report any of these

Confirm the sessions were poolable (`fps`, `n_animals`, segmentation settings — see
`PROJECT_SUMMARY.md`), state your coverage threshold and the preprocessing settings from
`manifest.json`, and record the `app_version` that produced the numbers. The full reporting
checklist is at the end of [[Statistics and Pseudoreplication]]; what can still change before
1.0 is in [[Known Issues]].
