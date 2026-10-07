# Multi-tracker import: scan, detect, confirm, read

**Status:** Approved design, 2026-10-07 (work not started)
**Audience:** contributors adding or changing readers
**Relates to:** [`README.md`](README.md) (inputs and status), `docs/dev/DECISIONS.md` (D-012),
`docs/USER_WORKFLOW.md` Stage 2, `docs/dev/UI_DESIGN.md` §6.2,
[`2026-10-07-tier-0-implementation-plan.md`](2026-10-07-tier-0-implementation-plan.md)

## 1. Context

Track2Data reads idtracker.ai output only. Today the reader contract is
folder-only (`SessionReader.detect(folder) -> bool`, `read(folder) -> Session`). A
parent folder of session folders matches no reader, and the only parent-folder
walk in the repository is a test helper. The reader the app picked is never
saved, so `Engine` re-detects on every use. `Session.raw_xy` is one pixel point
per animal.

**Workflow to build.**

1. The user points at the trajectories folder. For idtracker.ai that is a folder
   of session folders.
2. The app detects the tracking software from the structure of the outputs, asks
   the user to confirm, and lets them amend the choice in the UI.
3. The confirmed reader pathway is used from then on, and the user proceeds
   through the wizard.

**Rollout order** follows [`importer_priority.csv`](importer_priority.csv): seven
importers cover 80.5 % of recent animal-tracker citations. Ease of fit decides how
each importer is sliced and which design gates are spiked first. The reader
fixture-test suite in `tests/real_samples/` is the acceptance harness: each reader
turns its contract cases from XFAIL to PASS.

## 2. Decisions

| Topic | Decision |
|---|---|
| Base | The work builds on pp3 (`fix/pp3-identity-switch-rewrite`, `2017cc8`), which is merged first and published to `main` |
| Tests and samples | The reader fixture-test suite (42 quirk tests; 10 contract cases × 8 tests; 26 fixtures pinned by sha256, about 70 MB) is the acceptance harness. Public samples are added only where it has gaps |
| Documents | `animal_tracking_output_formats.md` is canonical. The table CSV predates its corrections ([`README.md`](README.md)) |
| D-012 | "Mixed": text and CSV readers may ship from the documented layout, labelled *unverified*. HDF5, MAT and NPZ readers need a real sample. Every priority container format (DLC `.h5`, SLEAP `.h5`, TRex `.npz`, Ctrax `.mat`) has a pinned real sample. Only `trx.mat` and FlyTracker lack one |
| Pose | One keypoint (user's choice; default best coverage) drives metrics. The full skeleton is also kept: stored only, no metric consumes it yet |
| Units | Native-unit mode for sources with no pixel frame (Anipose, ToxTrac RealSpace-only) |
| 3D | Metrics use a chosen 2-D plane (default x,y). z is kept in the keypoint array |
| fps and frame size | Most formats record neither (DLC, SLEAP, Anipose, AnimalTA size, Ctrax size). They are reader options: collected in the confirm dialog, saved in the manifest, passed to `read()`. Never defaulted, and never written into the input folder (FR-IMP-5). This is the suite's `provide_video_info()` hook, which it leaves open |
| UI placement | Modal confirm dialog inside the Sessions stage; no new wizard stage |

**Approaches considered.**

- **(A) chosen.** One read-only directory walk, then per-reader `discover`, a
  Qt-free `ConfirmDraft`, a modal dialog, and a persisted reader.
- **(B) rejected.** Adopt `movement` or `sleap-io` as the reading engine. It adds
  xarray/netCDF4 and PyInstaller weight and strains PRD C1/C2. They stay available
  only as optional differential tests.
- **(C) rejected.** Convert everything to idtracker.ai-style `.npy` first. It adds
  a user step and loses provenance.

## 3. Facts the design rests on

Verified on the pp3 base unless stated.

- **Session model.** `Session` requires `fps`, `n_frames`, `width_px` and
  `height_px`, and has no validators. fps is one constant per session. Frame
  offsets exist only through `tracking_intervals` (`api._map_array_index_to_true_frame`),
  and only when the interval lengths sum to `n_frames`.
- **Confidence.** The only per-point confidence is `id_probabilities`. It means
  identity confidence and feeds D-3 and `quality_threshold`. Keypoint likelihood
  must never go there.
- **Identity.** `track_wo_identities` and `SessionRef.is_identity_free()` already
  exist. They are reused for SLEAP synthetic tracks, fragments, and formats with no
  identity.
- **Calibration.** The default mode `bodylength` needs `body_length_px`, which only
  idtracker.ai supplies. It otherwise degrades silently to pixel-only.
- **D-5.** `metrics/diagnostic.py` defaults `fraction_identified` to 0.0 when
  `quality is None`, so every non-idtracker session with stable identities reads
  "weak".
- **Reader contract on pp3.** `read(self, folder, *, allow_pickle=False)` with the
  opt-in `accepts_allow_pickle` flag, and `read_session(folder, *, allow_pickle=False)`.
  The v4 stub reader is gone. `Engine.import_session` passes the project's
  `security.allow_pickle_trajectories`.
- **Input hashing on pp3.** `SessionRef.sha256` is filled after the probe from one
  file, `Session.trajectory_source`, and checked at run time. Multi-file readers
  (TRex, ToxTrac) need a `source_files` list.
- **Errors.** `Track2DataError` carries `code` and `remediation`. The suite requires
  both on every error a reader raises.
- **UI today.** `ImportScreen` uses a non-native multi-select dialog and accepts only
  directories on drop. `ProjectStore.add_session` appends the `SessionRef` and then
  probes with `read_session` on a single-thread `TaskRunner`. Any failed task raises
  the generic "Pipeline run failed" modal. After reopening a project the table shows
  "—". `docs/USER_WORKFLOW.md` already says the detected reader is saved on advance.
- **Reusable precedents.** The identity-free tri-state override, the
  session-calibration confirm checkbox, the schema-driven parameter form
  (`metrics/base.py::MetricParameter` and `metric_config_dialog._build_field`), and
  `core/progress.py` (`ProgressEvent`, `CancellationToken`).
- **Test seams to keep.** `tests/test_api.py` assigns
  `engine.import_session = lambda folder: …` and patches `track2data.api.read_session`.
  `tests/test_ui/test_project_store.py` patches `track2data.readers.read_session`. The
  suite calls `registry._REGISTRY`, `detect_reader(folder)` and `cls().read(folder)`, so
  the legacy call shape stays valid and `read(folder)` must accept a folder holding
  exactly one session.

## 4. Architecture

### 4.1 Flow and dialog

```
Add tracking folder… (or drop folder/file)
  → background scan: one read-only walk → ScanIndex → each reader's discover(index, peek)
  → ConfirmFormatDialog (modal, thin view over Qt-free ConfirmDraft)
  → OK: SessionRefs saved with reader + reader_options; probes use the NAMED reader
  → Next (wizard unchanged)
```

```
┌ Confirm tracking software ─────────────────────────────────────────────┐
│ Folder: D:\fish\trajectories        scanned 412 entries in 0.4 s       │
│ Detected: [ DeepLabCut (CSV/H5; also Lightning Pose) ▾ ]  ● High       │
│   Why? 14 files with scorer/individuals/bodyparts/coords header        │
│   Other matches: SLEAP analysis (low) · Choose software…               │
│ Options (all sessions)                                                 │
│   Animal position from [ snout — 98 % coverage ▾ ]  cutoff [0.60]     │
│   FPS [30] (from meta.pickle)   Frame size [1920]×[1080] (from video)  │
│   ☑ Keep full skeleton (14 keypoints, 38 MB)                           │
│ Sessions   include  id                      frames  animals  note      │
│            ☑        trial01DLC_resnet50…    18 485  1                  │
│            ☑        trial02DLC_resnet50…    17 902  1                  │
│                              [ Cancel ]   [ Add 14 sessions ]          │
└────────────────────────────────────────────────────────────────────────┘
```

Dialog rules:

- It opens with `open()` and a `finished` signal, never `exec()`. `exec()` would
  hang the screenshot driver, whose modal guard patches only `QMessageBox`.
- It installs no outside-click filter: a combo popup is a separate window, and a
  click on it could reject the dialog. Esc cancels.
- OK is disabled with a tooltip stating why (missing required option, duplicate id,
  nothing selected).
- A badge shows *unverified against real data* where it applies, and a banner shows
  a truncated scan.
- An empty state lists the file types seen, offers "Choose software…", and gives the
  remediation text for recognise-only formats.
- Changing the software combo uses precomputed alternatives. Only a reader that did
  *not* detect needs a lenient re-run on the retained index.
- Mixed-format roots confirm one group at a time.

### 4.2 Scan

- `readers/index.py` builds an immutable `ScanIndex` with `os.scandir` only. It skips
  `._*`, `__MACOSX`, `.git`, `$RECYCLE.BIN` and DLC's `labeled-data/` and
  `dlc-models/`, detects Windows reparse points with `st_file_attributes & 0x400`,
  never follows symlinks, goes four directory levels deep, and treats a claimed
  subtree as a leaf.
- Cloud-only files (`RECALL_ON_DATA_ACCESS` `0x400000`, `RECALL_ON_OPEN` `0x40000`,
  `OFFLINE` `0x1000`) are never opened. They report LOW confidence and a warning.
- `readers/peek.py` is the only place files are opened during a scan: head bytes,
  CSV header rows, `.npy` headers through `np.lib.format`, zip member names, HDF5
  root keys, node types and string attributes, `scipy.io.whosmat`, and SQLite
  read-only. A scan never unpickles and never writes.
- `readers/scan.py` runs every reader's `discover(index, peek)`, ranks the results,
  and resolves collisions. Errors come back as values inside the result, so a
  failed scan never becomes the generic failure modal.
- Budgets: 100k entries and 30 s, then `truncated=True`. Progress events are
  throttled to at least 100 ms apart, and the scan is cancellable.

### 4.3 Reader contract (additive)

New class attributes, all defaulted so third-party readers keep working:
`display_name`, `parameters` (`ReaderParameter` specs), `verification`
(`real_sample` or `synthetic_only`), `coordinate_frame`, `provides_body_length`.

- `discover(index, peek)` defaults to wrapping `detect`. For built-in readers
  `detect` and `discover` must agree on every suite folder.
- `read(path, *, options=None)` accepts a session folder **or** its primary file. A
  folder holding several sessions raises `SESSION_AMBIGUOUS`. Options are passed
  only when `parameters` is non-empty, in the same capability-flag style as pp3's
  `accepts_allow_pickle`.
- A missing required option raises `READER_OPTION_MISSING` and never falls back to a
  default.
- `read_session(path, *, reader=None, options=None)` extends pp3's `allow_pickle`
  through one `_call_read` helper. Naming a reader skips auto-detect.
- `get_reader(name)`, `reader_names()`, and the `_REGISTRY` list (a test seam).
- New errors: `READER_UNKNOWN`, `READER_NOT_AVAILABLE`, `READER_OPTION_MISSING`,
  `SESSION_AMBIGUOUS`, `FORMAT_AMBIGUOUS`. Each carries a `code` and a `remediation`.

### 4.4 Persistence and the engine seam

- `SessionRef.reader`, `reader_options` and `reader_chosen_by` are additive. The
  manifest stays `schema_version=1`; `project_hash` changes once, noted in the
  changelog.
- `SessionRef.folder` means "location": a folder, or the tracking file for
  single-file formats.
- `Engine._import_ref(ref)` keeps the legacy call shape when `reader is None`, takes
  the named-reader path otherwise, and stamps `session_id` from the ref so that the
  output directory and the metadata join cannot diverge from a reader-derived id.
- A persisted but unregistered reader raises `READER_NOT_AVAILABLE`. It never falls
  back to auto-detect, because that could change the numbers silently. Reader names
  are manifest API and are frozen.
- The dedupe key for added sessions is the resolved path plus the reader plus the
  selector option, so a second arena of one file is not dropped.
- `core/ids.py` holds the single session-id derivation (`default_session_id`,
  `sanitise_session_id`, `uniquify`).

### 4.5 Provenance

`SessionProvenance` gains `source_software`, `reader_verification`,
`reader_options`, `reader_chosen_by`, `detection_confidence` and `source_files`.
The run README gets a generic "Source software" section for non-idtracker readers;
the idtracker.ai block is unchanged. The D-5 diagnostic gets a `not_assessed`
status for readers that never provide `quality`.

### 4.6 Options, scale and units

fps, frame size, keypoint, cutoff and similar values are reader options. Where a
file or a neighbouring file records one, the dialog is pre-filled and says where the
value came from (file, video, tool default or required).

**Scale rule.** A scale a tool applied (ToxTrac RealSpace, TRex `cm_per_pixel`,
`trx.mat` `_mm`) is used only to rebuild true pixels. It never sets
`Session.length_unit`, and it never makes native units "physical" on its own: that
needs the user's explicit confirmation, reusing the existing "I confirm these
sessions were calibrated" checkbox. A tool-recorded scale is offered as a
pre-filled, unconfirmed suggestion. A factor of exactly 1.0 (the ToxTrac sample:
mm = px + ROI offset) or TRex's default 30 cm arena counts as uncalibrated and is
flagged. Unconfirmed native-unit sessions are labelled in tool units, not mm or cm.

### 4.7 Pose core and keypoints

- `readers/assemble.py`: `dense_from_long`, `dense_from_segments` (with a frame-offset
  record through `tracking_intervals`), `map_sentinels` (`inf`, `-1`, `0`, `NA`),
  `to_pixels`, `reduce_keypoints`, `classify_identity_regime` and `finalise_session`.
- `reduce_keypoints` defaults to the keypoint with the best coverage at the cutoff
  (tie: highest mean likelihood). It never averages the visible keypoints, because
  that jitters whenever the visible set changes.
- `Session.keypoints` (additive) holds `xy (F, A, K, D)` float32, names, per-keypoint
  confidence, edges, and a record of the selection (keypoint, cutoff, plane). It is
  stored and recorded in provenance. **No metric consumes it in this rollout.**
  A memory guard asks before keeping more than about 256 MB.
- `readers/video_meta.probe_video` (optional PyAV) returns fps, size and frame count
  to pre-fill the dialog. Frame size is never 0 for a pixel-frame session.

### 4.8 Identity regimes

Continuous per-animal identity maps to `has_stable_identities=True`. Formats with no
identity, positional placeholders and fragments set `track_wo_identities=True`
(detected default; the user can override in the dialog). Fragment formats keep every
fragment as its own slot, flagged identity-free; `top_n` (the user gives N) is opt-in.
Group metrics that skip frames with any NaN are reported in the dialog, not hidden.

### 4.9 Native-unit mode (own PR, gate G-units)

Touch points: `Session.coordinate_unit` and `has_pixel_frame`; the unit-suffix table
and codebook in `exporters/schema.py` (`_mm`, `_mm_s`, `_mm_s2`, `_mm2`, …); the run
README; the kinematics column names; calibration, which auto-uses the native unit
(`length_unit_label` is project-wide, so mixed units convert to the project unit when
the factor is known and otherwise block with `UNIT_MISMATCH`); zones and background,
which are disabled when there is no pixel frame; and the IL-3 and IL-14 arena
fallback, which uses data extent plus a warning instead of `width_px`/`height_px` = 0.
Existing idtracker.ai outputs stay unchanged.

## 5. Rollout tiers

| Tier | Prio | Importer | Citations | Cum. % | Gate | Suite cases that must flip XFAIL → PASS |
|---|---|---|---|---|---|---|
| 0 | – | Foundation: scan, detect, confirm, persist, provenance, CLI; idtracker.ai folder-of-folders; recognise-only registry; the suite | – | – | pp3 merged | suite imported: 42 quirk pass, 80 contract XFAIL |
| 1 | 1 | DeepLabCut CSV, then H5 (Lightning Pose, EKS, maDLC `_el.h5`) | 3,623 | 53.7 | G-H5 | `dlc_single_animal_h5`, `dlc_two_mice_csv`, `lightning_pose_eks_csv` |
| 1 | 2 | SLEAP analysis HDF5 (+ CSV layouts; `.slp` recognise-only) | 760 | 65.0 | none | `sleap_named_tracks`, `sleap_no_tracks` |
| 2 | 3 | Ctrax raw `.mat`, `trx.mat`, FlyTracker `-track.mat` | 371 | 70.5 | G-JAABA, G-fragments | `ctrax_raw_mat` |
| 3 | 4 | ToxTrac `Tracking_RealSpace.txt` (+ pixel twin) | 218 | 73.7 | G-units | `toxtrac_realspace` |
| 3 | 5 | Anipose pose-3d CSV (+ DLC-3D) | 195 | 76.6 | G-units | quirk tests; a Session-level case is added with the reader |
| 4 | 6 | TRex `.npz` (new and old versions; CSV export) | 166 | 79.0 | none | `trex_new_export`, `trex_old_export` |
| 4 | 7 | AnimalTA CSV (fixed and variable; detailed = recognise-only) | 95 | 80.5 | none | `animalta_fixed_csv` |
| 5 | – | Backlog by ease: FastTrack, OCTRON, generic table, WCON, TrackMate, Argos, Tierpsy, ZebraZoom, Stytra, ethoscope, `.slp`, NWB, movement `.nc`. Blocked (no documented schema): DANNCE, AlphaTracker, anTraX, MWT, MARGO, BioTracker, LabGym, pathtrackr, DeepPoseKit, FicTrac (not arena trajectories) | – | – | demand and a sample | – |

Priority order is followed strictly. Tiers group importers by *shared design gate*:
the pose core in Tier 1, the fragment policy in Tier 2, native units in Tier 3.
Tier 4 is the cheapest and fully pixel-native, so if a Tier 2 or 3 gate stalls it can
be pulled forward. The gate tasks themselves are never skipped.

## 6. Reader specs

Specified from `animal_tracking_output_formats.md` and the suite's pinned quirk
tests. Where they differ, the pinned tests win.

### P1 DeepLabCut family (cases `dlc_single_animal_h5`, `dlc_two_mice_csv`, `lightning_pose_eks_csv`)

- **Detect.** CSV: the first cell is `scorer`; the first cell of row 2 decides the
  depth (`individuals` means 4 header rows, `bodyparts` means 3), and the extension
  and first cell are identical for both. `.h5`: root key `df_with_missing` (single) or
  `tracks` (stitched `_el.h5`, a *group*, whereas SLEAP's `tracks` is a *dataset*).
  **Negatives:** `CollectedData_*` annotation files (index is an image path, no
  likelihood) and 3-D x,y,z files with no likelihood (Tier 3).
- **From the file.** Keypoints, individuals, 0-based frame index. Pinned: the EPM
  `.h5` is 18,485 × 24 with 0 NaN and 8 bodyparts; the two-mice CSV is 59,999 × 72
  with 5,890 NaN, `individual1` and `individual2`, 12 bodyparts; the EKS file is
  997 × 18. **The `.h5` records no fps or frame size** (pinned), and neither does the
  CSV.
- **From the user.** fps and frame size (pre-fill: `*_meta.pickle` [G-meta,
  unverified], then video, then typed); keypoint; cutoff (0.6 for DLC, off for
  LP/SLEAP); raw versus `_filtered`.
- **Traps.** Select coords by name: EKS has nine per keypoint (`x`, `y`,
  `likelihood`, `x/y_ens_median`, `x/y_ens_var`, `x/y_posterior_var`; scorer
  `ensemble-kalman_tracker`). `single` is the unique bodyparts and is excluded by
  default. `ind1…indn` are positional placeholders, so ask. Human-filled gaps carry
  likelihood 0.01. An `.h5` and `.csv` pair is one session (dedupe by stem). Empty
  cells and all-empty rows are missing. DLC-3D uses 0 for missing.
- **Identity.** Named individuals are stable. A single animal gives n = 1.
- **Reduction.** The suite is policy-neutral: positions must lie inside the animal's
  keypoint box, and the speed series must correlate at lag 0 (r > 0.5).
- **Gate G-H5 (for `.h5`).** The EPM `.h5` decodes to the same table as the suite's
  oracle (`pd.read_hdf`, PyTables in dev only) and as the EPM `.csv` mirror, and the
  `_el.h5` sample parses.

### P2 SLEAP analysis HDF5 (cases `sleap_named_tracks`, `sleap_no_tracks`)

- **Detect.** Root datasets `tracks` (a Dataset), `track_names`, `node_names`,
  `track_occupancy`. A file without the `.analysis` suffix is still detected.
- **Layout.** GUI exports carry no attributes at all (pinned). Use `dims` if present
  (sleap-io); otherwise assume `(n_tracks, 2, n_nodes, n_frames)` and check
  `track_occupancy (n_frames, n_tracks)` uint8 and `tracks.shape[-1] == n_frames`. If
  it is still ambiguous, raise `FORMAT_AMBIGUOUS` and never guess. Pinned: Aeon
  `tracks (3,2,1,601)`; EPM `(1,2,6,18485)`.
- **Names.** Bytes, decoded (`AEON3B_NTP`, …). A no-track project has an empty
  float64 `(0,)` `track_names` (not `track_0…`) and still one slot. A single-node
  skeleton has empty `(0,)` float64 `edge_inds` and `edge_names` instead of `(0,2)`.
- **Missing.** NaN. Occupancy is 0 exactly where the coordinates are NaN (Aeon: 1,575
  of 1,803 slots occupied, 456 NaN values).
- **From the user.** fps and frame size (neither recorded), node, cutoff.
- **Identity.** Named is stable. Empty names and one slot give n = 1 (the suite
  asserts nothing). Synthetic `track_0…` (sleap-io writer only) defaults to
  "identity-free" in the dialog.
- **Other.** CSV layouts: parse by column name; `track` is empty for untracked data;
  `instance.score` is a literal `nan`; frames with no instances are omitted. `.slp` is
  recognise-only ("Export Analysis HDF5").

### P3 Ctrax raw `.mat`, `trx.mat`, FlyTracker (case `ctrax_raw_mat`)

- **Ctrax raw (not `trx.mat`).** Nine variables: `ntargets, maj_ax, angle, min_ax,
  x_pos, y_pos, startframe, identity, timestamps`; no `trx`. Detections are
  concatenated frame by frame, so frame *t* occupies the next `ntargets[t]` rows
  (cumulative sum). Pinned: 12,033 frames, 159,765 detections, 9 to 17 targets per
  frame, **193 identities (0…192), which are fragments**. fps comes from
  `timestamps`: (n−1)/Δt = 25.0.
- **y is measured from the bottom:** `y' = H − y`. H is not in the file, so it comes
  from the user or the video (2160 in the sample). Without the flip the median offset
  to AnimalTA is 333 px; with it, about 1 px.
- **Policy.** Keep every identity as a slot (193 animals): `has_stable_identities=False`
  (the suite requires it) and `track_wo_identities=True`. `top_n` is opt-in.
- **`trx.mat`.** Struct `trx` (v5 through `whosmat`, v7.3 through h5py); 1-based
  frames with `off = 1 − firstframe`; `a` and `b` are quarter axes; `_mm` twins.
  **G-JAABA:** no sample is pinned yet, so until one is, it is recognise-only. The
  `trx` sniff must not claim Ctrax raw files, and vice versa.
- **FlyTracker `-track.mat`.** No public output, so recognise-only, pointing at the
  `-JAABA/` export (a `trx.mat`).

### P4 ToxTrac (case `toxtrac_realspace`)

- **Detect.** `Tracking_RealSpace_<k>.txt` whose header is exactly
  `Time (sec)⇥Arena⇥Track⇥Pos. X (mm)⇥Pos. Y (mm)⇥Label` (6 columns, tab; arenas from
  1). Siblings: `Stats_<k>.txt` (name line and value line alternating) and the pixel
  twin `Tracking_<k−1>.txt` (headerless, 6 columns, arenas from 0).
- **From the files, no typing.** fps (`Video FrameRate` 29.8568), frame size (`Video
  Resolution [1920 x 1080]`), `Analysed Video Frames` 18,034 (the suite allows ±12).
- **Traps.** Lost frames are **absent rows** (26 gaps of up to 66 frames), so rebuild
  a full grid (frame = round(Δt/step)) that **starts at the first row**
  (n_frames ≈ 18,034 ± 12), not at absolute frame 0. Time starts at 12.2585 s (the
  analysis start); record that offset through `tracking_intervals`. `Label` is a
  status code (0 predicted, 1 confirmed, 2 occluded, 3 mirror); 43 of 17,811 rows are
  predicted, and the suite requires every row to land, so the default keeps them,
  with an opt-in `predicted_as_missing`. `FrozenEvents` misspells `Time Lenght`.
  Per-arena files use arena-relative coordinates. The project-level
  `Tracking_RealSpace.txt` (a common virtual arena) was not inspected, so it is not
  claimed.
- **Units.** mm. The pixel twin gives true pixels when present: real = pixel +
  (494,144) at a scale of exactly 1.0, i.e. uncalibrated, so the scale rule applies.
  With no twin, native-unit mode applies. One session per arena. The suite's check is
  unit-neutral (axis directions only).

### P5 Anipose pose-3d CSV (quirk tests today; a Session-level case is added with the reader)

- **Detect.** Columns `<kp>_x/_y/_z/_error/_ncams/_score`, `M_00…M_22`, `center_0…2`,
  `fnum`. Pinned: 246 × 49, six keypoints (`l-base`, `l-edge`, `l-middle`, `r-base`,
  `r-edge`, `r-middle`).
- **Traps.** Hyphens in names mean suffixes are split **from the right**. `fnum` is
  0…245. Missing is NaN in x, y and z together (4,812 NaN).
- **From the user.** fps (200 in the sample, not stored) and the plane (default x,y).
  Board units (mm) mean native-unit mode with no pixel frame. z is kept in
  `Session.keypoints` (D = 3).

### P6 TRex `.npz` (cases `trex_new_export`, `trex_old_export`)

- **Detect.** npz members include `frame, missing, X, Y`; exclude `posture`,
  `tracklet_images`, `visual_field`. Names are `…_id<N>.npz` (new) and `…_fish<N>.npz`
  (old), so sort **numerically**. TRex writes loose per-individual `.npz` files under
  `data/`. The GIN `TRex_five-locusts.zip` is only how that sample is packaged: the
  suite extracts it into its temporary folder before testing, and the reader never
  extracts anything.
- **New export (5 locusts, 2,845 frames).** Self-describing: `id`, `frame_rate` (30),
  `cm_per_pixel` (0.02619), `video_size` (4096 × 3000), `detection_p`, seven pose
  keypoints in pixels. X/Y are in cm.
- **Old export (13 files).** No metadata arrays; tables named `frame_segments`,
  `segment_vxys`, `segment_length`. **X/Y are pixel-scale** (up to about 3,700)
  although labelled cm, so treat them as pixels and flag it. fps comes from `time`
  against `frame` (25.0); frame size from the user or the video.
- **Missing.** **`+inf` marks untracked frames in every float array, and there is no
  NaN anywhere. Derive missingness from `isfinite`, not the `missing` flag**, which
  disagrees in 3 of 13 old files. File lengths differ (12,013 to 12,024 frames, for a
  12,033-frame video): `n_frames` is the union of the file frames (12,024) and is
  **not** padded to the video length from a video probe.
- **CSV export.** Units in the headers, no identity, X but no Y in the sample, so it
  is recognised and identity-free.
- **Identity.** Per-individual files are stable (the suite asserts True).

### P7 AnimalTA CSV (case `animalta_fixed_csv`)

- **Detect.** `;`-delimited; first line `Frame;Time;X_Arena…`. A default comma read
  gives one column.
- **Fixed layout.** Pinned: 12,033 × 26 (Frame, Time, `X_Arena0_Ind<i>` and `Y_…` for
  12 individuals). Arena and individual numbers are 0-based. The literal `NA` is
  missing (5,242 of them).
- **fps.** `Time` is rounded to 0.01 s, so take fps from the whole span,
  (n−1)/(t_last−t_first) = 25.0 here, never from per-step differences or `frame/fps`.
- **From the user.** Frame size (not recorded).
- **Other layouts.** Variable (`Frame;Time;Arena;Ind;X;Y`) is verified only by the
  movement-data samples, which the suite lacks, so they are added. Detailed per-target
  files (unit not recorded) are recognise-only. Multi-arena gives one session per
  arena.

**Backlog facts already verified.** FastTrack: 23 columns, real order Head, Tail,
Body, spelling `Excentricity`, 0-based, scientific notation, SQLite twin
`tracking.db`. OCTRON: `key: value` preamble, extra `frame_counter`, one file has a
blank line after the preamble (find the header line rather than skipping 6 lines),
column sets differ per file. TrackMate CSV: 4 header rows, track id 0 is valid. WCON:
ids are strings, and `units` can be inconsistent in tests. Tierpsy: the id column is
`worm_index_joined` in `_skeletons` but `worm_index` in `_featuresN`.

## 7. Design gates

- **G-H5** (DLC `.h5` decoder). (a) h5py reads the compound `table` dataset and a
  restricted unpickler decodes the pickled column labels: all globals denied except
  numpy array reconstruction, with a size cap per attribute. (b) Otherwise fall back
  to an optional extra `[hdf]` with `tables`, behind pp3's pickle-consent gate. The
  scan itself never unpickles. The result is recorded as a DECISIONS entry.
- **G-meta.** Check whether DLC `*_meta.pickle` carries fps and frame size on the
  CatalystNeuro sample; if so, pre-fill both through the same restricted unpickler.
- **G-JAABA.** Fetch the JAABA sample. If it cannot be obtained, `trx.mat` stays
  recognise-only.
- **G-fragments.** Confirm the fragment default (section 4.8) on the Ctrax raw data.
- **G-units.** Native-unit mode (section 4.9), in its own PR.

## 8. Fixtures and licences

The repository is MIT. The suite's `fixtures_manifest.json` is the source of truth:
26 files, 70.2 MB, each with URL, sha256, bytes, licence and attribution. Files
download on first use into a cache directory (`T2D_FIXTURE_DIR`, default
`%LOCALAPPDATA%\track2data\fixture_cache` on Windows, outside any OneDrive-synced
worktree). A hash mismatch **fails** the test (upstream drift); a network failure
**skips** it; `T2D_FIXTURES_OFFLINE=1` never touches the network. The manifest is
extended, not forked.

- **Never committed:** everything in the cache (CC BY 4.0 and CC0 GIN files, GPL-3.0
  MoveR files, ToxTrac data with unstated terms, and the rest).
- **Committed:** structure clones for CI (`scripts/clone_sample_structure.py`: same
  key names, dtypes, header text and shapes, cropped to a few frames, generated
  values) and `NOTICE.md` with attribution. No third-party data is redistributed.
- **Rules.** "The sample wins" over a synthetic fixture. Every shipped reader declares
  `verification`, and a consistency test checks it has a fixture of that level.
  Container formats need `real_sample`. The suite's cross-tracker agreement tests
  (TRex and AnimalTA about 9 px apart; Ctrax about 1 px after the y-flip) double as the
  cross-reader regression.

Extras beyond the manifest, to be added with their reader: the maDLC
`ant_video_5DLC…_el.h5` (280 KB, Apache-2.0); the ToxTrac pixel twin
`Tracking_0.txt`, `Tracking_1.txt` and `Tracking_RealSpace_2.txt`; the movement-data
AnimalTA samples (9 files, about 10 KB, CC BY 4.0); and sleap's legacy
`small_robot…analysis.h5` and `minimal_instance…analysis.csv` (BSD-3-Clause-Clear).
Sizes not yet known: the EPM `.csv` mirror (needed for G-H5), the JAABA sample, the
CatalystNeuro `*_meta.pickle`, and MoveR's idtracker.ai and TrackR outputs.

## 9. Verification

- **Default run.** `py -3.14 -m pytest tests/ -m "not r_parity and not network and
  not corpus_local and not real_sample" -q`, plus `ruff` and `mypy`. The coverage
  floor of 85 % includes `app/` and `ui/`, so all confirm logic sits in the Qt-free
  `ConfirmDraft` and the dialog stays a thin view.
- **Real-sample suite (local, online).** `py -3.14 -m pytest tests/real_samples -m
  quirk` (42 pass), then `-m contract` (cases flip as readers land), run from the
  worktree root.
- **Legacy.** Existing idtracker.ai projects load and give byte-identical metrics.
- **Corpus (`corpus_local`).** The 70-session root yields one group, HIGH, 70
  sessions, in under 2 s.
- **GUI.** The `run-track2data` driver gains `scan`, `confirm` and `shot-dialog`.
  Manually, build a mixed root from cached samples (DLC, SLEAP, TRex, AnimalTA, an
  idtracker.ai session), drop it on the Sessions screen, confirm one group, run the
  pipeline, then save and reopen the project and check the Reader column survives.
- **Tier 0 pass criteria.** A junk folder gives an inline "nothing recognised" state,
  not a modal. Cancel stops a scan in under 1 s. A missing persisted reader fails
  loudly (`READER_NOT_AVAILABLE`) without falling back. Reading never modifies the
  input folder (the suite's tree-hash test).

## 10. Open decisions (defaults apply unless changed)

1. **Tier order.** Default: strict priority. Option: swap Tiers 3 and 4 so the cheap
   TRex and AnimalTA readers ship before the native-unit PR.
2. **Fragment default** (keep all, identity-free, `top_n` opt-in) is confirmed or
   changed at G-fragments, with data in hand.
3. **Mixed native units in one project:** convert to the project unit when the factor
   is known, else block.
4. **`Session.source_files`** is added with the first multi-file reader.
5. **Dialog versus inline panel.** Dialog by default.
6. **ToxTrac `Label` 0 rows** are kept by default, with an opt-in mask.
7. **CI for the real-sample suite.** Excluded from PR CI; an optional manual or
   nightly job caches the fixtures. `tables` is a dev-only oracle dependency; the
   production decoder is decided at G-H5.
8. **After pp3 lands on `main`:** rewrite `docs/INTEROPERABILITY.md` (the "DLC / SLEAP
   input: out of scope" row) and add these documents to the mkdocs site.
