# Handoff: running the public idtracker.ai datasets through the Track2Data CLI

Run on 2026-10-11, Python 3.14, Windows 11, on branch `fatina-del-codice/idtrackerai-samples-readers-42a9af`
(commit `c415348`, [PR #146](https://github.com/mbel-tech/Track2Data/pull/146): CSV time-column fix, probability
shape check, `fps`/`width_px`/`height_px` reader options, `IDT_PICKLE_REFUSED`). Everything below was run in this
session; nothing in the repository or in the input files was modified. The scratch work lives outside the repo.

Purpose: decide what has to change before "these datasets were run successfully through the software" can be
claimed in the documentation next to `tracker_test_datasets.csv`.

## 1. Result in one paragraph

All five datasets (movement-data h5, movement-data CSV bundle, synthetic no-fps CSV, MoveR pickled dict,
FishTank 4.0.9 pickled dict) go through `scan`, `add`, `validate` and `run` and write the full output set
(`metrics_long.csv`, `master_fish_by_frame.{csv,feather}`, `manifest.json`, `README.md`, ...) **only after the
project file has been edited by hand**. Straight from the command line, with the options the software itself
tells the user to give, none of them runs. The three things that stop a user are in section 4 (items 1-3).

## 1b. Follow-up: items 1-3 fixed (same branch, PR #146)

After this run, items 1-3 of section 4 were fixed and the flow re-run with only documented flags, no hand-edited project
file (h5, no-fps CSV, MoveR pickled dict: `new`, `add --option width_px=... height_px=... [fps=...] [--allow-pickle]`,
`validate`, `run`; all exit 0). Sections 3 and 4 below describe the state **before** the fix and stay as the record.

- Item 1: `IDTrackerAiReader.discover()` and the `trajectories/` subfolder hint now pass `parameters=cls.parameters`, so
  `add --option` (and the confirm dialog) know `fps`, `width_px`, `height_px`.
- Item 2: `track2data add --allow-pickle` sets `security.allow_pickle_trajectories` on the project and prints a warning
  that the file executes code on load. Without the flag the setting is untouched.
- Item 3: `validate` now also probes every session (`Engine.session_read_issues`, cheap probe path) and reports what `run`
  would fail on, together with the other issues, even when no metric is selected. The GUI's pre-flight is unchanged.
- Tests: `tests/test_cli/test_idtrackerai_bare_export.py` (7).
- Item 7 done: `tests/real_samples/test_idtrackerai_cli_run.py` (9 tests, `-m contract`) drives `new`, `add`, `validate`, `run`
  through the CLI on the cached fixtures (h5, CSV bundle, no-fps CSV, MoveR pickled dict) and checks the output file set,
  frames x animals row counts, h5-vs-CSV agreement, the `validate` refusal without options/consent, and that the input folder
  is unchanged. The 464k-frame FishTank file is not in it (not in the fixture manifest; ~100 s).
  Still open: items 4, 5, 6 and 8 (one error at a time, flat folders, all-NaN cm columns, smaller points).

## 2. Method

For each dataset: copy the cached, sha256-pinned fixture into `<session>/trajectories/<export>` (the only layout
the reader claims), then `track2data scan`, `new`, `add --yes`, `validate`, `run -e csv_long -e csv_wide -e feather -e readme`
with metrics IL-1, IL-2, IL-5, GL-1, GL-5, D-1, D-2, D-3, D-5 (the run adds the other diagnostics itself).
Three project variants per dataset:

| Variant | Reader options | Pickle consent |
|---|---|---|
| A | none | no |
| B | `width_px`, `height_px` (+ `fps` where the file has none) | no |
| C | same as B | yes (`security.allow_pickle_trajectories: true`) |

Video sizes are **placeholders** (1000x1000; MoveR 3840x2160, width assumed): no public bare export records the
video size. Only the mechanics are tested. Values in cm, cm/s or body lengths must not be quoted as results.

## 3. Results matrix

`ok` = exit 0 and outputs written. `fail(code)` = exit 1 with that code. Variants B and C used options written
into the project file by hand (see item 1 below for why).

| Dataset | scan | add (A) | validate (A) | run A | run B | run C | Wall time (run C) |
|---|---|---|---|---|---|---|---|
| movement-data h5 (508 fr, 8 animals) | ok, HIGH | ok | ok ("ready") | fail(`IDT_DICT_MISSING_KEY` width) | ok | ok | 20 s |
| movement-data CSV bundle (same session) | ok, HIGH | ok | ok | fail(`IDT_DICT_MISSING_KEY` width) | ok | ok | 20 s |
| synthetic no-fps CSV (2 animals, 4 rows) | ok, HIGH | ok | ok | fail(`IDT_DICT_MISSING_KEY` frames_per_second) | ok | ok | 19 s |
| MoveR pickled dict (12,033 fr, 20 slots) | ok, HIGH | ok | ok | fail(`IDT_PICKLE_REFUSED`) | fail(`IDT_PICKLE_REFUSED`) | ok | 24 s |
| FishTank 4.0.9 pickled dict (463,997 fr, 2 animals) | ok, HIGH | ok | ok | fail(`IDT_PICKLE_REFUSED`) | fail(`IDT_PICKLE_REFUSED`) | ok | 98 s |
| h5 placed flat (`trajectories.h5` beside nothing) | "No tracking output was recognised" | n/a | n/a | n/a | n/a | n/a | n/a |

About 15 s of each wall time is start-up (imports); the FishTank file therefore costs about 80 s of real work and
writes 134 MB (`master_fish_by_frame.csv` alone is 100 MB). Memory was not measured.

Output checks (variant C):
- h5 and CSV bundle of the same session agree: `x_px` differs by at most 0.0006 px (the CSV keeps 3 decimals),
  `id_probability` identical.
- Row count equals frames x animals (4,064 = 508 x 8). The exported positions are the preprocessed ones (gap fill,
  jump replacement, Savitzky-Golay smoothing): against an independent h5py read the median difference is 0.18 px,
  p99 1.4 px, max 17 px. This is by design, but the documentation must say the exports are not the raw positions.
- MoveR: 20 identity slots, 240,660 rows, `time_s` consistent with 25 fps; slots 13-19 carry 13.8-100 % NaN and
  the run logs one validation warning per slot.
- The synthetic no-fps CSV now reads with both animals and its probabilities (fixed in PR #146).
- Warnings seen: `IDT_VIDEO_PATH_UNREACHABLE` (h5, CSV: the recorded path is on the contributor's machine),
  `IDT_VERSION_UNKNOWN` (MoveR, FishTank, synthetic: no 5.x/6.x version string), `IDT_BODY_LENGTH_UNRELIABLE` (info).

## 4. What has to change, ranked

### 1. `add --option` and the confirm dialog do not know the idtracker.ai options (defect, introduced by PR #146)
`track2data list-readers` lists `fps, width_px, height_px` for `idtrackerai`, but

```
track2data add proj.t2d.json <session> --option width_px=1000 --option height_px=1000 --yes
[error] [READER_OPTION_INVALID] Reader 'idtrackerai': option 'width_px' is not an option of this reader
```

Cause: the confirm step takes its option list from `Detection.parameters`, and
`IDTrackerAiReader.discover()` / `_trajectories_subfolder_hint()` in `track2data/readers/idtrackerai/reader.py`
build their `Detection` without `parameters=cls.parameters` (compare `ctrax_mat.py:149`, `sleap_analysis.py:208`).
The PR's unit tests call `read_session(options=...)` directly, so they never went through `add`.
The GUI confirm dialog is fed from the same object, so it would show no fields either.
Fix: pass `parameters=cls.parameters` in both places. Test: `add --option ...` on the h5 fixture, then `run`, in
`tests/real_samples` (see item 7). This is the first thing to do; it is a two-line change.

### 2. Pickle consent cannot be given from the command line
`add` and `run` have no consent flag. The only route is editing `security.allow_pickle_trajectories` in the
`.t2d.json` by hand (the GUI has its own prompt). The error message tells the user to "enable
security.allow_pickle_trajectories for this project" without saying where. Both pickled datasets (MoveR, FishTank)
and every 4.x FishTank file depend on this. Options: an `add --allow-pickle` flag that sets the project field and
records the consent in the manifest, or a message that names the file and the key.

### 3. `validate` says "ready to run" for projects that `run` then rejects
`validate` exited 0 with "OK ... is ready to run" for every A and B project, including those that fail on the very
next command (missing width, missing fps, pickle refused). It checks the schema and reachability but does not
probe the sessions. Because a missing size or consent is the common first failure for bare exports, `validate`
(or a `validate --probe`) should run `probe_session` per session and report these. Without metrics selected
`validate` stops at "No metrics selected" before it looks at the sessions at all.

### 4. Errors arrive one at a time
FishTank variant B (options given, no consent) fails on consent; only after consent is the next problem shown. In
the other direction (consent but no size) the user gets the size error. A first-time user of a bare pickled export
therefore needs at least two failed runs. Report every blocking problem of a session at once.

### 5. Flat folders are invisible
`scan` on a folder holding only `trajectories.h5` says "No tracking output was recognised ... Files seen: .h5 x1".
All public samples are flat in their source repositories. The reader needs `<session>/trajectories/`. Cheapest
fix: when a lone `trajectories.{h5,npy,pickle,parquet}` or a `trajectories_csv` folder is found outside a
`trajectories/` folder, say so in the scan output ("looks like idtracker.ai output; put it in `<name>/trajectories/`"),
the way `_trajectories_subfolder_hint` already does for the opposite mistake. Decide whether flat exports should be
claimed outright (decision D4 of the earlier reader handoff).

### 6. Real units are silently absent for bare exports
With the default `bodylength` calibration and no `session.json`/cm scale, the cm and cm/s columns exist but are
100 % NaN (h5: IL-1 `path_length_cm`, IL-2 `mean_speed_cm_s`, GL-1, GL-5), while px and body-length columns are
filled. For the synthetic CSV (no body length) the run README explains this in "Notes on the readers"; for the h5
and the pickled files it does not. Also NaN by nature of a bare export: D-13 (fragment certainty), D-12, D-15,
D-6..D-9 (need the session artefacts), D-3 for the MoveR file (no `id_probabilities`). The docs should say which
metrics a bare export can and cannot fill, and the run README should name the cause for every all-NaN column.

### 7. No repeatable evidence yet (what the "we ran these" claim needs)
Today the evidence is this handoff plus reader-level tests. To make the claim checkable:
1. Add `tests/real_samples/test_idtrackerai_cli_run.py`: for each cached fixture, arrange the session folder,
   call the same functions `scan`, `add`, `validate` and `run` call (or `CliRunner`), with the options and consent a
   user would give, and assert exit code, the output file set, row counts (frames x animals), cross-format
   agreement (h5 vs CSV), and the absence of unexpected warnings. Reuse `_arrange` from
   `test_idtrackerai_samples.py` and the fetch logic of `repro_idtrackerai_samples.py`.
2. Keep the FishTank 4.0.9 file out of the default suite (29 MB download, ~100 s); mark it `slow`.
3. Only after items 1-3 are fixed can the test use the CLI as documented; until then it would encode the
   hand-edited project file.

### 8. Smaller points
- The video size must come from the user; the confirm dialog should say why ("idtracker.ai exports do not record
  the video size") and the run README should record that the size was user-supplied (reader options appear in
  `manifest.json` under `reader_options`, but nothing flags them as unverified).
- `IDT_VERSION_UNKNOWN` fires for every pre-5.x pickle; consider demoting it to info for the 4.x dict layout now that
  two real 4.x files are known to read.
- MoveR slots with more than 90 % NaN produce all-NaN metric rows; consider a note in the README rather than only
  log warnings.

## 5. What the dataset CSV can honestly claim after this run

| CSV row | Dataset | Run through the software (CLI, hand-edited project) | Blocked from plain CLI by |
|---|---|---|---|
| 31 | movement-data h5 | yes, scan/add/validate/run, outputs checked against an independent read | items 1, 3 |
| 32 | movement-data CSV bundle | yes, agrees with the h5 run | items 1, 3 |
| 33 | synthetic no-fps CSV | yes, both animals and probabilities kept | items 1, 3 |
| 34 | MoveR pickled dict | yes, with consent | items 1, 2, 3, 4 |
| 39 | FishTank (1 of 16 parsed files) | yes, the 4.0.9 file, with consent; 15 other files not run | items 1, 2, 3, 4 |
| 35-38, 40-42 | benchmark repo, 2019 data, Heras videos, docs videos, 6 non-numpy FishTank pickles, LogAI, zebrafish-aggression | not run (not downloaded, not opened, or not tracker output) | n/a |

Refresh the `notes` cells of rows 31-34 and 39: they still describe `main @7052e9b` before PR #146 (for example
"read() fails with a bare ValueError" for row 33). Do not yet write "run successfully through the CLI": that is
true only after items 1-3. Replacing `docs/tracker-formats/tracker_test_datasets.csv` (29 rows) with the 41-row
version `tracker_test_datasets(1).csv` (sha256 `136bf05e...`) requires updating the pin in
`tests/test_docs_tracker_formats.py` and the hash row in `docs/tracker-formats/README.md`.

## 6. Limits of this run

- Placeholder video sizes; no real video was available for any dataset.
- v4/v5 session folders (`video_object.npy`) were not run: no public sample has one.
- 15 other FishTank files were parsed by the earlier survey but not run here; 6 reference `_codecs.encode` and need
  a restricted unpickler.
- The GUI path (confirm dialog, consent prompt) was not exercised; conclusions about it are inferred from the shared
  `Detection` object.
- Peak memory was not measured. One run per variant; no repeat runs, so timings are indicative.
- Licences: the movement-data upstream licence is unconfirmed, MoveR_SampleData is GPL-3.0, FishTank is CC BY 4.0.
  The fixtures are downloaded and hash-checked, not redistributed.
- Two tests in `tests/test_integration` (3-D serial vs parallel) fail on the base commit too and are unrelated.
