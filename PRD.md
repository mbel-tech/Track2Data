# Track2Data — Product Requirements Document

**Status:** Draft v0.1
**Audience:** Implementation team, scientific contributors, OSS reviewers
**License:** MIT
**Distribution:** Open-source desktop application — Windows, macOS, Linux

---

## 1. Software Purpose

Track2Data is an open-source desktop application that turns raw
`idtracker.ai` output folders into analysis-ready behavioural datasets.
It provides a transparent, GUI-driven workflow — **Import → Calibrate →
Map metadata → Preprocess → Extract metrics → Preview → Export** — so that
behavioural ecologists, neuroethologists, and aquaculture researchers can
go from tracker output to publication-grade tables without writing custom
scripts.

The app is **not** a tracker; it consumes `idtracker.ai` outputs only.
It is **not** a statistics package; it produces tidy datasets that drop
straight into R, Python, JASP, SPSS, or Excel.

---

## 2. Target Users

| Persona | Background | Primary need |
|---|---|---|
| **Behavioural ecologist (primary)** | PhD / postdoc; familiar with R or Python but not a software engineer | Reproducible per-trial datasets across many sessions |
| **Aquaculture / welfare researcher** | Applied scientist; limited coding | One-click metrics (speed, zone use, activity) from large session libraries |
| **Neuroethology / pharmacology lab** | Trained in stats; runs identity-aware drug-response studies | Per-individual time-series with treatment metadata |
| **Open-source contributor** | Domain-savvy Python developer | Extensible metric / exporter plug-in points |

---

## 3. Core Use Cases

1. **Single-experiment processing.** Import one `idtracker.ai` session,
   define zones, choose metrics, export per-trial CSV.
2. **Batch processing.** Import dozens of `session_*` folders, attach a
   single metadata spreadsheet, run preprocessing + metrics in parallel,
   export a single tidy long-format dataset.
3. **Iterative re-analysis.** Re-run only the changed stage (e.g. new zone
   layout, new smoothing parameters) without re-importing raw trajectories
   — cached intermediate artefacts.
4. **QC review.** Inspect per-session diagnostics (jumps detected,
   identity switches flagged, % interpolated frames, % NA) before
   exporting.
5. **Cross-experiment harmonisation.** Re-use a saved project template
   (zone polygons, calibration, metric selection) on a new dataset.

---

## 4. User Stories

- *As a* researcher *I want to* drag-and-drop multiple `session_*` folders
  *so that* I can process a whole experiment in one job.
- *As a* researcher *I want to* draw zone polygons on a video frame *so
  that* I do not have to edit CSVs in a text editor.
- *As a* researcher *I want to* upload my trial-summary Excel and map its
  columns to sessions *so that* treatment and date are attached to every
  output row.
- *As a* researcher *I want to* see how many frames were interpolated and
  how many identity switches were flagged *so that* I can trust the
  downstream metrics.
- *As a* researcher *I want to* export both wide and long CSV plus a
  feather file *so that* my collaborators in R and Python can both read
  the data.
- *As a* researcher *I want to* save my project (zones, calibration,
  metadata mapping, preprocessing parameters) *so that* a reviewer can
  reproduce my results from the same `session_*` folders.
- *As an* open-source contributor *I want to* register a new metric via a
  plug-in entry point *so that* domain-specific indicators can be added
  without forking the app.

---

## 5. Functional Requirements

### 5.1 Project & session management

- **FR-PRJ-1** The app SHALL maintain a *project* (a directory + JSON
  manifest) that records: project name, app version, list of imported
  session folder paths and checksums, calibration, zone definitions,
  metadata-mapping rules, preprocessing parameters, metric selections,
  export targets, and a run log.
- **FR-PRJ-2** The app SHALL support multiple projects per user; opening
  a project restores all settings exactly.
- **FR-PRJ-3** The app SHALL provide a "duplicate as template" action that
  copies a project's settings but not its imported data.

### 5.2 idtracker.ai import

- **FR-IMP-1** The app SHALL accept **one or more** `idtracker.ai` output
  folders, selected via a native folder picker, drag-and-drop, or
  command-line argument.
- **FR-IMP-2** For each folder the app SHALL detect: `trajectories.npy`,
  `trajectories_wo_gaps.npy`, `video_object.npy`, `session.json` (and
  modern session-folder equivalents), the source video file path, frame
  count, FPS, frame size, number of tracked animals.
- **FR-IMP-3** The app SHALL flag missing files, version mismatches, and
  empty trajectories with actionable messages (not silent failures).
- **FR-IMP-4** The app SHALL prefer `trajectories_wo_gaps.npy` when
  available, and SHALL record which trajectory variant was used per
  session.
- **FR-IMP-5** The app SHALL never modify files inside the source
  `session_*` folder.

### 5.3 Arena calibration & zone definition

- **FR-CAL-1** The app SHALL accept calibration in two modes:
  (a) **scalar** px-per-cm; (b) **body-length** — auto-derived from the
  mean of per-fish median body length reported by idtracker.ai.
- **FR-CAL-2** The app SHALL support per-session **orientation pairing**
  (e.g. flow-top vs. flow-down) so that a single zone polygon set can be
  reused across mirrored video orientations without re-drawing.
- **FR-ZON-1** The app SHALL provide an interactive zone editor that
  draws polygon ROIs over an extracted video frame; users can name each
  ROI, assign it to a *zone level* (e.g. main, secondary), and assign
  multiple polygons to the same zone label.
- **FR-ZON-2** Zone definitions SHALL be persisted as CSV (schema
  compatible with the existing pipeline: `ROI_index, ROI_name,
  Vertex_index, X, Y`) and additionally as project JSON.
- **FR-ZON-3** The app SHALL support importing existing zone CSVs.
- **FR-ZON-4** Zone area (in user-specified units) MAY be entered per
  ROI for area-corrected occupancy metrics.

### 5.4 Metadata mapping

- **FR-MET-1** The app SHALL accept an **optional** metadata file in CSV
  or Excel (`.xlsx`).
- **FR-MET-2** The app SHALL present a column-mapping UI that lets the
  user assign metadata columns to canonical fields: `session_id`,
  `trial_id`, `individual_id`, `group_id`, `treatment`, `date`,
  `timepoint`, plus an arbitrary number of user-defined experimental
  factors.
- **FR-MET-3** Session-to-row matching SHALL support multiple join keys
  (e.g. by `video_ID`, by `tank + date`, by regex on folder name) with a
  live preview of which sessions matched.
- **FR-MET-4** Unmatched sessions SHALL be clearly listed; the user can
  proceed without metadata, in which case canonical fields default to
  the session-folder name.
- **FR-MET-5** Treatment and other categorical fields MAY be assigned a
  user-defined ordering that is preserved in the export.

### 5.5 Preprocessing

For each imported session, the user SHALL be able to enable / disable and
parameterise the following steps, in this order:

| Step | Parameters | Default |
|---|---|---|
| **PP-1 Gap filling** | max gap length (frames) for interpolation | 30 frames |
| **PP-2 Jump detection** | method = `sd_multiple` \| `percentile`; multiplier; replacement = `NA` \| `linear-interp` | `sd_multiple`, mult=10, linear-interp |
| **PP-3 Identity-switch detection** | Tier-1 mutual-NN ratio threshold; optional Tier-2 Hungarian; consolidation window | **off by default** (ratio=1.5, Tier-2 on when enabled) — measured on real data to re-permute 17.1% of a recording and inject ~640px single-frame teleports; pending a fragment-boundary-aware replacement |
| **PP-4 Smoothing** | method = none \| moving-avg \| Savitzky-Golay; window; polynomial order | Savitzky-Golay, window=5, order=2 |
| **PP-5 Trajectory validation** | min track length (frames); max % NA per individual | 90% coverage |

- **FR-PRE-1** The app SHALL recompute kinematics (speed, acceleration,
  heading) from the post-preprocessing coordinates.
- **FR-PRE-2** Every preprocessing step SHALL emit a diagnostic row in
  the run log: count of affected frames, % of total, per-individual
  breakdown.
- **FR-PRE-3** Preprocessing SHALL be deterministic: identical inputs +
  parameters yield bit-identical outputs.

### 5.6 Metric extraction

> **Canonical spec:** see [`docs/METRICS_SPEC.md`](docs/METRICS_SPEC.md)
> for the implementation-ready definition of every metric ID below
> (formulas, inputs, outputs, units, edge cases, citations) plus newer
> IDs (IL-6 acceleration, IL-7 freezing-bout stats, IL-8 turn rate,
> GL-8 rotational order, GL-9 centroid position, GL-10 group spread,
> Z-6 latency-to-first-entry, and the D-* diagnostic series), plus the
> 2026-08 reference-audit additions (IL-9 home-base occupancy, IL-10
> roaming entropy, IL-11 circular heading statistics, IL-14 wall-distance
> thigmotaxis, GL-11 order-state classification, GL-13 topological k-NN
> counts, GL-15 group elongation, Z-7 zone transition matrix, Z-8 zone
> preference index (Jacobs' D), Z-9 zone dwell-time distribution, and
> D-10 physical-plausibility violations).

The MVP metric catalogue, all selectable per project:

**Individual-level (identity-aware only)**
- IL-1 Path length (cm, BL)
- IL-2 Mean / median / max speed
- IL-3 Distance from arena centre (mean, time-series)
- IL-4 Time active vs. inactive (configurable BL/s threshold)
- IL-5 Tortuosity (path length / displacement)

**Group / collective (identity-aware or identity-free)**
- GL-1 Nearest-neighbour distance (NND)
- GL-2 Inter-individual distance (IID)
- GL-3 Polarisation (alignment order parameter)
- GL-4 Convex hull area
- GL-5 Centroid speed
- GL-6 Group cohesion (1/NND)
- GL-7 Frame-to-frame NN-matched speed (identity-free fallback)

**Zone-based**
- Z-1 Time in each zone (s, % of session)
- Z-2 Area-corrected time in each zone
- Z-3 Zone visit count
- Z-4 Zone transition count (identity-aware: per individual; identity-free: NN-matched flow↔calm crossings)
- Z-5 Entry / exit timestamps

- **FR-MTR-1** Each metric SHALL be computable per session, per trial
  (if defined via metadata), and per user-defined timepoint segment
  (e.g. 20-minute bins).
- **FR-MTR-2** Metric definitions SHALL be exposed via a Python plug-in
  entry point (`track2data.metrics`) so contributors can register new
  metrics without forking.
- **FR-MTR-3** Bodylength threshold for "active" classification SHALL
  default to per-trial mean of per-fish median body length (matching the
  reference R pipeline) and SHALL be overridable as a scalar.

### 5.7 Preview & diagnostics

- **FR-VIEW-1** The app SHALL render a session preview combining: an
  extracted video frame (if the source video is reachable), overlayed
  zone polygons, and the trajectory of each tracked animal.
- **FR-VIEW-2** A diagnostics panel SHALL display per-session: % frames
  with valid identity, count of jumps removed, count of identity
  switches flagged, per-individual coverage histogram, and a speed
  distribution.
- **FR-VIEW-3** A processed-metric preview SHALL show a sortable table
  of all extracted metrics for the current selection plus quick plots
  (boxplot per treatment, time-series per timepoint).
- **FR-VIEW-4** All preview panels SHALL update reactively when
  preprocessing or metric parameters change, without re-importing raw
  trajectories.

### 5.8 Export

- **FR-EXP-1** The app SHALL export tidy datasets in: CSV (long), CSV
  (wide), Excel (`.xlsx`, multi-sheet), Feather/Parquet (`pyarrow`,
  R-readable via `arrow::read_feather`).
- **FR-EXP-2** Each export bundle SHALL include: the data file(s), a
  `manifest.json` recording app version, project hash, all parameters,
  and per-file SHA-256, and a human-readable `README.md` summarising
  the run.
- **FR-EXP-3** Exports SHALL be reproducible: re-running the project on
  the same inputs SHALL yield byte-identical data files (timestamps in
  `manifest.json` excepted).
- **FR-EXP-4** Optional companion exports: zone polygon CSVs, per-frame
  preprocessed trajectory parquet, PNG diagnostics.

### 5.9 Reproducibility & provenance

- **FR-REP-1** Every export and every intermediate cache file SHALL
  reference the project manifest hash and the app version.
- **FR-REP-2** A "reproduce this export" CLI command SHALL accept a
  manifest and a folder of `session_*` inputs and regenerate the
  output without GUI interaction.
- **FR-REP-3** The run log SHALL be append-only and human-readable
  (Markdown).

---

## 6. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Platforms**: Windows 10/11, macOS 12+, Ubuntu 22.04 LTS+ |
| NFR-2 | **Distribution**: signed installer per OS; portable zip; PyPI install for advanced users |
| NFR-3 | **Performance**: process a 60-min, 8-fish, 30-fps session in ≤ 3 min on a 4-core 16-GB laptop |
| NFR-4 | **Memory**: stream trajectories where possible; ≤ 4 GB RSS for a 60-min, 16-fish session |
| NFR-5 | **Concurrency**: per-session parallelism via process pool; user-capped worker count (default = CPU count − 1, hard ceiling 8) |
| NFR-6 | **Determinism**: identical inputs + parameters → identical outputs (no nondeterministic threading inside a single session) |
| NFR-7 | **Accessibility**: keyboard-navigable, screen-reader labels on all controls, contrast-AA palette |
| NFR-8 | **Internationalisation**: UTF-8 file paths; decimal-point locale-independent output; date format ISO-8601 |
| NFR-9 | **Logging**: structured logs (JSONL) plus a user-friendly run log |
| NFR-10 | **License & governance**: MIT, public GitHub repo, semantic versioning, CONTRIBUTING.md, CODE_OF_CONDUCT.md |
| NFR-11 | **Test coverage**: ≥ 80% line coverage on the core engine; reference-pipeline parity tests against the user's existing R outputs |

---

## 7. Expected Inputs

1. One or more `idtracker.ai` session folders, each containing the
   canonical trajectory artefacts (`trajectories.npy` /
   `trajectories_wo_gaps.npy`, `video_object.npy`, `session.json`).
2. Optional source video file (referenced by `video_object.npy`).
3. Optional metadata file (`.csv` or `.xlsx`) with at minimum a column
   identifying each session.
4. Optional zone polygon CSV(s) (`ROI_index, ROI_name, Vertex_index,
   X, Y`).
5. Optional project file (`.t2d.json`) from a previous run.

---

## 8. Expected Outputs

1. **Primary data** — per-session and merged long-format datasets:
   `master_fish_by_frame.{csv,parquet}`,
   `trial_activity_summary.csv`,
   `trial_occupancy_long.csv`,
   `group_dynamics_summary.csv`.
2. **Wide companion** — `trial_summary_wide.csv` for spreadsheet users.
3. **Diagnostics** — `qc_per_session.csv`, `preprocessing_log.csv`,
   `identity_switches.csv`, PNG plots.
4. **Provenance** — `manifest.json`, `run_log.md`,
   `project.t2d.json`.
5. **Cache** (hidden, project-local) — intermediate `.feather` files
   keyed by content hash to enable incremental re-runs.

---

## 9. Assumptions

- A1. Users have already produced `idtracker.ai` outputs; Track2Data
  does not orchestrate tracking.
- A2. Sessions of interest fit in a single project directory tree.
- A3. Source video files, when needed for previews, are reachable via
  their recorded path or can be relocated by the user.
- A4. FPS, frame size, and animal count can be read from idtracker.ai
  metadata; the user does not need to retype them.
- A5. The user has read access to all imported folders and write access
  to the project directory.
- A6. R is **not** required at runtime; the engine is pure Python.

---

## 10. Constraints

- C1. No proprietary dependencies; everything ships under MIT-compatible
  licenses.
- C2. No telemetry, no network calls at runtime (offline-first); update
  check is opt-in.
- C3. No GPU dependency for MVP; pure CPU.
- C4. Single-user desktop scope; no server / multi-tenant mode.
- C5. Cannot modify or re-track within `session_*` folders.
- C6. Identity-aware metrics are only emitted when idtracker.ai reports
  stable identities for ≥ a user-configurable coverage threshold.

---

## 11. MVP Scope

**In MVP (v1.0)**

1. Folder import (multi-select, drag-drop) and parsing of idtracker.ai
   session artefacts.
2. Native folder-tree project model with a JSON manifest.
3. Arena calibration in both `px-per-cm` and `body-length` modes.
4. Interactive zone editor (polygon over still frame) + CSV import /
   export of zone definitions.
5. Metadata import (CSV / Excel) with a column-mapping UI and
   regex / multi-key join.
6. Preprocessing: gap filling, jump detection (`sd_multiple` +
   `percentile`), identity-switch detection (Tier-1 mutual-NN ratio,
   optional Tier-2 Hungarian), smoothing (moving-avg + Savitzky-Golay),
   trajectory validation.
7. Metric catalogue listed in §5.6, all toggleable.
8. Static preview (frame + zones + trajectories), diagnostics panel,
   processed-metric preview table + boxplot.
9. Export to CSV (long + wide), Excel, Feather.
10. Reproducible-run manifest + headless CLI (`track2data run project.t2d.json`).
11. Per-session parallel execution.

**Explicitly NOT in MVP**

- Inferential statistics (LMM, ANOVA, Tukey, FDR).
- Editable PowerPoint plot export.
- Interactive video scrubbing.
- Cloud / network storage.
- Running idtracker.ai from inside the app.
- A bespoke per-experiment template marketplace.

---

## 12. Future Features

- **v1.1** Interactive video scrubbing with frame-by-frame trajectory
  overlay; per-frame manual identity-swap correction with audit log.
- **v1.2** Statistics module — LMM/ANOVA, Tukey HSD + CLD, BH FDR, with
  RE selection by AICc (mirroring the reference R pipeline).
- **v1.3** Editable PPTX / SVG plot export with style tuner.
- **v1.4** Plug-in marketplace for community metrics; signed plug-ins.
- **v1.5** Multi-camera / multi-arena synchronisation.
- **v2.0** Optional cloud sync of project manifests (not raw data) for
  cross-lab reproducibility.

---

## 13. Risks & Edge Cases

| Risk | Mitigation |
|---|---|
| `idtracker.ai` file format changes between releases | Version-detect on import; maintain compatibility matrix in docs; fail loudly, never silently |
| Identity-aware metrics requested on identity-free trajectories | Detect at import; grey-out individual-level metrics with explanatory tooltip |
| Sessions with mixed FPS / frame sizes in one project | Normalise to per-session units; warn before merging |
| Zone polygons drawn on a frame from the wrong video orientation | Orientation tagging (FT/FD pattern) carried per session; refuse to apply mismatched zones |
| Very large sessions (> 4 h, > 30 fish) blow memory | Streaming parquet reader + chunked metric computation; warn at import |
| Source video file unreachable | Preview falls back to a synthetic background; export is unaffected |
| Metadata column ambiguity (`condition` vs `treatment`, `date` vs `trial_date`) | Mapping UI suggests canonical names; aliases recorded in manifest |
| Identity switches over-flagged on dense schools | Tier-2 Hungarian + consolidation window; visible per-event diagnostic; manual override |
| Time zones / locale-dependent CSV decimals | Force UTC + `.` decimal in writers |
| User overwrites an export folder | "Will overwrite N files" confirmation with diff-style preview |

---

## 14. Suggested Workflow & UI Structure

> The full user-facing workflow — wireframes, per-stage decision
> branches, exact validation messages, and save/resume behaviour —
> lives in [`docs/USER_WORKFLOW.md`](docs/USER_WORKFLOW.md). The
> summary below is the high-level structure only.

**Top-level layout** — a left-rail wizard with seven stages, plus a
persistent **Project** dropdown in the header. Each stage has a
"Next" button enabled only when validation passes.

1. **Project** — new / open / duplicate; recent projects list.
2. **Sessions** — folder picker; auto-detected session table (FPS,
   frames, animals, has-video); checkbox-include-in-batch.
3. **Calibration** — px-per-cm or body-length; orientation tagging.
4. **Zones** — interactive polygon editor over an extracted frame; zone
   level + name + optional area; import / export CSV.
5. **Metadata** — file picker; column-mapping UI; live match preview.
6. **Preprocessing & Metrics** — split pane: left = preprocessing
   toggles with parameters; right = metric catalogue with per-metric
   parameters; a single "Run" action computes both.
7. **Preview & Export** — three tabs: *Preview* (frame + zones +
   trajectories), *Diagnostics* (QC + identity-switch log), *Export*
   (format checkboxes, target directory, run-headless CLI snippet).

**Cross-cutting**

- **Run log** drawer (bottom): scrollable Markdown trail of every
  action with timestamps.
- **Status bar**: current project, worker count, last cache hit/miss
  rate.
- **Command palette** (Ctrl/Cmd-K): jump to any stage, trigger
  "Reprocess from step N", open recent project.

---

## 15. Data-Validation & Reproducibility Requirements

- **DV-1** On import, validate file presence, NumPy dtype, shape
  (frames × animals × 2), FPS > 0, frame count > 0.
- **DV-2** Validate metadata: required canonical columns present after
  mapping; categorical levels match expected set if user supplied one.
- **DV-3** Validate zone polygons: ≥ 3 vertices per ROI; no
  self-intersection; coordinates within frame bounds (warn otherwise).
- **DV-4** Validate calibration: px-per-cm > 0; body-length mode
  rejects sessions with < N valid body-length samples.
- **DV-5** Determinism check: a per-release CI job re-runs a fixture
  project and bit-compares against golden outputs (timestamps masked).
- **DV-6** Manifest schema versioned; older manifests upgraded with a
  migration step recorded in the run log.
- **DV-7** Parity tests against the reference R pipeline: same session
  + same parameters → metric values within a documented numerical
  tolerance (e.g. 1e-6 for kinematics, exact for counts).
- **DV-8** Per-export SHA-256 logged so reviewers can verify shared
  files match the manifest.

---

## 16. Open Questions / Decisions Needed

- Plug-in API stability target at v1.0 (frozen vs. experimental).
- Telemetry policy (proposed: none).
- Sample-data fixture source for parity tests — the checked-sessions
  output of the reference choice-experiment R pipeline, which lives
  outside this repository on the maintainer's machine (see
  `CONTRIBUTING.md` §6; the data itself is pre-publication embargoed and
  is never committed).
