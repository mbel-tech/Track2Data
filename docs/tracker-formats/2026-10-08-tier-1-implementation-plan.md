# Tier 1 implementation plan: pose trackers

Tier 1 turns DeepLabCut (53.7 % of recent citations) and SLEAP (a further 11.3 %) into readers.
Each step is its own pull request, strict test-first, with the suite's contract cases
(`tests/real_samples/`) as the acceptance harness: a case flips from XFAIL to PASS when its reader
lands.

| PR | Branch | What | Gate |
|---|---|---|---|
| T1-1 | `feat/pose-core` | Shared pose building blocks, `Session.keypoints`, keypoint choice in the export | none |
| T1-2 | `feat/reader-dlc-csv` | DeepLabCut CSV (single and multi-animal) and Lightning Pose / EKS CSV | T1-1 |
| T1-3 | `feat/reader-dlc-h5` | DeepLabCut `.h5` | G-H5 spike |
| T1-4 | `feat/reader-sleap-analysis` | SLEAP analysis HDF5 | T1-1 |

## PR T1-1: the pose core (built)

**What exists now.**

- `core/models.py`: `KeypointSelection` (the keypoint, the cutoff, who chose it, its coverage, the
  plane) and `KeypointData` (xy `(F, A, K, 2|3)` float32, names, optional likelihood, edges), and
  `Session.keypoints` defaulting to `None`. Consistency is validated at construction.
- `readers/assemble.py`: `to_nan` (infinity and named sentinels to NaN, on a copy);
  `reduce_keypoints` (the named keypoint, else best coverage after the cutoff with ties going to
  the higher mean likelihood and then the first; a missing likelihood counts as unreliable; a
  likelihood equal to the cutoff is kept; the chosen plane for 3-D data; `POSE_NO_POSITIONS` when
  nothing survives; `READER_OPTION_INVALID` listing the choices for an unknown keypoint);
  `build_keypoints`/`skeleton_fits` (float32 copy, 256 MB budget, can be declined);
  `assemble_session` (checks fps, frame size, shape, label count, interval total and skeleton
  agreement; `READER_OUTPUT_INVALID` with the field as `subject`).
- Export: `SessionProvenance.keypoint_selection`, an "Animal position" row in the README's source
  section, and the same facts in `manifest.json`.
- Cache schema 1 to 2: entries written before the new `Session` field would unpickle without it.

**Deliberately not here.**

- `dense_from_long` / `dense_from_segments` and `classify_identity_regime`: no Tier 1 reader needs
  them (DeepLabCut and SLEAP are already dense, by frame). They arrive with the first reader that
  does (Ctrax / TRex, Tier 2 and 4), so they are written against a real file.
- `probe_video` (PyAV, to prefill fps and frame size): optional, arrives with the dialog work in
  T1-2 if the metadata pickle (G-meta) does not already answer it.
- A long-form export of the skeleton: stored only, as decided.

**Decisions recorded.**

- The chosen position is always a real keypoint, never a centroid of the visible ones (a centroid
  jumps whenever one keypoint drops out, and that reads as speed).
- Keypoint likelihood never goes into `id_probabilities` (that is identity confidence).
- The chosen keypoint is judged on coverage after the cutoff, so a keypoint that is always
  present but unreliable loses to one that is reliable.
