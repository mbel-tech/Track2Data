# Starter analysis of a Track2Data export, in R.
#
#   Rscript examples/analysis/analyse.R out/
#
# Reads metrics_long.csv, joins the codebook for units, joins D-11 for data
# quality, and fits the model this design actually calls for -- animals
# nested in sessions, not treated as independent.
#
# It is a starting point, not a recommendation for your experiment. The
# model at the bottom assumes you have a between-session treatment; adapt it.

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
  library(readr)
  library(lme4)
  library(lmerTest)   # p-values for lmer; drop if you prefer not to have them
})

args <- commandArgs(trailingOnly = TRUE)
run_dir <- if (length(args) > 0) args[1] else "out"

# ── load ──────────────────────────────────────────────────────────────────────

# One row per measured value, across every metric level.
long <- list.files(run_dir, pattern = "^metrics_long\\.csv$",
                   recursive = TRUE, full.names = TRUE) |>
  lapply(read_csv, show_col_types = FALSE) |>
  bind_rows()

# What each column means, in what unit, from which paper.
codebook <- read_csv(file.path(run_dir, "codebook.csv"), show_col_types = FALSE)

# Recording facts that decide whether sessions are comparable at all.
sessions <- read_csv(file.path(run_dir, "sessions.csv"), show_col_types = FALSE)

# ── check the sessions are poolable BEFORE modelling them ─────────────────────

# This is not boilerplate. fps scales speed, acceleration and path length;
# group size changes every group metric by construction. Pooling across
# either without accounting for it produces a wrong answer that looks fine.
if (n_distinct(sessions$fps) > 1) {
  warning("Sessions differ in frame rate: ",
          paste(unique(sessions$fps), collapse = ", "),
          ". Speed and path length are not comparable across them. ",
          "Model fps as a covariate, or analyse the groups separately.")
}
if (n_distinct(sessions$n_animals) > 1) {
  warning("Sessions differ in group size. Group-level metrics ",
          "(GL-*) are not comparable across them.")
}

cat("\n-- sessions --\n")
sessions |>
  select(session_id, fps, duration_s, n_animals, is_calibrated) |>
  print(n = Inf)

# ── data quality: how much of each value is real? ─────────────────────────────

# D-11 reports, per individual, how many frames the metrics actually used and
# what fraction of those were measured rather than interpolated. A ratio
# computed from 200 frames and one computed from 20,000 look identical in a
# table; this is how you tell them apart.
quality <- long |>
  filter(metric_id == "D-11") |>
  select(session_id, individual_id, column, value) |>
  pivot_wider(names_from = column, values_from = value)

cat("\n-- data quality per individual --\n")
print(quality)

MIN_COVERAGE <- 0.80   # state whatever you choose in your methods section
usable <- quality |>
  filter(frac_frames_used >= MIN_COVERAGE) |>
  select(session_id, individual_id)

# ── build a tidy per-individual table ─────────────────────────────────────────

individual <- long |>
  filter(is.na(zone_name), !is.na(individual_id), metric_id != "D-11") |>
  inner_join(usable, by = c("session_id", "individual_id")) |>
  select(session_id, individual_id, column, value) |>
  pivot_wider(names_from = column, values_from = value)

cat("\n-- per-individual metrics --\n")
print(individual)

# Units, straight from the codebook -- no guessing from the column name.
unit_of <- function(col) {
  codebook |> filter(column == col) |> pull(unit) |> unique() |> head(1)
}
cat("\npath_length_cm is measured in:", unit_of("path_length_cm"), "\n")
cat("time_pct is measured in:       ", unit_of("time_pct"),
    "  <- a FRACTION, not a percentage\n")

# ── the model ─────────────────────────────────────────────────────────────────

# The random intercept for session_id is the point. Four fish in one tank are
# not four independent observations: they interact, share water, and share
# every disturbance. Dropping (1 | session_id) inflates n by the group size
# and shrinks every p-value to match.
#
# With one session in the example there is nothing to estimate that variance
# from, so this is written out rather than run. With several sessions and a
# between-session treatment, uncomment it.

# individual <- individual |>
#   left_join(select(sessions, session_id, duration_s, fps), by = "session_id")
#
# model <- lmer(
#   mean_speed_cm_s ~ treatment + (1 | session_id),
#   data = individual
# )
# print(summary(model))
#
# For a *total* rather than a rate -- path length, visit counts, bout counts --
# unequal session durations matter. Use an offset instead of the raw total:
#
# model_total <- glmmTMB::glmmTMB(
#   n_visits ~ treatment + offset(log(duration_s)) + (1 | session_id),
#   family = poisson, data = individual
# )

if (n_distinct(individual$session_id) < 2) {
  cat("\nOnly one session here, so the mixed model is left commented out:\n",
      "there is no between-session variance to estimate from a single tank.\n")
}
