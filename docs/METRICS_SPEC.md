# Behavioural Metrics Specification

**Status:** Draft v0.1 — implementation-ready
**Audience:** Engineers implementing `track2data/metrics/*`; reviewers;
researchers wanting to know what each number means.
**Companion docs:**

- [`../PRD.md` §5.6](../PRD.md) — high-level catalogue
- [`./ENGINE_DESIGN.md` §8](./ENGINE_DESIGN.md) — engine API
- [`./USER_WORKFLOW.md` Stage 6](./USER_WORKFLOW.md) — wizard UI
- [`./UI_DESIGN.md` Page 6](./UI_DESIGN.md) — PySide6 controls
- [`./IDTRACKERAI_FORMAT_ANALYSIS.md`](./IDTRACKERAI_FORMAT_ANALYSIS.md) — provenance of diagnostic inputs

> This document is the **canonical** definition of every metric that
> Track2Data can compute. The PRD lists *which* metrics exist; this
> document defines *what each one is and how to compute it*.

---

## 1. Scope & non-goals

**In scope.** Every metric derivable from idtracker.ai trajectory data
(`Session.raw_xy`, `Session.id_probabilities`, `Session.bbox_table`,
`Session.quality`, `Session.inconsistent_frames`) plus user-supplied
calibration and zones.

**Out of scope.** Any metric that needs video pixels (e.g. body
posture, fin beat), audio (vocalisation), or external sensors
(temperature). These belong in plug-in metric packages, not the
built-in catalogue.

---

## 2. Conventions

| Concept | Convention |
|---|---|
| Frame index | 0-based integer; `t = frame / fps` (seconds) |
| Position | `(x, y)` in pixels; calibrated outputs in cm or BL (body lengths) |
| Missing data | `NaN` in `raw_xy[:, k, :]` for animal `k` |
| Identity-aware | Per-individual columns include `individual_id` (1..N) |
| Identity-free | Group-level only; no per-individual rows |
| Time bins | Whole-session + optional `timepoint_minutes` bins from `MetricSelection.timepoint_minutes` |
| Calibration | All metrics in **two units**: native (px / px·s⁻¹) and calibrated (cm / BL) when `CalibrationConfig` is populated |
| Zones | Polygons from `ZoneSet.rois`; point-in-polygon test via `shapely.geometry.Point.within(Polygon)` |
| Tracking-quality gate | Each per-frame metric is masked out when `id_probabilities[frame, animal] < quality_threshold` (default 0.0; configurable via `MetricSelection.quality_threshold`) |

### 2.1 Body-length source for BL-calibrated outputs

Per-individual body length comes from `Session.body_length_px`, populated
by the reader from idtracker.ai's own `body_length` /
`session.json:median_body_length` value (a single session-wide scalar,
broadcast across all animals -- see `readers/idtrackerai/normaliser.py`).
When `Session.length_unit` is present, this is converted to real units by
`calibration/bodylength.py`; otherwise it stays in pixels.

**`Session.bbox_table` (the `<session>_bboxes.csv` produced by
`extract_bboxes.py`) is deliberately NOT used for calibration**, and no
future revision of this spec should reintroduce it without re-reading
`docs/EXTRACT_BBOXES_FIX.md` first. Measured on a real session, that
script's per-identity median overestimates the tracker's own
`median_body_length` by **+27.8%**, with a **1.75×** spread between
individual medians of the same species in the same arena -- because it
medians over every `is_an_individual` blob rather than the narrower
`seems_like_individual` + unicity-frame population idtracker.ai itself
uses. A correctly-filtered per-identity value (superior to the
session-wide broadcast above) requires reading
`preprocessing/list_of_blobs.pickle` directly with that filter; this is
planned but not yet implemented (format-alignment plan, Fase 6c).

`IDT_BODY_LENGTH_UNRELIABLE` and `Session.body_length_reliable` (always
`False` regardless of source -- `output_structure_idtrackerai.md`
explicitly warns this value depends on segmentation parameters and video
conditions) still gate user acknowledgement before BL-calibrated metrics
are treated as trustworthy.

### 2.2 Output schema

Every metric produces a long-format DataFrame with at least:

```
session_id | individual_id | metric_id | value | unit | t_start_s | t_end_s | timepoint_label
```

`individual_id` is `NA` for group/zone metrics. `t_start_s/t_end_s`
delimit the time window (whole session or one bin). Wide-format export
is a presentation choice handled by exporters, not metrics.

### 2.3 Required preprocessing

Most metrics assume the preprocessing pipeline (`PreprocessConfig`) has
run: gap fill, jump detection, identity-switch correction, smoothing.
Each metric below states whether it tolerates raw input.

### 2.4 Priority tiers

| Tier | Symbol | Meaning |
|---|---|---|
| Primary | P | Built by v1.0 MVP, on by default in UI |
| Optional | O | Built by v1.0, opt-in |
| Advanced | A | Built by v1.1+ |
| Diagnostic | D | Auto-computed, always exported |

---

## 3. Metric taxonomy

```
Level             Category                 IDs
─────────────────────────────────────────────────────────────────
Individual        Locomotion               IL-1, IL-2, IL-6
                  Activity / freezing      IL-4, IL-7
                  Space use                IL-3
                  Path geometry            IL-5, IL-8
Group             Social spacing           GL-1, GL-2
                  Cohesion                 GL-4, GL-6, GL-10
                  Collective motion        GL-3, GL-5, GL-8, GL-9
                  Identity-free fallback   GL-7
Zone              Occupancy                Z-1, Z-2
                  Visits                   Z-3, Z-5, Z-6
                  Flow / crossings         Z-4
Diagnostic        Coverage                 D-1
                  idtracker.ai quality     D-2, D-3, D-4, D-5
```

---

## 4. Metric catalogue

Every entry below has **the same field layout**, suitable for the
info-button modal (§6).

### 4.1 Individual locomotion

#### IL-1 — Distance travelled / path length

| Field | Value |
|---|---|
| **Manuscript label** | Total distance travelled |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy[:, k, :]` for each animal `k` |
| **Required preprocessing** | Gap-fill + smoothing recommended; raw permitted with warning |
| **Formula** | `Σ_t ‖xy[t+1, k] − xy[t, k]‖` over non-NaN frame pairs |
| **Output columns** | `individual_id`, `path_length_px`, `path_length_cm`, `path_length_bl` |
| **Units** | px / cm / BL |
| **Assumptions** | Inter-frame displacement reflects real movement (not jump artefacts) |
| **Warnings** | Under-smoothed data inflates path length; NaN gaps are skipped (not interpolated for this metric) |
| **Reference** | Standard kinematics; e.g. Romero-Ferrero et al. 2019 (idtracker.ai paper) |

#### IL-2 — Speed (mean / median / max)

| Field | Value |
|---|---|
| **Manuscript label** | Locomotor speed |
| **Level** | Individual; frame, individual time-series, trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy[:, k, :]`, `Session.video.fps` |
| **Required preprocessing** | Smoothing strongly recommended |
| **Formula** | `v[t, k] = ‖xy[t+1, k] − xy[t, k]‖ · fps`; mean/median/max over time window |
| **Output columns** | `individual_id`, `mean_speed`, `median_speed`, `max_speed` (×3 unit suffixes) |
| **Units** | px/s, cm/s, BL/s |
| **Assumptions** | Constant fps; small inter-frame displacement vs. body size |
| **Warnings** | `max_speed` is sensitive to single-frame jumps; report only after jump filter |
| **Reference** | Standard kinematics |

#### IL-3 — Distance from arena centre

| Field | Value |
|---|---|
| **Manuscript label** | Centre-distance |
| **Level** | Individual; frame time-series, trial summary |
| **Priority** | Optional |
| **Inputs** | `Session.raw_xy`, arena centre (auto-computed as mean of all ROI vertices or user-supplied centre point) |
| **Required preprocessing** | None |
| **Formula** | `d[t, k] = ‖xy[t, k] − centre‖` |
| **Output columns** | `individual_id`, `mean_centre_distance`, `time_in_centre_pct` (within radius `r = R/2` by default) |
| **Units** | px, cm, BL |
| **Assumptions** | Arena is roughly circular or a centre point is meaningful |
| **Warnings** | For non-circular arenas, "centre-distance" is interpretable only with a clearly defined origin |
| **Reference** | Open-field test paradigm (Hall 1934) |

#### IL-4 — Activity / freezing time fraction

| Field | Value |
|---|---|
| **Manuscript label** | Time active vs. inactive |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | IL-2 speed series, `threshold_bl_per_s` (default 0.1 BL/s) |
| **Required preprocessing** | Smoothing required (raw speed is noisy → false activity) |
| **Formula** | `active[t, k] = 1 if v[t, k] > threshold else 0`; `active_fraction = mean(active[:, k])`; `freezing_fraction = 1 − active_fraction` |
| **Output columns** | `individual_id`, `active_fraction`, `freezing_fraction`, `threshold_bl_per_s` |
| **Units** | dimensionless (fraction); threshold in BL/s |
| **Assumptions** | Speed < threshold ≈ true immobility, not tracking gap |
| **Warnings** | NaN frames are excluded from denominator; high NaN rates make this unreliable (see D-1) |
| **Reference** | Speed-threshold immobility is standard in zebrafish freezing assays; e.g. Stewart et al. 2012 |

#### IL-5 — Tortuosity (path length / displacement)

| Field | Value |
|---|---|
| **Manuscript label** | Path tortuosity |
| **Level** | Individual; trial summary |
| **Priority** | Optional |
| **Inputs** | IL-1 path length, start/end positions |
| **Required preprocessing** | Gap-fill + smoothing |
| **Formula** | `tortuosity = path_length / max(‖xy[end, k] − xy[start, k]‖, ε)` |
| **Output columns** | `individual_id`, `tortuosity` |
| **Units** | dimensionless |
| **Assumptions** | Straight-line displacement is a meaningful baseline |
| **Warnings** | Undefined when start == end; cap at 1e6 or report `inf` |
| **Reference** | Benhamou 2004, *J. Theor. Biol.* |

#### IL-6 — Acceleration

| Field | Value |
|---|---|
| **Manuscript label** | Locomotor acceleration |
| **Level** | Individual; frame, trial summary |
| **Priority** | Optional |
| **Inputs** | IL-2 speed time-series |
| **Required preprocessing** | Smoothing required (acceleration amplifies noise) |
| **Formula** | `a[t, k] = (v[t+1, k] − v[t, k]) · fps`; mean / median / RMS over window |
| **Output columns** | `individual_id`, `mean_abs_accel`, `rms_accel`, `max_accel` |
| **Units** | px/s², cm/s², BL/s² |
| **Assumptions** | Constant fps; well-smoothed input |
| **Warnings** | Without smoothing this is numerical noise; emit warning if smoothing is disabled |
| **Reference** | Standard kinematics |

#### IL-7 — Freezing-bout statistics

| Field | Value |
|---|---|
| **Manuscript label** | Freezing-bout count and duration |
| **Level** | Individual; trial summary |
| **Priority** | Optional |
| **Inputs** | IL-4 active/inactive boolean series, `min_bout_frames` (default 5) |
| **Required preprocessing** | Smoothing required |
| **Formula** | Run-length encode `inactive`; keep runs ≥ `min_bout_frames` |
| **Output columns** | `individual_id`, `freezing_bout_count`, `mean_freezing_duration_s`, `total_freezing_duration_s` |
| **Units** | count; seconds |
| **Assumptions** | Same as IL-4 |
| **Warnings** | Discards short pauses; min duration is study-specific |
| **Reference** | Speed-threshold bout detection; e.g. Cachat et al. 2010 |

#### IL-8 — Turn rate / heading change

| Field | Value |
|---|---|
| **Manuscript label** | Mean turn rate |
| **Level** | Individual; trial summary |
| **Priority** | Advanced |
| **Inputs** | `Session.raw_xy`; derived heading vectors |
| **Required preprocessing** | Smoothing strongly recommended |
| **Formula** | `θ[t] = atan2(Δy, Δx)`; `turn_rate = mean(|wrap(θ[t+1] − θ[t])|) · fps` |
| **Output columns** | `individual_id`, `mean_turn_rate_rad_per_s`, `median_turn_rate_rad_per_s` |
| **Units** | rad/s, or deg/s on demand |
| **Assumptions** | Heading is well-defined (i.e. speed > small ε) |
| **Warnings** | Stationary frames produce undefined heading; skip them |
| **Reference** | Couzin et al. 2002 |

### 4.2 Zone metrics

#### Z-1 — Time in each zone

| Field | Value |
|---|---|
| **Manuscript label** | Zone occupancy |
| **Level** | Zone; trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy`, `ZoneSet.rois` |
| **Required preprocessing** | None |
| **Formula** | For each zone Z: `time_s = (count of frames where xy[t, k] ∈ Z) / fps` |
| **Output columns** | `zone_name`, `individual_id` (NA if group), `time_s`, `time_pct` |
| **Units** | s, % |
| **Assumptions** | ROIs are non-overlapping (warning if they overlap) |
| **Warnings** | Point-in-polygon for NaN frames returns False (frames are dropped from numerator and denominator) |
| **Reference** | Standard ethology |

#### Z-2 — Area-corrected occupancy

| Field | Value |
|---|---|
| **Manuscript label** | Area-corrected occupancy |
| **Level** | Zone; trial summary |
| **Priority** | Optional |
| **Inputs** | Z-1 + zone polygon area |
| **Formula** | `occupancy_density = time_pct / area_pct_of_arena` |
| **Output columns** | `zone_name`, `individual_id`, `area_corrected_occupancy` |
| **Units** | dimensionless ratio |
| **Assumptions** | Arena bounding polygon is defined or inferred from union of zones |
| **Warnings** | If no arena polygon, normalise by union-of-zones area + warn |
| **Reference** | Choice-experiment R script provenance |

#### Z-3 — Zone visit count

| Field | Value |
|---|---|
| **Manuscript label** | Zone visits |
| **Level** | Zone; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 in/out boolean series |
| **Formula** | Count rising edges (False → True) in zone-membership series |
| **Output columns** | `zone_name`, `individual_id`, `visit_count` |
| **Units** | count |
| **Assumptions** | A "visit" is any zero-or-more-frame stay; configurable `min_visit_frames` (default 1) |
| **Warnings** | Sensitive to flicker on zone boundaries; smoothing or `min_visit_frames` mitigates |
| **Reference** | Standard ethology |

#### Z-4 — Zone transitions

| Field | Value |
|---|---|
| **Manuscript label** | Inter-zone transitions |
| **Level** | Zone-pair; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (default 1) |
| **Formula** | For each consecutive frame pair, increment `transitions[zone_a → zone_b]` if zone_a ≠ zone_b |
| **Output columns** | `from_zone`, `to_zone`, `individual_id`, `transition_count` |
| **Units** | count |
| **Assumptions** | Single-zone-per-frame (resolve overlaps with priority list or longest-overlap) |
| **Warnings** | Identity-free sessions: transitions are counted on NN-matched tracklets, not individuals. Sensitive to flicker on zone boundaries; `min_dwell_frames` debounces a visit shorter than the threshold by merging the transitions either side of it into one continuous stay. |
| **Reference** | Choice-experiment R script |

#### Z-5 — Entry / exit timestamps

| Field | Value |
|---|---|
| **Manuscript label** | Zone entry/exit times |
| **Level** | Event log |
| **Priority** | Optional |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (default 1) |
| **Formula** | Emit one row per edge transition with `t_s = frame / fps`; a run inside a zone shorter than `min_dwell_frames` produces no enter/exit events at all |
| **Output columns** | `zone_name`, `individual_id`, `event` (enter/exit), `t_s`, `frame` |
| **Units** | seconds |
| **Reference** | Standard ethology |

#### Z-6 — Latency to first entry

| Field | Value |
|---|---|
| **Manuscript label** | Latency to first zone entry |
| **Level** | Zone; trial summary |
| **Priority** | Optional |
| **Inputs** | Z-5 event log; forwards `min_dwell_frames` to Z-5 |
| **Formula** | Per zone, per individual: `t_s` of first "enter" event (after Z-5's debounce) |
| **Output columns** | `zone_name`, `individual_id`, `first_entry_t_s` |
| **Units** | seconds |
| **Warnings** | NaN when the individual never enters; encode as `inf` for sortability |
| **Reference** | Standard ethology |

### 4.3 Social spacing

#### GL-1 — Nearest-neighbour distance (NND)

| Field | Value |
|---|---|
| **Manuscript label** | Nearest-neighbour distance |
| **Level** | Group (per frame averaged across individuals); trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy[t, :, :]` per frame |
| **Required preprocessing** | None (but jump correction recommended) |
| **Formula** | `nnd[t] = mean_k min_{j≠k} ‖xy[t, k] − xy[t, j]‖`, computed via `scipy.spatial.cKDTree` |
| **Output columns** | `mean_nnd_px`, `mean_nnd_cm`, `mean_nnd_bl` (and time-series option) |
| **Units** | px, cm, BL |
| **Assumptions** | All `N_animals` are present in the frame (NaN-bearing frames are skipped) |
| **Warnings** | With NaN ≥ 1 in a frame, frame is excluded; report % skipped |
| **Reference** | Pitcher 1973; Krause & Ruxton 2002, *Living in Groups* |

#### GL-2 — Inter-individual distance (IID)

| Field | Value |
|---|---|
| **Manuscript label** | Mean inter-individual distance |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy[t, :, :]` |
| **Formula** | `iid[t] = mean(pdist(xy[t, :, :]))`, computed via `scipy.spatial.distance.pdist` |
| **Output columns** | `mean_iid_px`, `mean_iid_cm`, `mean_iid_bl` |
| **Units** | px, cm, BL |
| **Reference** | Krause & Ruxton 2002 |

### 4.4 Cohesion & collective motion

#### GL-3 — Polarisation

| Field | Value |
|---|---|
| **Manuscript label** | Polarisation order parameter (Φ) |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary |
| **Inputs** | Heading vectors per individual per frame (computed from `Session.raw_xy`) |
| **Required preprocessing** | Smoothing required for stable headings |
| **Formula** | `Φ[t] = ‖(1/N) Σ_k ê_k[t]‖` where `ê_k` is the unit heading vector for animal `k` |
| **Output columns** | `mean_polarisation`, `median_polarisation`, time-series option |
| **Units** | dimensionless ∈ [0, 1] |
| **Assumptions** | All N animals present and moving (heading is undefined for stationary fish — they're excluded from the sum) |
| **Warnings** | Mostly stationary group → polarisation is unreliable; report N(effective) per frame |
| **Reference** | Couzin et al. 2002, *J. Theor. Biol.* 218, 1–11; Vicsek et al. 1995 |

#### GL-4 — Convex hull area (school area)

| Field | Value |
|---|---|
| **Manuscript label** | School area (convex hull) |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy[t, :, :]` |
| **Formula** | `area[t] = scipy.spatial.ConvexHull(xy[t, :, :]).volume` (in 2-D, `.volume` returns area) |
| **Output columns** | `mean_hull_area_px2`, `mean_hull_area_cm2` |
| **Units** | px², cm² |
| **Assumptions** | N ≥ 3 (hull undefined for fewer points) |
| **Warnings** | Hull collapses to a line / point when fish are colinear; emit warning if degenerate ≥ 5% of frames |
| **Reference** | Buhl et al. 2006, *Science* |

#### GL-5 — Centroid speed / school speed

| Field | Value |
|---|---|
| **Manuscript label** | Group centroid speed |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy`, `Session.video.fps` |
| **Formula** | `C[t] = (1/N) Σ_k xy[t, k]`; `centroid_speed[t] = ‖C[t+1] − C[t]‖ · fps` |
| **Output columns** | `centroid_x`, `centroid_y` (frame-level); `mean_centroid_speed`, `median_centroid_speed` (summary) |
| **Units** | px, cm, BL; speed in px/s, cm/s, BL/s |
| **Assumptions** | Fewer-than-N animals → centroid is over the available `M(t)`, emit warning if `M(t) < N` ≥ 5% |
| **Reference** | Standard kinematics; e.g. Tunstrøm et al. 2013, *PLoS Comp Bio* |

#### GL-6 — Group cohesion index

| Field | Value |
|---|---|
| **Manuscript label** | Group cohesion |
| **Level** | Group (trial summary) |
| **Priority** | Optional |
| **Inputs** | GL-1 mean NND or GL-2 mean IID, selected via `cfg['cohesion_source']` |
| **Formula** | `cohesion = 1 / mean_nnd` (`cohesion_source='nnd'`, **default**) or `1 / mean_iid` (`cohesion_source='iid'`) |
| **Output columns** | `cohesion_index` |
| **Units** | BL⁻¹ |
| **Assumptions** | Calibration available (BL) |
| **Warnings** | Without calibration, expressed in 1/px (interpretability low) |
| **Reference** | Krause & Ruxton 2002 |

> **Implementation note:** this metric was NND-only (not user-selectable)
> before `cohesion_source` was added (§8 open question 3), so the default
> is `'nnd'` -- preserving the historical value with zero change for any
> project that doesn't touch the new parameter -- even though an earlier
> draft of this table implied IID as the primary formula.

#### GL-7 — NN-matched speed (identity-free)

| Field | Value |
|---|---|
| **Manuscript label** | Frame-to-frame matched speed |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary (when identity-free) |
| **Inputs** | `Session.raw_xy`; greedy or Hungarian matching of points across consecutive frames |
| **Formula** | For each `t`: solve assignment problem on `xy[t, :, :] ↔ xy[t+1, :, :]` minimising total distance; speed = matched distance · fps |
| **Output columns** | `mean_matched_speed`, `median_matched_speed` |
| **Units** | px/s, cm/s, BL/s |
| **Assumptions** | Animals do not swap positions faster than 1 frame; large jumps degrade matching |
| **Warnings** | Always emits a "matched, not identity-stable" note in the manifest |
| **Reference** | Standard tracking-fallback approach |

#### GL-8 — Angular momentum / rotational order

| Field | Value |
|---|---|
| **Manuscript label** | Rotational order parameter (M) |
| **Level** | Group (per frame); trial summary |
| **Priority** | Optional |
| **Inputs** | Per-individual position vectors, heading vectors, group centroid |
| **Required preprocessing** | Smoothing required |
| **Formula** | `M[t] = ‖(1/N) Σ_k r̂_k(t) × ê_k(t)‖`, where `r̂_k = (xy[t,k] − C[t]) / ‖…‖` and `ê_k` is unit heading; 2-D cross product is a scalar |
| **Output columns** | `mean_rotational_order`, `median_rotational_order`, time-series |
| **Units** | dimensionless ∈ [0, 1] |
| **Assumptions** | Distinguishes milling (M high, Φ low) from polarised motion (Φ high, M low) |
| **Warnings** | Same heading-stability caveat as GL-3 |
| **Reference** | Couzin et al. 2002, *J. Theor. Biol.*; Tunstrøm et al. 2013, *PLoS Comp Bio* |

#### GL-9 — Group centroid position

| Field | Value |
|---|---|
| **Manuscript label** | Group centroid position |
| **Level** | Group (frame time-series); trial summary |
| **Priority** | Optional |
| **Inputs** | `Session.raw_xy` |
| **Formula** | `C[t] = (1/N) Σ_k xy[t, k]` (the centroid is also a GL-5 by-product; this metric exposes it as a primary output rather than a side column) |
| **Output columns** | `t_s`, `centroid_x`, `centroid_y` (with unit-suffixed copies) |
| **Units** | px, cm, BL |
| **Reference** | Standard kinematics |

#### GL-10 — Group expansion

| Field | Value |
|---|---|
| **Manuscript label** | Group expansion (centroid spread) |
| **Level** | Group (per frame); trial summary |
| **Priority** | Optional |
| **Inputs** | `Session.raw_xy`, `C[t]` |
| **Formula** | `σ[t] = sqrt( (1/N) Σ_k ‖xy[t, k] − C[t]‖² )` |
| **Output columns** | `mean_group_spread_px`, `mean_group_spread_cm`, `mean_group_spread_bl` |
| **Units** | px, cm, BL |
| **Assumptions** | Complement to GL-4 (hull); easier to compute and tolerates N < 3 |
| **Reference** | Tunstrøm et al. 2013 |

### 4.5 Identity-free variants

| Metric | Identity-free derivable? | Note |
|---|---|---|
| GL-1 NND | ✅ | Unordered point set per frame |
| GL-2 IID | ✅ | Unordered point set per frame |
| GL-3 Polarisation | ❌ | Heading requires per-individual tracklets |
| GL-4 Hull area | ✅ | Frame-by-frame point set |
| GL-5 Centroid speed | ✅ | Frame-by-frame centroid |
| GL-7 NN-matched speed | ✅ | Designed for identity-free sessions |
| GL-8 Rotational order | ❌ | Requires headings |
| GL-9 Centroid position | ✅ | Frame-by-frame centroid |
| GL-10 Group spread | ✅ | Frame-by-frame centroid |

### 4.6 Tracking-quality diagnostics

These are auto-computed for **every** session, regardless of user
selection, and exported alongside the metrics CSV in a separate
`quality.csv` file (and as a second sheet in the Excel export).

#### D-1 — Missing-data proportion

| Field | Value |
|---|---|
| **Manuscript label** | Tracking coverage |
| **Level** | Per individual + session summary |
| **Priority** | Diagnostic (always on) |
| **Inputs** | `Session.raw_xy` |
| **Formula** | `coverage[k] = mean(~isnan(raw_xy[:, k, 0]))`; `session_coverage = mean(coverage)` |
| **Output columns** | `individual_id`, `coverage_fraction`, `nan_frames_count` |
| **Units** | dimensionless ∈ [0, 1] |
| **Reference** | Tracking-pipeline convention |

#### D-2 — Tracking accuracy

| Field | Value |
|---|---|
| **Manuscript label** | idtracker.ai accuracy |
| **Level** | Session summary |
| **Priority** | Diagnostic (always on) |
| **Inputs** | `Session.quality["estimated_accuracy"]`, `Session.quality["fraction_identified"]` |
| **Formula** | Pass-through |
| **Output columns** | `estimated_accuracy`, `fraction_identified` |
| **Units** | dimensionless |
| **Reference** | Romero-Ferrero et al. 2019, *Nat. Methods* (idtracker.ai) |

#### D-3 — ID-probability distribution

| Field | Value |
|---|---|
| **Manuscript label** | Identity confidence |
| **Level** | Per individual; session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.id_probabilities` (shape `(N, M)`) |
| **Formula** | Per individual: median, p10, p90 of probability over time; fraction ≥ 0.9 |
| **Output columns** | `individual_id`, `id_prob_median`, `id_prob_p10`, `id_prob_p90`, `id_prob_frac_above_0p9` |
| **Units** | probability ∈ [0, 1] |
| **Warnings** | When `id_probabilities` is None (older version), emit `IDT_DICT_MISSING_KEY` and set columns to NaN |
| **Reference** | idtracker.ai docs |

#### D-4 — Inconsistent-frame count

| Field | Value |
|---|---|
| **Manuscript label** | Inconsistent-frame count |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.inconsistent_frames` (a `set[int]` populated by the reader) |
| **Formula** | `n_inconsistent = len(inconsistent_frames)`; `frac_inconsistent = n_inconsistent / n_frames` |
| **Output columns** | `inconsistent_frame_count`, `inconsistent_frame_fraction` |
| **Units** | count, fraction |
| **Reference** | Custom post-processing pipeline (`*_bboxes.csv` parser) |

#### D-5 — Identity stability flag

| Field | Value |
|---|---|
| **Manuscript label** | Identity stability |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.has_stable_identities`, `Session.quality["fraction_identified"]` |
| **Formula** | Pass-through + categorical (`stable`, `weak`, `identity_free`) |
| **Output columns** | `identity_stability_status` |
| **Reference** | PRD §5.2 (FR-IMP-3); fraction-identified threshold |

---

## 5. Engine implementation map

Every metric ID maps to a concrete class in `track2data/metrics/*.py`.

| Metric ID(s) | Module | Class | Notes |
|---|---|---|---|
| IL-1, IL-2, IL-3, IL-5 | `metrics/individual.py` | `PathLength`, `Speed`, `CentreDistance`, `Tortuosity` | scipy not required |
| IL-4, IL-7 | `metrics/individual.py` | `Activity`, `FreezingBouts` | Depend on IL-2 speed series |
| IL-6, IL-8 | `metrics/individual.py` | `Acceleration`, `TurnRate` | Smoothing-dependent |
| GL-1, GL-2, GL-6 | `metrics/group.py` | `NND`, `IID`, `Cohesion` | `scipy.spatial.cKDTree`, `pdist` |
| GL-3, GL-8 | `metrics/group.py` | `Polarisation`, `RotationalOrder` | Vectorised; np-only |
| GL-4 | `metrics/group.py` | `ConvexHullArea` | `scipy.spatial.ConvexHull` |
| GL-5, GL-9, GL-10 | `metrics/group.py` | `CentroidSpeed`, `CentroidPosition`, `GroupSpread` | Shared centroid cache |
| GL-7 | `metrics/identity_free.py` | `NNMatchedSpeed` | `scipy.optimize.linear_sum_assignment` |
| Z-1..Z-6 | `metrics/zone.py` | `TimeInZone`, `AreaCorrectedTime`, `VisitCount`, `ZoneTransitions`, `EntryExitEvents`, `LatencyFirstEntry` | `shapely` for point-in-polygon |
| D-1..D-5 | `metrics/diagnostic.py` (NEW FILE) | `Coverage`, `TrackingAccuracy`, `IdProbabilityStats`, `InconsistentFrames`, `IdentityStability` | Always-on |

### 5.1 Shared computations (no duplicated work)

A per-session `_kinematics_cache` memoises speed, acceleration, heading,
and centroid. Metrics that need them request from the cache; the cache
is built once per session per pipeline run.

### 5.2 `Metric.documentation` field (for info button)

The abstract base in `track2data/metrics/base.py` exposes a
`documentation: MetricDocumentation` attribute. Each concrete metric
class fills its `documentation` from §4 above verbatim — this spec is
the single source of truth, and the info-modal (§6) renders the
attached `MetricDocumentation`.

```python
class MetricDocumentation(BaseModel):
    definition: str
    formula_plain: str
    formula_latex: str | None = None
    inputs: list[str]
    assumptions: list[str]
    warnings: list[str]
    citation: str | None = None
    citation_doi: str | None = None
```

```python
class Metric(ABC):
    id: str
    name: str
    label: str
    level: Literal["individual", "group", "zone", "diagnostic"]
    priority: Literal["primary", "optional", "advanced", "diagnostic"]
    requires_identity: bool = False
    output_columns: list[str]
    documentation: MetricDocumentation
```

---

## 6. UI info-button architecture

### 6.1 Surface

In `UI_DESIGN.md` Page 6, each row in the metric-selection list becomes:

```
[ ✓ ]  Speed (mean/median/max)         ⓘ   ⚙
```

Note the row shows only the display label ("Speed (mean/median/max)"),
never the registry id ("IL-2") or the snake_case internal name
("speed") — neither is something a researcher reads to pick a metric.

- ✓ — selection checkbox (existing)
- ⓘ — info icon
- ⚙ — per-metric config — **stub in v1**: present on every row, but
  clicking it shows a "Not yet implemented" message. No metric has a
  config schema and Screen 6.3 does not exist yet.

### 6.2 Click behaviour

Click on ⓘ opens a modal `MetricInfoDialog(metric: Metric)`:

```
┌─ Speed ─────────────────────────────────── ✕ ─┐
│                                              │
│  Manuscript label: Locomotor speed           │
│  Level: Individual                           │
│                                              │
│  Definition                                  │
│  ─────────                                   │
│  Mean / median / maximum locomotor speed of  │
│  each tracked individual.                    │
│                                              │
│  Formula                                     │
│  ───────                                     │
│  v(t, k) = ||xy(t+1, k) − xy(t, k)|| · fps   │
│                                              │
│  Inputs                                      │
│  ──────                                      │
│  • Session.raw_xy                            │
│  • Session.video.fps                         │
│                                              │
│  Assumptions / warnings                      │
│  ──────────────────────                      │
│  • Constant fps                              │
│  • Max speed sensitive to single-frame jumps │
│                                              │
│  Reference                                   │
│  ─────────                                   │
│  Standard kinematics                         │
│                                              │
│                            [ Copy citation ] │
└──────────────────────────────────────────────┘
```

### 6.3 Close behaviour

The modal closes on:

- title-bar ✕
- `Escape` key (QDialog's own default behaviour)
- click outside the modal's rect — implemented as a QApplication-wide
  event filter installed for the dialog's lifetime, checking whether a
  `MouseButtonPress` falls outside `self.rect()`

### 6.4 Implementation

`MetricInfoDialog` is a small `QDialog` subclass that:

1. Receives a `Metric` class.
2. Reads `metric.documentation` (the `MetricDocumentation` model from §5.2).
3. Renders the panels above as plain text in a read-only `QTextEdit`
   (no Markdown/LaTeX rendering — `formula_latex`, when present, is
   shown as its raw source string).
4. Provides a "Copy citation" button that copies the citation string
   (plus DOI, when present) to the clipboard.
5. Relies on `QDialog`'s own default Escape handling, plus a
   QApplication-wide event filter installed while shown/removed when
   hidden, for outside-click closure.

### 6.5 Visibility rule

Show the ⓘ icon **only when** `metric.documentation.citation is not
None` *or* `metric.documentation.formula_plain is not None`. Metrics
without a published formula or canonical reference (e.g. ad-hoc
diagnostic outputs) get a tooltip instead, not the modal.

Note: `MetricDocumentation.formula_plain` (§5.2) is currently a
required, non-`None` `str` field on every built-in metric, so this
rule never actually hides the ⓘ icon today. It's implemented as
specified for forward compatibility, in case a future metric type
legitimately has no formula.

### 6.6 Source of truth

The `documentation` content for each built-in metric is generated
**from this spec document**. Future contributors who add a metric MUST
add a corresponding section to `METRICS_SPEC.md` before merging — the
modal is the user-facing surface of that spec.

---

## 7. Configuration: `MetricSelection`

```python
class MetricSelection(BaseModel):
    individual: list[str] = []         # IL-* IDs
    group: list[str] = []              # GL-* IDs
    zone: list[str] = []               # Z-* IDs
    diagnostic: list[str] = []         # D-* IDs (default: all D-* always on)
    timepoint_minutes: int | None = None
    quality_threshold: float = 0.0     # Mask per-frame metrics when id_prob below
```

`diagnostic` defaults to `[]` in the manifest but the engine treats
every `D-*` metric as always-on regardless of selection. The list is
exposed so future per-user opt-outs are non-breaking.

---

## 8. Open questions

1. **Citations** — `MetricDocumentation.citation_doi` is the place to
   add DOI links once collected. Initial draft uses author/year only.
2. **Zone overlap policy** — default "longest-overlap-wins"; settable
   per project. To be confirmed during Stage 4 implementation.
3. **Per-metric config** — resolved at the engine level: metrics
   declare a `parameters: list[MetricParameter]` schema
   (`track2data/metrics/base.py`), and `MetricSelection.config` (keyed
   `metric_id -> {param_name: value}`) now actually reaches
   `Metric.compute()`'s `cfg` argument via `Engine._effective_cfg()` --
   previously this path existed in several metrics but nothing ever
   called it, so it was dead code. Parameters that are a property of
   the session's own tracked arena rather than a user choice (IL-3's
   centre-radius, Z-2's zone areas) are derived per session
   (`track2data/metrics/derived.py`) instead of stored in
   `MetricSelection.config`. Every parameter this question named is now
   declared and implemented: IL-3's `inner_radius_fraction`, IL-4's
   `threshold_multiplier`, IL-7's `min_bout_frames` (already read, now
   also declared), GL-6's `cohesion_source` (`'nnd'`/`'iid'`, default
   `'nnd'` to preserve the historical NND-only behaviour), plus
   Z-3/Z-4/Z-5/Z-6's `min_visit_frames`/`min_dwell_frames` boundary-
   flicker debounce. Still open: the GUI's ⚙ button remains a stub (no
   `MetricConfigDialog` yet) -- the engine-side plumbing and the
   parameters themselves are done; wiring them to the screen is tracked
   separately.
