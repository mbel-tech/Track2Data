# Statistics and pseudoreplication

**Applies to:** Track2Data v0.1.0 and later.

Track2Data computes the numbers; it cannot choose your unit of replication. This page is
about the decision that most often invalidates a behavioural-tracking analysis: treating
frames, or animals sharing a tank, as independent observations.

The short version of the traps is in
[`examples/README.md`](https://github.com/mbel-tech/Track2Data/blob/main/examples/README.md#four-ways-to-get-this-wrong),
and both starter scripts in
[`examples/analysis/`](https://github.com/mbel-tech/Track2Data/blob/main/examples/analysis)
implement the model described below. This page is the longer form: which unit applies to
which metric family, and what to do about it.

## The nesting Track2Data exports

```
frame  →  individual (individual_id)  →  session (session_id)  →  treatment / batch / day
```

Frames are never the unit of replication. They are autocorrelated by construction — an
animal's position at frame *t+1* is mostly its position at frame *t* — so a per-frame test
on 20,000 frames reports a precision you do not have. Every summary metric already
aggregates over frames; use the summary.

Animals within a session are not independent either. They see each other, share water, and
share every disturbance. For group-living species that is not a nuisance term, it is the
biology.

## What the unit of replication is, by metric family

| Family | What a row is | Unit of replication | Model |
|---|---|---|---|
| **IL-\*** individual locomotion | one per animal per session | the animal, nested in session | `metric ~ treatment + (1 \| session_id)` |
| **Z-3 … Z-9** zone metrics that follow a slot | one per animal per zone | the animal, nested in session; zone is a within-animal factor | `+ (1 \| session_id)`, zone as a fixed factor or analysed per zone |
| **Z-1, Z-2, Z-8** occupancy | per animal, or **pooled** on identity-free sessions | the animal, or the session when pooled | check for an `individual_id`; pooled rows are session-level |
| **GL-\*** group metrics | **one per session** | the session | ordinary regression on session-level rows; *n* = number of sessions |
| **D-\*** diagnostics | per animal or per session | not an outcome — a covariate or a filter | use for weighting and exclusion, not as a dependent variable |

The row that catches people out is **GL-\***. A tank of eight fish yields one nearest-neighbour
distance, one polarisation, one cohesion index. Eight animals do not buy eight observations
of a group property, so a shoaling study needs replicate *tanks*, not replicate fish.

With time bins switched on, bins are repeated measures *within* a session, not new sessions:
add `bin_index` as a fixed effect (or a smooth term) and keep the session random effect.

## Before pooling sessions at all

Two differences make sessions incomparable rather than merely variable:

- **Frame rate** scales speed, acceleration and path length.
- **Group size** changes every group metric by construction.

`sessions.csv` carries `fps`, `duration_s`, `n_frames`, `n_animals` and `is_calibrated` so
this is checkable in one line, and both starter scripts warn before modelling. The engine
also flags sessions whose idtracker.ai segmentation parameters, `resolution_reduction` or
`id_image_size` differ — body length and area are defined by those, and identity matching
across sessions needs them equal. Read `PROJECT_SUMMARY.md` from the run before you pool.

```r
if (n_distinct(sessions$fps) > 1) stop("speed and path length are not comparable")
```

## Totals, rates and unequal duration

`path_length_*`, `visit_count`, `freezing_bout_count`, zone transitions and every other
count or total scale with how long the session ran. A session 20 % longer produces a 20 %
larger value for identical behaviour.

- Prefer a rate (`mean_speed_*`, `*_fraction`, `*_pct`) when one exists.
- For counts, model the total with an exposure offset rather than dividing:

```r
glmmTMB::glmmTMB(visit_count ~ treatment + offset(log(duration_s)) + (1 | session_id),
                 family = poisson, data = individual)
```

## Bounded ratios need bounded models

`time_pct`, every `frac_*` column, `active_fraction`, `freezing_fraction` and the
polarisation means live in [0, 1]; `jacobs_d` lives in [−1, 1]. A Gaussian model on these
predicts impossible values near the bounds and understates the variance of extreme cases.
Use beta regression (`glmmTMB(family = beta_family())`, `betareg`), or a binomial model on
the underlying frame counts when you have them, or logit-transform and say so.

A fraction computed from few frames is far noisier than one computed from many, and the two
look identical in a table. Join **D-11** and either weight by `n_frames_used` or exclude
individuals below a coverage threshold you state in your methods:

```python
quality = long[long.metric_id == "D-11"].pivot_table(
    index=["session_id", "individual_id"], columns="column", values="value"
).reset_index()
usable = quality.loc[quality.frac_frames_used >= 0.80, ["session_id", "individual_id"]]
```

Pick the threshold before you look at the outcome, not after.

## Headings are circular

`heading_rad` and the IL-11 circular statistics are angles. Do not take arithmetic means,
SDs or ordinary regressions of them: the mean of 350° and 10° is 0°, not 180°. Use circular
statistics (`circular` in R, `scipy.stats.circmean`, `pingouin.circ_*`); IL-11 already
reports `resultant_length` and `rayleigh_p` for exactly this reason.

## Preprocessing choices are analysis choices

Smoothing window, `max_gap_frames` and whether identity-switch correction ran all change
the numbers — on the shipped example, the freezing-bout count moves 6.7 % across a
preprocessing grid while path length moves 1.2 %. They are recorded in `manifest.json`;
report them in your methods, and if a result sits near your significance threshold, check
whether it survives a different window:

```bash
track2data sensitivity project.t2d.json -o sensitivity/
```

That writes a per-column coefficient of variation across a grid of smoothing windows and
`max_gap_frames` values. It deliberately prints no robust/not-robust verdict: where that
line sits depends on the effect size you are claiming.

## Multiplicity

The long table makes it trivial to test 50 metrics against one treatment, and equally
trivial to find a significant one by chance. Decide which metrics are primary before you
run the analysis, state the rest as exploratory, and correct within families of related
outcomes. `metric_id` is in every row, so pre-registering a list of ids is enough.

## Reporting checklist

State, in the methods: Track2Data `app_version` and `project_hash` from `manifest.json`;
the preprocessing settings; the calibration mode and whether values are in cm or body
lengths; the coverage threshold and how many individuals it excluded; the bout criterion
actually applied (`bout_criterion_effective`, `min_bout_frames_used`); the random-effects
structure; and the unit of replication with *n* at that level — not the number of animals,
unless that is genuinely the level you analysed.
