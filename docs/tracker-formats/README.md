# Tracker output formats: research notes and rollout inputs

Inputs for the multi-tracker import work (scan, detect, confirm, read). The four
research files below are third-party notes, kept **byte-identical** to the copies
supplied. Do not edit them in place: re-copy the file, then update its pin in
`tests/test_docs_tracker_formats.py` and its row here (a test keeps the two in step).

| File | What it is | sha256 |
|---|---|---|
| `animal_tracking_output_formats.md` | The per-tool description of output layouts. This is the 2026-10-07 12:57 revision, which corrects the earlier copy and is canonical | `4b683240…` |
| `animal_tracking_formats_table.csv` | One-row-per-tool summary table. It predates the corrections above (see below) | `9c9f3df7…` |
| `importer_priority.csv` | Importer priority by recent citation share. Seven importers cover 80.5 % of animal-tracker citations, and the rollout follows this order | `b4307f31…` |
| `tracker_test_datasets.csv` | Public datasets for each importer, with licence and what was verified. The provenance record for every fixture | `195247aa…` |

Not copied here: the reader fixture-test suite (`t2d_reader_fixture_tests.zip`)
lives in `tests/real_samples/`, because it is test code, not documentation.

## Design and plan

- [`2026-10-07-tracker-import-design.md`](2026-10-07-tracker-import-design.md): the
  approved design (scan, detect, confirm, persist; tiers; reader specs; gates).
- [`2026-10-07-tier-0-implementation-plan.md`](2026-10-07-tier-0-implementation-plan.md):
  the Tier 0 task-by-task plan. Each later tier gets its own plan when it starts.

## Where the sources disagree

The table CSV was written before the formats document was corrected against real
files. Where they disagree, **the document and the pinned samples win**. Cells in
the table that are now known to be stale or incomplete:

- **ToxTrac.** The table lists seven columns including `video_seq` and unnumbered
  `Tracking.txt` / `Tracking_RealSpace.txt`. Real files are per arena: pixel
  `Tracking_N.txt` (headerless, 6 columns, arenas numbered from 0) and
  `Tracking_RealSpace_N.txt` (6 columns with a header, arenas numbered from 1).
  `Label` is a position status code, not a track number.
- **SLEAP.** The table says "synthetic `track_0..n` when no tracks". In real
  GUI-exported files a project without tracks has an empty float64 `track_names`,
  and GUI exports carry no `dims` or `preset` attributes at all.
- **TRex.** File names are `…_fish<N>.npz` in older exports and `…_id<N>.npz` in
  newer ones, and the key sets differ between versions. Untracked frames are
  `+inf` in every float array, and X/Y labelled cm can be pixel-scale.
- **Ctrax.** Ctrax's raw `.mat` is a flat per-detection layout, not the `trx`
  struct array, its y axis is measured from the bottom of the frame, and its
  identities are track fragments.
- **AnimalTA.** Arena and individual numbers start at 0 in the real files.

## Rollout status

Order follows `importer_priority.csv`. "Suite cases" are the contract cases of the
reader fixture-test suite that must go from XFAIL to PASS when the reader lands.

| Prio | Importer | Tier | Status | Suite cases |
|---|---|---|---|---|
| 1 | DeepLabCut CSV (Lightning Pose, EKS, maDLC) | 1 | **built** (CSV); `.h5` planned | `dlc_two_mice_csv`, `lightning_pose_eks_csv` pass; `dlc_single_animal_h5` waits for the G-H5 decision |
| 2 | SLEAP analysis HDF5 | 1 | **built** | `sleap_named_tracks`, `sleap_no_tracks` pass |
| 3 | Ctrax raw `.mat` (**built**), `trx.mat`, FlyTracker | 2 | raw `.mat` built; `trx.mat` waits for a real sample; FlyTracker recognise-only | `ctrax_raw_mat` passes |
| 4 | ToxTrac `Tracking_RealSpace.txt` | 3 | planned | `toxtrac_realspace` |
| 5 | Anipose pose-3d CSV (and DLC-3D) | 3 | planned | quirk tests only |
| 6 | TRex `.npz` | 4 | planned | `trex_new_export`, `trex_old_export` |
| 7 | AnimalTA CSV | 4 | planned | `animalta_fixed_csv` |

Tier 0 (the scan, detect, confirm and persist foundation, including
idtracker.ai folder-of-folders) comes first. **Built so far:** the reader contract
(options, verification, `discover`), the read-only scan, the persisted reader with
provenance and pre-flight notes, `ConfirmDraft` and the `list-readers` / `scan` / `add`
commands, the store and task runner, the confirm dialog, the GUI driver verbs, and the
list of formats that are recognised but not yet readable. Tier 0 is complete. The decisions are
D-026 to D-031 in `docs/dev/DECISIONS.md`. Everything else, such as FastTrack,
OCTRON, WCON and the fragment-ID formats, is backlog ordered by ease.

## Reader cards

### DeepLabCut CSV (`deeplabcut`)

Also reads Lightning Pose and EKS tables, which share the layout. Verified against the real
`DLC_two-mice.predictions.csv` and `EKS_IBL-paw_multicam_left.predictions.csv` samples.

| | |
|---|---|
| Session | One per `.csv` file (one per video). A folder of them is scanned and added together. |
| Detect | First cell `scorer`; second row `individuals` (4 header rows, multi-animal) or `bodyparts` (3 rows, single animal); a `coords` row containing `x`, `y` and `likelihood`. Annotation files (`CollectedData_*`) and 3-D tables have no likelihood and are not claimed. |
| You supply | Frame rate, frame width and height (the file records none of them), never defaulted. Optionally: which keypoint stands for the animal, the likelihood cutoff (default 0.6; the dialog proposes 0 for a Lightning Pose / EKS table), which animals to read, and whether to keep the full skeleton. |
| Position | One real keypoint, never a centroid: the one you name, else the keypoint present most often after the cutoff (ties go to the higher mean likelihood). The whole skeleton is stored beside it and no metric reads it. |
| Identity | Named individuals are stable. `ind1`, `ind2`... are positional placeholders and are flagged and treated as unstable. `single` (DeepLabCut's unique body parts) is not an animal and is left out unless asked for. One animal: stable. |
| Missing | Empty cells; positions under the cutoff. A text cell is an error, never a gap. |
| Traps handled | EKS tables carry six more coordinates per keypoint (`x_ens_median`...): only `x`, `y`, `likelihood` are read, by name. EKS writes a likelihood of exactly 0 for every frame, a placeholder: it is ignored and the session says so, otherwise a cutoff would erase the recording. A human-filled gap has likelihood 0.01 and is dropped by the default cutoff. Frames are placed by their number, so a gap in the numbers is a run of missing frames. |
| Not yet | `.h5` (waits for the decoder decision), the `.csv` / `.h5` pair counted as one session, 3-D tables (recognised, not read). |


### SLEAP analysis HDF5 (`sleap_analysis`)

Reads the file SLEAP writes from File > Export Analysis HDF5. Verified against the real
`SLEAP_three-mice_Aeon_mixed-labels.analysis.h5` and `SLEAP_single-mouse_EPM.analysis.h5` samples.

| | |
|---|---|
| Session | One per `.h5` file (a `.analysis.h5` suffix is not required). A folder of them is scanned and added together. |
| Detect | Top-level datasets `tracks` (4-D), `track_names`, `node_names`, `track_occupancy`. `tracks` as a *group* is stitched DeepLabCut tracklets and is not claimed; neither is a DeepLabCut `.h5`. `.slp` project files are recognised and the scan says to export the analysis file instead. |
| You supply | Frame rate, frame width and height (the file records none of them), never defaulted. Optionally: which skeleton node stands for the animal, a point-score cutoff (default off: SLEAP's scores are not a calibrated probability), and whether to keep every node. |
| Layout | `tracks` is `(tracks, 2, nodes, frames)`. The GUI export carries no attributes, so the layout is *checked* (the occupancy, the node names and the track names must agree with it) and a file that does not fit is refused with `SLEAP_LAYOUT_AMBIGUOUS`, never guessed. A `dims` attribute, if present, must be the standard order; any other is `SLEAP_LAYOUT_UNSUPPORTED`. |
| Position | One real node, never a centroid: the one you name, else the node present most often; among equally covered nodes the one nearest the middle of the skeleton (the steadiest stand-in for the animal; a snout or tail tip jitters). The whole skeleton, its edges and the point scores are stored beside it. |
| Identity | Named tracks: stable, with the names as labels. No names and one slot (a project with no tracking): one animal. No names, or SLEAP's synthetic `track_0`, `track_1`, with several slots: positional, so identity-free by construction (`track_wo_identities`), and the scan flags it. |
| Missing | NaN. |
| Traps handled | A project with no tracks writes an empty *float64* `track_names`. A skeleton with no edges writes an empty `(0,)` `edge_inds`. Names are bytes and are decoded. |
| Not yet | Other axis orders (no real sample), the sleap-io writer's CSV layouts, `.slp` projects. |


### Ctrax raw `.mat` (`ctrax_mat`)

The file Ctrax's "Save Tracks as Matlab File" writes. Verified against the real
`2602_ISA3080_Low_5.mat` sample (12,033 frames, 159,765 detections, 193 track ids).

| | |
|---|---|
| Session | One per `.mat` file. A folder of them is scanned and added together. |
| Detect | A classic (v5) MATLAB file whose variables include `ntargets`, `x_pos`, `y_pos`, `identity`, `timestamps` and `startframe`, and **no** `trx`. A `trx.mat` (Ctrax / FlyTracker / JAABA struct) is a different format and is not claimed; v7.3 (HDF5) files are not claimed either, as there is no real sample of one. |
| You supply | Frame width and **height** in pixels (the file records neither; height is needed to flip y). Optionally `top_n`: keep only that many of the longest tracks. The frame rate is **not** asked for: it is read from `timestamps`. |
| Layout | Everything is per *detection*, concatenated frame by frame: frame `t` owns the next `ntargets[t]` rows. The counts, the per-detection arrays and the timestamps must agree, or the file is refused with `CTRAX_INCONSISTENT`. |
| y axis | Ctrax measures y from the **bottom**. Positions are returned as `height - y`, in image coordinates (verified against AnimalTA on the same video: about 1 px with the flip, over 300 px without). |
| Frame rate | `(n_frames - 1) / (last timestamp - first timestamp)`, an average over the whole span. A file whose timestamps wander by more than half a frame says so on the session instead of hiding it. |
| Identity | Track ids are **fragments**, not animals: Ctrax starts a new id each time it loses a track. Every id becomes a slot, the session is identity-free by construction (`track_wo_identities`), and the scan says so. `top_n` keeps the longest tracks (ties to the lower id). A file whose slots would not fit in memory is refused with a request to set `top_n`. |
| Frame offset | `startframe` greater than 0 is recorded as the tracking interval, so true frame numbers are kept. |
| Missing | A frame with no detection for a track is NaN. |
| Not yet | `trx.mat` (needs a real sample), v7.3 files, ellipse axes and angle (`maj_ax`, `min_ax`, `angle` are not used). |
