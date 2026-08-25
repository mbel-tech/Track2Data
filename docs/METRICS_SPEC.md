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
                  Segmentation / identity  D-6, D-7, D-8, D-9
```

---

## 4. Metric catalogue

Every entry below has **the same field layout**, suitable for the
info-button modal (§6).

> Each entry's **Reference** row is generated from that metric's
> `MetricDocumentation.citation` / `.citation_doi` in the code, which is
> the single source of truth. The same data is published as a
> machine-readable table in
> [`METRIC_REFERENCES.csv`](./METRIC_REFERENCES.csv), regenerated with
> `python scripts/generate_metric_references.py`.
> `tests/test_metric_references_consistency.py` fails if the code, this
> document, and that CSV ever disagree.

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
| **Reference** | Standard kinematics |

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
| **Inputs** | `Session.raw_xy`; arena centre and radius, both **derived per session** — never user-supplied (see below) |
| **Required preprocessing** | Zone assignment, when zones are defined (supplies `main_zone`) |
| **Formula** | `d[t, k] = ‖xy[t, k] − centre[k]‖` |
| **Output columns** | `individual_id`, `mean_centre_distance`, `time_in_centre_pct` (within radius `r = R · inner_radius_fraction`, default 0.5) |
| **Units** | px, cm, BL |
| **Assumptions** | Arena is roughly circular or a centre point is meaningful |
| **Warnings** | For non-circular arenas, "centre-distance" is interpretable only with a clearly defined origin |
| **Parameters** | `inner_radius_fraction` (float, default 0.5). `centre` / `arena_radius` / `centres` / `arena_radii` are `derived=True` and cannot be overridden. |

> **Where the centre comes from.** It is derived in
> `track2data/metrics/derived.py`, not supplied by the user — a value
> hand-set in `MetricSelection.config` for any of these keys is
> discarded. The centre is the **bounding-box midpoint** of the
> project's `main`-level zone; the radius is the **inscribed** half-
> extent (`min` of the two half-extents, the largest circle fitting
> inside the arena). With no zones defined, both fall back to the video
> frame's own centre and half-shorter-dimension.
>
> **Each animal is measured from the arena it occupies.** Under the
> `exclusive_rois` layout — several separate `main` arenas, which the
> pipeline explicitly supports — one shared centre would sit in the
> empty gap between arenas, so every distance would be measured from a
> point no animal ever visits. `centres` / `arena_radii` therefore carry
> one entry per animal, assigned from the *modal* arena in that animal's
> own `main_zone` column (modal, so a few stray boundary frames can't
> move it). An animal never seen inside any arena falls back to the
> session-level `centre` / `arena_radius`, which is the largest arena.
> With a single arena every entry is identical, so the common case has
> no special path.
| **Reference** | Schnörr et al. 2012, Behav. Brain Res. 228(2):367-374 (thigmotaxis in larval zebrafish); paradigm originates with Hall 1934's open-field test — DOI [10.1016/j.bbr.2011.12.016](https://doi.org/10.1016/j.bbr.2011.12.016) |

#### IL-4 — Activity / freezing time fraction

| Field | Value |
|---|---|
| **Manuscript label** | Time active vs. inactive |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | IL-2 speed series; `threshold_px_s`, auto-computed when unset |
| **Required preprocessing** | Smoothing required (raw speed is noisy → false activity) |
| **Formula** | `active[t, k] = 1 if v[t, k] > threshold else 0`; `active_fraction = mean(active[:, k])`; `freezing_fraction = 1 − active_fraction` |
| **Output columns** | `individual_id`, `active_fraction`, `freezing_fraction`, `threshold_px_s` |
| **Units** | dimensionless (fraction); threshold in px/s |
| **Parameters** | `threshold_px_s` (float, px/s, **no default** — when unset the threshold is `mean(speed) * threshold_multiplier`, computed from this session's own data); `threshold_multiplier` (float, dimensionless, default 0.1) |
| **Assumptions** | Speed < threshold ≈ true immobility, not tracking gap |
| **Warnings** | NaN frames are excluded from denominator; high NaN rates make this unreliable (see D-1) |
| **Reference** | Stewart et al. 2012, Neuropharmacology 62(1):135-143 (speed-threshold immobility in zebrafish anxiety assays) — DOI [10.1016/j.neuropharm.2011.07.037](https://doi.org/10.1016/j.neuropharm.2011.07.037) |

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
| **Reference** | Benhamou 2004, J. Theor. Biol. 229(2):209-220 (how to reliably estimate path tortuosity); underlying circular statistics: Batschelet 1981, Circular Statistics in Biology — DOI [10.1016/j.jtbi.2004.03.016](https://doi.org/10.1016/j.jtbi.2004.03.016) |

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
| **Reference** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 — DOI [10.1006/jtbi.2002.3065](https://doi.org/10.1006/jtbi.2002.3065) |

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
| **Reference** | Walsh & Cummins 1976, Psychol. Bull. 83(3):482-504 (the open-field test, whose central measure is time spent in defined sub-regions) — DOI [10.1037/0033-2909.83.3.482](https://doi.org/10.1037/0033-2909.83.3.482) |

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
| **Reference** | Area-normalised occupancy (observed time in a zone relative to that zone's share of the arena), the standard correction for comparing unequal-area regions of interest. No single originating work |

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
| **Reference** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) -- frequency counting of discrete behavioural events |

#### Z-4 — Zone transitions

| Field | Value |
|---|---|
| **Manuscript label** | Inter-zone transitions |
| **Level** | Zone-pair; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (default 1) |
| **Formula** | Run-length encode the per-frame zone column; drop runs shorter than `min_dwell_frames` (runs of the empty "no zone" sentinel are always kept, so a tracking dropout cannot be spliced into a crossing); collapse consecutive duplicates; then for each adjacent pair in the resulting sequence increment `transitions[zone_a → zone_b]`. Pairs involving the empty zone are not counted. |
| **Output columns** | `from_zone`, `to_zone`, `individual_id`, `transition_count` |
| **Units** | count |
| **Assumptions** | Single-zone-per-frame (resolve overlaps with priority list or longest-overlap) |
| **Warnings** | Identity-free sessions: transitions are counted on NN-matched tracklets, not individuals. Sensitive to flicker on zone boundaries; `min_dwell_frames` debounces a visit shorter than the threshold by merging the transitions either side of it into one continuous stay. |
| **Reference** | Fagen & Young 1978, 'Temporal patterns of behaviors', in Colgan (ed.) Quantitative Ethology, pp. 79-114 (Wiley) -- sequence and transition analysis of behavioural states |

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
| **Reference** | Boundary-crossing event extraction underlying the event/state distinction in Martin & Bateson 2007, Measuring Behaviour, 3rd ed. (Cambridge University Press) |

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
| **Reference** | Bourin & Hascoët 2003, Eur. J. Pharmacol. 463(1-3):55-65 -- latency to first entry as a standard exploration/anxiety readout in the light/dark box test — DOI [10.1016/S0014-2999(03)01274-3](https://doi.org/10.1016/S0014-2999(03)01274-3) |

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
| **Reference** | Pitcher 1973, Anim. Behav. 21:673-686 (three-dimensional structure of minnow schools); see also Krause & Ruxton 2002, Living in Groups — DOI [10.1016/S0003-3472(73)80091-0](https://doi.org/10.1016/S0003-3472(73)80091-0) |

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
| **Reference** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) |

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
| **Reference** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 — DOI [10.1006/jtbi.2002.3065](https://doi.org/10.1006/jtbi.2002.3065) |

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
| **Reference** | Standard spatial-cohesion measure; convex-hull area is widely used as a group-spread metric in collective-behaviour studies |

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
| **Reference** | Standard kinematics applied to the group centroid; no single originating work. Used as a group descriptor in e.g. Tunstrøm et al. 2013, PLoS Comput. Biol. 9(2):e1002915 |

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
| **Reference** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) |

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
| **Reference** | Frame-to-frame point matching is a standard multi-object-tracking technique (assignment problem); no animal-behaviour-specific originating work |

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
| **Reference** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 — DOI [10.1006/jtbi.2002.3065](https://doi.org/10.1006/jtbi.2002.3065) |

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
| **Reference** | Standard kinematics (arithmetic mean position); no single originating work |

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
| **Reference** | Standard spatial-dispersion measure; complements GL-4 (convex-hull area). No single originating work |

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
| **Reference** | Tracking-pipeline convention (fraction of frames with a successfully assigned position); no single originating work |

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
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

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
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

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
| **Reference** | Track2Data's own bounding-box post-processing pipeline; no external work defines this counter |

#### D-5 — Identity stability flag

| Field | Value |
|---|---|
| **Manuscript label** | Identity stability |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.has_stable_identities`, `Session.quality["fraction_identified"]` |
| **Formula** | Pass-through + categorical (`stable`, `weak`, `identity_free`) |
| **Output columns** | `identity_stability_status` |
| **Reference** | Track2Data engineering threshold on idtracker.ai's own fraction_identified (PRD §5.2, FR-IMP-3); not an external scientific result |

#### D-6 — Segmentation error frames

| Field | Value |
|---|---|
| **Manuscript label** | Segmentation error frames |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.number_of_error_frames` (idtracker.ai's own counter), `Session.n_frames` |
| **Formula** | `error_frame_fraction = number_of_error_frames / n_frames` |
| **Output columns** | `number_of_error_frames`, `error_frame_fraction` |
| **Units** | count, fraction ∈ [0, 1] |
| **Warnings** | Distinct from D-4: this is idtracker.ai's own count of frames with more blobs than animals (shadows, reflections, dust), not Track2Data's post-hoc bounding-box check. It is the only place this surfaces when the tracking run had `check_segmentation` disabled, which silences it in idtracker.ai's own log. |
| **Reference** | idtracker.ai's own internal segmentation-error counter (number_of_error_frames), documented in its usage guide rather than named as a metric in Romero-Ferrero et al. 2019 |

#### D-7 — Fragment length distribution

| Field | Value |
|---|---|
| **Manuscript label** | Fragment length distribution |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.fragments` (`preprocessing/list_of_fragments.json`) |
| **Formula** | Over individual fragments only: median, p10, p90, max of fragment length in frames; plus `n_individual_fragments` |
| **Output columns** | `n_individual_fragments`, `fragment_length_median`, `fragment_length_p10`, `fragment_length_p90`, `fragment_length_max` |
| **Units** | frames |
| **Warnings** | A short median means identity is re-established constantly, which bounds how far any per-individual metric can be trusted across fragment breaks. Measured on a real corpus session: median 3 frames (p90 118, max 3409) — a fact invisible without this metric. |
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

#### D-8 — Crossing rate

| Field | Value |
|---|---|
| **Manuscript label** | Crossing rate |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.fragments` (both individual and crossing fragments) |
| **Formula** | `crossing_fragment_fraction = n_crossing_fragments / n_fragments`; `crossing_frame_fraction = sum(len of crossing fragments) / sum(len of all fragments)` |
| **Output columns** | `crossing_fragment_fraction`, `crossing_frame_fraction` |
| **Units** | fraction ∈ [0, 1] |
| **Warnings** | Directly quantifies a confound for every GL-* metric: animals inside a crossing fragment are by definition touching or overlapping for that whole span, so distance- and orientation-based group metrics are unreliable there. The frame-weighted fraction is the one to read — crossing and individual fragments have very different typical lengths. |
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

#### D-9 — Identity swap opportunity count

| Field | Value |
|---|---|
| **Manuscript label** | Identity swap opportunities |
| **Level** | Session summary |
| **Priority** | Diagnostic |
| **Inputs** | `Session.fragments`, `Session.n_frames` |
| **Formula** | `boundaries = {f.end_frame for f in individual_fragments if not f.identity_is_fixed}`; `swap_opportunity_count = len(boundaries)`; `swap_opportunity_fraction = count / n_frames` |
| **Output columns** | `swap_opportunity_count`, `swap_opportunity_fraction` |
| **Units** | count, fraction ∈ [0, 1] |
| **Warnings** | Deliberately a **declarative** diagnostic, not a corrector. It reports the exact bounded set of frames where a swap is physically possible and leaves the judgement to the researcher, rather than silently re-permuting trajectories — see `preprocess/identity_switch.py`, off by default for exactly that reason (CHANGELOG v0.1.0). |
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

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

1. **Citations** — resolved. Every one of the 33 metrics now carries a
   citation, and 11 carry a verified DOI. Previously all six zone
   metrics and all nine diagnostics had none at all, this document and
   the code disagreed on 14 metrics, and one DOI (Couzin et al. 2002)
   had been copy-pasted onto GL-1, whose citation named a different
   paper entirely. The list is published as
   [`METRIC_REFERENCES.csv`](./METRIC_REFERENCES.csv) and pinned by
   `tests/test_metric_references_consistency.py`; see
   [`../CONTRIBUTING.md` §7](../CONTRIBUTING.md) for the
   regenerate-on-change rule. Where no specific work applies, the
   citation says so plainly rather than borrowing an unrelated one —
   `citation_doi` stays `None` in those cases, by design.
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
   flicker debounce. The GUI's ⚙ button now opens `MetricConfigDialog`
   (`ui/dialogs/metric_config_dialog.py`) for any metric that declares
   `parameters`, one widget per parameter keyed off `MetricParameter.kind`;
   it is disabled with an explanatory tooltip for the 13 of the 24
   metrics it lists that declare none (diagnostics always run and
   aren't selectable there, so they don't count towards either
   figure; both are pinned by
   `tests/test_metric_references_consistency.py`). A `derived=True` parameter (IL-3's centre/radius, Z-2's zone
   areas) renders as a read-only "derived from this session's zones"
   label -- it is never user-editable and Save never writes it into
   `MetricSelection.config`. A parameter with no declared default (IL-4/
   IL-7's `threshold_px_s`: "auto-computed from data when unset") shows
   "Auto (data-driven)" rather than a numeric 0 -- 0 would be a real,
   very different threshold, and leaving the control on "Auto" omits the
   key entirely so `Engine._effective_cfg()`'s own auto-compute branch
   still runs. Saved edits round-trip through
   `MetricSelection.config[metric_id]`, the same manifest field the
   engine already reads.
