# Reader fixture tests for Track2Data

Tests for future non-idtracker.ai readers (DeepLabCut, SLEAP, TRex, AnimalTA, Ctrax, ToxTrac, Lightning Pose),
built from real tracker output files. Written against Track2Data at commit `0b9b860` (`SessionReader`
contract, `Session` model, `DataValidationError`) and imported here on the pp3 base.

## Two layers

| layer | marker | needs Track2Data | what it does |
|---|---|---|---|
| format quirks | `quirk` | no | parses the raw files directly and asserts the properties that make each format awkward (42 tests) |
| reader contract | `contract` | yes | arranges the files into a session folder, finds the registered reader, reads it, checks the `Session` against an independent oracle (8 tests x 10 cases) |

While no reader claims a folder, each contract test is reported as **XFAIL** ("no registered reader claims ...").
As soon as a reader that detects the folder is registered, the same test runs for real.

## Run

This directory is part of the Track2Data repository (`tests/real_samples/`). From the
repository root, with the interpreter that has the dev dependencies:

```bash
py -3.14 -m pip install "tables>=3.9"              # once: the DLC .h5 oracle needs PyTables
py -3.14 -m pytest tests/real_samples -m quirk     # parses the raw files; needs no Track2Data
py -3.14 -m pytest tests/real_samples -m contract  # reader contract; XFAIL until a reader exists
```

The suite is **opt-in**: it downloads about 70 MB, so it only runs when `-m` names one of its
markers (`quirk`, `contract`, `real_sample`) or `T2D_REAL_SAMPLES=1` is set. Every test is also
marked `network`, so CI and the default developer run (`-m "not network"`) never touch it.

Fixtures (70 MB, 26 files) are downloaded on first use, verified against a pinned SHA-256 in
`fixtures_manifest.json`, and cached **outside the worktree** (the worktree is OneDrive-synced).
A hash mismatch **fails** the test (upstream drift); a network failure **skips** it.

| variable | effect |
|---|---|
| `T2D_FIXTURE_DIR` | cache location (default `%LOCALAPPDATA%	rack2dataixture_cache`, or `$XDG_CACHE_HOME/track2data/fixture_cache`) |
| `T2D_FIXTURES_OFFLINE=1` | never use the network; skip what is not cached |
| `T2D_REAL_SAMPLES=1` | run the suite without naming one of its markers in `-m` |
| `T2D_REFERENCE_READERS=1` | register the test-only readers in `reference_readers.py`; leave unset when testing your own |

## What the quirk tests pin

| format | quirk (each is an executable test in `test_format_quirks.py`) |
|---|---|
| DeepLabCut | header is 3 or 4 rows (decided from row 2); h5 key `df_with_missing`; no fps or frame size anywhere in the file; NaN for lost keypoints |
| Lightning Pose | 9 coords per keypoint (`x_ens_median`, `x_posterior_var`, ...); select `x`,`y`,`likelihood` by name |
| SLEAP analysis h5 | GUI export has **no** `dims`/`preset` attributes; layout `(tracks, 2, nodes, frames)`; no-track projects have an empty float64 `track_names`; occupancy agrees with the NaN pattern |
| Anipose | 3-D; keypoint names contain `-`; split column names from the right; `fnum` is 0-based |
| TRex | NPZ key set differs between versions (`id`, `frame_rate`, `cm_per_pixel`, `video_size`, `detection_p` absent in the older export); `_fish0` vs `_id0` names need a numeric sort; untracked frames are `+inf` (never NaN); the `missing` flag disagrees with the `+inf` frames in 3 of 13 older files; per-file frame counts differ; older `X` is pixel-scale |
| AnimalTA | `;`-delimited; missing target is the literal `NA`; `Time` is rounded to 0.01 s so fps must come from the total span |
| Ctrax raw `.mat` | flat per-detection layout sliced by `ntargets`; 193 identities = fragments; y measured from the bottom |
| ToxTrac | exact 6-column header; `Label` is a status code (0 predicted / 1 confirmed / 2 occluded / 3 mirror); lost frames are **absent rows**; time starts at 12.26 s; `Time Lenght` misspelled; `Stats` is alternating name/value lines |
| cross-tracker | TRex and AnimalTA share a pixel frame (median ~9 px); Ctrax matches AnimalTA only after `y' = 2160 - y` |

## What the contract tests check (policy-neutral)

For every case: exactly one reader claims the folder; the `Session` is well formed (float64 `(n_frames, n_animals, 2)`,
no `inf`); `video` equals what the file records or what was supplied, never a default; positions agree with the oracle
(inside the animal's own keypoint box, NaN where the source has none, speed series aligned at lag 0); the identity
claim is honest (e.g. Ctrax fragments are not stable identities); reading does not modify the folder (FR-IMP-5);
an empty or truncated file fails with a coded `DataValidationError`, or is not claimed at all.

## Decisions this suite does not make (marked POLICY in `reference_readers.py`)

1. **fps, width, height.** `Session.video` requires them, and most formats record none or only some (DLC, SLEAP, Anipose,
   Ctrax width/height, AnimalTA size record nothing). `provide_video_info()` in `fixtures.py` is the single place that
   supplies them; replace its body with your mechanism.
2. **Keypoints to one point.** `Session.raw_xy` is one point per animal. The tests accept any reduction that stays inside the
   animal's keypoints.
3. **3-D data.** `raw_xy` is 2-D; Anipose output is 3-D, so Anipose is covered by quirk tests only.
4. **ToxTrac units and `Label`.** Positions are millimetres, not pixels, and 43 of 17,811 sample rows are predicted positions.
   Only axis direction is checked.
5. **Fragmented identities (Ctrax raw).** The suite requires `has_stable_identities` to be false but does not say whether
   to stitch.
6. **TRex without `cm_per_pixel`.** Older files are treated as pixels because their values are pixel-scale.

## Not covered

No public fixture was found for FlyTracker or `trx.mat` (JAABA's sample data is on SourceForge and was not downloaded); also
not covered: DeepLabCut stitched `_el.h5`, SLEAP `.slp`, AnimalTA variable/detailed layouts, Anipose at `Session` level.

## Verification done

* 42 quirk tests pass on the pinned files.
* Contract tests with no readers: 80 XFAIL, 0 errors. With the reference readers: 75 passed, 5 skipped (text formats have no truncation test; one case has no identity information).
* 11 deliberate bugs in the reference readers (missing y flip, `inf` left in, lexicographic file order, wrong units, default fps, wrong SLEAP axes, one-frame shift, compacted ToxTrac rows, false identity claim, cache file written into the input folder, silently skipped unreadable file) were each caught by at least one test.
* The reference readers are scaffolding, not a proposal for the real readers.

## Fixture licences

Fixtures are not redistributed here. Terms differ by source (CC BY 4.0, CC0, GPL-3.0, a credit licence, or none stated); see
`fixtures_manifest.json` and check them before copying any file into another repository.
