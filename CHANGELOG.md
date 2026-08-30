# Changelog

All notable changes to Track2Data are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`CITATION.cff`, PyPI publishing, and a release checklist.** GitHub's
  "Cite this repository" button now works, and it cites idtracker.ai
  alongside this tool — a paper citing Track2Data without the tracker
  misattributes the part of the pipeline that did the hard work, so a test
  pins that reference. `tests/test_version_consistency.py` also pins the
  version, which otherwise goes stale and makes every citation name a
  release that did not produce the results being cited.

  `release.yml` gains a `pypi` job publishing the engine wheel via **trusted
  publishing** (OIDC — no API token stored anywhere), with `twine check`
  first, because a PyPI version can never be re-uploaded. The desktop
  binaries serve someone clicking through a wizard; a wheel serves the
  headless and HPC cases a binary cannot.

  Both Zenodo and PyPI need a **one-time manual setup** that cannot live in
  a workflow file. `docs/dev/RELEASING.md` is the checklist for each,
  including which of Zenodo's two DOIs goes where.

  `pyproject.toml` gains the author, keywords, classifiers and project URLs
  a PyPI page needs.

- **`SECURITY.md` and `.github/dependabot.yml`.** For a project that ships
  desktop binaries built from PyPI wheels, dependency updates are a real
  supply-chain control rather than paperwork: a vulnerable transitive
  dependency reaches users as a signed-looking executable rather than as
  something they chose to install. Dependabot is grouped and monthly, because
  an update stream nobody reads trains the maintainer to merge without
  looking. `SECURITY.md` covers private reporting, scope, and — at length —
  how to handle a session folder someone else sent you.

- **Property-based invariants for every preprocessing step**
  (`tests/test_preprocess/test_preprocess_invariants.py`). `hypothesis` was a
  declared dev dependency with zero uses anywhere; it now pins the promises
  each step makes: no step mutates its input, `gap_fill` never introduces a
  NaN or fills a gap longer than `max_gap_frames`, `jump_detect` never fills
  a gap it did not create (the generalised form of a real regression),
  smoothing never changes which frames have a position, and
  `identity_switch` only ever permutes — it never alters a coordinate.

  The generator draws gaps as explicit runs rather than an independent coin
  flip per frame. That matters: with per-cell flips only 2 examples in 200
  contained a gap long enough to exercise `max_gap_frames`, and none
  contained an animal that was never detected, so the headline property was
  passing vacuously.

- **`track2data/py.typed`, and mypy in CI.** Ruff's `ANN` rules have required
  annotations throughout the engine since early on, but nothing verified they
  were *correct*, and PEP 561 meant a downstream type checker ignored all of
  them anyway for want of a marker file. Both are fixed: the marker ships in
  the wheel, and `mypy` runs as part of the required `CI passed` gate.

  Getting there fixed 87 real type errors, which fell into five patterns:
  `Metric`'s class attributes were declared as instance variables, making all
  45 concrete metrics' assignments errors (they are `ClassVar` now, which is
  what they always were); `Metric.compute` declared its parameter as `object`
  and every subclass narrowed it, an unsound override 36 times over (it is
  `Any`, with the reason written down: D-1..D-10 take a `Session` and
  everything else a `PreprocessedSession`, and that split is real);
  `_effective_cfg` took a bare `type`; the reader contract did not carry
  `allow_pickle`; and `idtrackerai_v5._find_trajectory` returned `str` where a
  `Literal` was required.

  `warn_unused_ignores` then found **8 stale `# type: ignore` comments** — the
  accumulation the audit flagged — all now removed.


- **Input provenance: the manifest's central claim is now checkable.**
  `SessionRef.sha256` was always `""`, so "these bytes produced these
  numbers" — the whole point of the manifest for a tool whose deliverable
  ends up in a figure — could not be verified by anyone.

  The reader now records which trajectory file it actually read
  (`Session.trajectory_source`); it has to, because `_load_payload` falls
  back through the formats present in a folder, so the file that was read
  is not always the highest-ranked one and cannot be re-derived afterwards.
  Every run hashes that file and records the digest and filename in
  `sessions.csv`. The GUI fills `SessionRef.sha256` on import, which also
  makes `ProjectManifest.project_hash()` cover the inputs rather than only
  the parameters.

  That in turn gives a **staleness check**: when a session folder's
  trajectory file no longer matches the hash the project recorded, the run
  says so loudly. Silently re-exporting a source folder used to change what
  a "reproduced" run meant, with nothing anywhere to notice.

  Never fatal — an input that cannot be hashed costs provenance, not
  results.

- **D-11 Metric Input Provenance, and a `was_jump_replaced` per-frame
  column.** No summary metric said how much of its input was real. A
  session with 92 % coverage and one with 41 % produced indistinguishable
  `path_length_px` rows; D-1 was the only handle, and it measures the
  tracker's raw output rather than what the metrics consumed.

  D-11 reports, per individual: `n_frames_used` (frames non-NaN *after*
  preprocessing — a metric cannot be affected by a frame it never saw),
  plus `frac_interpolated`, `frac_jump_replaced` and `frac_measured`.
  Keyed on `(session_id, individual_id)`, the same key the exporters merge
  summary metrics on, so any metric row can be joined to the quality of the
  data behind it.

  Separately, `master_fish_by_frame.csv` gains `was_jump_replaced`. This is
  **new information, not a split of `was_interpolated`**, which was already
  gap-fill-only by design: a jump-replaced position started life as a real
  measurement that `jump_detect` judged implausible, and was previously
  visible only as an aggregate count in `PreprocessReport`. The mask is
  captured mid-pipeline, since smoothing moves every position afterwards
  and "differs from the input" stops isolating the step once it runs.

- **Cross-session consistency reporting, and a `sessions.csv` in every
  export.** Nothing previously guarded against pooling sessions that are
  not interchangeable. `fps` alone reaches the numbers in four places —
  `compute_kinematics` scales speed and acceleration by it, `JumpCfg`
  thresholds are per *frame*, `SmoothCfg.window` is a frame count (5 frames
  is 167 ms at 30 fps and 83 ms at 60 fps), and path length is a sum over
  inter-frame steps — so a project pooling 30 fps and 60 fps sessions, a
  normal consequence of a camera change mid-study, produced systematically
  different metric values per group with nothing in the export to say so.

  New `track2data.core.session_consistency` reports every way a project's
  sessions disagree: frame rate, group size, video resolution, calibration
  mode, and calibration availability. Each warning names the affected
  sessions and the consequence, not just the discrepancy.

  Surfaced in three places: `Engine.consistency_warnings()` for
  programmatic use, the GUI's Validate action and the CLI's `validate`
  command, and every run's output.

  **These warn, they do not block.** A mixed-frame-rate design is
  legitimate when the analyst knows and can model it; the failure being
  prevented is not knowing. `Engine.validate()` keeps returning only
  blocking issues.

- **Two project-level files at the root of every run's output directory.**
  `sessions.csv` — one row per session with `fps`, `n_frames`,
  `duration_s`, `n_animals`, video resolution, calibration mode,
  `length_unit`, the `px_per_cm` actually used, and identity-free state, so
  a downstream analyst can filter or build a covariate directly. Sessions
  that failed keep a row carrying their id and error, because a silently
  shorter table reads as a smaller study.

  `PROJECT_SUMMARY.md` — the human-readable counterpart, leading with
  anything that makes the sessions non-poolable. Named `PROJECT_SUMMARY.md`
  rather than `README.md` so it cannot be confused with the per-session
  README the `readme` exporter writes into each session folder.

  Both are built from summaries the run already collected, so they cost no
  additional session reads, and neither can fail a run: a bookkeeping file
  that cannot be written is logged, not raised.


- **Opt-in data-derived bout/visit/dwell thresholds (Sibly et al. 1990
  log-survivorship bout-criterion interval).** New module
  `track2data/metrics/bouts.py` fits a two-segment ("broken-stick") line
  to the log-survivorship curve of a session's own pooled run-length
  distribution and takes the segments' crossover as the threshold
  separating short, spurious runs (tracking flicker, brief pauses) from
  genuine ones. Wired to a new per-metric `derive_bout_criterion`
  switch on **IL-7** (`min_bout_frames`), **Z-3** (`min_visit_frames`)
  and **Z-4**/**Z-5** (`min_dwell_frames`, inherited by **Z-6**/**Z-9**),
  exposed as a checkbox in the ⚙ config dialog on the Metrics screen.

  **The switch defaults to off, so no existing project's numbers
  change.** Turning it on is a deliberate, per-metric choice, because it
  moves results substantially. Measured on a synthetic 6-minute,
  4-animal fixture built for this feature (the embargoed real
  idtracker.ai corpus was not available in this environment — these are
  not corpus numbers, but they show the actual magnitude, not just the
  direction): IL-7 freezing-bout counts fell 6–28% per animal (e.g. 18
  bouts → 13) as the fitted threshold (28 frames) absorbed brief speed
  dips the fixed default of 5 had counted as freezing; Z-3 zone-visit
  counts fell 90–94% per animal (e.g. 204 → 12), because the fixed
  default of 1 frame counts every single-frame boundary flicker as a
  distinct visit while the fitted threshold (29 frames) does not; Z-9's
  mean dwell time rose correspondingly (e.g. 0.20 s → 1.83 s).

  Every affected metric now emits two extra columns —
  `min_bout_frames_used`/`min_visit_frames_used`/`min_dwell_frames_used`
  and `bout_criterion_effective` (`fixed`, `log_survivorship`, or
  `fixed_fallback` when the switch was on but the fit did not
  converge) — so the threshold actually applied, and any fallback, is
  visible in the exported data rather than only in the docs. The switch
  takes precedence over an explicit threshold in
  `MetricSelection.config` -- ticking it means "let the data decide",
  which a typed number would contradict -- but preserves that value
  rather than clearing it, so unticking restores it. The ⚙ dialog greys
  the threshold row out while the switch is on, so a control the metric
  will not read does not look editable.
- **`MetricParameter.disabled_by`**, which greys out a config row whose
  value another (boolean) parameter overrides -- so the ⚙ dialog cannot
  offer an editable control the metric will ignore.
- **`MetricParameter.auto_label`**, so a parameter left unset can say
  what that actually means. The generic "Auto (data-driven)" is right
  for IL-4's `threshold_px_s` but would be wrong for a threshold whose
  unset behaviour depends on another parameter, so IL-7's
  `min_bout_frames` shows "Default (5, or fitted)" instead.
- **11 new metrics from the 2026-08 reference audit's proposals**,
  taking the catalogue from 33 to 44: **IL-9** Home-Base Occupancy,
  **IL-10** Roaming Entropy, **IL-11** Circular Statistics of Heading,
  **IL-14** Wall-Distance Thigmotaxis, **GL-11** Order-State
  Classification (polarised/milling/swarm), **GL-13** Topological k-NN
  Counts, **GL-15** Group Elongation/Anisotropy, **Z-7** Zone Transition
  Matrix & Sequence Entropy, **Z-8** Zone Preference Index (Jacobs' D),
  **Z-9** Zone Dwell-Time Distribution, and **D-10** Physical-
  Plausibility Violation Rate -- the only diagnostic independent of
  idtracker.ai's own self-report, screening `Session.raw_xy` directly
  for implausible steps and single-frame "teleport" jumps. Nine other
  proposals were deliberately not built; see `docs/dev/ROADMAP.md`'s
  "Reserved metric IDs" table for which, and why.
- **`track2data/metrics/references.py`**, a canonical bibliography of
  ~35 verified works. Metrics now cite a shared `Reference` object
  (`MetricDocumentation.primary_reference` / `.supporting_references`)
  rather than retyping citation strings, so two metrics citing the same
  paper are byte-identical by construction. `docs/references.bib` is
  generated from it alongside `docs/METRIC_REFERENCES.csv` (which
  gained a `supporting_references` column) by
  `scripts/generate_metric_references.py`, and both are pinned by
  `tests/test_metric_references_consistency.py`.
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
  disabled, with an explanatory tooltip, for metrics that declare
  no parameters. A `derived=True` parameter (IL-3's centre/
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

- **Coverage now measures the whole shipped package, with two floors.**
  `[tool.coverage.run] source` listed `track2data` alone, so the single 80 %
  figure measured the engine while `tests/test_ui/` (14 files) and
  `tests/test_app/` ran against no floor at all — and the number was
  naturally read as whole-project coverage. `app` and `ui` are now included,
  and CI enforces two thresholds from the one coverage run: **90 % on the
  engine** (~96 % today) and **85 % on the GUI** (~90 %). Two rather than
  one, because a well-covered GUI must not be able to mask an engine
  regression: an engine bug silently changes numbers that end up in a
  figure, while a GUI bug is visible to the person hitting it. Policy
  documented in `docs/TECHNICAL_SPEC.md` §11.1a.

- **The README leads with the user path.** It opened with a list of eight
  internal design documents, PRD first. It now opens with what the tool is
  for, what it deliberately does not do (no tracking, no statistics), how to
  install it, a five-line quickstart, an example of the output table, and
  how to cite it. `PRD.md`, `DECISIONS.md`, `docs/ROADMAP.md` and
  `docs/UI_DESIGN.md` moved to `docs/dev/`; `idtrackerai_output_structure.md`
  moved into `docs/`; `extract_bboxes.py` moved to `scripts/`. Every internal
  markdown link was repaired and is checked to resolve.

- **`docs/dev/ROADMAP.md` cut to milestones** (258 → 149 lines). The
  completed M1–M3 task lists were a third place recording what shipped,
  alongside the CHANGELOG and the issue tracker; three places to update meant
  two went stale.

- **`scripts/extract_bboxes.py` is marked unmaintained and known-wrong.**
  The audit recommended condensing `docs/EXTRACT_BBOXES_FIX.md` into a
  CHANGELOG entry and deleting it. That would have been wrong: the four
  defects it catalogues were **never applied to this copy** — `blob.contours`
  is still there at line ~47 — so the document is a pending correction guide,
  not a fix narrative. It moved to `docs/dev/` and the script now says so in
  its module docstring, along with a pointer to the packaged blob reader,
  which does the same job behind a restricted unpickler.

- **Five metrics were returning columns they did not declare.**
  `Metric.output_columns` is what the UI, the exporters and the generated
  docs promise, and IL-1 (`path_length_cm`, `path_length_bl`), IL-2
  (`mean_speed_cm_s`, `mean_speed_bl_s`), GL-1 (`mean_nnd_cm`,
  `mean_nnd_bl`), GL-5 and GL-7 (`*_cm_s`) all under-declared. All are
  emitted unconditionally — NaN when uncalibrated rather than absent — so
  they are now declared.

  The 33 per-metric `test_output_columns_present` tests could not catch
  this: each asserted a hardcoded list of names was *present*, a subset
  check against a literal that never read `output_columns` at all. They are
  replaced by one parametrised test over the whole registry asserting set
  **equality**, run against both a calibrated and an uncalibrated session —
  which also pins that the calibration-dependent columns never change the
  schema's shape. Metrics are run through the engine's effective config, so
  derived parameters (IL-3's arena radius, which gates
  `time_in_centre_pct`) are supplied as they are in a real run.

- **Speed, acceleration and heading are now Savitzky–Golay derivatives.**
  **Every speed, acceleration and turning value will change.** The previous
  estimator had two compounding defects:

  1. *A half-frame offset.* Speed was a forward difference assigned to frame
     *t*, which actually estimates the derivative at *t + ½*. On a uniformly
     accelerating trajectory the resulting bias is exactly `a·Δt/2`, every
     frame, in the same direction — now pinned by a regression test.
  2. *Squared noise.* Acceleration was a first difference **of that first
     difference**, so positional noise was amplified twice over.

  Both quantities now come from one filtered derivative of position each,
  using the Savitzky–Golay filter family already applied to positions — no
  new dependency, since `scipy` was already required.

  Measured on a synthetic correlated random walk with realistic positional
  noise (3000 frames at 30 fps; **not** corpus numbers — the embargoed
  corpus was not available here — but they show the magnitude, not just the
  direction): mean speed **−10.6 %**, max speed **−55.1 %**, mean |accel|
  **−76.1 %**, max |accel| **−71.3 %**. The old maxima were largely noise.

  Two further improvements fall out of the method: there is no longer a
  special case at the end of a session (a forward difference had nowhere to
  look, so the last frame's speed and the last two accelerations were NaN —
  an artefact of the arithmetic, not a property of the data), and a single
  missing position no longer destroys its neighbour's value, because
  derivatives are taken per contiguous segment and never bridge a gap.

  **The old estimator is retained** as
  `PreprocessConfig.kinematics.method = "forward_difference"` for one
  release, so a project can reproduce earlier numbers; its artefacts are
  pinned by tests as known behaviour rather than as goals.

- **IL-6 acceleration is documented as tangential**, i.e. the rate of change
  of speed `d|v|/dt` — which is what it always was, and what the metric spec
  says, but the distinction was never written down. It is obtained from the
  exact identity `(v · a)/|v|` rather than by differencing a differenced
  series. It is *not* the magnitude of the acceleration vector: an animal
  circling at constant speed reports zero, and the centripetal component
  belongs to the turning metrics. A test pins this, so the two can never be
  swapped silently.

- **Caveats the estimator cannot fix are now recorded on the metrics they
  affect.** IL-1 records that summing step lengths sums `|dx|` rather than
  `dx`, so `E[|dx|] > |E[dx]|` whenever there is positional noise: path
  length is biased *upward*, always, and the bias grows with frame rate —
  making path length non-comparable across the mixed-rate projects
  `sessions.csv` now surfaces. IL-8 records that stationary frames carry no
  heading and are therefore absent from its denominator, so a mostly-still
  animal's turn rate is estimated from a small, non-random subset of its
  behaviour.


- **PP-3 is dramatically faster and no longer degrades quadratically.**
  Measured on synthetic 8-animal sessions: an hour-long session (108k
  frames) went from 47.8 s to 4.7 s on the full-scan path, and to 0.07 s
  when fragment boundaries are available. The nested Python loop that
  rebuilt a distance matrix already computable by broadcasting is gone.
  A crowded session, where many permutations are accepted, previously did
  not terminate in any useful time; the running permutation is now
  materialised in one pass, keeping the whole step linear in frame count.
  Performance guards with explicit budgets were added so either
  regression fails in CI rather than in someone's afternoon.

- **PP-3's tests now assert what the step did to the data.** Several
  previously asserted only `out.shape == xy.shape` — including one that
  injected a real identity swap and never checked whether it had been
  corrected, which is how these defects survived. Added
  `tests/test_preprocess/test_identity_switch_crossing_regression.py`
  covering the canonical crossing cases.


- **Second reference-audit pass: primary citations corrected on 11
  metrics, supporting references added to ~20 more.** An external
  audit resolved every DOI in the repo against Crossref and found none
  fabricated and none wrong, but several attributions named a paper
  that does not actually support the metric:
  **IL-4** (Activity/Freezing Fraction) cited Stewart et al. 2012, a
  conceptual review with no operational velocity threshold; a
  configurable-threshold metric needs a protocol source, so IL-4 and
  **IL-7** (Freezing-Bout Count & Duration) now cite Cachat et al. 2010,
  which gives one (Stewart moves to supporting).
  **IL-8** (Turn Rate) cited Couzin et al. 2002, a *simulation* paper
  where turning is a model parameter, not a measurement protocol; now
  cites Kareiva & Shigesada 1983 (correlated-random-walk turn-angle
  analysis), with Mwaffo 2015's zebrafish-specific formulation as
  supporting.
  **Z-4** (Zone Transitions) cited a real but Crossref-unindexed book
  chapter (Fagen & Young 1978 in Colgan's *Quantitative Ethology*) that
  no reader could resolve; now cites Bakeman & Gottman 1997.
  **GL-1** (NND) cited Pitcher 1973 as primary, but the statistic
  itself originates with Clark & Evans 1954; Pitcher moves to
  supporting as the schooling-specific application.
  **GL-3** (Polarisation) cited Couzin et al. 2002, but the polar order
  parameter is Vicsek 1995's; Couzin now supports it.
  **GL-4** (Convex Hull Area) turned out not to be reference-less after
  all — the minimum convex polygon (of which this is the 2-D case)
  originates with Mohr 1947.
  **GL-7** (NN-Matched Speed) now cites Bernardin & Stiefelhagen 2008
  (CLEAR MOT), matching what the code actually computes (a greedy,
  one-pass nearest-neighbour match — not the Hungarian/assignment-
  problem solve the previous "greedy or Hungarian" spec text implied).
  Z-3, Z-5, GL-2, and GL-6 had a real citation but no DOI (Martin &
  Bateson 2007 and Krause & Ruxton 2002's book DOIs); both are now
  filled in. Full detail and the audit's own verdict table are in the
  commit history; nothing above changes what any metric computes.
- **Z-2 (Area-Corrected Occupancy) marked superseded by Z-8** (`Metric.
  superseded_by`, rendered in the ⓘ dialog and the metrics-screen row).
  Z-2's unbounded, asymmetric ratio cannot be meaningfully averaged
  across animals or compared across arena designs; Z-8 (Jacobs' D) is
  bias-corrected and bounded [-1, +1] on the same underlying data. Z-2
  itself is untouched — no existing project's exported numbers change.
- **Spec-vs-code corrections (no numeric change):** GL-7's spec
  described "greedy or Hungarian matching" and "solve assignment
  problem"; the implementation has only ever been greedy, one pass —
  the spec now says so. IL-5's spec named no specific tortuosity
  estimator; it now states the code computes the reciprocal of the
  whole-track straightness index D/L, not sinuosity or a fractal
  estimator, per Benhamou 2004's own point that these are not
  interchangeable. D-5's spec said "pass-through + categorical" instead
  of naming the actual `fraction_identified >= 0.5` rule the code has
  always used. GL-10's spec now states it computes RMS distance to the
  centroid specifically, not SD of positions or mean pairwise distance.
  D-1's spec now states its denominator explicitly (frames ×
  individuals). Z-6's spec now states that the `inf` convention for an
  animal that never enters is this tool's own choice, not something its
  citation (a rodent light/dark-box paradigm) specifies.
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

### Removed

- **Agent planning artefacts** (`docs/superpowers/plans/`, `docs/superpowers/specs/`)
  — 1,978 lines of working notes for one already-shipped UI redesign. They
  are in the git history and in the PR that shipped it.

- **`track2data/readers/idtrackerai_v4.py`.** A stub whose `detect()` always
  returned `False` and whose `read()` raised `NotImplementedError`: it could
  never be selected, and could only fail if it somehow were. D-012 had already
  removed its entry point, but the class stayed registered as a built-in,
  where it did nothing except violate the reader contract that `read()` returns
  a `Session`. A class that raises on use is worse than an absent one. The
  decision record keeps the history.

- **`codebook.csv` in every export.** One row per exported column with its
  unit, level, originating metric, definition, citation and DOI, generated
  from the registry. That turns "45 cited metrics" from a README claim into
  a machine-readable artefact shipped with the data.

  It also fixes a unit trap nothing else records: **every `*_pct` column in
  this project holds a fraction in [0, 1], not a percentage.** `time_pct =
  0.42` means 42 %, and a reader trusting the suffix records 0.42 %. All
  eight such columns (`time_pct`, `time_in_centre_pct`, `home_base_time_pct`,
  `wall_contact_time_pct`, `polarised_time_pct`, `milling_time_pct`,
  `swarm_time_pct`) are documented as fractions. The names are unchanged —
  renaming them would break every existing analysis script — so the codebook
  is where the units are stated truthfully.

  A test asserts every column in the registry resolves to a known unit, so a
  new metric cannot ship a codebook row reading "unknown".

- **`metrics_long.csv` — a genuinely long table.** Despite its name, the
  `csv_long` exporter only wrote *wide* tables: one row per session ×
  individual with a column per metric, with `metric_id` dropped during the
  merge. The new file is
  `session_id, individual_id, zone_name, from_zone, to_zone, metric_id,
  column, value, unit` — one row per measured value, across individual,
  group, zone and diagnostic metrics at once. It keeps `metric_id`, so a
  value can be traced back through the codebook to the work that defines it,
  and it joins to `codebook.csv` on `column`.

### Fixed

- **PP-3 identity-switch correction now corrects identity switches.** The
  step was unsound in three compounding ways, all of which changed data
  for the worse when enabled. It remains **off by default**, so no
  existing project's numbers change unless it was deliberately switched
  on in the manifest.

  1. *Silent no-op for dyads.* The Tier-1 gate compared distances **among
     conspecifics within a single frame**, so self-distance had to be
     excluded — leaving one finite distance at `n_animals == 2` and a
     ratio test that could never fire. On a synthetic dyadic crossing
     with a persistent swap at frame 21, the step reported 0 frames
     corrected and left mean absolute error at 16.0 px, unchanged. Dyads
     are one of the commonest designs in the target literature.
  2. *Corrections did not persist.* An identity switch is a **persistent**
     relabelling, but the permutation was applied one frame at a time for
     the 5 frames of `consolidate_window` and never propagated. On a
     4-animal crossing this corrected 6 frames, moved mean absolute error
     only from 8.00 px to 7.35 px, left 32 of 60 frames on the wrong
     identity, and introduced a 14 px per-frame step where the true step
     is 2 px — converting one discontinuity into several, which is worse
     for speed, acceleration and IL-1 than leaving the switch alone.
  3. *Implementation did not match its own docstring.* The documented
     algorithm (predicted next positions extrapolated from *t-1* to *t*,
     matched against observations at *t+1*) was never implemented; what
     ran was a proximity detector that fired whenever two animals were
     close relative to a third, regardless of whether the assignment was
     actually ambiguous. Tier-2 assigned on a constant-*position*
     prediction, which fails precisely in the moving-crossing case it
     exists for. One computed cost matrix was never read.

  The rewrite uses constant-velocity prediction, keeps an accepted
  permutation in effect until something later supersedes it, and accepts
  a permutation only when it beats the tracker's own labelling by
  `tier1_ratio` — so a crossing on its own, where the two costs tie, no
  longer triggers a swap.

  **`consolidate_window` is retained for manifest compatibility and is no
  longer read.** `tier1_ratio` keeps its name and default (1.5) but is now
  the acceptance margin rather than a nearest-neighbour ratio.

- **PP-3 uses idtracker.ai fragment boundaries when the session has them.**
  `preprocess.pipeline` now passes `fragment_swap_boundaries(session.fragments)`
  into `correct_switches`, mirroring how the crossing mask already reaches
  `fill_gaps`. Fragment boundaries are the only frames where a swap is
  physically possible, so everywhere else the search could only manufacture
  false positives. Sessions without `preprocessing/list_of_fragments.json`
  fall back to scanning every frame, as before — fragment data is a bonus,
  never a requirement.


The following were found by a review of the metrics work above, before
any of it shipped in a release. The first six produced wrong numbers or
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

And the remaining low-severity items from that review, mostly
robustness against inputs the code accepted but couldn't represent:

- **A `null` in a saved config silently dropped the whole metric.**
  `Engine._effective_cfg()` skipped a `None` *default* so the key stayed
  absent, but copied a `None` *override* straight through — a metric
  then passed its `"key" in cfg` check, failed the conversion, and was
  logged and dropped, leaving the export quietly missing it. The guard
  is now symmetric: a null means "unset".
- **A typo'd `cohesion_source` silently produced NND numbers.** GL-6
  fell through to its default branch for any unrecognised value, so
  `"IID"` or `"iid "` exported nearest-neighbour cohesion while the
  project file recorded the user choosing inter-individual. It now
  raises.
- **Z-2 guarded a zero total arena area but not a negative one.** Zone
  areas are signed, so exclusion polygons outweighing their parent gave
  a negative total that sailed past the check and exported negative
  occupancy fractions that look like real measurements.
- **IL-7 didn't honour the IL-4 threshold rule it claimed to share.**
  IL-4 gained a configurable `threshold_multiplier`; IL-7 kept a
  hardcoded 0.1 while its help text said "same threshold rule as IL-4",
  so raising IL-4's left `active_fraction` and `freezing_bout_count`
  measured against different thresholds in one export. IL-7 now declares
  the same parameter — set independently, which the help text now says.
- **The ⚙ dialog mis-rendered values it couldn't represent.** A saved
  choice outside the declared options was silently replaced by the first
  one; a bool stored as the JSON string `"false"` rendered *checked*,
  the exact opposite of what was stored. Both are now shown faithfully.
- **Opening ⚙ and saving without editing no longer writes anything.**
  It used to freeze every declared default into the project as though
  chosen, so a later change to a metric's default would silently not
  reach it. Untouched, never-configured rows are omitted; the engine
  layers the schema default anyway, so results are unchanged.
- **`METRICS_SPEC.md` documented parameters that don't exist.** IL-4's
  row named `threshold_bl_per_s` (in BL/s) where the code has
  `threshold_px_s` (px/s, auto) and `threshold_multiplier` — setting the
  documented key did nothing, silently, and the shared `0.1` made it
  easy to miss. Z-4's formula row still described the pre-debounce
  implementation. A new test now fails if the spec names a parameter no
  metric declares. Also corrected a metric count stated wrongly in three
  places, and IL-3's `output_columns`, which omitted a column it always
  emits.

### Security

- **Loading a trajectory file no longer executes whatever code it contains.**
  `formats/npy.py` called `np.load(..., allow_pickle=True)` unconditionally
  while its own docstring claimed the GUI/CLI enforced a consent gate first.
  No such gate existed anywhere — a fact `docs/IDTRACKERAI_FORMAT_ANALYSIS.md`
  had already recorded. Since `npy` is one of idtracker.ai's default
  trajectory output formats, that path was reached by importing an *ordinary*
  session folder, which made any shared, downloaded or collaborator-supplied
  folder an execution vector. That matters more for a desktop app that
  invites the user to point a file dialog at data than it would for a library.

  New `ProjectManifest.security.allow_pickle_trajectories`, **defaulting to
  False**, is threaded from the manifest through `Engine.import_session()` →
  `read_session()` → `IDTrackerAiReader.read()` → `_load_payload()` into the
  loader, which now refuses with `IDT_PICKLE_REFUSED` — a documented error
  code that had never been implemented (issue #77).

  **A refusal is not an import failure.** The reader's existing
  format-fallback walk treats it like any other unreadable format, so a
  folder carrying an h5 or csv trajectory alongside the pickled one — which
  a standard idtracker.ai session does — imports exactly as before and never
  prompts. Only a pickle-only folder forces the question, and the error then
  names consent as the cause rather than leaving the user thinking the file
  is corrupt.

  The GUI asks once per project, naming the folder, and persists the answer;
  the CLI reports it. The audit named one ungated call site — there were
  **two**: `idtrackerai_v5.py`'s `video_object.npy` load is a second,
  separately reachable one. It carries metadata only, with a session.json
  fallback, so refusing it degrades the import rather than failing it.

  Third-party readers are unaffected: `read_session()` passes the keyword
  only to readers that set `SessionReader.accepts_allow_pickle`, so one
  written against the original `read(folder)` signature keeps working.

  **Existing projects that import pickle-only session folders will need to
  opt in once**, via the GUI prompt or by setting
  `security.allow_pickle_trajectories` in the project file.

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
- `docs/dev/EXTRACT_BBOXES_FIX.md` — a measured +27.8% body-length bias found in
  `scripts/extract_bboxes.py` (a script used in an adjacent pipeline) and its root
  causes.
