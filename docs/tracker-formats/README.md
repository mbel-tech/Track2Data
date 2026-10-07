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
| 1 | DeepLabCut CSV, then H5 (Lightning Pose, EKS, maDLC) | 1 | planned | `dlc_single_animal_h5`, `dlc_two_mice_csv`, `lightning_pose_eks_csv` |
| 2 | SLEAP analysis HDF5 | 1 | planned | `sleap_named_tracks`, `sleap_no_tracks` |
| 3 | Ctrax raw `.mat`, `trx.mat`, FlyTracker | 2 | planned | `ctrax_raw_mat` |
| 4 | ToxTrac `Tracking_RealSpace.txt` | 3 | planned | `toxtrac_realspace` |
| 5 | Anipose pose-3d CSV (and DLC-3D) | 3 | planned | quirk tests only |
| 6 | TRex `.npz` | 4 | planned | `trex_new_export`, `trex_old_export` |
| 7 | AnimalTA CSV | 4 | planned | `animalta_fixed_csv` |

Tier 0 (the scan, detect, confirm and persist foundation, including
idtracker.ai folder-of-folders) comes first. Everything else, such as FastTrack,
OCTRON, WCON and the fragment-ID formats, is backlog ordered by ease.
