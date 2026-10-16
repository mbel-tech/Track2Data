# Known issues

**Last reviewed:** 2026-10-11, against v0.1.0 and `main` (1c9e828).

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

**Zone transitions (Z-4, Z-7) can still count a transition across an unobserved gap.** In a
session tracked in separate intervals, the last zone of one interval and the first zone of
the next are counted as one transition, although the animal was not observed in between.
Z-5, Z-6 and Z-9 do cut at the gap. See `D-032` in
[`docs/dev/DECISIONS.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/dev/DECISIONS.md).

**Interpolating across gaps between tracking intervals is an estimate, and is off by
default.** The Preprocessing screen can fill a gap of up to 30 s (adjustable) with a straight
line between the last and next observed positions. Those frames are marked
`was_interpolated` and `in_tracking_interval = False`, and distance, speed and zone time
include them. Report how much of a result rests on them (the *Interpolated* column of the
quality grid).

## Input formats

**idtracker.ai v4 output is not supported.** 6.x is supported and the legacy v5 layout
works; a v4-looking folder fails with `V4_NOT_SUPPORTED` rather than being misread. The
reader is blocked on real v4 sample folders — if you have some, see
[`docs/IDTRACKERAI_V4_SAMPLES.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/IDTRACKERAI_V4_SAMPLES.md).

**An idtracker.ai v5 project on default (body-length) calibration carries no body length.**
Those sessions are exported in pixels only. The run now says so instead of skipping the
calibration silently.

**Only some trackers are readable.** idtracker.ai, DeepLabCut, SLEAP (analysis HDF5), Ctrax
(raw `.mat`), `trx.mat`, Anipose `pose-3d` CSV and DeepLabCut 3-D tables are. A scan *names* formats it recognises but cannot read — SLEAP
`.slp`, a `-v7.3` `trx.mat`, FlyTracker `-track.mat`, DANNCE, Multi-Worm Tracker `.blobs`,
AnimalTA and FicTrac — and says what to export instead. See
[[Formats and Interoperability]] and [[Compatibility]].

**The `trx.mat` reader has not been checked against a real file.** It follows the documented
layout (a `trx` struct, 1-based frames, `pxpermm`), and the confirm step labels it so. Compare a
few trajectories with the tracker's own output before relying on it, and check the position
orientation in particular.

**Session calibration needs a scale in each session.** idtracker.ai sessions that were never
calibrated in the Validator, and sessions from trackers that record none (give **Scale (pixels
per cm)** when adding them), have no scale. The run is blocked with a message naming them
rather than guessing one. If the saved idtracker.ai `length_unit` differs from the average of its
measurements, the saved value is used and the run log warns.

**The Zones canvas has no picture for trackers other than idtracker.ai.** idtracker.ai
sessions show their background image to draw over. A session from any other tracker gets a
blank canvas the size of the video frame, so zones are drawn by coordinates or loaded from a
CSV. Zones drawn on that canvas in earlier versions were on a blank 640×480 scene, not in
video pixels, and should be redrawn.

**A required option is never defaulted.** If the files do not record something a reader
needs — frame rate is the common case — you get `READER_OPTION_MISSING` and must supply it.
A guessed frame rate would corrupt every speed and path-length value instead.

## 3-D data

**3-D assumes one right-angle camera pair and no optics correction.** A fused project
combines a top and a side view as if both were orthographic: the side view's horizontal
scale comes from the tank height (square pixels, no perspective), there is no refraction or
parallax correction, and its vertical axis is image y, so a rotated side camera cannot be
described. A wrong tank height scales every vertical distance. A side camera mounted upside
down is supported (tick **The side view is upside down** in the Fusion dialog).

**A fused depth is kept, and flagged, when it rests on a reconstructed side position.** Where
the side view was gap-filled or jump-replaced, `depth_interpolated` or `depth_jump_replaced`
is True in the per-frame table; the depth itself is not blanked. Report how much of a 3-D
result rests on flagged frames. Native 3-D files are cleaned like x and y: `z` is gap-filled
and smoothed with the same settings, so the smoothing window changes IL-16 and IL-17.

**GL-1 and GL-16 can use different frames.** Both skip a frame when an animal is missing, but
GL-16 also needs a depth for every animal, so missing depth leaves it on fewer, cleaner
frames and biases `mean_nnd_3d_cm` upward against `mean_nnd_cm`. Read `frac_frames_used_3d`
before comparing the two.

**The native water column is one surface and floor for the whole project.** Native files in
a project must share a vertical axis (a mix is refused at import) and an origin (this cannot
be checked from the files, so check it yourself). Samples outside the column are left out of
IL-15, IL-16, IL-17, IL-18 and GL-16, never clipped, and the run `README.md` counts them.

**`flip` reverses the vertical axis only, which also mirrors the view from above.** For a
native file, headings and the sign of `left_right_turn_bias` change with it. The horizontal
plane itself is right-handed for every `vertical_axis`.

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
