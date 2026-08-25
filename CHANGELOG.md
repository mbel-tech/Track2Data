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

### Changed

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
