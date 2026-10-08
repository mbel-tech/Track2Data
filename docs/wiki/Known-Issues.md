# Known issues

**Last reviewed:** 2026-10-08, against v0.1.0 and `main`.

What is currently wrong, missing, or in flux. Fixed items are removed from this page and
live in the
[changelog](https://github.com/mbel-tech/Track2Data/blob/main/CHANGELOG.md) instead.
This page is reviewed at every release; if something here looks stale,
[open an issue](https://github.com/mbel-tech/Track2Data/issues).

## Affecting your numbers

**Metric definitions can still change before 1.0.** Definitions are being corrected as the
reference audit proceeds, and a correction can change exported values. Before publishing,
record the `app_version` and `project_hash` from your export's `manifest.json`, and read
[[Reanalysing After a Metric Fix]].

**`*_pct` columns hold fractions in [0, 1], not percentages.** `time_pct = 0.42` means
42 %. The names are kept so existing analysis scripts do not break; `codebook.csv` carries
the true unit for every column. Do not multiply by 100 twice.

**`*_cm` columns are empty without a scale.** No pixels-per-unit scale means no physical
units — this is not an error. Use `*_bl` (body lengths, which need the tracker's body
length) or set a scale on the Calibration screen.

**Identity-switch correction is off by default, and should usually stay off.** It changes
which animal is which. Turn it on only when you have looked at Preview ▸ Trajectories with
*Raw + processed* and seen swaps that need repairing.

**D-15 (tracker correction census) reports NaN unless pickle loading is allowed.** It reads
the blob layer, which lives in a pickle, so it needs `blob_diagnostics` and
`security.allow_pickle_trajectories`. NaN means "not read", never zero corrections. The
same applies to `CalibrationConfig.body_length_source = "blobs"`, which also changes
`*_cm` values and is therefore not the default.

## Input formats

**idtracker.ai v4 output is not supported.** 6.x is supported and the legacy v5 layout
works; a v4-looking folder fails with `V4_NOT_SUPPORTED` rather than being misread. The
reader is blocked on real v4 sample folders — if you have some, see
[`docs/IDTRACKERAI_V4_SAMPLES.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/IDTRACKERAI_V4_SAMPLES.md).

**An idtracker.ai v5 project on default (body-length) calibration carries no body length.**
Those sessions are exported in pixels only. The run now says so instead of skipping the
calibration silently.

**Other trackers are not readable yet.** The reader foundation (`scan`, saved readers,
confirm-before-add, declared options) is in place, but no second tracker has shipped. A scan
does now *name* formats it recognises but cannot read — SLEAP `.slp`, `trx.mat`, FlyTracker
`-track.mat`, DANNCE, Multi-Worm Tracker `.blobs`, AnimalTA, DeepLabCut 3-D and FicTrac — and
says what to export instead, rather than reporting nothing recognised. See
[[Formats and Interoperability]].

**A required option is never defaulted.** If the files do not record something a reader
needs — frame rate is the common case — you get `READER_OPTION_MISSING` and must supply it.
A guessed frame rate would corrupt every speed and path-length value instead.

## Output and performance

**Excel splits large tables across sheets.** Past Excel's row limit, the per-frame table
continues on a second sheet (*Fish by Frame 2*). Use the CSV or Feather file for the
complete table.

**Parallel runs are not faster on short sessions, and the default is one worker.** Worker
start-up dominates on small sessions. One synthetic benchmark showed 3.2× on 4 cores for 4
sessions of 20,000 frames; this has not yet been measured on real long sessions, which is
why the default is conservative. See
[`docs/BENCHMARKING.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/BENCHMARKING.md).

**A single numpy or shapely call cannot be interrupted.** Cancel is polled between
sessions, preprocessing steps and metrics, so a long single operation finishes first.

## Distribution and citation

**Release binaries are unsigned.** Windows SmartScreen and macOS Gatekeeper will object on
first run; a plain double-click on macOS reports the app as damaged, which is Gatekeeper,
not a bad download. Signing is wired into the release workflow but needs certificates and a
published release — the free programme for open-source projects requires a release to
exist first. Verify your download with `sha256sum -c SHA256SUMS.txt` and see
[`docs/CODE_SIGNING.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/CODE_SIGNING.md).

**There is no release DOI yet.** The Zenodo integration is prepared but not switched on,
and `CITATION.cff` has no ORCID. Until then, cite the version and commit recorded in your
export's `manifest.json` — see [[Citing Track2Data]]. The plan is in
[`docs/dev/RELEASING.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/dev/RELEASING.md).

## Full audit trail

The external critical-issues audit, what was true, what was fixed and what is still open:
[`docs/CRITICAL_ISSUES.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/CRITICAL_ISSUES.md).
