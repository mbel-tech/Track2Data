# Changelog

All notable changes to Track2Data are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project has not yet made a versioned release, so everything below is
listed under **Unreleased** pending the v0.1.0 tag.

## [Unreleased]

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
- `docs/EXTRACT_BBOXES_FIX.md` — a measured +27.8% body-length bias found in
  `extract_bboxes.py` (a script used in an adjacent pipeline) and its root
  causes.
