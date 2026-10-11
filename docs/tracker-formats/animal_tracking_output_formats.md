# Open-source animal-tracking software and the structure of their tracking output

Compiled 2026-10-07. idtracker.ai is excluded by request.

Every format description below was taken from the project's own documentation or from the
source code that writes the file (links given per entry). Where a project does not document
its output layout, that is stated explicitly rather than guessed. Field and dataset names are
reproduced verbatim from the source.

A note on what "format" means here, since the target is a statistics pipeline: for each tool I
give the **container** (HDF5 / CSV / MAT / JSON / SQLite / NPZ), the **axis layout** (what a row
or an array dimension means), the **identity model** (whether IDs are continuous per animal or
fragments that need stitching), the **coordinate convention** (units, origin, y-direction, frame
base), and the **missing-data encoding** — the last two being the usual source of silent errors
when importing.

---

## 1. Pose / keypoint trackers

### 1.1 DeepLabCut
Python, LGPL-3.0, <https://github.com/DeepLabCut/DeepLabCut>

**Output files** — `analyze_videos()` writes a pandas DataFrame in **HDF5** next to the video
(or in `destfolder`), optionally also as CSV with `save_as_csv=True`. `filterpredictions()`
writes a parallel file with the `_filtered` suffix. Multi-animal projects additionally produce
`*_full.pickle` (raw per-frame detections), `*_assemblies.pickle` (assembled skeletons), a
tracklet pickle from `convert_detections2tracklets`, and the final stitched `.h5`.

**Structure** — the HDF5 holds a pandas DataFrame under the key **`df_with_missing`**
(multi-animal stitched tracklets live under the key **`tracks`**, typically in `*_el.h5`). The
columns are a MultiIndex with levels **`scorer` → (`individuals`) → `bodyparts` → `coords`**,
where `coords` takes values `x`, `y`, `likelihood` (or `x`, `y`, `z` for 3D triangulation output,
which carries no likelihood). The `individuals` level is present only in multi-animal projects.
The row index is the frame number. In pandas `table` format the values are in the compound
dataset `<key>/table` with column labels pickled in the block's `_kind` attribute; in `fixed`
format each block stores values at `<key>/block<k>_values` with labels at
`block<k>_items_level<i>` / `block<k>_items_label<i>` and the frame index at `<key>/axis1`.
The CSV mirror is the same wide table with the multi-level header written as the first 3–4 rows
and the frame index in the first column.

**Coordinates** — `(x, y)` in pixels, image convention (origin top-left). Frame index is 0-based.
No fps is recorded in the file.

**Missing data** — NaN in HDF5, empty field in CSV. Body parts the annotator could not see are
simply left unlabeled. During tracklet refinement, human-filled gaps are written with a
deliberately low likelihood of `0.01` so they are distinguishable from network estimates.

**Identity** — multi-animal identity lives in the `individuals` column level; names come from
`config.yaml`. Body parts not assigned to any animal (`uniquebodyparts`) are stored under the
pseudo-individual **`single`**. If the number of recovered tracks differs from the configured
individuals, columns fall back to dummy names `ind1 … indn`.

**Confidence** — per-keypoint `likelihood`; `pcutoff` (default 0.6 in the PyTorch engine) is the
conventional threshold.

Sources: [standard user guide](https://github.com/DeepLabCut/DeepLabCut/blob/main/docs/standardDeepLabCut_UserGuide.md),
[multi-animal guide](https://github.com/DeepLabCut/DeepLabCut/blob/main/docs/maDLC_UserGuide.md),
[aniread `read_deeplabcut.R`](https://github.com/animovement/aniread/blob/main/R/read_deeplabcut.R),
[movement `load_poses.py`](https://github.com/neuroinformatics-unit/movement/blob/main/movement/io/load_poses.py).

### 1.2 SLEAP
Python, BSD-3-Clause-Clear, <https://github.com/talmolab/sleap>

SLEAP has two quite different outputs: the native project file and a flat analysis export. For a
statistics pipeline you almost always want the second.

**Native `.slp`** — an HDF5 file. Core layout: `/metadata` (attrs `format_id`, plus JSON holding
skeletons, nodes, provenance), `/videos_json`, `/tracks_json`, `/suggestions_json`,
`/provenance_json`, `/frames` (`frame_id`, `video`, `frame_idx`, `instance_id_start`,
`instance_id_end`), `/instances` (`instance_id`, `instance_type`, `frame_id`, `skeleton`, `track`,
`from_predicted`, `score`, `point_id_start`, `point_id_end`, `tracking_score`), `/points`
(`x`, `y`, `visible`, `complete`) and `/pred_points` (same plus `score`). Frames and instances
index into the flat point tables by `*_id_start`/`*_id_end` ranges. Newer `sleap-io` writers
extend this with `/bboxes`, `/centroids`, `/masks` (+ `/mask_rle`), `/rois` (+ `/roi_wkb`),
`/identity`, `/categories`, `/embeddings` and `/events` groups. `/tracks_json` stores each track
as `[spawned_frame_index, track_name]`.

**Analysis HDF5** (`sleap-convert --format analysis`, or *Export Analysis HDF5* in the GUI) —
dense arrays, gzip-compressed:

| dataset | shape (`matlab` preset, default) | shape (`standard` preset) |
|---|---|---|
| `tracks` | `(n_tracks, 2, n_nodes, n_frames)` f8 | `(n_frames, n_tracks, n_nodes, 2)` |
| `point_scores` | `(n_tracks, n_nodes, n_frames)` | `(n_frames, n_tracks, n_nodes)` |
| `instance_scores` | `(n_tracks, n_frames)` | `(n_frames, n_tracks)` |
| `tracking_scores` | as `instance_scores` | as `instance_scores` |
| `track_occupancy` | `(n_frames, n_tracks)` bool — same in both presets | |

plus `track_names`, `node_names`, `edge_names`, `edge_inds`, `video_path`, `video_ind`,
`labels_path`, `provenance`. **Do not hardcode the axis order.** Files written by newer `sleap-io` versions carry a `dims`
attribute on each dataset, e.g. `["track","xy","node","frame"]`, and a file-level `preset` attribute
(`matlab`/`standard`/`custom`). **Files exported from the SLEAP GUI/CLI that I inspected carry neither**: the file
and every dataset had an empty attribute set, and the layout was always the `matlab` one,
`tracks` = `(n_tracks, 2, n_nodes, n_frames)`. An importer therefore has to treat the attributes as optional
and fall back to that layout (checking that `track_occupancy` is `(n_frames, n_tracks)` and
`tracks.shape[-1] == n_frames`). Two further details from real files: when the project has no tracks,
`track_names` is an **empty** dataset of shape `(0,)` and dtype float64 (not synthetic `track_0…` names), while
`tracks` still has one slot; and with a single-node skeleton `edge_names`/`edge_inds` are empty `(0,)` float64
datasets rather than `(0, 2)`.

**CSV exports** — five distinct layouts, selected at export: `sleap` (one row per instance:
`track`, `frame_idx`, `instance.score`, then `{node}.x`, `{node}.y`, `{node}.score` per node),
`dlc` (DeepLabCut-compatible multi-header), `points` (one row per point: `video_path`,
`frame_idx`, `track`, `instance_idx`, `instance_score`, `node`, `x`, `y`, `score`), `instances`,
and `frames` (one row per frame, columns `inst{N}.{node}.x` …). An optional `data.json` sidecar
preserves skeletons, tracks and provenance for round-tripping.

**Coordinates** — pixels, origin at the **centre** of pixel `(0,0)` for format ≥ 1.1 (readers
apply a −0.5 offset to older files), x right, y down. `frame_idx` is 0-based. Since v0.7.0 the
analysis file spans the whole video (`n_frames == len(video)`), not just up to the last labeled
frame.

**Missing data** — NaN throughout `tracks`, `point_scores`, `instance_scores`, `tracking_scores`;
`track_occupancy` is `False`. In `.slp`, untracked instances have `track = -1`, and `-1` is the
general missing-index sentinel; deliberately empty frames are recorded in `/negative_frames`.

**Identity** — `track_names` aligned to the track axis. Important caveat for analysis: if the
source project has no track assignments, `n_tracks` is sized to the largest instance count in any
frame and slots are filled with synthetic names `track_0 … track_{n-1}` whose **per-frame
assignment is arbitrary** — these are not identities.

Sources: [SLP format reference](https://github.com/talmolab/sleap-io/blob/main/docs/formats/slp.md),
[analysis HDF5 reference](https://github.com/talmolab/sleap-io/blob/main/docs/formats/analysis_h5.md),
[CSV reference](https://github.com/talmolab/sleap-io/blob/main/docs/formats/csv.md),
[format index](https://github.com/talmolab/sleap-io/blob/main/docs/formats/index.md).

### 1.3 Lightning Pose
Python, MIT, <https://github.com/paninski-lab/lightning-pose>

Writes predictions in **DeepLabCut's CSV layout** (single individual), so the §1.1 description
applies. Its Ensemble Kalman Smoother output (scorer `ensemble-kalman_tracker`) carries nine
coords per keypoint: `x`, `y`, `likelihood` plus `x_ens_median`, `y_ens_median`, `x_ens_var`,
`y_ens_var`, `x_posterior_var`, `y_posterior_var`. Multi-camera 3D results
(`multicam_3d_results.csv`) are `x`, `y`, `z` with no confidence column.
Source: [aniread `read_anipose.R` / `read_lightningpose.R`](https://github.com/animovement/aniread/blob/main/R/read_lightningpose.R).

### 1.4 Anipose (3D triangulation on top of 2D pose)
Python, BSD-2-Clause, <https://github.com/lambdaloop/anipose>

**`pose-3d/<name>.csv`** — one row per frame. For every body part `bp`: `bp_x`, `bp_y`, `bp_z`
(3D coordinates), `bp_error` (mean reprojection error), `bp_ncams` (number of cameras that
contributed a valid 2D point), `bp_score` (minimum of the 2D detection scores across cameras).
Then the flattened coordinate-frame rotation matrix `M_00 … M_22` and the new origin
`center_0`, `center_1`, `center_2`, and finally `fnum` = `np.arange(n_frames)`, i.e. 0-based.
**`angles/<name>.csv`** — one column per configured joint angle (`<name>`, or `<name>_flex`,
`<name>_rot`, `<name>_abduct` for chains) plus `fnum`.

**Units** are set by the calibration board (`board_square_side_length`), typically mm — not
pixels. 2D points below `score_threshold` are set to NaN before triangulation; where too few
cameras see a point, `bp_score`/`bp_error`/`bp_ncams` become NaN. There is no individual/track
column: one subject per file.
Source: [`anipose/triangulate.py`](https://github.com/lambdaloop/anipose/blob/master/anipose/triangulate.py), [`compute_angles.py`](https://github.com/lambdaloop/anipose/blob/master/anipose/compute_angles.py).

### 1.5 DANNCE (3D markerless, multi-camera)
Python, MIT, <https://github.com/spoonsso/dannce>

`dannce-predict` writes **`save_data_AVG.mat`** into the prediction folder. The repository
documents the *input* `*dannce.mat` in detail — MATLAB cell arrays `params` (per-camera
calibration structs with fields `R`, `t`, `K`, `RDistort`, `TDistort`), `sync` (frame
synchronisation vector) and `labelData` (frame identities + 3D labels) — but **does not document
the internal arrays of the prediction output** in the README. Treat the `.mat` as something to
inspect with `scipy.io.loadmat`/`h5py` rather than assume.
Source: [README](https://github.com/spoonsso/dannce/blob/master/README.md).

### 1.6 DeepPoseKit
Python, Apache-2.0, <https://github.com/jgraving/DeepPoseKit> (last commit 2022)

The annotation/dataset HDF5 is fully specified: `images` `(n_images, h, w, channels)` uint8;
`annotations` `(n_images, n_keypoints, 2)` float64 holding x/y, initialised to **−1**;
`annotated` `(n_images, n_keypoints)` bool; `skeleton` `(n_keypoints, 2)` int32 holding
`[tree, swap_index]`; `skeleton_names` `(n_keypoints,)` `S10`. The skeleton source table has
columns `name`, `parent`, `x`, `y`, `tree`, `swap`, `swap_index`. `model.predict()` returns a
predictions array in memory; the README does not define an on-disk prediction format.
DeepPoseKit does **not** carry track IDs — multiple individuals are handled by giving them
separate keypoint names (`head1`, `tail1`, `head2` …).
Source: [`deepposekit/io/utils.py`](https://github.com/jgraving/DeepPoseKit/blob/master/deepposekit/io/utils.py).

### 1.7 AlphaTracker
Python, no license file, <https://github.com/ZexinChen/AlphaTracker> (last commit 2023)

Pipeline: `demo.py` writes **`alphapose-results.json`**, which is passed to the PoseFlow tracker
(`tracker-general-fixNum-newSelect-noOrb.py`) producing
**`alphapose-results-forvis-tracked.json`**, plus a `pose_track_vis/` image directory and an MP4.
The repository code shows only the command-line wiring; **the JSON schema is not documented**
there, so it has to be read from an example file. Tracking is governed by `max_pid_id_setting`
(set to 1 to skip tracking for a single animal), `match` and `weights`.
Source: [`Tracking/AlphaTracker/track.py`](https://github.com/ZexinChen/AlphaTracker/blob/main/Tracking/AlphaTracker/track.py).

---

## 2. Centroid / blob multi-animal trackers

### 2.1 TRex
C++, <https://github.com/mooch443/trex> — the closest functional substitute for idtracker.ai,
and the best-documented output format in this list.

**Output files** — `data/[VIDEONAME]_fish[NUMBER].npz`, one NPZ **per individual** (CSV export
also available); `[FILENAME]_posture_*.npz` when `output_posture_data=true`;
`<VIDEO>_tracklet_images.npz`; `..._visual_field_fish0.npz`; heatmap NPZs; and the `.pv`
preprocessed-video container.

**Structure** — the positional NPZ is a zip of `.npy` arrays, one array per selected output
field, all the same length for that individual. Available fields include `X`, `Y`, `SPEED`,
`VX`, `VY`, `AX`, `AY`, `ANGLE`, `time`, `timestamp`, `frame`, `missing`, `num_pixels`, `blobid`,
`midline_length`, `outline_size`, `tracklet_id`, `category`, `average_category`,
`BORDER_DISTANCE`, `NEIGHBOR_DISTANCE`, `MIDLINE_OFFSET`. Field names can carry a `#source`
suffix (`#head`, `#centroid`, `#wcentroid`, `#pcentroid`) selecting which body point the metric
refers to. The posture NPZ holds `frames`, `offset`, `midline_lengths`, `midline_centimeters`,
`midline_offsets`, `midline_angle`, `posture_area`, `midline_points`, `midline_points_raw`,
`outline_lengths`, `outline_points`. Tracklet-image NPZs hold `images` `(N,W,H)` and `meta`
`(N,3)` = `[ID, segment start, segment end]`. Visual-field arrays are `(N, 2 eyes, 2 depth
layers, 512)`.

**Coordinates** — `X`/`Y` in **centimetres** (via `cm_per_pixel`; if unset TRex assumes a 30 cm
arena width), y origin top-left. `ANGLE` in radians relative to the image x-axis, 0 = pointing
right. `time` is seconds from video start, `timestamp` is a UNIX timestamp. `frame` is a
monotonically increasing integer consistent across individuals, but **per-individual files need
not start at frame 0** and need not cover the full range — an animal that appears late simply has
no rows before that.

**Missing data** — the `missing` array is `0` when the individual had data in that frame and `1`
otherwise (with `output_interpolate_positions`, X/Y may be interpolated where `missing == 1`).
Metrics that could not be computed (e.g. posture when no valid posture was found) are set to
**infinity, not NaN** — a reader that only checks for NaN will silently ingest `inf`.

**Identity** — one file per individual, so identity is in the filename and (in the NPZ) the `id`
array. `tracklet_id` groups consecutively tracked segments; `blobid` is the per-frame object
identifier used for manual assignment. The CSV export does **not** record identity or detection
probability.

**Observed in real files (two TRex versions).** The positional NPZ differs between TRex releases, so an
importer cannot assume one key set. A 2025 export (5 locusts, 2,845 frames, 30 fps) contains per-frame arrays
including `frame`, `time`, `timestamp`, `missing`, `X`, `Y`, `X#wcentroid`, `Y#wcentroid`, `SPEED`, `SPEED#wcentroid`,
`ACCELERATION#…`, `ANGLE`, `ANGULAR_V#centroid`, `BORDER_DISTANCE#pcentroid`, pose keypoints `poseX0…poseX6` and
`poseY0…poseY6` (pixels), `detection_p`, plus metadata arrays `id`, `frame_rate`, `cm_per_pixel`, `video_size` and
segmentation tables `tracklets` `(n,2)` and `tracklet_vxys`. An older export (13 individual files of 12,013 to 12,024 frames each, for a video of 12,033 frames) lacks
`id`, `frame_rate`, `cm_per_pixel`, `video_size`, `detection_p` and the pose keypoints, and names its tables
`frame_segments`, `segment_vxys` and `segment_length`. File names also differ: `…_fish0.npz` in the older export
and `…_id0.npz` in the newer one, so the `_fish[NUMBER]` pattern above is not stable. When `frame_rate` and
`cm_per_pixel` are absent they must come from TRex's settings file or from the user.
Untracked frames were confirmed to be encoded as `+inf` in **every** float array at once — coordinates, speeds,
pose keypoints and `detection_p` — and no NaN or `-inf` appeared in any of the 18 files checked (22 of 2,845
frames in one locust file; 939 of 12,013 in the first older file). In the five newer files the `+inf` frames
coincide exactly with `missing == 1`. In the older export they do so in 10 of 13 files; in the other three
one frame is `+inf` while `missing` is 0 (frame 0 in two files, frame 27 in the third). **Derive missingness from `isfinite`, not from the
`missing` flag.** The files inspected start at frame 0 and are contiguous; the older sample's first file stops at
frame 12,012 although the video has 12,033 frames, so file length should not be taken as video length. One sample's `X` values are of pixel magnitude (about 2,280) while labelled as cm, consistent
with `cm_per_pixel` being left at its default.

Sources: [`docs/formats.rst`](https://github.com/mooch443/trex/blob/main/docs/formats.rst),
[`docs/UsageTracker.md`](https://github.com/mooch443/trex/blob/main/docs/UsageTracker.md),
[aniread `read_trex.R`](https://github.com/animovement/aniread/blob/main/R/read_trex.R).

### 2.2 ToxTrac
C++/Windows, free and open-source, <https://sourceforge.net/projects/toxtrac/>
(Rodriguez et al. 2018, *Methods Ecol. Evol.* <https://doi.org/10.1111/2041-210X.12874>)

Writes a project folder with one subfolder per video sequence. Per arena it writes tab-delimited text
files: `Tracking_N.txt` (pixel coordinates, frame numbers, arenas numbered from 0),
**`Tracking_RealSpace_N.txt`** (calibrated, arenas numbered from 1 — the one to import),
`Instant_Speed_N.txt`, `Instant_Accel_N.txt`, `Dist_Edges_N.txt`, `Dist_CenterPos_N.txt`,
`Dist_MeanPos_N.txt`, `Exploration_N.txt`, `Transitions_N.txt`, `FrozenEvents_N.txt` and `Stats_N.txt`, plus JPEG
trajectory and heat-map images and a project-level Excel file.

`Tracking_RealSpace_N.txt` has **six** tab-separated columns, with a header row, in long format
(one row per track per frame):

| column header | meaning |
|---|---|
| `Time (sec)` | seconds, not frames |
| `Arena` | arena number, from 1 |
| `Track` | track number |
| `Pos. X (mm)` | x position (units depend on the calibration unit; mm typically) |
| `Pos. Y (mm)` | y position |
| `Label` | position status code, defined in the manual: 0 = predicted position, 1 = confirmed, 2 = occluded, 3 = mirror (in the real sample 17,768 rows are 1 and 43 are 0) |

An earlier version of this report listed seven columns including `video_seq` with different header names;
that was not checked against a real file and was wrong. The layout above was read from a real ToxTrac
output (6 columns, 17,811 data rows, 1920 x 1080 video at 29.857 fps). The sample has 17,811 rows for 18,034
analysed frames: frames with no position are **absent rows** (26 gaps of up to 66 frames), not NaN rows, so a full frame grid has to be rebuilt, and rows with `Label` 0 are predicted positions rather than observations and agrees with Table 8 of the ToxTrac manual.
Per-arena files use coordinates relative to a reference point (so arenas have different spatial coordinates);
the project-level `Tracking_RealSpace.txt` projects all arenas onto a common virtual arena — that population-level
file was not inspected. Other files follow the same pattern, e.g. `FrozenEvents_N.txt` has the header
`Time (sec)`, `Arena`, `Track`, `Avg. Pos. X (mm)`, `Avg. Pos. Y (mm)`, `Time Lenght (sec)` — note the
misspelling "Lenght" in the real header, which a column-name match must reproduce. `Stats_N.txt` is a
two-line-per-parameter key/value file (parameter name on one line, value on the next), not a table.

Sources: [ToxTrac manual/paper, arXiv 1706.02577](https://arxiv.org/pdf/1706.02577) (output-file tables 6–9 and 24–26);
real sample output from the
[ToxTrac-Data-Analyser repository](https://github.com/AmanRathoreP/ToxTrac-Data-Analyser/tree/master/samples).

### 2.3 AnimalTA
Python/GUI, MIT, <https://github.com/VioletteChiara/AnimalTA>; paper: Chiara V. & Kim S.-Y., *AnimalTA: A highly flexible and easy-to-use program
for tracking and analysing animal movement in different environments*, **Methods in Ecology and
Evolution** 14(7):1699–1707 (2023), <https://doi.org/10.1111/2041-210X.14115>
(bibliographic details retrieved from Crossref, 2026-10-07)

All files are **semicolon-delimited CSV**. Three distinct layouts — this is the main import trap:

1. **fixed** (tracking a fixed number of targets): one row per frame, a column pair per target
   named `X_Arena<a>_Ind<i>` / `Y_Arena<a>_Ind<i>`. With *Separate head from tail* the columns
   become `..._Head`/`..._Tail` before correction and `..._part0`/`..._part1` after.
   Corrected files land in `corrected_coordinates/<video>_Corrected.csv`.
2. **variable** (variable number of targets): long format, columns `Frame;Time;Arena;Ind;X;Y`.
3. **detailed** (written by *Run analyses*): one file per target at
   `Results/Detailed_data/<video>/Arena_<a><target>.csv`, one row per frame, with the columns
   ticked under *Detailed data columns* — by default `Time`, `X`, `Y` (or `X_Smoothed`,
   `Y_Smoothed`), plus derived measures such as `Distance`, `Speed`, `Moving`, and
   `Dist_to_*`; `Frame` only if ticked.

**Coordinates** — image convention, origin top-left. Coordinate files are in **pixels**; detailed
files are in whatever scale unit was set in AnimalTA (**the unit is not recorded in the file**),
falling back to pixels. `Time` is seconds from video start, rounded to 0.01 s in coordinate files
and 0.001 s in detailed files, first frame at t = 0.

**Missing data** — `nan` where the target was lost in detailed files; empty string or `NA` in
coordinate files. A detailed file has a row for every frame from first to last tracked.

**Identity** — individuals are numbered from 0 within each arena; `arena` + `individual` together
identify a target, and `individual` holds either `Ind<i>` or a user-supplied name. No confidence
scores are produced.

Source: [aniread `read_animalta.R`](https://github.com/animovement/aniread/blob/main/R/read_animalta.R)
(checked against AnimalTA's own source, see [PR #162](https://github.com/animovement/aniread/pull/162)).

### 2.4 FastTrack
C++/Qt, GPL-3.0, <https://github.com/FastTrackOrg/FastTrack>

Writes **`tracking.txt`**, tab-delimited, one row per individual per frame, with head/body/tail
triplets: `xHead`, `yHead`, `tHead`, `xBody`, `yBody`, `tBody`, `xTail`, `yTail`, `tTail`, each
with `*MajorAxisLength`, `*MinorAxisLength`, `*Excentricity`, plus `areaBody`, `imageNumber`
(frame) and **`id`** (identity). Image coordinates, origin top-left; the video resolution is
**not** recorded in the file, so a y-flip needs the height supplied externally. First frame is 0.
Source: [aniread `read_fasttrack.R`](https://github.com/animovement/aniread/blob/main/R/read_fasttrack.R).

### 2.5 Ctrax + the `trx.mat` family (Ctrax / FlyTracker / JAABA)
Ctrax: <https://ctrax.sourceforge.net/>; JAABA: <https://github.com/kristinbranson/JAABA>;
FlyTracker: <https://github.com/kristinbranson/FlyTracker>

`trx.mat` is the de-facto MATLAB interchange format in the *Drosophila* community and is worth
supporting because several trackers export to it.

**`trx.mat`** contains the variable **`trx`**, a MATLAB struct array with one element per animal.
Per-element fields: `x`, `y` (pixels, `1 × nframes`), `theta` (orientation), `a`, `b` (quarter
major/minor axis length in px), `nframes`, `firstframe`, `endframe`, `off` (= `1 - firstframe`,
the index offset), `id`, the real-unit mirrors `x_mm`, `y_mm`, `theta_mm`, `a_mm`, `b_mm`, `sex`
(a single char `M`/`F`/`?`, or a per-frame cell array), `dt` (`1 × nframes-1`, seconds between
frames), `fps`, and optional `timestamps` (serial date number, days). Larva trackers add `area`,
`xcontour`/`ycontour` (cell arrays), `xspine`/`yspine` (`11 × nframes`) and their `_mm` versions.
Note that trajectories are **per-animal segments** delimited by `firstframe`/`endframe`, so
indexing into a frame requires the `off` offset; MATLAB convention means frame numbering is
1-based.

**Ctrax's own raw `.mat` is a different, flat layout — not a `trx` struct array.** A real Ctrax output
(12,033 frames, 159,765 detections) contains nine variables: `ntargets` `(n_frames,1)` (number of targets in
each frame), and per-detection column vectors `x_pos`, `y_pos`, `angle`, `maj_ax`, `min_ax`, `identity`
(all `(159765,1)`), plus `startframe` and `timestamps` `(n_frames,1)`. Detections are concatenated frame by
frame, so frame *t* occupies the next `ntargets[t]` rows (use a cumulative sum to slice). Targets per frame
ranged 9–17 and the file contained **193 distinct `identity` values**, i.e. Ctrax identities are track fragments,
not one ID per animal. The y coordinate in this file is **flipped relative to image coordinates**: after
`y' = 2160 − y` (the video height) its positions agreed with AnimalTA's on the same video to a median of about 1 px
(without the flip the median offset was 333 px). The `trx` structure described above is produced from these raw
files by the Ctrax MATLAB toolbox (`load_tracks.m`) and is what JAABA consumes.

**FlyTracker** writes `-track.mat` with a struct `trk`: `trk.names` `{1 × n_fields}`,
`trk.data` `[n_flies × n_frames × n_fields]`, and `trk.flags` `[n_flags × 5]` recording potential
identity swaps as `(fly1, fly2, start_fr, end_fr, ambig)`. `-feat.mat` holds `feat.names`,
`feat.units` and `feat.data` `[n_flies × n_frames × n_fields]` with features such as `vel`,
`ang_vel`, `min_wing_ang`, `max_wing_ang`, `mean_wing_length`, `axis_ratio`, `fg_body_ratio`,
`contrast`, `dist_to_wall` and the pairwise `dist_to_other`, `leg_dist`, `angle_between`,
`facing_angle`. `-seg.mat` holds foreground/body/wing/leg pixel locations; `-actions.mat` holds
`behs` and `bouts` `{n_flies × n_behs}` with `(start_fr, end_fr, certainty)`; `-JAABA/` is a
ready-made JAABA folder (written when `options.save_JAABA` is set). Per-frame features can also be written as
a folder of per-fly CSV files when `options.save_xls` is true, according to the FlyTracker `core_tracker.m` header.

Sources: [JAABA data-formatting docs](https://github.com/kristinbranson/JAABA/blob/master/docs/DataFormatting.html),
[FlyTracker documentation](https://github.com/kristinbranson/FlyTracker/blob/main/docs/documentation.html),
[Ctrax usage](https://ctrax.sourceforge.net/ctrax.html).

### 2.6 Argos
Python, GPL-3.0, <https://github.com/subhacom/argos>

**HDF5 (default)** — a pandas `HDFStore` with two keys: `segmented` (fixed format, columns
`frame`, `x`, `y`, `w`, `h`) and **`tracked`** (table format), whose columns are
`frame`, `trackid`, `x`, `y`, `w`, `h`, `cx`, `cy`, `obb_w`, `obb_h`, `angle`, `area`,
`major_axis`, `minor_axis`, `solidity`. `(x, y)` is the **top-left corner** of the axis-aligned
bounding box; `cx`,`cy` and the `obb_*`/`angle` fields describe the oriented box.
Legacy CSV writers produce `<prefix>.seg.csv` (`frame,x,y,w,h`) and `<prefix>.trk.csv`.
Argos can also read MOT-format text (`frame`, `trackid`, `x`, `y`, `w`, `h`, `confidence`, `xc`,
`yc`, `zc`).

**Identity** — integer `trackid` from SORT, assigned in strictly increasing order and never
reused; objects lost for longer than *Maximum age* are dropped and reappear as a **new ID**, so
tracks are fragments. The Review tool's corrections are stored in the same file under
`changes/changelist_<timestamp>` with columns `frame`, `end`, `change`, `code`, `orig`, `new`,
`idx` (`end = -1` means "to end of video"; `orig`/`new` are the track IDs involved). After
`saveChanges`, the `tracked` table is rewritten with only `frame`, `trackid`, `x`, `y`, `w`, `h`.
Argos's own output carries **no confidence column** even though the YOLACT detector produces one.
Sources: [user documentation](https://github.com/subhacom/argos/blob/master/doc/user.rst),
[`argos/writer.py`](https://github.com/subhacom/argos/blob/master/argos/writer.py),
[`argos/trackreader.py`](https://github.com/subhacom/argos/blob/master/argos/trackreader.py).

### 2.7 anTraX (barcoded/marked ants)
MATLAB, GPL-3.0, <https://github.com/Social-Evolution-and-Behavior/anTraX>

Experiment directory (`expdir`) holds a `videos/` subdirectory plus one subdirectory per tracking
session storing parameters and results. Videos sharing a base name are suffixed with `_<index>`
and may be grouped into range-named folders (`1_24`). Each video may have a sibling
**`<videoname>.dat`**: a header row of variable names and one value row per frame (timestamps,
sensor channels); if a variable named `dt` is present it overrides the nominal frame rate as the
inter-frame interval. The repository documentation describes the directory organisation, the
classification/propagation pipeline and a JAABA export path, but **does not specify the internal
schema of the session result tables** — read those via anTraX's own MATLAB/Python API.
Source: [docs](https://github.com/Social-Evolution-and-Behavior/anTraX/blob/master/docs/data_organization.md).

### 2.8 Tracktor
Python (notebooks), MIT, <https://github.com/vivekhsridhar/tracktor> (last commit 2022)

A template script rather than an application: outputs one overlay video and one **CSV of XY
coordinates**. Column names are defined by the user's own copy of the script, so there is no
fixed schema. Coordinates are in pixels and time in frames; the worked examples convert using
user-set `framerate` and `pxpercm`. Identity is maintained during tracking (e.g. 2 spiders, up to
8 termites) but the README does not define how IDs are laid out in the file.
Source: [README](https://github.com/vivekhsridhar/tracktor/blob/master/README.md).

### 2.9 pathtrackr (R)
R, <https://github.com/aharmer/pathtrackr> (single animal)

`trackPath()` returns an R list with (1) a matrix of per-frame xy coordinates, (2) a matrix of
between-frame distances, velocities and bearings, (3) summary data, which `pathSummary()`
tabulates. Arena size is given in mm (`xarena`/`yarena`), frame size in pixels, and `fps` drives
the kinematics. Outputs are in-memory R objects plus optional MP4/PDF diagnostics; the package
defines no on-disk tabular format, and column names are not documented.
Source: [README](https://github.com/aharmer/pathtrackr/blob/master/README.md).

### 2.10 OCTRON
Segmentation-based tracker exporting **CSV with a 6-line key/value metadata preamble**
(including `video_height:` and `frame_count_analyzed:`) followed by a table with
`frame_idx`, `track_id`, `label`, `confidence`, centroid `pos_x`/`pos_y`, bounding box
`bbox_x_min`/`bbox_x_max`/`bbox_y_min`/`bbox_y_max`, and dozens of scikit-image region-property
columns under their expanded names (`area`, `orientation`, `moments_hu-0`,
`weighted_centroid-0-0`, …). Two gotchas: frames with no detections are **omitted entirely**, so
a gap in `frame_idx` means "no observation" rather than "frame absent"; and when several
disconnected mask segments map to one track in one frame, cells contain tuple-strings like
`"(120.5, 85.3)"`. Image coordinates (top-left origin); `orientation` is scikit-image's axial
long-axis angle, not a heading.
Source: [aniread `read_octron.R`](https://github.com/animovement/aniread/blob/main/R/read_octron.R).

---

## 3. Organism- and assay-specific systems

### 3.1 Tierpsy Tracker (*C. elegans*, multi-worm)
Python, MIT, <https://github.com/Tierpsy/tierpsy-tracker>

A chain of HDF5 files per video, each stage adding one:

- **`basename.hdf5`** — `/mask` `(tot_images, im_high, im_width)` compressed masked frames with
  attributes `expected_fps`, `time_units`, `microns_per_pixel`, `xy_units`,
  `is_light_background`; `/full_data`; `/mean_intensity`; `/timestamp/raw` and `/timestamp/time`.
- **`basename_skeletons.hdf5`** — the tracking core. `/plate_worms` (one row per blob
  detection: `worm_index_blob`, `worm_index_joined`, `threshold`, `frame_number`, `coord_x`,
  `coord_y`, `box_length`, `box_width`, `angle`, `area`, `bounding_box_*`);
  `/trajectories_data` keyed by (`worm_index_joined`, `frame_number`) with `skeleton_id`,
  `has_skeleton`, `is_good_skel`, `skel_outliers_flag`, `roi_size`, `timestamp_raw`,
  `timestamp_time`, `int_map_id`; `/blob_features` (shape descriptors, Hu moments);
  `/skeleton`, `/contour_side1`, `/contour_side2` each `(tot_valid_skel, n_segments, 2)`;
  `/contour_width`; `/width_midbody`; `/contour_area`; `/food_cnt_coord`.
- **`basename_intensities.hdf5`** — `/straighten_worm_intensity`
  `(tot_valid_skel, n_length, n_width)` float16.
- **`basename_features.hdf5`** / **`basename_featuresN.hdf5`** — `/features_timeseries` or
  `/timeseries_data` (speed, angular velocity, curvature, `eigen_projection_1..7`, `motion_mode`,
  `food_region`, `turn`, derivatives) and `/features_stats` or `/features_summary` (percentiles,
  means, medians, with `_split` variants).

**Units** — `xy_units` is `microns` when a valid `microns_per_pixel` was given, otherwise
`pixels`; `time_units` is `seconds` when `expected_fps` or a timestamp exists, otherwise `frames`.

**Identity** — `worm_index_blob` is the raw trajectory index; **`worm_index_joined`** is the index
after joining across short gaps and discarding spurious tracks (invalid rows get `-1`). Each time
a worm is lost and re-found it gets a **new** index, so IDs are fragments, and long trajectories
may be deliberately split into `_split` tables. `skeleton_id = -1` marks frames with no skeleton
match.
Source: [`docs/OUTPUTS.md`](https://github.com/Tierpsy/tierpsy-tracker/blob/master/docs/OUTPUTS.md).

### 3.2 Multi-Worm Tracker (MWT) + Choreography
C++/LabVIEW, LGPL-2.1, <https://sourceforge.net/projects/mwt/>,
core at <https://github.com/Ichoran/mwt-core>
(Swierczek et al. 2011, *Nat. Methods* 8:592–598)

MWT does real-time tracking and emits a **custom text-based format**: a directory per experiment
containing **`.blobs`**, **`.summary`**, **`.set`** and `.png` files; per-animal movement tables
(`.dat`) are produced off-line by the companion **Choreography** (`Chore.jar`) program. The
`mwt-core` README documents the internal C++ classes (`Blob`, `Dancer`, `Performance`,
`SummaryData`) but not the on-disk schema. The practical specification is the OpenWorm
Tracker Commons converter, which states that the format is "largely compatible with WCON" and
that **centroids, skeletons and outlines are preserved as written**, with areas carried under the
`@XJ` tag; it assumes 0.026 mm/pixel unless told otherwise.
Sources: [MWT→WCON converter](https://github.com/openworm/tracker-commons/blob/master/converters/MultiWormTracker/README.md),
[mwt-core README](https://github.com/Ichoran/mwt-core/blob/master/README.md).

### 3.3 ZebraZoom (larval/adult zebrafish)
Python, AGPL-3.0, <https://github.com/oliviermirat/ZebraZoom>

**`results_{videoName}.txt`** is JSON despite the extension — a "super structure" with
`wellPositions` (`topLeftX`, `topLeftY`, `lengthX`, `lengthY`) and `wellPoissMouv`, a nested list
indexed `[well][animal][bout]`. Each bout is an object with `FishNumber`, `BoutStart`, `BoutEnd`,
`TailAngle_Raw`, `TailAngle_smoothed`, `HeadX`, `HeadY`, `Heading_raw`, `Heading`,
`TailX_VideoReferential`, `TailY_VideoReferential`, `TailX_HeadingReferential`,
`TailY_HeadingReferential`, `Bend_TimingAbsolute`, `Bend_Timing`, `Bend_Amplitude`, `curvature`,
`alternativeCurvatureCalculation`.

Also written: `allData_{videoName}_wellNumber{i}_animal{j}.csv` (frame-by-frame per animal, with
`curvature{n}` columns, NaN-filled outside bout ranges), and an HDF5 with group paths
`dataForWell{i}/dataForAnimal{j}/dataPerFrame` containing `HeadPos`, `TailPosX`, `TailPosY` and a
structured `curvature` dataset of shape `(lastFrame-firstFrame+1, nbTailPoints-2)` whose field
names are in `dataset.attrs['columns']`.

Note the two coordinate frames: `*_VideoReferential` is the original video frame;
`*_HeadingReferential` places the head at `(0,0)` with the y-axis along the heading. Data are
organised as **discrete bouts**, not a continuous per-frame track.
Source: [`zebrazoom/code/dataPostProcessing/perBoutOutput.py`](https://github.com/oliviermirat/ZebraZoom/blob/master/zebrazoom/code/dataPostProcessing/perBoutOutput.py).

### 3.4 Stytra (closed-loop zebrafish behaviour)
Python, GPL-3.0, <https://github.com/portugueslab/stytra>

Streaming logs (stimulus state, raw tracking variables, estimated fish state) are written through
pandas as **CSV, HDF5 or Feather**. For freely swimming fish the dataframe has per-fish columns
prefixed `f{N}_` — `f0_x`, `f0_y`, `f0_theta` plus tail-segment angles `theta_XX`; for embedded
fish the columns are `tail_sum` and `theta_XX`. `x`/`y` are camera coordinates; `theta` is the
tail direction (add π for heading). Metadata goes to a hierarchical
`stytra_last_config.json` with fixed top-level categories `general`, `animal`, `stimulus`,
`imaging`, `behavior`, `camera`; the camera→projector mapping is `cam_to_proj` in
`metadata.json`. Fish numbering is **not stable** — identities change when fish leave the field
of view or cross.
Source: [data-saving docs](https://github.com/portugueslab/stytra/blob/master/docs/source/devdocs/3_data_saving.rst).

### 3.5 ethoscope (long-term *Drosophila* monitoring)
Python, GPL-3.0, <https://github.com/gilestrolab/ethoscope>

Each experiment produces a **SQLite database** (MySQL in the networked setup). Schema:
`ROI_MAP(roi_idx INTEGER, roi_value INTEGER, x INTEGER, y INTEGER, w INTEGER, h INTEGER)`;
`VAR_MAP(var_name TEXT, sql_type TEXT, functional_type TEXT)`; one data table **per ROI** named
`ROI_{idx}` with `id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER` plus one column per tracked
variable (named from each data row's `header_name`, typed INTEGER/REAL/TEXT);
`METADATA(field TEXT, value TEXT)`; `START_EVENTS(id, t, event TEXT)` logging e.g.
`graceful_start`, `appending`; optional `IMG_SNAPSHOTS(id, t, img BLOB)` and `CSV_DAM_ACTIVITY`.
Identity is positional: one animal per ROI, one table per ROI, with no cross-ROI track ID.
Source: [`ethoscope/io/sqlite.py`](https://github.com/gilestrolab/ethoscope/blob/main/src/ethoscope/ethoscope/io/sqlite.py).

### 3.6 FicTrac (spherical treadmill, fictive path)
C++, <https://github.com/rjdmoore/fictrac>

A single headerless delimited **`.dat`** with 23, 24 or 25 columns depending on version. Columns
1–21 are stable: `frame`, `delta_rot_cam_x/y/z`, `delta_rot_error`, `delta_rot_lab_x/y/z`,
`abs_rot_cam_x/y/z`, `abs_rot_lab_x/y/z`, `pos_x`, `pos_y`, `heading`, `direction`, `speed`,
`movement_x`, `movement_y`. The remainder are timestamp fields that differ by release:
23 columns (v2.0–2.02) add `timestamp`, `seq_num`; 24 columns (pre-2.03) add `alt_timestamp`
(ms since midnight), `seq_num`, `delta_timestamp`; 25 columns (v2.03+) add all four. `pos_x`/
`pos_y` describe a fictive 2D path; `heading` is in radians. This is a single-animal format with
no identity column.
Source: [aniread `read_fictrac.R`](https://github.com/animovement/aniread/blob/main/R/read_fictrac.R).

---

## 4. General-purpose vision frameworks used for animal tracking

### 4.1 TrackMate (Fiji/ImageJ)
Java, GPL-3.0, <https://github.com/trackmate-sc/TrackMate>

**XML** (`.xml`) is the native format: root carries a `version` attribute; `Model` carries
`spatialunits` and `timeunits`; `Settings/ImageData` carries `height`, `pixelheight`,
`pixelwidth`, `timeinterval`. Detections live at `AllSpots/SpotsInFrame/Spot`, each `Spot`
carrying `ID`, `POSITION_X`, `POSITION_Y`, `POSITION_Z`, `POSITION_T`, `FRAME`, and (non-slim)
`RADIUS` and `QUALITY`. Links live in `Track` elements (`TRACK_ID`, `name`) containing `Edge`
elements with `SPOT_SOURCE_ID` / `SPOT_TARGET_ID`; `TrackID` elements list the filtered tracks.

**CSV export** writes three files sharing a prefix: `*_spots.csv` (required; recognisable by the
header `LABEL, ID, TRACK_ID, QUALITY, POSITION_X, POSITION_Y`), `*_edges.csv` (supplies
`LINK_COST`, usable as a tracking score) and `*_tracks.csv` (track-level summary). All three have
**four header rows** — field names, descriptions, abbreviations, units — before the data.

Two things matter for animal data. First, calibration: an uncalibrated image defaults to
`timeunits='sec'` and `timeinterval=1`, so "time" may in fact be frame number. Second, TrackMate
was built for cells, so tracks can **divide**: a track holding more than one spot in a frame is a
lineage, which readers split into branches with a `parent` column recording the branch origin.
Sources: [sleap-io TrackMate reference](https://github.com/talmolab/sleap-io/blob/main/docs/formats/trackmate.md),
[aniread `read_trackmate.R`](https://github.com/animovement/aniread/blob/main/R/read_trackmate.R).

### 4.2 Bonsai
C#, MIT, <https://github.com/bonsai-rx/bonsai>

Bonsai is a reactive dataflow environment, so **the output schema is whatever the user's workflow
writes**. The conventional centroid-tracking workflow produces a CSV with a timestamp column, a
`Centroid.X`/`Centroid.Y` pair, an `*.Orientation` column, and frame-size fields
`Size.Width`/`Size.Height` (often prefixed `Item1.`, `Item2.` … when several ROIs are logged
against one shared timestamp); `RegionOfInterest.Width/Height` is the ROI, distinct from frame
size. Image coordinates, pixels. `Orientation` is the blob's long-axis angle in radians within
`(-π/2, π/2]` — **axial, with no front/back**, so it is not a heading. There is **no identity
column** and no confidence. The timestamp is the software receipt time, not camera capture time,
so inter-sample intervals vary and no constant sampling rate should be inferred.
Source: [aniread `read_bonsai.R`](https://github.com/animovement/aniread/blob/main/R/read_bonsai.R).

### 4.3 ilastik (animal-tracking workflow)
<https://www.ilastik.org/documentation/animaltracking/animaltracking>

ilastik's animal-tracking workflow exports object-level tables through its plugin export system
(`CSV-Table` among them), giving one row per detected object per frame. The exact column set
depends on the object features selected in the workflow, so it is configuration-dependent rather
than fixed; see the linked documentation page for the current export options.

---

## 5. Interchange standards and converters

These matter directly for a pipeline that ingests several trackers: rather than writing N
importers, you can often target one of these.

### 5.1 WCON — Worm tracker Commons Object Notation
<https://github.com/openworm/tracker-commons> (OpenWorm)

A single JSON object per file (`.wcon`/`.json`, optionally zipped). Required keys: **`units`**
(declares the unit string for `t`, `x`, `y` and every other numeric field — e.g. `"s"`, `"mm"`;
compound units via `*`, `/`, `^`) and **`data`** (one object or an array of records). Each data
record requires `id` (string), `t` (increasing timestamps) and `x`/`y`, each "arrayable" so a
timepoint may hold either a single coordinate or an array of body-point coordinates. Optional
per-record fields: `ox`/`oy` (per-timepoint origin — everything else at that timepoint is
relative to it), `cx`/`cy` (centroid), `head` (`L`/`R`/`?`), `ventral` (`CW`/`CCW`/`?`), `px`/`py`
(perimeter), `ptail`, and `walk` (run-length encoded pixel paths). Lab-specific extensions go
under `@labcode` tags. Optional top-level `metadata` (`lab`, `who`, `timestamp`, `temperature`,
`humidity`, `arena`, `food`, `media`, `sex`, `stage`, `age`, `strain`, `protocol`, `interpolate`,
`software`) and `files` (`current`/`next`/`prev`) for time-chunked experiments.

Because JSON has no NaN/Inf, **missing values are `null`** (or simply omitted). The same `id` may
appear in several records with different timepoints — that is how splitting and merging across
chunks works — but not twice at the same timepoint.
Source: [`WCON_format.md`](https://github.com/openworm/tracker-commons/blob/master/WCON_format.md).

### 5.2 NWB + ndx-pose
Pose data can be written into NWB as a `PoseEstimation` object (predictions, with confidence and
multiple tracks) or `PoseTraining` (manual annotations). Each keypoint becomes a
`PoseEstimationSeries` with `data` of shape `(n_frames, n_space)` and `confidence` of shape
`(n_frames,)`. The `ndx-multisubjects` extension maps each track to a real NWB `Subject`, which
requires every instance to be track-assigned. Required session metadata: `session_description`,
`identifier`, `session_start_time`.
Source: [sleap-io NWB reference](https://github.com/talmolab/sleap-io/blob/main/docs/formats/nwb.md).

### 5.3 `movement` (Python)
BSD-3-Clause, <https://github.com/neuroinformatics-unit/movement>

Loads DeepLabCut, SLEAP (`.slp` and analysis `.h5`), Lightning Pose, Anipose, COCO keypoint
results, NWB and VIA-tracks into a single **xarray.Dataset** with `position`
`(time, space, keypoints, individuals)` and `confidence` `(time, keypoints, individuals)`;
bounding-box sources additionally get `shape`. Conventions worth knowing because they apply to
everything it loads: time defaults to 0-based frame numbers and becomes seconds when `fps` is
given; missing observations are NaN (confidence defaults to an all-NaN array when the source has
none); individuals are auto-named `id_0`, `id_1`, … when the source carries no names. For
VIA-tracks it converts the file's top-left bbox corner into a **centroid** (`x + w/2`, `y + h/2`).
It also warns about the two identity traps: COCO keypoint results carry no track identity (the
i-th detection in each image is assigned to individual i, order not stable), and a SLEAP file
with no tracks is treated as single-individual.
Source: [`movement/io/load_poses.py`](https://github.com/neuroinformatics-unit/movement/blob/main/movement/io/load_poses.py),
[`load_bboxes.py`](https://github.com/neuroinformatics-unit/movement/blob/main/movement/io/load_bboxes.py).

### 5.4 `aniread` / animovement (R)
<https://github.com/animovement/aniread>

The widest set of readers of anything surveyed here, with a content-based detector per format —
useful as a specification source even if you work in Python. Registered sources: `aniframe`
(its own Parquet/CSV), `animalta`, `anipose`, `bonsai`, `boris`, `c3d`, `deeplabcut`,
`fasttrack`, `fictrac`, `freemocap`, `idtrackerai`, `lightningpose`, `movement`, `octron`,
`sleap`, `trackball_bonsai`, `trackmate`, `trex`. Its detection signatures double as a cheat
sheet for identifying an unknown file: Anipose CSVs contain `fnum` plus `_score`/`_error`/
`_ncams` columns; DeepLabCut CSVs start with a `scorer` row followed by `bodyparts` and `coords`;
SLEAP HDF5s have `tracks` and `node_names`; movement files have `position` and `confidence`;
FicTrac files are headerless and ≥ 23 numeric columns; TrackMate XML has a `Model` node.
Every reader normalises to the same long columns — `time`, `individual`, `keypoint`, `x`, `y`,
`confidence` (+ `yaw`, `z` where available) — and **re-reflects y to a bottom-left origin**,
which is the opposite of what most trackers write.

### 5.5 `sleap-io` (Python)
BSD-3-Clause, <https://github.com/talmolab/sleap-io>

Reads/writes `.slp`, NWB, JABS HDF5, SLEAP analysis HDF5, Label Studio JSON, DeepLabCut CSV,
five SLEAP CSV layouts, LEAP `.mat`, COCO (incl. panoptic), TrackMate CSV, labelled TIFF stacks,
GeoJSON ROIs and Ultralytics YOLO directories. Its `docs/formats/` directory is the single best
written reference for several of these formats.

---

## 6. Tools included for completeness, with output format not specified in the sources checked

These are genuinely open-source animal trackers, but I could not find a documented output schema
in their repositories — the layout has to be read off an example file or from the source.

| Tool | Repo | License | Note |
|---|---|---|---|
| MARGO | <https://github.com/de-Bivort-Lab/margo> | MIT | MATLAB, high-throughput *Drosophila*; README describes the GUI, not the saved data layout |
| BioTracker | <https://github.com/BioroboticsLab/biotracker_core> | none stated | C++ plugin-based tracker; README covers building, not output |
| LabGym | <https://github.com/umyelab/LabGym> | GPL-3.0 | behaviour quantification; states results "are output in spreadsheets" (count, duration, latency, speed, acceleration, distance travelled, intensity, vigor) with no column spec |
| JAABA | <https://github.com/kristinbranson/JAABA> | — | behaviour classifier rather than a tracker; consumes `trx.mat` (§2.5) and writes per-frame feature `.mat` files and label files such as `labeledChases.mat` |

---

## 7. Practical notes for an import layer

1. **Three identity regimes.** Continuous per-individual files (TRex, Tierpsy's
   `worm_index_joined` after joining, trx.mat); fragment IDs that must be stitched or
   hand-corrected (Argos, Tierpsy raw, Stytra, TrackMate branches); and no identity at all
   (Bonsai, TRex CSV export, COCO results, DeepPoseKit). The third case is the dangerous one,
   because array slots still look like individuals — SLEAP's synthetic `track_0 … track_n` and
   `movement`'s `id_0 … id_n` are positional placeholders, not animals.
2. **Missing data is not always NaN.** TRex writes `inf`; `movement`, SLEAP, DeepLabCut and
   Tierpsy's float fields write NaN; WCON writes `null`; Tierpsy and SLEAP use `-1` as a missing
   *index*; OCTRON and SLEAP CSV omit the row entirely, so absence has to be reconstructed
   against a full frame grid.
3. **Y-axis and origin.** Most trackers write image coordinates (origin top-left, y
   increasing downward): DeepLabCut, SLEAP, TRex, AnimalTA, FastTrack, TrackMate, Bonsai, OCTRON. A verified
   exception is Ctrax's raw `.mat`, whose y is measured from the bottom (`y_image = H − y`).
   Anything computing turning angles or comparing with a physical arena needs an explicit flip,
   and the frame height needed to do it is often **not stored in the file** (FastTrack, TRex CSV,
   AnimalTA).
4. **Units are frequently out-of-band.** TRex writes cm but silently assumes a 30 cm arena if
   `cm_per_pixel` is unset; AnimalTA detailed files are in the GUI's scale unit without recording
   which; TrackMate defaults an uncalibrated image to `timeinterval = 1 s`, making "seconds"
   actually frames; `trx.mat` carries both pixel and `_mm` variants of every field.
5. **Frame indexing base.** 0-based in SLEAP, DeepLabCut, Anipose (`fnum`), FastTrack, OCTRON,
   TRex; 1-based in the MATLAB `trx` family, where `off = 1 - firstframe` is the required offset.
6. **Treat axis-order attributes as optional.** SLEAP analysis HDF5 from newer `sleap-io` ships two layouts
   distinguished by a `preset` file attribute and per-dataset `dims`; files exported from the SLEAP GUI carry
   no attributes at all and always use `(n_tracks, 2, n_nodes, n_frames)`. Detect by shape, not by attribute.
