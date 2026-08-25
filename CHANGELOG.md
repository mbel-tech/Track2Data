# Changelog

All notable changes to Track2Data are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **New "session" calibration mode** (`CalibrationConfig.mode = "session"`).
  Uses each session's own `length_unit` -- idtracker.ai's px-to-real-unit
  ratio from the validator's Length Calibration tool -- so different
  sessions in the same project can have their own calibration, instead of
  one project-wide scalar value. The Calibration screen now shows three
  modes (Body length / Custom / Session calibration) with a unit picker,
  a required "I confirm" checkbox, and a per-session readiness list so a
  session missing `length_unit` is visible before running.
  `Engine.validate()` blocks the run and names every session missing it
  rather than letting each one fail individually mid-pipeline.
- **`IDT_LENGTH_UNIT_INVALID` warning** is now logged when a session's
  `length_unit` is a genuinely corrupt value (non-numeric, non-finite, or
  a non-positive number other than idtracker.ai's own `-1` "never
  calibrated" sentinel) -- distinguishing "never calibrated" from
  "corrupt value", both of which previously normalised to `None`
  identically and silently.
- **Per-metric configuration is now wired end to end.**
  `Metric.compute(session, cfg)` has accepted a config dict since it was
  written, and six built-in metrics read one, but nothing in the
  pipeline ever passed one -- every `cfg`-reading branch in every metric
  was dead code. `MetricSelection.config` (keyed `metric_id ->
  {param_name: value}`) now feeds `Engine.compute_metrics()`, layered as
  metric defaults, then the user's saved overrides, then this session's
  own derived values (`track2data/metrics/derived.py`) for parameters
  that can't be user-typed, such as IL-3's arena centre or Z-2's zone
  areas.
- **Z-2 (Area-Corrected Occupancy) produces output for the first time.**
  It always returned an empty `DataFrame` in production, since it
  requires `cfg['roi_areas']`/`cfg['total_arena_area']` and nothing ever
  supplied them. With zones defined, these are now derived automatically
  via `zones.geometry.roi_area_px2` (also previously fully tested but
  never called in production).
- **New configurable parameters** across 9 metrics, settable via
  `MetricSelection.config` (GUI wiring for the ⚙ dialog itself is
  tracked separately): IL-3's `inner_radius_fraction` (default 0.5,
  the historical hardcoded value); IL-4's `threshold_multiplier`
  (default 0.1, the historical hardcoded value); GL-6's
  `cohesion_source` (`'nnd'`/`'iid'`, default `'nnd'`, matching this
  metric's prior NND-only behaviour -- see `METRICS_SPEC.md` §8 open
  question 3); Z-3's `min_visit_frames`, Z-4's and Z-5's (and, by
  forwarding, Z-6's) `min_dwell_frames` -- all default to 1 (every
  run counts, matching prior behaviour) and debounce brief boundary
  flicker when raised. IL-7's already-configurable `threshold_px_s`/
  `min_bout_frames` and GL-3's/GL-8's `stationary_threshold_px_s` are
  now formally declared in each metric's `parameters` schema too.
- **The Metrics screen's ⚙ button now works.** It previously did
  nothing but show a "not yet implemented" message. It now opens
  `MetricConfigDialog`, rendering one widget per declared
  `MetricParameter` (a spin box, combo box, or checkbox depending on
  `kind`), with a per-row ↺ reset-to-default and Save/Cancel. It is
  disabled, with an explanatory tooltip, for the 24 metrics that
  declare no parameters. A `derived=True` parameter (IL-3's centre/
  radius, Z-2's zone areas) renders read-only -- it is computed per
  session and can never be saved as a user override. A parameter with
  no declared default (IL-4's and IL-7's `threshold_px_s`, both
  "auto-computed from data when unset") shows "Auto (data-driven)"
  rather than defaulting the control to 0 -- 0 is a real, very
  different threshold from "let the engine compute one" -- and leaving
  it on Auto omits the key from the saved config entirely. Saved edits
  persist into `MetricSelection.config[metric_id]`, round-tripping
  through the project manifest like any other setting.
- **`docs/METRIC_REFERENCES.csv`** — the scientific reference behind
  every metric, in one citable, machine-readable table (`metric_id`,
  `level`, `priority`, `metric_name`, `reference`, `doi`). Generated
  from the code by `scripts/generate_metric_references.py` and pinned
  by `tests/test_metric_references_consistency.py`, which fails if the
  committed file, the code, and `METRICS_SPEC.md` ever disagree — so
  adding a metric without regenerating is caught in CI rather than
  silently publishing a stale list.
- **A "Request a metric" issue form**
  (`.github/ISSUE_TEMPLATE/metric_request.yml`), the repository's
  first. Collects the metric's level (the four `Metric.level` values,
  so a request maps onto the engine's own vocabulary), its name, and a
  DOI. GitHub issue forms have no regex validation, so a companion
  workflow labels a DOI-less request `needs-doi` with an explanatory
  comment and clears the label once the author edits one in.

### Changed

- **Metric citations corrected and completed.** All 33 metrics now
  carry a reference; 15 previously had none at all (every zone metric
  and every diagnostic). The code and `METRICS_SPEC.md` disagreed on
  14 metrics and have been reconciled, with the code as the single
  source of truth. Three substantive corrections:
  **GL-1** (Nearest-Neighbour Distance) cited Couzin et al. 2002 and
  carried its DOI — copy-pasted from GL-3/GL-8. Couzin 2002 is about
  collective memory and spatial sorting, not nearest-neighbour
  distance; GL-1 now cites Pitcher 1973, as the spec had said all
  along. **GL-4** (Convex Hull Area) attributed convex-hull area to
  Buhl et al. 2006, which characterises order via alignment and
  density rather than hull area; replaced with an honest generic
  description and no DOI. **GL-8** named two papers but carried one
  DOI, making it read as covering both; reduced to the single work the
  DOI belongs to. Where no specific work applies, citations now say so
  plainly instead of borrowing an unrelated one.
- **`METRICS_SPEC.md` now documents D-6, D-7, D-8 and D-9**, which had
  been shipping with no section at all — the document described 29 of
  the 33 metrics that actually run, violating its own §6.6 rule that
  every metric must have one.
- **IL-3 (Distance from Arena Centre) now measures each animal from the
  arena it occupies.** With several `main`-level zones — the
  `exclusive_rois` layout, where identities are physically partitioned
  between separate arenas and the pipeline already refuses to compute
  group metrics across them — IL-3 used a single session-wide centre.
  That point sits in the empty gap between arenas, so every animal's
  distance was measured from somewhere none of them ever swam. On a
  two-arena session, an animal sitting dead centre of its own arena
  scored `mean_centre_distance_px = 1196` and `time_in_centre_pct = 0`;
  it now scores `36.5` and `1.0`.

  Which arena an animal belongs to comes from the zone assignment the
  pipeline already computes, taking the *modal* arena across its tracked
  frames so a few stray boundary frames can't move it. An animal never
  seen inside any arena falls back to the session-level centre. With a
  single arena — the common case — every animal shares one centre
  exactly as before, so those projects see **no change**.

  `cfg` gained `centres` / `arena_radii` (one entry per animal,
  `derived=True`, so never user-settable). The scalar `centre` /
  `arena_radius` keys still work for anyone calling `compute()`
  directly.

- **IL-3 (Distance from Arena Centre)'s centre/radius fallback changed.**
  Previously, with no `cfg['centre']` supplied (which was always the
  case -- see above), IL-3 fell back to the centroid of every tracked
  position in the session: a circular definition where "the centre"
  drifts toward wherever the animal happened to spend time, biasing the
  metric it's meant to measure. It now derives the centre/radius from
  the project's own "main"-level zone geometry when one is defined, or
  the video frame's own geometric centre otherwise -- both fixed,
  data-independent references. If you were relying on the old
  centroid-of-positions fallback, `cfg['centre']`/`cfg['arena_radius']`
  are no longer settable overrides for this reason (see "Per-metric
  configuration" above -- derived parameters always win).

- **Body-length calibration mode no longer reads `length_unit`.**
  Previously, whenever a session happened to carry a `length_unit`,
  `bodylength` mode silently divided by it and set `px_per_cm` from it --
  every `*_cm` export column was quietly calibrated from a value the user
  never confirmed using. `body_length_cm` is now always stored in pixel
  units (the field name is a long-standing misnomer, kept for interface
  stability) regardless of whether `length_unit` is present. If your
  project relied on the implicit calibration, switch to the new
  **"session" calibration mode** for the same ratio, now with an explicit
  user confirmation step.

### Fixed

The following were found by a review of the metrics work above, before
any of it shipped in a release. All six produced wrong numbers or
discarded user input rather than failing visibly.

- **Saving a metric's ⚙ configuration discarded any unapplied
  selection.** Saving wrote straight to the project store, whose change
  signal reloads the screen from the manifest -- so every metric ticked
  but not yet applied, plus the quality threshold, silently reverted to
  the last-applied state. The save now carries the on-screen state with
  it, exactly as **Apply selection** does.
- **Z-2 (Area-Corrected Occupancy) produced nothing for a
  self-intersecting arena polygon.** `roi_area_px2` measured the raw
  ring while `assign_zones` repaired it first, so a self-crossing
  polygon -- 2 of 10 in a real idtracker.ai sample -- measured as zero
  area, and Z-2 fell back to the empty output it was just fixed to
  stop producing. A partially-cancelling ring was worse: a plausible
  but wrong area, silently exported. Both now use the same repair.
- **Raising Z-4's `min_dwell_frames` could *increase* the transition
  count it exists to reduce.** The debounce also dropped short runs of
  the "no zone" sentinel, splicing the zones either side of a brief
  tracking dropout into a direct crossing that never happened. Empty
  runs are now always kept: a gap in tracking is missing knowledge, not
  a flicker to smooth over.
- **IL-3's arena radius depended on whether a zone had been drawn.** The
  zone path circumscribed (longer half-extent) while the video-frame
  fallback inscribed (shorter), so the same physical arena gave a 2x
  different radius. On a 2:1 arena the default `inner_radius_fraction`
  boundary landed on the walls, scoring wall-hugging animals as
  centre-dwelling and inverting the thigmotaxis reading. Both paths now
  inscribe.
- **IL-3's centre fell outside the arena when several "main" zones were
  defined.** Pooling them into one bounding box centred it on the empty
  gap between two arenas -- the `exclusive_rois` layout the pipeline
  explicitly supports -- so every centre distance was measured from
  dead space. It now uses the largest such zone and logs that a single
  centre is ill-defined for a multi-arena layout.
- **Opening a ⚙ dialog and pressing Save rewrote values the widget
  couldn't represent.** Values were read back from the spin box even
  for untouched rows, so a stored threshold finer than 6 decimals or
  above the widget's inferred maximum was silently rounded or clamped.
  Untouched rows now round-trip their stored value verbatim.

Three more from the same review, in the contributor-facing tooling
rather than the app:

- **The metric-request DOI check never ran on a triaged request.** It
  fired on `opened` and `edited` only. A metric request that arrives as
  a blank issue and is labelled `metric-request` afterwards emits
  `labeled` — so the check silently skipped exactly the requests that
  came in through triage. It now also runs on `labeled`, and tolerates
  a concurrent label removal instead of failing the run.
- **`scripts/generate_metric_references.py` could silently publish a
  truncated reference list.** The registry imports each metric module
  optionally, so on a venv without `scipy`/`shapely` it holds 23 of the
  33 metrics — and the generator would rewrite the CSV with ten rows
  deleted while printing a success line. It now refuses to write unless
  every built-in metric module imported, and names the one that didn't.
- **The test pinning the DOI regex couldn't fail on the typo it exists
  to catch.** Its extractor read straight across an unescaped `/` — the
  error that terminates the JavaScript regex literal early and would
  throw on every metric request — and returned a truncated pattern that
  still passed every assertion. It now only matches a well-formed
  literal.

## [0.1.0] — 2026-08-24

First public release: the engine, the wizard GUI, and the CLI, wired
end to end and validated against a real 70-session idtracker.ai corpus.

Binaries for Windows, macOS and Linux are published on the release page.
They are **unsigned** — see [`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md)
for the per-OS trust path and why the first release cannot be signed.

Everything below is the change history that led here; for a new user
it reads as a description of what the tool does and does not do rather
than as a diff.

### Changed

- **Identity-switch correction is now off by default** (`PreprocessConfig.identity_switch.enabled`,
  was `True`, now `False`). Measured against the real idtracker.ai corpus, the
  corrector re-permuted 17.1% of a recording and injected ~640px single-frame
  teleports (inflating one stationary animal's measured path length from
  218px to 11,639px, +5234%) — it reasons about identity from raw geometry
  alone, with no knowledge of idtracker.ai's own fragment boundaries, the
  only frames where an identity swap is actually possible. Off by default
  pending a fragment-boundary-aware replacement. If you were relying on this
  correction running automatically, set `identity_switch.enabled = true`
  explicitly in your project manifest.

### Fixed

- **Exported provenance could silently report the wrong app version.**
  `ProjectManifest.app_version` — stamped into every exported
  `manifest.json` and the run README's "App version" row — was an
  independent string literal, one of seven places that hardcoded the
  version with nothing coupling them. Cutting a release by bumping
  `track2data/_version.py` would have left every subsequently exported
  dataset claiming it came from the previous version, with nothing
  failing to indicate it. All seven now derive from
  `track2data/_version.py`, pinned by `tests/test_version_consistency.py`.
- **`trial_activity_summary` and `group_dynamics_summary` had one row per
  (individual × metric) instead of one row per individual.** The
  `csv_long` and `feather` exporters merged metric tables on *every*
  shared column name rather than on the key columns, and every metric
  emits a `metric_id` column holding its own ID — so the join key never
  matched and each metric contributed its own near-empty row. A
  3-metric, 2-animal session produced 6 mostly-`NaN` rows where it should
  have produced 2 complete ones. Both exporters now restrict the join to
  `session_id`/`individual_id`, matching what `csv_wide` already did.
  Note: `metric_id` no longer appears as a column in these two summary
  files — it was the column corrupting the join and carried no
  information there; per-metric provenance remains in the run README.
- Session import previously failed on every real idtracker.ai session
  shipping the default `trajectories.h5` output format (0/70 in the real
  corpus used to validate this project) — the reader had no HDF5 loader and
  raised a fatal error instead of falling back to a readable `.npy`/`.csv`
  format sitting in the same folder. All 70 corpus sessions now import.
- The h5/npy/csv format-fallback now also covers a *present but corrupt*
  higher-priority file (e.g. a truncated `trajectories.h5`), not just a
  missing loader — it previously let a raw, unhelpful I/O exception escape
  instead of falling through to a readable format next to it.
- `jump_detect` was erasing `gap_fill`'s deliberate NaN gaps instead of only
  replacing genuinely anomalous jumps, silently fabricating trajectory data
  across long real gaps.
- `frames_per_second`, `body_length`, and trajectory array shape were
  previously fabricated or discarded instead of read/validated, breaking the
  default body-length calibration mode and masking malformed input.
- Diagnostic D-3 (identity-probability stats) returned `NaN` for every
  animal on every real session, since `np.median`/`np.percentile` propagate
  `NaN` and ~44.5% of `id_probabilities` entries are `NaN` on real data;
  switched to `nanmedian`/`nanpercentile`.
- `idtrackerai.log` parsing didn't match the real log format and reported
  every run identically as "Unknown", including genuine crashes.
- `import_sessions()` silently caught and logged an unreadable session
  instead of raising — a bad session in a project was invisible unless
  someone happened to read the log. `Engine.run()` still tolerates a single
  session failing without aborting the rest of a multi-session batch, but
  now surfaces it as that session's own recorded error rather than dropping
  it. The CLI reports failed sessions explicitly and exits non-zero.
- `run_all()`/`Engine.run()` wrote every session in a batch to the same
  output directory, so a 2+ session run silently overwrote all but the last
  session's output. Each session now writes to its own `<out_dir>/<session_id>/`.

### Added

- Standalone binaries for Windows, macOS, and Linux via PyInstaller, built
  and published through a release workflow triggered on version tags.
- Opt-in code-signing support for all three platforms (Authenticode,
  Apple Developer ID + notarisation, and detached GPG). The steps
  activate automatically once the relevant repository secrets exist and
  are skipped entirely otherwise, so enabling signing is a secrets-only
  change. Releases remain unsigned until then — see
  [`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md), which also explains why
  the first release necessarily cannot be signed.
- `docs/EXTRACT_BBOXES_FIX.md` — a measured +27.8% body-length bias found in
  `extract_bboxes.py` (a script used in an adjacent pipeline) and its root
  causes.
