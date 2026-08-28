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
                  Space use                IL-3, IL-9, IL-10, IL-14
                  Path geometry            IL-5, IL-8, IL-11
Group             Social spacing           GL-1, GL-2, GL-13
                  Cohesion                 GL-4, GL-6, GL-10, GL-15
                  Collective motion        GL-3, GL-5, GL-8, GL-9, GL-11
                  Identity-free fallback   GL-7
Zone              Occupancy                Z-1, Z-2, Z-8
                  Visits                   Z-3, Z-5, Z-6, Z-9
                  Flow / crossings         Z-4, Z-7
Diagnostic        Coverage                 D-1
                  idtracker.ai quality     D-2, D-3, D-4, D-5
                  Segmentation / identity  D-6, D-7, D-8, D-9
                  Independent screening    D-10
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
| **Supporting references** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) (DOI: 10.1017/CBO9780511810893) |

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
| **Supporting references** | Bjorneraas et al. 2010, J. Wildl. Manage. 74(6):1361-1366 (screening GPS location data for errors using animal movement characteristics) (DOI: 10.2193/2009-405) |

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
| **Warnings** | For non-circular arenas, "centre-distance" is interpretable only with a clearly defined origin. In a non-circular (e.g. rectangular) arena, centre-distance is not monotonic in distance-to-wall — a corner-hugging animal can score the same centre-distance as one near a wall's midpoint; see **IL-14** for the wall-distance-specific measure. |
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
| **Reference** | Schnorr et al. 2012, Behav. Brain Res. 228(2):367-374 (thigmotaxis in larval zebrafish) — DOI [10.1016/j.bbr.2011.12.016](https://doi.org/10.1016/j.bbr.2011.12.016) |
| **Supporting references** | Simon et al. 1994, Behav. Brain Res. 61(1):59-64 (thigmotaxis as an index of anxiety in mice) (DOI: 10.1016/0166-4328(94)90008-6); Hall 1934, J. Comp. Psychol. 18(3):385-403 (emotional behavior in the rat: I. Defecation and urination as measures of individual differences in emotionality) (DOI: 10.1037/h0071444) |

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
| **Reference** | Cachat et al. 2010, Nat. Protoc. 5(11):1786-1799 (measuring behavioral and endocrine responses to novelty stress in adult zebrafish) — DOI [10.1038/nprot.2010.140](https://doi.org/10.1038/nprot.2010.140) |
| **Supporting references** | Stewart et al. 2012, Neuropharmacology 62(1):135-143 (modeling anxiety using adult zebrafish: a conceptual review -- no operational threshold given) (DOI: 10.1016/j.neuropharm.2011.07.037); Kalueff et al. 2013, Zebrafish 10(1):70-86 (towards a comprehensive catalog of zebrafish behavior 1.0 and beyond) (DOI: 10.1089/zeb.2012.0861); Egan et al. 2009, Behav. Brain Res. 205(1):38-44 (understanding behavioral and physiological phenotypes of stress and anxiety in zebrafish) (DOI: 10.1016/j.bbr.2009.06.022) |

#### IL-5 — Tortuosity (path length / displacement)

| Field | Value |
|---|---|
| **Manuscript label** | Path tortuosity |
| **Level** | Individual; trial summary |
| **Priority** | Optional |
| **Inputs** | IL-1 path length, start/end positions |
| **Required preprocessing** | Gap-fill + smoothing |
| **Formula** | `tortuosity = path_length / max(‖xy[end, k] − xy[start, k]‖, ε)` — the reciprocal of the **straightness index D/L**, computed once over the whole track (no windowing). This is one of several tortuosity estimators in the literature (straightness index, sinuosity, fractal dimension); the citation below supports this specific form, not "tortuosity" as a general concept — Benhamou 2004's own central finding is that these estimators are not interchangeable and are scale-dependent. |
| **Output columns** | `individual_id`, `tortuosity` |
| **Units** | dimensionless |
| **Assumptions** | Straight-line displacement is a meaningful baseline |
| **Warnings** | Undefined when start == end; cap at 1e6 or report `inf`. Whole-track D/L is scale- and duration-dependent — comparing sessions of different length or sampling rate is not meaningful without accounting for this. |
| **Reference** | Benhamou 2004, J. Theor. Biol. 229(2):209-220 (how to reliably estimate path tortuosity) — DOI [10.1016/j.jtbi.2004.03.016](https://doi.org/10.1016/j.jtbi.2004.03.016) |
| **Supporting references** | Kareiva & Shigesada 1983, Oecologia 56(2-3):234-238 (analyzing insect movement as a correlated random walk) (DOI: 10.1007/BF00379695); Benhamou 2013, Ecol. Lett. 17(3):261-272 (of scales and stationarity in animal movements) (DOI: 10.1111/ele.12225) |

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
| **Inputs** | IL-4 active/inactive boolean series, `min_bout_frames` (fixed 5, or fitted when `derive_bout_criterion` is on) |
| **Required preprocessing** | Smoothing required |
| **Formula** | Run-length encode `inactive`; keep runs ≥ `min_bout_frames`. `min_bout_frames` defaults to a fixed **5 frames**. Switching `derive_bout_criterion` on instead fits the Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion interval (`metrics/bouts.py`) to this session's own pooled inactive-run lengths across every individual, still falling back to the fixed 5 when that fit does not converge. The switch **overrides** an explicit `min_bout_frames`, which applies only while the switch is off. |
| **Output columns** | `individual_id`, `freezing_bout_count`, `mean_freezing_duration_s`, `total_freezing_duration_s`, `min_bout_frames_used`, `bout_criterion_effective` |
| **Units** | count; seconds; frames; categorical (`log_survivorship` / `fixed` / `fixed_fallback`) |
| **Assumptions** | Same as IL-4 |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`** — the opt-in switch), `min_bout_frames` (int, frames, no declared default — resolved per the switch) |
| **Warnings** | Discards short pauses; min duration is study-specific. `min_bout_frames_used`/`bout_criterion_effective` report the threshold actually applied and how it was derived (`fixed`, `log_survivorship`, or `fixed_fallback` when a requested fit did not converge). With the switch **on** the threshold is fit per session and can differ session to session — check `min_bout_frames_used` before comparing freezing-bout counts across sessions. |
| **Reference** | Cachat et al. 2010, Nat. Protoc. 5(11):1786-1799 (measuring behavioral and endocrine responses to novelty stress in adult zebrafish) — DOI [10.1038/nprot.2010.140](https://doi.org/10.1038/nprot.2010.140) |
| **Supporting references** | Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts) (DOI: 10.1016/S0003-3472(05)80726-2) |

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
| **Warnings** | Stationary frames produce undefined heading; skip them. Reports only turn **rate** (magnitude), discarding direction — see **IL-11** for a directional / circular-statistics treatment that also reveals left/right bias. |
| **Reference** | Kareiva & Shigesada 1983, Oecologia 56(2-3):234-238 (analyzing insect movement as a correlated random walk) — DOI [10.1007/BF00379695](https://doi.org/10.1007/BF00379695) |
| **Supporting references** | Mwaffo et al. 2015, J. R. Soc. Interface 12(102):20140884 (a jump persistent turning walker to model zebrafish locomotion) (DOI: 10.1098/rsif.2014.0884); Marques et al. 2018, Curr. Biol. 28(2):181-195 (structure of the zebrafish locomotor repertoire revealed with unsupervised behavioral clustering; bouts segmented from tail shape at ~700 fps -- not applicable to centroid-only tracking) (DOI: 10.1016/j.cub.2017.12.002) |

#### IL-9 — Home-base occupancy

| Field | Value |
|---|---|
| **Manuscript label** | Home-base occupancy |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | `PreprocessedSession.xy`; `cfg['bin_size_px']` (default 20.0) |
| **Required preprocessing** | None |
| **Formula** | Bin non-NaN xy into `bin_size_px` square cells; `home_base_time_pct = max(cell counts) / total valid frames`; `home_base_stable = True` iff the top cell of the first half of the session equals the top cell of the second half |
| **Output columns** | `individual_id`, `home_base_time_pct`, `home_base_stable` |
| **Units** | dimensionless fraction; boolean |
| **Assumptions** | Zone-free: no drawn regions needed, unlike Z-1..Z-9 |
| **Warnings** | Grid resolution (`bin_size_px`) directly sets what counts as "the same locus" — too coarse merges genuinely separate loci, too fine fragments one real home base into many cells. `home_base_stable` is a binary same-cell/different-cell flag, not a continuous stability score. |
| **Parameters** | `bin_size_px` (float, px, default 20.0) |
| **Reference** | Eilam & Golani 1989, Behav. Brain Res. 34(3):199-211 (home base behavior of rats exploring a novel environment) — DOI [10.1016/S0166-4328(89)80102-0](https://doi.org/10.1016/S0166-4328(89)80102-0) |
| **Supporting references** | Freund et al. 2013, Science 340(6133):756-759 (emergence of individuality in genetically identical mice) (DOI: 10.1126/science.1235294) |

#### IL-10 — Roaming entropy

| Field | Value |
|---|---|
| **Manuscript label** | Roaming entropy |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | `PreprocessedSession.xy`; `cfg['bin_size_px']` (default 20.0, shared with IL-9) |
| **Required preprocessing** | None |
| **Formula** | Same occupancy grid as IL-9; `p_i = count_i / total valid frames` over visited cells `i`; `roaming_entropy_bits = -sum(p_i * log2(p_i))`; `roaming_entropy_normalised = roaming_entropy_bits / log2(n_visited_cells)` (1.0 = uniform use of every visited cell), `NaN` when `n_visited_cells <= 1` |
| **Output columns** | `individual_id`, `roaming_entropy_bits`, `roaming_entropy_normalised`, `n_visited_cells` |
| **Units** | bits; dimensionless ∈ [0, 1]; count |
| **Assumptions** | Zone-free: no drawn regions needed, unlike Z-1..Z-9 |
| **Warnings** | Grid resolution (`bin_size_px`) directly affects the entropy value — comparing entropies computed at different bin sizes is not meaningful. `roaming_entropy_normalised` divides by log2 of the number of cells VISITED, not the number of cells the arena could hold — it measures evenness of use among visited cells, not coverage of the arena. |
| **Parameters** | `bin_size_px` (float, px, default 20.0) |
| **Reference** | Freund et al. 2013, Science 340(6133):756-759 (emergence of individuality in genetically identical mice) — DOI [10.1126/science.1235294](https://doi.org/10.1126/science.1235294) |
| **Supporting references** | Eilam & Golani 1989, Behav. Brain Res. 34(3):199-211 (home base behavior of rats exploring a novel environment) (DOI: 10.1016/S0166-4328(89)80102-0) |

#### IL-11 — Circular statistics of heading

| Field | Value |
|---|---|
| **Manuscript label** | Circular statistics of heading |
| **Level** | Individual; trial summary |
| **Priority** | Advanced |
| **Inputs** | `PreprocessedSession.kinematics.heading_rad` |
| **Required preprocessing** | None beyond the heading computation IL-8 already relies on |
| **Formula** | `C = mean(cos(heading))`, `S = mean(sin(heading))` over non-NaN headings; `mean_heading_rad = atan2(S, C)`; resultant length `r = sqrt(C² + S²)`; Rayleigh test via Zar's approximation: `Z = n·r²`, `p = exp(-Z) · (1 + (2Z − Z²)/(4n) − (24Z − 132Z² + 76Z³ − 9Z⁴)/(288n²))`; `left_right_turn_bias = mean(sign(wrap(θ[t+1] − θ[t])))` |
| **Output columns** | `individual_id`, `mean_heading_rad`, `resultant_length`, `rayleigh_p`, `left_right_turn_bias` |
| **Units** | radians; dimensionless ∈ [0, 1]; probability ∈ [0, 1]; dimensionless ∈ [-1, 1] |
| **Assumptions** | Heading is well-defined (i.e. speed > small ε); undefined frames are excluded |
| **Warnings** | Undefined (NaN) `resultant_length`/`rayleigh_p` when fewer than 2 valid headings. `rayleigh_p` tests only for non-uniformity, not for any specific mean direction — a small p-value says headings are not random, not that they point any particular way. |
| **Reference** | Berens 2009, J. Stat. Softw. 31(10):1-21 (CircStat: a MATLAB toolbox for circular statistics) — DOI [10.18637/jss.v031.i10](https://doi.org/10.18637/jss.v031.i10) |
| **Supporting references** | Kareiva & Shigesada 1983, Oecologia 56(2-3):234-238 (analyzing insect movement as a correlated random walk) (DOI: 10.1007/BF00379695) |

#### IL-14 — Wall-distance thigmotaxis

| Field | Value |
|---|---|
| **Manuscript label** | Wall-distance thigmotaxis |
| **Level** | Individual; trial summary |
| **Priority** | Primary |
| **Inputs** | `PreprocessedSession.xy`; arena boundary, derived per session (same source as IL-3, see below — never user-supplied) |
| **Required preprocessing** | Zone assignment, when zones are defined (supplies `main_zone`) |
| **Formula** | `d[t,k]` = distance from `xy[t,k]` to the boundary of the animal's own arena polygon (Shapely `Polygon.exterior.distance`); `mean_wall_distance_px` = mean over non-NaN frames; `wall_contact_time_pct` = fraction of non-NaN frames with `d[t,k] < wall_contact_threshold_px` |
| **Output columns** | `individual_id`, `mean_wall_distance_px`, `wall_contact_time_pct` |
| **Units** | px; dimensionless fraction |
| **Assumptions** | The arena boundary is derived per session from the project's own main-level zone geometry (same source as IL-3), or the video frame rectangle when no zones are defined; with several main arenas each animal is measured from the one it occupies. Only additive ("+") polygons contribute; subtractive exclusion holes are not treated as walls for this metric. |
| **Warnings** | IL-3 measures distance from the arena CENTRE, which conflates wall proximity with corner geometry in any non-circular arena — in a rectangular tank the centre distance is not monotonic in wall distance; this measures the actual thigmotaxis construct. Requires shapely (an optional dependency; see `pyproject.toml`'s `zones` extra) — unlike every other IL-* metric. `wall_contact_threshold_px` has no calibration-derived default, for the same reason as D-10: `Session.body_length_reliable` is always `False` (§2.1). |
| **Parameters** | `arena_polygon_vertices` / `arena_polygon_vertices_per_animal` are `derived=True` and cannot be overridden. `wall_contact_threshold_px` (float, px, default 20.0). |
| **Reference** | Simon et al. 1994, Behav. Brain Res. 61(1):59-64 (thigmotaxis as an index of anxiety in mice) — DOI [10.1016/0166-4328(94)90008-6](https://doi.org/10.1016/0166-4328(94)90008-6) |
| **Supporting references** | Schnorr et al. 2012, Behav. Brain Res. 228(2):367-374 (thigmotaxis in larval zebrafish) (DOI: 10.1016/j.bbr.2011.12.016); Maximino et al. 2010, Behav. Brain Res. 214(2):157-171 (measuring anxiety in zebrafish: a critical review) (DOI: 10.1016/j.bbr.2010.05.031) |

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
| **Reference** | Walsh & Cummins 1976, Psychol. Bull. 83(3):482-504 (the open-field test: a critical review) — DOI [10.1037/0033-2909.83.3.482](https://doi.org/10.1037/0033-2909.83.3.482) |
| **Supporting references** | Hall 1934, J. Comp. Psychol. 18(3):385-403 (emotional behavior in the rat: I. Defecation and urination as measures of individual differences in emotionality) (DOI: 10.1037/h0071444) |

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
| **Warnings** | If no arena polygon, normalise by union-of-zones area + warn. This ratio is unbounded and asymmetric (over- and under-representation are not on comparable scales), so it cannot be meaningfully averaged across animals or compared across arena designs — see **Z-8** (Jacobs' D) for a bounded [-1, +1] alternative built on the same zone-area data. |
| **Superseded by** | **Z-8** (Jacobs' D). Z-2 keeps computing exactly the ratio above — no existing project's numbers change — but Z-8 is the better statistic for any new analysis; see Z-8 below. |
| **Reference** | Area-normalised occupancy (observed time in a zone relative to that zone's share of the arena), the standard correction for comparing unequal-area regions of interest. No single originating work |
| **Supporting references** | Jacobs 1974, Oecologia 14(4):413-417 (quantitative measurement of food selection -- origin of the bias-corrected D electivity index) (DOI: 10.1007/BF00384581); Krause & Ruxton 2002, Living in Groups (Oxford University Press) (DOI: 10.1093/oso/9780198508175.001.0001) |

#### Z-3 — Zone visit count

| Field | Value |
|---|---|
| **Manuscript label** | Zone visits |
| **Level** | Zone; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 in/out boolean series |
| **Formula** | Count rising edges (False → True) in zone-membership series, after debouncing runs shorter than `min_visit_frames`. `min_visit_frames` defaults to a fixed **1 frame**. Switching `derive_bout_criterion` on instead fits the Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion interval (`metrics/bouts.py`, shared with Z-4/Z-5) to this session's own pooled in-zone run lengths, still falling back to the fixed 1 when that fit does not converge. The switch **overrides** an explicit `min_visit_frames`, which applies only while the switch is off. |
| **Output columns** | `zone_name`, `individual_id`, `visit_count`, `min_visit_frames_used`, `bout_criterion_effective` |
| **Units** | count; frames; categorical (`log_survivorship` / `fixed` / `fixed_fallback`) |
| **Assumptions** | A "visit" is any zero-or-more-frame stay; configurable `min_visit_frames` (fixed 1, or fitted when `derive_bout_criterion` is on) |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`** — the opt-in switch), `min_visit_frames` (int, frames, no declared default — resolved per the switch) |
| **Warnings** | Sensitive to flicker on zone boundaries; smoothing or `min_visit_frames` mitigates. `min_visit_frames_used`/`bout_criterion_effective` report the threshold actually applied. At the default 1-frame threshold every single-frame boundary flicker counts as a distinct visit — switching `derive_bout_criterion` on typically reduces visit counts sharply on flickery data. |
| **Reference** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) — DOI [10.1017/CBO9780511810893](https://doi.org/10.1017/CBO9780511810893) |
| **Supporting references** | Bakeman & Gottman 1997, Observing Interaction: An Introduction to Sequential Analysis, 2nd ed. (Cambridge University Press) (DOI: 10.1017/CBO9780511527685); Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts) (DOI: 10.1016/S0003-3472(05)80726-2) |

#### Z-4 — Zone transitions

| Field | Value |
|---|---|
| **Manuscript label** | Inter-zone transitions |
| **Level** | Zone-pair; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (fixed 1, or fitted when `derive_bout_criterion` is on) |
| **Formula** | Run-length encode the per-frame zone column; drop runs shorter than `min_dwell_frames` (runs of the empty "no zone" sentinel are always kept, so a tracking dropout cannot be spliced into a crossing); collapse consecutive duplicates; then for each adjacent pair in the resulting sequence increment `transitions[zone_a → zone_b]`. Pairs involving the empty zone are not counted. `min_dwell_frames` defaults to a fixed **1 frame**; switching `derive_bout_criterion` on instead fits the Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion interval (`metrics/bouts.py`, shared with Z-3/Z-5) to this session's own pooled in-zone run lengths, still falling back to the fixed 1 when that fit does not converge. The switch **overrides** an explicit `min_dwell_frames`, which applies only while the switch is off. |
| **Output columns** | `from_zone`, `to_zone`, `individual_id`, `transition_count`, `min_dwell_frames_used`, `bout_criterion_effective` |
| **Units** | count; frames; categorical (`log_survivorship` / `fixed` / `fixed_fallback`) |
| **Assumptions** | Single-zone-per-frame (resolve overlaps with priority list or longest-overlap) |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`** — the opt-in switch), `min_dwell_frames` (int, frames, no declared default — resolved per the switch) |
| **Warnings** | Identity-free sessions: transitions are counted on NN-matched tracklets, not individuals. Sensitive to flicker on zone boundaries; `min_dwell_frames` debounces a visit shorter than the threshold by merging the transitions either side of it into one continuous stay. Collapses the full transition sequence to a scalar count per zone pair — see **Z-7** for the full transition matrix and sequence entropy computed from this same run-length-encoded data. `min_dwell_frames_used`/`bout_criterion_effective` report the threshold actually applied. |
| **Reference** | Bakeman & Gottman 1997, Observing Interaction: An Introduction to Sequential Analysis, 2nd ed. (Cambridge University Press) — DOI [10.1017/CBO9780511527685](https://doi.org/10.1017/CBO9780511527685) |
| **Supporting references** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) (DOI: 10.1017/CBO9780511810893); Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts) (DOI: 10.1016/S0003-3472(05)80726-2) |

#### Z-5 — Entry / exit timestamps

| Field | Value |
|---|---|
| **Manuscript label** | Zone entry/exit times |
| **Level** | Event log |
| **Priority** | Optional |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (fixed 1, or fitted when `derive_bout_criterion` is on) |
| **Formula** | Emit one row per edge transition with `t_s = frame / fps`; a run inside a zone shorter than `min_dwell_frames` produces no enter/exit events at all. `min_dwell_frames` defaults to a fixed **1 frame**; switching `derive_bout_criterion` on instead fits the Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion interval (`metrics/bouts.py`, shared with Z-3/Z-4) to this session's own pooled in-zone run lengths, still falling back to the fixed 1 when that fit does not converge. The switch **overrides** an explicit `min_dwell_frames`, which applies only while the switch is off. |
| **Output columns** | `zone_name`, `individual_id`, `event` (enter/exit), `t_s`, `frame`, `min_dwell_frames_used`, `bout_criterion_effective` |
| **Units** | seconds; frames; categorical (`log_survivorship` / `fixed` / `fixed_fallback`) |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`** — the opt-in switch), `min_dwell_frames` (int, frames, no declared default — resolved per the switch) |
| **Warnings** | `min_dwell_frames_used`/`bout_criterion_effective` report the threshold actually applied and how it was derived; Z-6 and Z-9 inherit whichever was used here, since both forward their own cfg into this compute() unchanged. |
| **Reference** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) — DOI [10.1017/CBO9780511810893](https://doi.org/10.1017/CBO9780511810893) |
| **Supporting references** | Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts) (DOI: 10.1016/S0003-3472(05)80726-2) |

#### Z-6 — Latency to first entry

| Field | Value |
|---|---|
| **Manuscript label** | Latency to first zone entry |
| **Level** | Zone; trial summary |
| **Priority** | Optional |
| **Inputs** | Z-5 event log; forwards `min_dwell_frames`/`derive_bout_criterion` to Z-5 |
| **Formula** | Per zone, per individual: `t_s` of first "enter" event (after Z-5's debounce) |
| **Output columns** | `zone_name`, `individual_id`, `first_entry_t_s` |
| **Units** | seconds |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`**), `min_dwell_frames` (int, frames, no declared default); both forwarded to Z-5 unchanged |
| **Warnings** | NaN when the individual never enters; encode as `inf` for sortability. The source paradigm (mouse light/dark box) gives no censoring convention of its own for a never-entering animal — the `inf` encoding is this tool's own deliberate choice, not something the citation specifies. Inherits Z-5's `derive_bout_criterion` switch: with it on, a brief flicker no longer counts as the first entry. |
| **Reference** | Bourin & Hascoet 2003, Eur. J. Pharmacol. 463(1-3):55-65 (the mouse light/dark box test) — DOI [10.1016/S0014-2999(03)01274-3](https://doi.org/10.1016/S0014-2999(03)01274-3) |
| **Supporting references** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) (DOI: 10.1017/CBO9780511810893) |

#### Z-7 — Zone transition matrix & sequence entropy

| Field | Value |
|---|---|
| **Manuscript label** | Zone transition matrix & sequence entropy |
| **Level** | Zone-pair; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1 zone-membership series; configurable `min_dwell_frames` (default 1, same as Z-4) |
| **Formula** | Same debounced zone sequence as Z-4; `transition_probability[a,b] = count(a→b) / Σ_b' count(a→b')` (row-normalised, i.e. `P(next=b \| current=a)`); `sequence_entropy_bits = -Σ p_ij·log2(p_ij)` over all observed transitions `(a,b)`, `p_ij = count(a,b) / total_transitions` — the joint distribution's entropy, not the row-normalised one |
| **Output columns** | `individual_id`, `from_zone`, `to_zone`, `transition_count`, `transition_probability`, `sequence_entropy_bits` |
| **Units** | count; probability ∈ [0, 1]; bits |
| **Assumptions** | Zone arrays are pre-assigned object arrays of zone-name strings |
| **Warnings** | Only named zone-to-zone transitions are counted, same as Z-4. `sequence_entropy_bits` is repeated on every row for a given individual — it is one scalar per individual, broadcast across the matrix rows for long-format consistency. Undefined (no rows) for an individual with zero qualifying transitions. |
| **Parameters** | `min_dwell_frames` (int, frames, default 1) — same parameter as Z-4 |
| **Reference** | Bakeman & Gottman 1997, Observing Interaction: An Introduction to Sequential Analysis, 2nd ed. (Cambridge University Press) — DOI [10.1017/CBO9780511527685](https://doi.org/10.1017/CBO9780511527685) |
| **Supporting references** | Martin & Bateson 2007, Measuring Behaviour: An Introductory Guide, 3rd ed. (Cambridge University Press) (DOI: 10.1017/CBO9780511810893) |

#### Z-8 — Zone preference index (Jacobs' D)

| Field | Value |
|---|---|
| **Manuscript label** | Zone preference index (Jacobs' D) |
| **Level** | Zone; trial summary |
| **Priority** | Primary |
| **Inputs** | Z-1's per-frame zone counts; `cfg['roi_areas']` / `cfg['total_arena_area']` (derived per session, shared with Z-2) |
| **Formula** | `r` = observed `time_pct` in the zone (same computation as Z-1); `p = roi_area / total_arena_area` (same derivation as Z-2); `jacobs_d = (r − p) / (r + p − 2·r·p)`, or 0 when `r == p == 0` |
| **Output columns** | `zone_name`, `individual_id`, `jacobs_d` |
| **Units** | dimensionless ∈ [-1, +1] |
| **Assumptions** | Zone arrays are pre-assigned object arrays of zone-name strings; `roi_areas`/`total_arena_area` are supplied in cfg (derived, same as Z-2 — never user-typed) |
| **Warnings** | Returns empty DataFrame when cfg is missing or incomplete |
| **Parameters** | `roi_areas` / `total_arena_area` are `derived=True` and cannot be overridden — shared derivation with Z-2 |
| **Reference** | Jacobs 1974, Oecologia 14(4):413-417 (quantitative measurement of food selection -- origin of the bias-corrected D electivity index) — DOI [10.1007/BF00384581](https://doi.org/10.1007/BF00384581) |
| **Supporting references** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) (DOI: 10.1093/oso/9780198508175.001.0001) |

> **Bounded [-1, +1] replacement for Z-2.** Z-2's raw area-corrected
> ratio is unbounded and asymmetric (over- and under-representation are
> not on comparable scales), so it cannot be meaningfully averaged
> across animals or compared across arena designs. Jacobs' D is
> bias-corrected and fixes exactly that. Z-2 is kept, unchanged, for
> output compatibility with existing projects (see its own **Superseded
> by** row above) — Z-8 is the better statistic for any new analysis.

#### Z-9 — Zone dwell-time distribution

| Field | Value |
|---|---|
| **Manuscript label** | Zone dwell-time distribution |
| **Level** | Zone; trial summary |
| **Priority** | Optional |
| **Inputs** | Z-5 event log; forwards `min_dwell_frames`/`derive_bout_criterion` to Z-5 |
| **Formula** | Pair each "enter" event with its next "exit" event (same zone, individual) from the Z-5 event log; `dwell_s = exit.t_s − enter.t_s`; mean/median/max computed over all paired visits. A visit still open at the final frame (Z-5's unmatched "enter") is excluded, not counted as an open-ended visit. |
| **Output columns** | `zone_name`, `individual_id`, `n_visits`, `mean_dwell_s`, `median_dwell_s`, `max_dwell_s` |
| **Units** | count; seconds |
| **Assumptions** | Zone arrays are pre-assigned object arrays of zone-name strings |
| **Warnings** | An animal's final, still-open visit at session end is excluded from these statistics (its true duration is unknown). Undefined (no row) for a (zone, animal) pair with zero completed visits. Inherits Z-5's `derive_bout_criterion` switch: with it on, brief flickers drop out of the dwell-time distribution, typically raising the mean. |
| **Parameters** | `derive_bout_criterion` (bool, **default `False`**), `min_dwell_frames` (int, frames, no declared default) — both forwarded to Z-5, same as Z-6 |
| **Reference** | Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts) — DOI [10.1016/S0003-3472(05)80726-2](https://doi.org/10.1016/S0003-3472(05)80726-2) |
| **Supporting references** | Bourin & Hascoet 2003, Eur. J. Pharmacol. 463(1-3):55-65 (the mouse light/dark box test) (DOI: 10.1016/S0014-2999(03)01274-3) |

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
| **Reference** | Clark & Evans 1954, Ecology 35(4):445-453 (distance to nearest neighbor as a measure of spatial relationships in populations) — DOI [10.2307/1931034](https://doi.org/10.2307/1931034) |
| **Supporting references** | Pitcher 1973, Anim. Behav. 21(4):673-686 (the three-dimensional structure of schools in the minnow, Phoxinus phoxinus) (DOI: 10.1016/S0003-3472(73)80091-0); Krause & Ruxton 2002, Living in Groups (Oxford University Press) (DOI: 10.1093/oso/9780198508175.001.0001) |

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
| **Reference** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) — DOI [10.1093/oso/9780198508175.001.0001](https://doi.org/10.1093/oso/9780198508175.001.0001) |
| **Supporting references** | Miller & Gerlai 2007, Behav. Brain Res. 184(2):157-166 (quantification of shoaling behaviour in zebrafish) (DOI: 10.1016/j.bbr.2007.07.007); Delcourt & Poncin 2012, Rev. Fish Biol. Fish. 22(3):595-619 (shoals and schools: back to the heuristic definitions and quantitative references) (DOI: 10.1007/s11160-012-9260-z) |

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
| **Reference** | Vicsek et al. 1995, Phys. Rev. Lett. 75(6):1226-1229 (novel type of phase transition in a system of self-driven particles -- origin of the polar order parameter) — DOI [10.1103/PhysRevLett.75.1226](https://doi.org/10.1103/PhysRevLett.75.1226) |
| **Supporting references** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 (collective memory and spatial sorting in animal groups) (DOI: 10.1006/jtbi.2002.3065); Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 (collective states, multistability and transitional behavior in schooling fish) (DOI: 10.1371/journal.pcbi.1002915) |

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
| **Reference** | Mohr 1947, Am. Midl. Nat. 37(1):223-249 (table of equivalent populations of North American small mammals -- origin of the minimum convex polygon) — DOI [10.2307/2421652](https://doi.org/10.2307/2421652) |
| **Supporting references** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) (DOI: 10.1093/oso/9780198508175.001.0001) |

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
| **Warnings** | Centroid speed is **NOT** the mean of individual speeds — it can be near zero even while every animal moves fast, whenever the group mills or the animals' velocities cancel. |
| **Reference** | Standard kinematics applied to the group centroid; no single originating work |
| **Supporting references** | Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 (collective states, multistability and transitional behavior in schooling fish) (DOI: 10.1371/journal.pcbi.1002915) |

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
| **Reference** | Krause & Ruxton 2002, Living in Groups (Oxford University Press) — DOI [10.1093/oso/9780198508175.001.0001](https://doi.org/10.1093/oso/9780198508175.001.0001) |
| **Supporting references** | Delcourt & Poncin 2012, Rev. Fish Biol. Fish. 22(3):595-619 (shoals and schools: back to the heuristic definitions and quantitative references) (DOI: 10.1007/s11160-012-9260-z) |

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
| **Inputs** | `Session.raw_xy`; greedy nearest-neighbour matching of points across consecutive frames |
| **Formula** | For each `t`: greedily match each detection in `xy[t, :, :]` to its nearest unmatched detection in `xy[t+1, :, :]` (one pass, first-come-first-served — **not** a globally optimal assignment-problem solve); speed = matched distance · fps |
| **Output columns** | `mean_matched_speed`, `median_matched_speed` |
| **Units** | px/s, cm/s, BL/s |
| **Assumptions** | Animals do not swap positions faster than 1 frame; large jumps degrade matching |
| **Warnings** | Always emits a "matched, not identity-stable" note in the manifest; greedy assignment may be biased in crowded scenes, where a true Hungarian solve would differ |
| **Reference** | Bernardin & Stiefelhagen 2008, EURASIP J. Image Video Process. 2008:246309 (evaluating multiple object tracking performance: the CLEAR MOT metrics) — DOI [10.1155/2008/246309](https://doi.org/10.1155/2008/246309) |

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
| **Reference** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 (collective memory and spatial sorting in animal groups) — DOI [10.1006/jtbi.2002.3065](https://doi.org/10.1006/jtbi.2002.3065) |
| **Supporting references** | Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 (collective states, multistability and transitional behavior in schooling fish) (DOI: 10.1371/journal.pcbi.1002915) |

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
| **Warnings** | This is **RMS distance to the centroid** specifically — neither SD of positions nor mean pairwise distance, which are different "spread" statistics with different values. |
| **Reference** | Standard spatial-dispersion measure; complements GL-4 (convex-hull area). No single originating work |
| **Supporting references** | Clark & Evans 1954, Ecology 35(4):445-453 (distance to nearest neighbor as a measure of spatial relationships in populations) (DOI: 10.2307/1931034) |

#### GL-11 — Order-state classification

| Field | Value |
|---|---|
| **Manuscript label** | Order-state classification (polarised / milling / swarm) |
| **Level** | Group (per frame); trial summary |
| **Priority** | Primary |
| **Inputs** | `Session.raw_xy`, `Session.kinematics.heading_rad`, `Session.kinematics.speed_px_s` |
| **Formula** | Per frame: compute Φ[t] and M[t] exactly as GL-3/GL-8 do (same `stationary_threshold_px_s`); `state[t] = 'polarised'` if `Φ[t] >= polarised_threshold`, else `'milling'` if `M[t] >= milling_threshold`, else `'swarm'`; `*_time_pct` = fraction of classified frames in that state |
| **Output columns** | `polarised_time_pct`, `milling_time_pct`, `swarm_time_pct`, `n_classified_frames` |
| **Units** | dimensionless fraction; count |
| **Assumptions** | A frame is classified only when both Φ[t] and M[t] are defined (same per-frame skip rules as GL-3 and GL-8) |
| **Warnings** | Threshold choice is a modelling decision, not a physical constant — the defaults follow Tunstrøm 2013's empirical milling-state boundaries for fish schools and may not transfer to other species or group sizes without re-checking |
| **Parameters** | `polarised_threshold` (float, default 0.65), `milling_threshold` (float, default 0.65), `stationary_threshold_px_s` (float, px/s, default 1e-6) |
| **Reference** | Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 (collective states, multistability and transitional behavior in schooling fish) — DOI [10.1371/journal.pcbi.1002915](https://doi.org/10.1371/journal.pcbi.1002915) |
| **Supporting references** | Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 (collective memory and spatial sorting in animal groups) (DOI: 10.1006/jtbi.2002.3065); Vicsek et al. 1995, Phys. Rev. Lett. 75(6):1226-1229 (novel type of phase transition in a system of self-driven particles -- origin of the polar order parameter) (DOI: 10.1103/PhysRevLett.75.1226) |

#### GL-13 — Topological neighbour counts (k-NN structure)

| Field | Value |
|---|---|
| **Manuscript label** | Topological k-NN counts |
| **Level** | Group (per frame); trial summary |
| **Priority** | Optional |
| **Inputs** | `Session.raw_xy`, all IDs |
| **Formula** | Per frame, per animal: query `cKDTree` (same tree GL-1 already builds) for the `k_max` nearest other animals; `kth_nn_distance[k]` = distance to the k-th; `neighbours_within_radius` = count of other animals within `radius_px`; both averaged over all animals and valid frames |
| **Output columns** | `k`, `mean_kth_nn_distance_px`, `mean_neighbours_within_radius` |
| **Units** | px; count |
| **Assumptions** | Frames where any animal has NaN position are skipped |
| **Warnings** | Requires at least `k_max + 1` animals with valid positions in a frame for that frame to contribute to the `k=k_max` distance |
| **Parameters** | `k_max` (int, default 3), `radius_px` (float, px, default 50.0) |
| **Reference** | Ballerini et al. 2008, Proc. Natl. Acad. Sci. 105(4):1232-1237 (interaction ruling animal collective behavior depends on topological rather than metric distance) — DOI [10.1073/pnas.0711437105](https://doi.org/10.1073/pnas.0711437105) |
| **Supporting references** | Clark & Evans 1954, Ecology 35(4):445-453 (distance to nearest neighbor as a measure of spatial relationships in populations) (DOI: 10.2307/1931034) |

#### GL-15 — Group elongation / shape anisotropy

| Field | Value |
|---|---|
| **Manuscript label** | Group elongation / anisotropy |
| **Level** | Group (per frame); trial summary |
| **Priority** | Optional |
| **Inputs** | `Session.raw_xy`, all IDs |
| **Formula** | Per frame: `Σ = cov(xy[t, valid, :])` (2×2); `λ1 >= λ2 = eigenvalues(Σ)`; `elongation_ratio[t] = sqrt(λ1 / λ2)` (NaN if `λ2 <= 0`); `major_axis_orientation[t]` = angle of the eigenvector for `λ1`; metric = mean over frames with ≥3 valid animals |
| **Output columns** | `mean_elongation_ratio`, `mean_major_axis_orientation_rad` |
| **Units** | dimensionless ratio ≥ 1; radians |
| **Assumptions** | Requires ≥3 valid animal positions in a frame to define a covariance matrix |
| **Warnings** | Orientation is averaged as a circular quantity mod π (an axis has no head/tail), not as a plain arithmetic mean of angles |
| **Reference** | Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 (collective states, multistability and transitional behavior in schooling fish) — DOI [10.1371/journal.pcbi.1002915](https://doi.org/10.1371/journal.pcbi.1002915) |
| **Supporting references** | Mohr 1947, Am. Midl. Nat. 37(1):223-249 (table of equivalent populations of North American small mammals -- origin of the minimum convex polygon) (DOI: 10.2307/2421652) |

### 4.5 Identity-free variants

`Metric.requires_identity` is not documentation: `Engine.compute_metrics`
refuses to compute a ❌ metric for a session that was tracked without
identification (`session.json`'s `track_wo_identities`) or that the user
marked identity-free on the Sessions screen. On such a session the row
index is a per-frame detection slot rather than a persistent animal, so
anything following an individual across frames is noise.

The criterion, applied to what `compute()` actually reads: **does it
consume a value derived from more than one frame at a fixed row index?**
(`kinematics.speed_px_s`, `kinematics.heading_rad`, any `xy[t] → xy[t+1]`
pairing at matching indices.) GL-7 shows the criterion is about *how*,
not *what*: it reports a speed but re-matches detections between each
frame pair by nearest neighbour instead of trusting the row index.

The classification is pinned by
`tests/test_metrics/test_identity_classification.py` and published as the
`requires_identity` column of `docs/METRIC_REFERENCES.csv`; change all
three together.

| Metric | Identity-free derivable? | Note |
|---|---|---|
| IL-1 Distance Travelled | ❌ | Per-animal time series |
| IL-2 Speed (mean / median / max) | ❌ | Per-animal time series |
| IL-3 Distance from Arena Centre | ❌ | Per-animal time series |
| IL-4 Activity / Freezing Fraction | ❌ | Per-animal time series |
| IL-5 Tortuosity | ❌ | Per-animal time series |
| IL-6 Acceleration (mean abs / RMS / max) | ❌ | Per-animal time series |
| IL-7 Freezing-Bout Count & Duration | ❌ | Per-animal time series |
| IL-8 Turn Rate (Heading Change) | ❌ | Per-animal time series |
| IL-9 Home-Base Occupancy | ❌ | Per-animal time series |
| IL-10 Roaming Entropy | ❌ | Per-animal time series |
| IL-11 Circular Statistics of Heading | ❌ | Per-animal time series |
| IL-14 Wall-Distance Thigmotaxis | ❌ | Per-animal time series |
| GL-1 Nearest-Neighbour Distance | ✅ | Unordered point set per frame |
| GL-2 Inter-Individual Distance | ✅ | Unordered point set per frame |
| GL-3 Polarisation | ❌ | Heading requires per-individual tracklets |
| GL-4 Convex Hull Area | ✅ | Frame-by-frame point set |
| GL-5 Centroid Speed | ✅ | Frame-by-frame centroid |
| GL-6 Group Cohesion | ✅ | Frame-by-frame point set |
| GL-7 NN-Matched Speed | ✅ | Designed for identity-free sessions: re-matches per frame pair |
| GL-8 Rotational Order | ❌ | Requires headings |
| GL-9 Group Centroid Position | ✅ | Frame-by-frame centroid |
| GL-10 Group Spread | ✅ | Frame-by-frame centroid |
| GL-11 Order-State Classification | ❌ | Thresholds GL-3 against GL-8; inherits both |
| GL-13 Topological k-NN Counts | ✅ | Per-frame k-nearest-neighbour counts |
| GL-15 Group Elongation / Anisotropy | ✅ | Per-frame covariance of the point set |
| Z-1 Time in zone | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-2 Area-Corrected Occupancy | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-3 Zone visit count | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-4 Zone Transitions | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-5 Zone Entry/Exit Events | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-6 Latency to First Entry | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-7 Zone Transition Matrix & Sequence Entropy | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-8 Zone Preference Index (Jacobs' D) | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| Z-9 Zone Dwell-Time Distribution | ✅ | **Known gap** — emits per-`individual_id` rows; see below |
| D-1 Tracking Coverage | ✅ | Per-slot non-NaN fraction |
| D-2 Tracking Accuracy | ✅ | Per-frame / session-level only |
| D-3 ID-Probability Distribution | ❌ | Reports idtracker.ai's per-identity id_probabilities |
| D-4 Inconsistent-Frame Count | ✅ | Per-frame / session-level only |
| D-5 Identity Stability Flag | ✅ | Reports the identity-free status itself |
| D-6 Segmentation Error Frames | ✅ | Per-frame / session-level only |
| D-7 Fragment Length Distribution | ✅ | Reads idtracker.ai's own fragment records |
| D-8 Crossing Rate | ✅ | Per-frame / session-level only |
| D-9 Identity Swap Opportunity Count | ✅ | Reads fragment boundaries, not trajectories |
| D-10 Physical-Plausibility Violation Rate | ✅ | Assumes a fixed row index *by design* — it measures how badly that assumption fails, so it must keep running on identity-free sessions |

**Known gap — zone metrics.** All nine Z-* metrics are listed ✅ above and
are therefore still computed for an identity-free session, yet every one
emits an `individual_id` column and indexes by animal slot `k`. The
occupancy-style ones (Z-1, Z-2, Z-3, Z-5, Z-8, Z-9) remain correct once
summed over individuals; Z-4 (transitions), Z-6 (latency to first entry)
and Z-7 (transition matrix / sequence entropy) need the animal to be the
same throughout and have no such reading. They are left ungated
deliberately, not by oversight: correcting them means emitting pooled rows
instead of per-individual rows on identity-free sessions, which changes
the output shape of six metrics. Do not "fix" this by flipping the flags
alone — that would simply make all zone analysis unavailable for such a
session. See `track2data/metrics/zone.py`'s module docstring and
`docs/ROADMAP.md`.

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
| **Formula** | `coverage[k] = mean(~isnan(raw_xy[:, k, 0]))`; `session_coverage = mean(coverage)` — equivalently, total non-NaN detections / (n_frames × n_animals) |
| **Output columns** | `individual_id`, `coverage_fraction`, `nan_frames_count` |
| **Units** | dimensionless ∈ [0, 1] |
| **Reference** | Tracking-pipeline convention (fraction of frames with a successfully assigned position); no single originating work |
| **Supporting references** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) (DOI: 10.1038/s41592-018-0295-5) |

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
| **Supporting references** | Bernardin & Stiefelhagen 2008, EURASIP J. Image Video Process. 2008:246309 (evaluating multiple object tracking performance: the CLEAR MOT metrics) (DOI: 10.1155/2008/246309) |

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
| **Formula** | `identity_free` if `has_stable_identities=False`; else `stable` if `fraction_identified >= 0.5` (default 0.0 when missing); else `weak` |
| **Output columns** | `identity_stability_status` |
| **Reference** | Track2Data engineering threshold on idtracker.ai's own fraction_identified (PRD §5.2, FR-IMP-3); not an external scientific result |
| **Supporting references** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) (DOI: 10.1038/s41592-018-0295-5) |

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
| **Reference** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) — DOI [10.1038/s41592-018-0295-5](https://doi.org/10.1038/s41592-018-0295-5) |

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
| **Supporting references** | Bernardin & Stiefelhagen 2008, EURASIP J. Image Video Process. 2008:246309 (evaluating multiple object tracking performance: the CLEAR MOT metrics) (DOI: 10.1155/2008/246309) |

#### D-10 — Physical-plausibility violation rate

| Field | Value |
|---|---|
| **Manuscript label** | Physical-plausibility violation rate |
| **Level** | Per individual + session summary |
| **Priority** | Diagnostic (always on) |
| **Inputs** | `Session.raw_xy`, `Session.video.fps` |
| **Formula** | `step_speed[t,k] = ‖raw_xy[t+1,k] − raw_xy[t,k]‖ · fps` (NaN pairs skipped); `speed_limit_px_s = cfg['speed_limit_px_s']` if given, else the `speed_limit_percentile`-th percentile of this session's own pooled `step_speed` distribution (default 99.5th); `violation_fraction` = fraction of an animal's steps with `step_speed > speed_limit_px_s`; `teleport_jump_count` = count with `step_speed > speed_limit_px_s · teleport_multiplier` (default 5.0) |
| **Output columns** | `individual_id`, `violation_fraction`, `teleport_jump_count`, `speed_limit_px_s` |
| **Units** | dimensionless fraction; count; px/s |
| **Assumptions** | Uses `raw_xy`, not the preprocessed trajectory — deliberately independent of gap-fill/jump-detect/smoothing, which this diagnostic exists to help evaluate |
| **Warnings** | The only diagnostic independent of idtracker.ai's own self-report (D-1..D-9 all inherit it) — this is what catches the errors the tracker did not know it made, exactly what silently corrupts IL-2's max speed and IL-6's acceleration downstream. No calibration-derived default: `Session.body_length_reliable` is always `False` (§2.1), so the default limit is data-driven rather than body-length-based; a `cfg['speed_limit_bl_per_s']`-style override is possible once that caveat is explicitly acknowledged, but is not the default. A data-driven percentile default is circular on a session that is mostly bad data — it screens outliers relative to the session's own distribution, not an absolute biological limit. |
| **Parameters** | `speed_limit_px_s` (float, px/s, no default — auto-computed from this session's data when unset), `speed_limit_percentile` (float, default 99.5), `teleport_multiplier` (float, default 5.0) |
| **Reference** | Bjorneraas et al. 2010, J. Wildl. Manage. 74(6):1361-1366 (screening GPS location data for errors using animal movement characteristics) — DOI [10.2193/2009-405](https://doi.org/10.2193/2009-405) |
| **Supporting references** | Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai) (DOI: 10.1038/s41592-018-0295-5) |

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
| GL-7 | `metrics/group.py` | `NNMatchedSpeed` | Greedy nearest-neighbour matching, one pass -- not a globally optimal assignment-problem solve; no `scipy.optimize` dependency |
| GL-11 | `metrics/group.py` | `OrderStateClassification` | Reuses GL-3/GL-8's own per-frame formulas |
| GL-13 | `metrics/group.py` | `TopologicalNeighbourCounts` | `scipy.spatial.cKDTree`, same tree GL-1 builds |
| GL-15 | `metrics/group.py` | `GroupElongation` | `np.linalg.eigh` on the per-frame position covariance |
| Z-1..Z-6 | `metrics/zone.py` | `TimeInZone`, `AreaCorrectedOccupancy`, `ZoneVisitCount`, `ZoneTransitions`, `Z5EntryExitEvents`, `Z6LatencyToFirstEntry` | `shapely` for point-in-polygon |
| Z-7 | `metrics/zone.py` | `ZoneTransitionMatrix` | Reuses Z-4's debounced zone sequence |
| Z-8 | `metrics/zone.py` | `ZonePreferenceIndex` | Reuses Z-2's `roi_areas`/`total_arena_area` derivation |
| Z-9 | `metrics/zone.py` | `ZoneDwellTimeDistribution` | Built on Z-5's event log |
| D-1..D-9 | `metrics/diagnostic.py` | `TrackingCoverage`, `TrackingAccuracy`, `IdProbabilityStats`, `InconsistentFrameCount`, `IdentityStability`, `SegmentationErrorFrames`, `FragmentLengthDistribution`, `CrossingRate`, `SwapOpportunityCount` | Always-on |
| D-10 | `metrics/diagnostic.py` | `PhysicalPlausibilityViolations` | Runs on `Session.raw_xy`, independent of preprocessing |
| IL-9, IL-10 | `metrics/individual.py` | `HomeBaseOccupancy`, `RoamingEntropy` | Share `_occupancy_grid_counts` |
| IL-11 | `metrics/individual.py` | `CircularHeadingStats` | np-only; Zar's Rayleigh-test approximation |
| IL-14 | `metrics/individual.py` | `WallDistanceThigmotaxis` | `shapely` -- the only IL-* metric with that dependency |

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
    primary_reference: Reference | None = None      # metrics/references.py
    supporting_references: list[Reference] = []
```

A metric sets `citation`/`citation_doi` directly as free text when no
single work applies ("Standard kinematics; no single originating
work"), or sets `primary_reference` to a canonical `Reference` from
`metrics/references.py` -- which then fills `citation`/`citation_doi`
automatically, so two metrics citing the same work always render
byte-identical text. Setting both raises at class-definition time.
`supporting_references` is independent of that choice.

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
    parameters: ClassVar[list[MetricParameter]] = []
    superseded_by: ClassVar[str | None] = None       # e.g. Z-2 -> "Z-8"
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

A metric whose class declares `superseded_by` (e.g. Z-2 → `"Z-8"`) gets
a small "superseded by Z-8" note appended to its row label and
repeated at the top of its ⓘ dialog. The superseded metric still
computes exactly what it always has -- this is a steer towards the
better statistic, not a behaviour change.

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
│  Supporting references                       │
│  ──────────────────────                      │
│  • Bjorneraas et al. 2010 (DOI: ...)         │
│                                              │
│                            [ Copy citation ] │
└──────────────────────────────────────────────┘
```

The "Supporting references" panel is omitted entirely when
`documentation.supporting_references` is empty, rather than shown
empty. "Copy citation" copies only the primary citation (plus DOI) --
supporting references are informational, not the manuscript's cited
work.

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
   shown as its raw source string). A "Supporting references" section
   follows "Reference", rendered only when the list is non-empty.
4. Provides a "Copy citation" button that copies the primary citation
   string (plus DOI, when present) to the clipboard; supporting
   references are not included.
5. When `metric_cls.superseded_by` is set, shows a one-line notice at
   the top of the dialog naming the superseding metric.
6. Relies on `QDialog`'s own default Escape handling, plus a
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
   it is disabled with an explanatory tooltip for the 15 of the 34
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
4. **Second reference audit (2026-08)** — resolved. Item 1 above
   describes the first pass, at 33 metrics; a second, independent audit
   found that pass's DOI work sound (no fabricated citation, no wrong
   DOI in either pass) but flagged 11 metrics whose primary citation
   named a paper that does not actually support the method (a
   conceptual review cited for an operational threshold, a simulation
   paper cited for an empirical measurement protocol, an
   unindexed book chapter with no resolvable DOI), plus ~20 metrics
   that would be materially strengthened by a supporting reference.
   Folding a supporting reference into the existing free-text
   `citation` string was not viable — it would have made
   `test_no_doi_is_shared_by_metrics_citing_different_works` unfailable
   only by accident, since several works (Cachat 2010, Romero-Ferrero
   2019, Martin & Bateson 2007, Krause & Ruxton 2002) are now cited by
   more than one metric. `MetricDocumentation` gained
   `primary_reference`/`supporting_references` fields
   (`track2data/metrics/base.py`) backed by a canonical bibliography,
   `track2data/metrics/references.py`, so two metrics citing the same
   work share the same `Reference` object and are byte-identical by
   construction rather than by contributor discipline. The audit's 20
   proposed new metrics were triaged for actual feasibility against
   this codebase (rather than taken at face value) and 11 were built —
   see §3/§4 above and `docs/ROADMAP.md`'s "Reserved metric IDs" table
   for the 9 that were not, and why.
5. **Bout-criterion thresholds (2026-08)** — resolved, as an **opt-in**.
   IL-7's `min_bout_frames`, Z-3's `min_visit_frames`, and Z-4/Z-5's
   `min_dwell_frames` (inherited by Z-6/Z-9 via cfg forwarding) are
   fixed, hand-picked round numbers — defensible as defaults, but
   arbitrary. New module `track2data/metrics/bouts.py` implements the
   Sibly, Nott & Fletcher 1990 log-survivorship bout-criterion
   interval: fit a two-segment line to the log-survivorship curve of
   this session's own pooled run-length distribution and take the
   segments' crossover as the threshold.

   It is wired to a per-metric `derive_bout_criterion` switch that
   **defaults to `False`**, so every existing project keeps the numbers
   it already had; a researcher who wants the data-derived threshold
   turns it on per metric via the ⚙ dialog on the Metrics screen. Making
   it the default was considered and rejected: it changes freezing-bout
   and zone-visit numbers substantially (see CHANGELOG.md for measured
   deltas), and a change of that size to an existing project's results
   should be a decision the researcher makes deliberately, not one a
   version bump makes for them.

   Every affected metric reports which criterion actually took effect
   (`bout_criterion_effective`: `fixed`, `log_survivorship`, or
   `fixed_fallback` when a requested fit did not converge) and the
   threshold actually applied
   (`min_bout_frames_used`/`min_visit_frames_used`/`min_dwell_frames_used`),
   so neither the switch's state nor a fallback is ever silent.

   The switch takes precedence over an explicit threshold in
   `MetricSelection.config`: ticking it means "let the data decide",
   which a typed number would contradict. The typed value is preserved
   rather than cleared, and applies again the moment the switch goes
   off. The ⚙ dialog greys the threshold row out while the switch is on
   (`MetricParameter.disabled_by`) so a control the metric will not read
   does not look editable.
