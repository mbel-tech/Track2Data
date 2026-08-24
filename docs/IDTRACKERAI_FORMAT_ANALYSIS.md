# idtracker.ai Format Analysis, Drift & Normalisation Strategy

**Status:** Historical. Written as Draft v0.2 ("analysis with real-data
evidence; no code changes yet") before the reader rewrite this document
motivated. Most of §2/§3's gap table has since been implemented across a
multi-commit branch (h5/parquet-priority format fallback; fps/width/
height/version fallback to session.json; body_length/areas capture;
signed roi_list → ZoneSet; session.json fields including
number_of_error_frames/exclusive_rois/length_calibrations/segmentation
params/velocity_threshold; the idtrackerai.log parser rewrite;
preprocessing/ROI_mask.png+background.png+list_of_fragments.json+
list_of_blobs.pickle readers; new D-6..D-9 diagnostics). This document is
kept for its real-corpus evidence (§1, §9) rather than as a current
gap-status reference -- treat any "❌ missing" row in §3 as unverified
against the current codebase, not as still-true. Three factual errors
from the original draft are corrected in place below (§1.4 x2, §3)
rather than left standing.

**Authoritative references:**
- [`../idtrackerai_output_structure.md`](../idtrackerai_output_structure.md) — official idtracker.ai 6.0.14 docs (superseded by `docs_from_idtracker.ai/output_structure_idtrackerai.md`, 6.0.15a0, for anything not cited by line number below)
- `Checked sessions GOT/` — 70 real session folders (idtracker.ai 6.0.13)

**Audience:** Engineers and reviewers before any reader rewrite
**Companion docs:** [`./TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md), [`./ENGINE_DESIGN.md`](./ENGINE_DESIGN.md)

> All "what the format contains" statements cite either
> `reference:LINE`, `file:LINE`, or `sample:<session>`.
> Anything not citable is flagged "unverified".

---

## 1. Output map: official vs. real

### 1.1 Official session-folder layout (`reference:6-34`)

```
session_[SESSION_NAME]/
├─ accumulation/             # NN weights (idmatcher.ai consumer)
├─ crossings_detector/       # crossing-classifier weights
├─ bounding_box_images/      # only with data_policy="all"
├─ identification_images/    # one image per animal per frame
├─ preprocessing/            # blobs/fragments + ROI_mask.png + background.png
├─ trajectories/             # h5/npy/parquet/pickle/csv/csv_tidy variants
├─ session.json              # human-readable JSON metadata
└─ idtrackerai.log
```

### 1.2 Real-data layout from the corpus

70 sessions, idtracker.ai **6.0.13**, all from the same processing
pipeline. The layout differs from the reference in two systematic
ways:

**Always present** (every session):
```
session_trial*_Segment*/
├─ accumulation/                   # identifier_cnn.model.pt + contrastive_checkpoint.pt + model_params.json
├─ identification_images/          # id_images_{0..29}.h5  (~30 files / 14 911 frames)
├─ preprocessing/                  # ROI_mask.png + background.png + list_of_blobs.pickle + list_of_fragments.json + list_of_global_fragments.json
├─ trajectories/
│  ├─ trajectories.h5
│  ├─ trajectories.npy             # pickled dict, ALL 17 reference keys present
│  └─ trajectories_csv/
│     ├─ trajectories.csv
│     ├─ id_probabilities.csv
│     ├─ areas.csv
│     ├─ attributes.json           # 14 keys (subset of the trajectory dict)
│     ├─ <session>_bboxes.csv             ← NOT in reference; custom output
│     └─ <session>_bboxes_summary.json    ← NOT in reference; custom output
├─ session.json                    # 40+ keys (much richer than reference suggests)
├─ idtrackerai.log
└─ inconsistent_frames.csv         ← NOT in reference; produced by post-processing
```

**Absent** in every session: `crossings_detector/`, `bounding_box_images/`.
The log explicitly states the crossings_detector dir "has been
removed" — a `data_policy` choice.

**Conditionally present**: `matching_results/<other_session_id>/`
(idmatcher.ai output; observed in 1/4 sampled).

**OS-sync noise**: macOS resource-fork files `._*` appear at every
level due to OneDrive cross-platform sync. Must be ignored.

### 1.3 `session.json` real schema (sample: trial10_Segment1)

Beyond the keys the reference doc implies, the real
`session.json` carries:

| Key | Notes |
|---|---|
| `version`, `width`, `height`, `frames_per_second`, `number_of_frames`, `number_of_animals` | Core media metadata. |
| `video_paths` | Windows backslash paths. Often unreachable from a different machine. |
| `name`, `session_folder` | Original folder name + processing-machine path. |
| `tracking_intervals` | `[[start, end], ...]` frame ranges. |
| `roi_list` | List of strings `"+ Polygon [...]"` / `"- Polygon [...]"` — additive / subtractive polygons. |
| `intensity_ths`, `area_ths` | Preprocessing parameters; **`area_ths` may contain the literal `Infinity`** (not strict JSON). |
| `identities_labels`, `identities_groups`, `identities_colors`, `setup_points` | Validator output. Often default (numeric labels, empty groups). |
| `silhouette_score`, `fragment_connectivity`, `estimated_accuracy` | Quality metrics. |
| `last_validated` | ISO-8601 timestamp from validator. |
| `timers` | Per-stage timings: name, start_time, finish_time. |
| `presence_intervals` | Per-individual presence ranges. |
| `data_policy`, `id_image_size`, `frames_per_episode`, ... | Processing parameters. |
| `trajectories_formats` | List of formats that were written, e.g. `["h5","npy","csv"]`. |

The reference doc does not enumerate these; this list is from
inspecting the actual file.

### 1.4 Trajectory dict — actual vs. documented

Loading `trajectories.npy` from a real session (`sample:trial10_Segment1`)
returns a dict with **all 17 keys** listed in the reference
(`reference:63-96`).

| Reference says | Reality (sample) |
|---|---|
| `id_probabilities` shape `(N_frames, N_animals)` (`reference:65`) | **`(N_frames, N_animals, 1)`** — extra trailing axis |
| `areas`: "dict containing mean/median/sd per individual" (`reference:83`) | **Corrected 2026-08** (was originally flagged here as a reference deviation; it is not one): `{'mean': ndarray(n_animals,), 'median': ndarray(n_animals,), 'std': ndarray(n_animals,)}` is exactly a dict of three per-individual stat arrays, matching `output_structure_idtrackerai.md:87` ("mean, median and standard deviation of the blobs area for each individual") precisely. |
| `length_unit`: px↔real-distance ratio | **Corrected 2026-08** (was originally reported as `None` in *all* real data from a single sample; that was an overgeneralisation): `None` in `trial10_Segment1` specifically -- the validator's Length-Calibration tool was not used for that session -- but a corpus-wide check found **26 of 70 sessions have a valid `length_unit`** from `length_calibrations` entries. See R11 below, also corrected. |
| `body_length`: mean diagonal of blob bounding boxes | **150.15** px in this sample, but `length_unit=None`, so it cannot be converted to cm |
| `video_paths` | macOS absolute paths under `/Volumes/Expansion/...` — unreachable from Windows |
| `version` | `"6.0.13"` — string |

### 1.5 Custom outputs not in the reference

| File | Schema (real sample) | Status |
|---|---|---|
| `inconsistent_frames.csv` | Single column, no header, integer frame indices (74 rows in trial10_Segment1) | Universal (all 70 sessions) |
| `<session>_bboxes.csv` | Columns: `session_id, frame, identity, body_length_px, body_length_cm, is_individual, is_crossing, identity_certainty, area_px` (42 898 rows) | Custom post-processing; per-(frame, identity) rows |
| `<session>_bboxes_summary.json` | `{session_id, status, reason, n_frames_in_blobs, n_rows_written, metadata, identity_stats, exclusion_counts}` | Custom; per-session bbox QC |
| `matching_results/<other_session>/csv/direct_matches.csv` + `.../png/direct_matches.png` | idmatcher.ai cross-session identity matches | Optional |

These are **not** part of idtracker.ai per se — they come from the
user's own post-processing scripts. The reader should detect them
opportunistically and surface them as optional companion data.

---

## 2. Current reader

### 2.1 Behaviour matrix (cited to source)

| Aspect | Current | Reference | Real data |
|---|---|---|---|
| Detection | requires `video_object.npy` + `trajectories/` (`idtrackerai_v5.py:88-95`) | Not in reference | `video_object.npy` **never present** in 70/70 sessions |
| Primary trajectory file | `trajectories_wo_gaps.npy` then `trajectories.npy` (`:126-132`) | Only `trajectories.npy` / `.h5` / etc. (`reference:23-30`) | `trajectories_wo_gaps.npy` **never present** in 70/70 sessions |
| `np.load` flag | `allow_pickle=False` for trajectory (`:150`) | `allow_pickle=True` required (`reference:158`) | Trajectory **is a pickled dict** — strict load crashes |
| Session metadata | `video_object.npy` first, fallback `session_progress.json` (`:255-263`) | Only `session.json` documented (`reference:31`) | Only `session.json` exists |
| FPS / W / H source | tries `fps/frames_per_second`, `height/original_height`, ... (`:216-218`) | Keys named `frames_per_second`, `height`, `width` (`reference:69-75`) | Real file uses `frames_per_second`, `height`, `width` |
| Identity-stability | 0.50 non-NaN heuristic (`:266-270`) | Reference exposes authoritative `fraction_identified` | Real file ships `fraction_identified=0.822` — should be used directly |
| Quality / probability fields | not captured | 7 quality keys documented | All present in real files |
| ROI mask / background image | not captured | `preprocessing/` documented | Present in 70/70 |
| `length_unit` calibration | not captured | Documented (`reference:91`) | Present but `None` in sample (user hadn't calibrated) |
| Custom artefacts (bboxes, inconsistent_frames) | not detected | Not in reference | Present in 70/70 |

### 2.2 Test fixture (`tests/conftest.py:89-97`)

The synthetic `_build_video_object()` writes keys (`fps`,
`frame_number`, `paths_to_video_files`) that match **neither** the
reference doc **nor** any real session. The 75-test green suite
validates the reader against its own fictional contract.

### 2.3 Net consequence

The current reader **cannot read any of the 70 real session
folders**. It would fail at `detect()` because `video_object.npy`
is missing.

---

## 3. Gap analysis

Legend: ✅ supported · 🟡 partial / wrong · ❌ missing · ⚠ risky

| Item | Status | Evidence |
|---|---|---|
| HDF5 trajectories.h5 | ❌ missing | reader has no h5 path; `h5py` not in deps |
| NPY trajectories.npy (pickled dict) | 🟡 wrong assumption | `allow_pickle=False` → crash on real file |
| Parquet trajectories.parquet | ❌ missing | not opted-in by any sample; user-configurable per `trajectories_formats` |
| Pickle trajectories.pickle | ❌ missing | same |
| CSV bundle (trajectories_csv/) | ❌ missing | universal in real data, supported alongside h5/npy |
| Tidy CSV trajectories_tidy.csv | ❌ missing | format option; not in sample but officially supported |
| Legacy v4/v5 layout | 🟡 implemented but unused | none of the 70 real sessions are legacy; future / external users may have these |
| `session.json` parsing | 🟡 partial | only used for fallback FPS/size; ignores 40+ other keys |
| JSON literal `Infinity` | 🟡 handling built, premise wrong | real `session.json` contains `Infinity` (e.g. `area_ths: [668.0, Infinity]`). **Corrected 2026-08**: the original claim that "stdlib `json.loads` rejects" this is false -- verified directly, `json.loads('{"a": Infinity}')` returns `{'a': inf}` without any hook. `session_json.py`'s `parse_constant` handling is harmless but was built on an incorrect premise; it logs `IDT_JSON_NONSTRICT` on every real session for what is, by default, not an error at all. |
| `idtrackerai.log` | ❌ missing | universal; encodes processing timing + warnings |
| `preprocessing/ROI_mask.png` | ❌ missing | universal; perfect zone-editor seed |
| `preprocessing/background.png` | ❌ missing | universal; useful preview fallback |
| `preprocessing/list_of_blobs.pickle` | ❌ ignored (intended for v1) | large, pickle, opt-in only |
| `preprocessing/list_of_fragments.json` | ❌ missing | per-fragment quality |
| `accumulation/` | ❌ ignored (intended) | NN weights for idmatcher.ai |
| `crossings_detector/` | ❌ ignored (intended) | optional anyway |
| `identification_images/id_images_*.h5` | ❌ ignored (v1.1 feature) | useful for per-fish visual previews; F7 |
| `bounding_box_images/` | ❌ missing | optional via data_policy |
| `id_probabilities` shape (N,M,1) | ❌ no normalisation | would crash any consumer expecting (N,M) |
| `body_length` reliability warning | ❌ missing | reference doc explicitly warns (`reference:100`) |
| `length_unit = None` handling | ❌ missing | universal in this corpus; will be common |
| `length_unit > 0` auto-calibration | ❌ missing | should populate `CalibrationConfig.px_per_cm` |
| `identities_labels` / `groups` import | ❌ missing | useful for Stage-5 metadata seeding |
| `setup_points` import | ❌ missing | validator-defined reference points |
| `roi_list` parsing | ❌ missing | useful for Stage-4 zone seeding (signed polygons) |
| `tracking_intervals` | ❌ missing | important — frames outside intervals are not valid |
| `timers` extraction | ❌ missing | feeds diagnostics dashboard |
| `inconsistent_frames.csv` | ❌ missing | universal in corpus; should mark these frames as suspect |
| `<session>_bboxes.csv` | ❌ missing | per-(frame, identity) bounding-box body length — superior to `body_length` mean |
| `<session>_bboxes_summary.json` | ❌ missing | per-session bbox QC |
| `matching_results/` | ❌ missing | cross-session identity matches (idmatcher.ai); optional |
| macOS `._*` resource forks | ⚠ silently fail | OneDrive sync artefact; reader must filter |
| Windows / macOS path mismatch | ⚠ silently fail | `video_paths` is from the processing machine, not the analysis one |
| pickle / NPY security | ⚠ not gated | unrestricted `allow_pickle=True` is a code-execution vector |
| Test fixtures vs. reality | ❌ wrong | 75 tests pinned to a fiction |
| Golden CSV vs. reality | ❌ wrong | needs rebaseline |

---

## 4. Cross-version normalisation strategy

The keystone idea: **one internal representation, many input
shapes**. Every supported flavour of idtracker.ai output flows
through a small normaliser that returns a `Session`. Downstream
code never branches on version or format.

```
   ┌────────────┐    ┌──────────────────────────┐    ┌──────────┐
   │ Session    │    │  Format-specific loader  │    │ Session  │
   │ folder on  │───▶│  (h5 / npy / parquet /   │───▶│ +        │
   │ disk       │    │   csv / tidy / pickle /  │    │ optional │
   └────────────┘    │   legacy v5)             │    │ extras   │
                     └──────────────┬───────────┘    └──────────┘
                                    ▼
                     ┌──────────────────────────┐
                     │  TrajectoryPayload       │  <-- intermediate dict
                     │  (single normalised dict │      with the 17 keys
                     │   shape per reference)   │      + format metadata
                     └──────────────┬───────────┘
                                    ▼
                     ┌──────────────────────────┐
                     │  Normaliser              │  <-- reshapes, fills
                     │  • id_prob → (N, M)      │      defaults, attaches
                     │  • length_unit gating    │      session.json /
                     │  • areas dict canonical  │      log / preprocessing
                     │  • video_paths Path-ify  │      / custom artefacts
                     └──────────────┬───────────┘
                                    ▼
                     ┌──────────────────────────┐
                     │  Session (Pydantic)      │
                     └──────────────────────────┘
```

### 4.1 Normalisation rules (idempotent, version-agnostic)

| Field | Rule |
|---|---|
| `trajectories` | accept `(N, M, 2)`; if `(M, N, 2)` and `N==session.json.number_of_frames`, transpose; else reject |
| `id_probabilities` | accept `(N, M)` or `(N, M, 1)`; squeeze trailing axis; missing → set to `None`, derive coverage from NaN mask |
| `frames_per_second` | trajectory dict first, then `session.json.frames_per_second`; require > 0 |
| `width`, `height` | trajectory dict first, then `session.json`; require > 0 |
| `video_paths` | parse each, store as `Path`; do **not** assume reachable; surface a warning if no path exists locally |
| `body_length` | always loaded; **always** flagged `body_length_reliable=False` per `reference:100` until user acknowledges |
| `length_unit` | if `> 0`, populate `CalibrationConfig.px_per_cm`; if `None` or `<= 0`, leave calibration empty + warn |
| `identities_labels` / `_groups` | accept list-of-strings; default to `["1", "2", ...]` when empty; do not auto-overwrite metadata mapping unless user opts in |
| `setup_points` | accept any dict; persist verbatim in `Session.metadata` |
| `roi_list` (from session.json) | parse the `"+ Polygon [...]" / "- Polygon [...]"` strings into structured `Polygon(vertices, sign)` for the zone editor |
| `tracking_intervals` | `list[tuple[int, int]]`; frames outside → mark as out-of-range |
| `version` | parse as string; classify (`legacy_v4`, `legacy_v5`, `6.x`, `unknown`) |
| `estimated_accuracy`, `fraction_identified`, `silhouette_score`, `fragment_connectivity`, `areas` | loaded as-is into `Session.quality` |
| `inconsistent_frames.csv` | if present, load as `Session.inconsistent_frames: set[int]`; otherwise `None` |
| `<session>_bboxes.csv` | if present, load as `Session.bbox_table: pd.DataFrame` indexed by (frame, identity); else `None` |
| `<session>_bboxes_summary.json` | if present, load as `Session.bbox_summary: dict` |
| `matching_results/` | if present, list the matched sessions in `Session.matching_results: list[str]`; deeper data deferred to v1.1 |
| Resource-fork `._*` files | filtered out by `iter_session_files()` at the discovery layer |
| `session.json` `Infinity` | use `json.loads(..., parse_constant=_safe_inf)`; replace with `float('inf')` |
| `session.json` `NaN` | same hook → `float('nan')` |
| `idtrackerai.log` | tail-read to extract: last status line (Success / Error), per-stage durations, WARN/ERROR lines; surface as `Session.tracking_log` summary |

### 4.2 Detection: file-tree probing, not file presence

```python
def detect(folder) -> ReaderHit | None:
    if not (folder / "trajectories").is_dir():
        # legacy: trajectories.npy + video_object.npy at root
        return _detect_legacy_v5(folder)

    candidates = [
        ("h5",       folder / "trajectories" / "trajectories.h5"),
        ("parquet",  folder / "trajectories" / "trajectories.parquet"),
        ("npy",      folder / "trajectories" / "trajectories.npy"),
        ("pickle",   folder / "trajectories" / "trajectories.pickle"),
        ("csv_tidy", folder / "trajectories" / "trajectories_tidy.csv"),
        ("csv",      folder / "trajectories" / "trajectories_csv"),
    ]
    found = [(name, p) for name, p in candidates if p.exists()]
    if not found:
        return None
    return ReaderHit(format=found[0][0], path=found[0][1], all_present=found)
```

Priority order: **h5 → parquet → npy → pickle → csv_tidy → csv
bundle → legacy**. Rationale: h5 is binary, cross-platform, and
secure; parquet next; npy/pickle last for safety.

### 4.3 Version classification

```python
def classify(version: str | None) -> Literal["legacy_v4", "legacy_v5",
                                              "v6", "unknown"]:
    if version is None: return "legacy_v5" if has_video_object_npy else "unknown"
    if version.startswith("6."): return "v6"
    if version.startswith("5."): return "legacy_v5"
    if version.startswith("4."): return "legacy_v4"
    return "unknown"
```

Classification controls **only** the format probing — the
normalised `Session` is identical regardless.

### 4.4 Resilience checklist

The reader must survive every one of these without crashing:

- A session with no `trajectories/` folder → partial-session warning,
  load only `session.json` + `idtrackerai.log`.
- A session whose `session.json` contains `Infinity` / `NaN`.
- A trajectory dict missing **any** subset of the 17 keys.
- `id_probabilities` shape `(N, M)` *or* `(N, M, 1)`.
- `length_unit` = `None`, `0`, negative, or `inf`.
- `video_paths` pointing at an unreachable filesystem.
- Resource-fork `._*` files at every level.
- A future idtracker.ai version writing a new key — unknown keys
  are preserved verbatim in `Session.metadata["raw"]`.
- A 6.x release **renaming** an existing key — handled by an
  alias map in `idtrackerai/key_aliases.py` (e.g. if 6.1 renames
  `fragment_connectivity` to `connectivity`, add the alias there).

---

## 5. Feature proposals (informed by real data)

| # | Feature | Source files | UI surface |
|---|---|---|---|
| F1 | **Import-completeness report** (per file present/absent + size + sha256) | file tree | Stage 2 row drawer |
| F2 | **Tracking-quality dashboard** (`estimated_accuracy`, `fraction_identified`, `silhouette_score`, `fragment_connectivity`, `id_probabilities ≥ 0.9 %`, `areas`) | trajectory dict + session.json | Stage 7 Diagnostics |
| F3 | **Session metadata pane** (`name`, `tracking_intervals`, `roi_list`, `last_validated`, `timers`, `data_policy`, `frames_per_episode`) | session.json | Stage 2 preview |
| F4 | **Auto-seeded zones from `roi_list`** (signed polygons → ROIs) | session.json | Stage 4 |
| F5 | **ROI / background preview** (`preprocessing/ROI_mask.png`, `background.png`) | preprocessing/ | Stage 2 + Stage 4 |
| F6 | **`length_unit` → calibration** | trajectory dict | Stage 3, with confirmation step |
| F7 | **Identity labels / groups import** | trajectory dict + session.json | Stage 5 (auto-fill, overridable) |
| F8 | **Per-(frame, identity) bbox body length** (more reliable than mean `body_length`) | `<session>_bboxes.csv` | Stage 3 + Stage 7; preferred over `body_length` when present |
| F9 | **Inconsistent-frame mask** | `inconsistent_frames.csv` | preprocessing step optionally excludes these frames; surfaces as a "suspicious frames" counter |
| F10 | **Tracking-log digest** (Success / Error, per-stage durations, WARN/ERROR lines) | `idtrackerai.log` | Stage 2 row drawer |
| F11 | **Cross-session match awareness** | `matching_results/` | Stage 5 (offer to import idmatcher.ai labels) |
| F12 | **Body-length unreliability banner** | `reference:100` | Stage 3 + manifest record |
| F13 | **Import report export** (`import_report.{md,csv}` + `quality.csv` in export bundle) | all of the above | Stage 7 Export |
| F14 | **Path-rebase tool** when `video_paths` is unreachable (Windows ↔ macOS) | session.json + `video_paths` | Stage 2 toast → "Locate video files…" dialog |

### 5.1 Quality-card sketch (Stage 2 per-row drawer)

```
session_trial10_Segment1            idtracker.ai 6.0.13
─────────────────────────────────────────────────────────
trajectories: h5 ✓  npy ✓  csv ✓   length_unit: — (not calibrated)
fraction_identified: 0.822          estimated_accuracy: 0.752
silhouette_score:   0.781           fragment_connectivity: 1.34
id_probabilities ≥ 0.9: 71.4 %
inconsistent_frames: 74             tracking_status: Success
video_paths reachable: no (rebase…)
custom: bboxes.csv ✓ bboxes_summary.json ✓
warnings: body_length is segmentation-dependent (Acknowledge…)
```

---

## 6. Implementation plan by module

| Step | Module(s) | Change |
|---|---|---|
| 6.1 | `track2data/readers/idtrackerai/` (new package) | Scaffold subpackage layout (detect, formats/*, session_json, log, preprocessing, custom_artefacts, normaliser) |
| 6.2 | `…/detect.py` | File-tree probe with priority order (§4.2); ignore `._*` files |
| 6.3 | `…/session_json.py` | Load `session.json` with `Infinity`/`NaN` hook; parse `roi_list`, `tracking_intervals`, `timers`, etc. |
| 6.4 | `…/log.py` | Tail-read `idtrackerai.log`; extract last status, per-stage durations, WARN/ERROR lines |
| 6.5 | `…/preprocessing.py` | Load `ROI_mask.png`, `background.png`; fragment summaries |
| 6.6 | `…/formats/h5.py` | `h5py` loader (gated behind `track2data[idtrackerai-h5]` extra) |
| 6.7 | `…/formats/npy.py` | `np.load(allow_pickle=True).item()`; security policy from §7 |
| 6.8 | `…/formats/parquet.py` | `pyarrow.parquet` loader + schema-metadata attrs |
| 6.9 | `…/formats/pickle.py` | `pickle.load` with policy gate |
| 6.10 | `…/formats/csv_bundle.py` | Read 3 CSVs + `attributes.json`; reshape to canonical dict |
| 6.11 | `…/formats/csv_tidy.py` | pandas pivot to `(N, M, 2)` |
| 6.12 | `…/formats/legacy.py` | Pre-6.x: `video_object.npy` + `trajectories.npy` raw array |
| 6.13 | `…/key_aliases.py` | Map known renames across versions (extensible) |
| 6.14 | `…/normaliser.py` | Map any `TrajectoryPayload` → `Session`; apply §4.1 rules |
| 6.15 | `…/custom_artefacts.py` | Opportunistic loaders for `inconsistent_frames.csv`, `<session>_bboxes.csv`, `<session>_bboxes_summary.json`, `matching_results/*` |
| 6.16 | `track2data/core/models.py::Session` | Add: `id_probabilities`, `quality`, `length_unit`, `body_length_px`, `body_length_reliable`, `identities_labels`, `identities_groups`, `setup_points`, `tracking_intervals`, `roi_list`, `tracking_log`, `inconsistent_frames`, `bbox_table` (np ref or path), `bbox_summary`, `matching_results`, `idtrackerai_version`, `trajectory_format`, `raw_attrs` |
| 6.17 | `track2data/readers/__init__.py` | Register the new unified `IDTrackerAiReader`; deprecate the v4/v5 split |
| 6.18 | `track2data/calibration/` | Auto-fill from `length_unit` (with confirmation) |
| 6.19 | `track2data/zones/` | Auto-seed from `roi_list` (signed polygons) |
| 6.20 | `tests/fixtures/sessions/` | Replace tiny_v5 fixtures with a **`tiny_real/`** fixture that mirrors the real layout (h5 + npy + csv_csv + session.json with Infinity + log + inconsistent_frames + bboxes) |
| 6.21 | `tests/fixtures/r_outputs/` | Re-baseline golden CSV |
| 6.22 | `pyproject.toml` | Add `h5py`, `pyarrow` (already present), `Pillow` (PNGs) under `idtrackerai` extra |
| 6.23 | `docs/ENGINE_DESIGN.md` | Replace §5 (Readers) with the new package layout |
| 6.24 | `docs/USER_WORKFLOW.md` | Surface F1–F14 message text + error codes |
| 6.25 | `docs/TECHNICAL_SPEC.md` | Add h5py + Pillow extras; mention idtracker.ai key-alias policy under §12 |

**Sequencing (test-driven):**

1. 6.16 (extend Session) → 6.14 (normaliser stub).
2. 6.20 (tiny_real fixture matching the corpus).
3. 6.2 + 6.7 + 6.10 (detect + npy + csv bundle — the two formats every real session ships).
4. 6.3 + 6.4 + 6.5 (session.json + log + preprocessing).
5. 6.15 (custom artefacts).
6. 6.17 (swap reader registry).
7. 6.6 + 6.8 + 6.9 + 6.11 (other formats; not blocked by real-data tests).
8. 6.12 (legacy fallback; tested separately).
9. 6.18 + 6.19 (calibration + zone seeding).
10. 6.21 (golden rebaseline).
11. 6.22 + 6.23–6.25 (deps + docs).

Each step keeps the test suite green by extending fixtures alongside
code; the old `tiny_v5` fixture is removed only after `tiny_real`
fully covers the reader's contract.

---

## 7. Validation & error-handling plan

### 7.1 New error codes (add to `core/errors.py` + USER_WORKFLOW §6 catalogue)

**Status column added 2026-08.** This table was aspirational when
written; roughly half the codes now exist, with different severities in
one case.

| Code | Severity | Message | Status |
|---|---|---|---|
| `IDT_NO_TRAJ` | error | "No trajectory file found in `<folder>/trajectories/`." | ✅ implemented (`reader.py`, `formats/*.py`) |
| `IDT_FORMAT_AMBIGUOUS` | info | "Multiple trajectory formats present (`<list>`); chose `<best>`." | ✅ implemented at **info**, matching this spec (`reader.py::_load_payload`) -- was previously misused as a fatal `error` for an unrelated "not a dict" condition; that use is gone |
| `IDT_PICKLE_REFUSED` | error | "Loading `<path>` requires explicit consent (`--allow-pickle` / GUI prompt)." | ❌ not implemented as a code; the *behaviour* exists differently -- `readers/idtrackerai/blobs.py`'s blob-pickle loader requires an explicit `allow_pickle=True` **function parameter**, not a CLI flag or manifest field (see §7.2) |
| `IDT_VERSION_UNKNOWN` | warning | "idtracker.ai version `<v>` not recognised; using v6.x assumptions." | ❌ not implemented; no 5.x/6.x version gating exists (`readers/idtrackerai_detect.py::sniff_version` has no production caller) |
| `IDT_PARTIAL_SESSION` | warning | "Session looks incomplete (no `trajectories/`; log ended in error)." | ❌ not implemented as this code, but the underlying signal exists: `log.py`'s rewritten parser now returns `status: "Failed"` with a `failure_summary` when a crash is detected, surfaced in the export's provenance section |
| `IDT_BODY_LENGTH_UNRELIABLE` | warning | (§5 / F12) | ❌ not a logged code, but `Session.body_length_reliable` (always False regardless of source) carries the same caveat through to the README's provenance section |
| `IDT_DICT_MISSING_KEY` | warning | "Trajectory dict missing optional key `<k>`; field set to None." | ✅ implemented, but as **error** not warning, and only for the `trajectories` key specifically (`normaliser.py::_extract_trajectories`) and fps/width/height (`_require_positive_number`) -- not generically for every optional key |
| `IDT_SHAPE_MISMATCH` | error | "`id_probabilities` shape `<a>` incompatible with trajectories `<b>`." | ✅ implemented, but for `trajectories` vs `session.json.number_of_animals`, not specifically the `id_probabilities`-vs-`trajectories` case this row describes (`normaliser.py::_extract_trajectories`) |
| `IDT_LENGTH_UNIT_INVALID` | warning | "`length_unit=<v>` invalid; manual calibration required." | ✅ implemented (`normaliser.py::_normalise_length_unit`) -- logged only for genuinely corrupt values (non-numeric, non-finite, or a non-positive number other than idtracker.ai's own `-1` "never calibrated" sentinel); a bare `None` or the `-1` sentinel still normalise to `None` silently, since those are the expected "never calibrated" case, not corruption |
| `IDT_ROI_MASK_UNREADABLE` | warning | "Could not decode `<path>`." | N/A -- `preprocessing.py` records the path only, never decodes the PNG (see `docs/ENGINE_DESIGN.md`'s status note), so there is nothing to fail to decode |
| `IDT_JSON_NONSTRICT` | info | "`session.json` contains non-strict JSON literal (`Infinity`/`NaN`); parsed leniently." | ✅ implemented (`session_json.py`), but see §1.4's correction above -- the premise that stdlib `json.loads` rejects these literals is false, so this fires on every real session for something that was never actually an error |
| `IDT_VIDEO_PATH_UNREACHABLE` | warning | "`video_paths` `<p>` unreachable on this machine. Use 'Locate video…' to rebase." | ❌ not implemented; `Session.video.path` is silently `None` when unreachable (`normaliser.py::_resolve_video_path`), with no logged code and no rebase tool |
| `IDT_RESOURCE_FORK_IGNORED` | info | "Ignored `<count>` macOS resource-fork files (`._*`)." | ❌ not implemented as a logged code; the filtering itself works (`custom_artefacts.py`, `preprocessing.py`, `blobs.py` all filter `._*`), it just doesn't log a count. The original `detect.py` resource-fork filter this row was likely inspired by was and remains dead code (unreachable, since its candidate paths are all literals) -- see the dead-code cleanup note below. |

### 7.2 Security policy

Reference doc (`reference:150`, `reference:173`): *pickle is not
secure*. Policy:

| Surface | Default |
|---|---|
| Programmatic / notebook | Loads `.npy` / `.pickle` without prompting (user owns the files) |
| CLI | Refuse without `--allow-pickle`; emit `IDT_PICKLE_REFUSED` |
| GUI | One-time-per-project consent modal; choice persisted in manifest as `security.allow_pickle_trajectories` |

**Status (2026-08):** not built as specified. `formats/npy.py`'s
docstring claimed this gate existed (`security.allow_pickle_trajectories`
in the project manifest) when it never did -- that phantom claim has not
been corrected, and `np.load(path, allow_pickle=True)` still runs
unconditionally for `.npy` trajectories, same as when this table was
written. The new `readers/idtrackerai/blobs.py` (list_of_blobs.pickle
reader) takes a different, narrower approach instead of implementing
this table as written: a restricted `pickle.Unpickler` allowlist (stubs
every `idtrackerai.*` class, refuses everything outside a small numpy
allowlist -- no idtracker.ai code ever executes) plus a mandatory
`allow_pickle: bool` **function parameter** that the caller must pass
`True` explicitly. No CLI flag, no GUI modal, no `ProjectManifest.security`
field exist. A caller wiring this into the CLI/GUI still needs to build
the consent surface this table describes; the loader itself is ready for it.

### 7.3 JSON-strictness hook

```python
def _safe_constant(c: str) -> float:
    return {"Infinity": float("inf"),
            "-Infinity": -float("inf"),
            "NaN": float("nan")}.get(c, float(c))

json.loads(text, parse_constant=_safe_constant)
```

Triggers `IDT_JSON_NONSTRICT` (info) when any constant is replaced.

**Status (2026-08):** implemented exactly as specified
(`session_json.py`), but see §1.4's correction: the premise is wrong.
`json.loads('{"a": Infinity}')` already returns `{'a': inf}` with the
stdlib parser alone -- no `parse_constant` hook is required for this to
work. The hook is harmless (it does the same thing stdlib already does,
plus logs), but the log line fires on every real session
(`area_ths: [668.0, Infinity]` is universal in the corpus) narrating a
non-event as if it were a compatibility fix.

### 7.4 Path-rebase

When `video_paths` does not resolve, the reader stores the path
unchanged and sets `Session.video.path = None`. UI offers a
"Locate video files…" rebase dialog; CLI accepts
`--video-path-prefix <new>=<old>`.

---

## 8. Tests / fixtures needed

### 8.1 Corpus-mirroring fixture (`tiny_real/`)

Mirrors the **observed real layout** at miniature scale (10 frames,
2 animals):

```
tiny_real/
├─ accumulation/identifier_cnn.model.pt      (empty placeholder)
├─ identification_images/id_images_0.h5      (empty placeholder)
├─ preprocessing/
│  ├─ ROI_mask.png                            (2x2 px PNG)
│  ├─ background.png
│  ├─ list_of_fragments.json
│  └─ list_of_global_fragments.json
├─ trajectories/
│  ├─ trajectories.h5                         (real h5py write)
│  ├─ trajectories.npy                        (real pickled dict)
│  └─ trajectories_csv/
│     ├─ trajectories.csv
│     ├─ id_probabilities.csv
│     ├─ areas.csv
│     ├─ attributes.json                      (with "Infinity" literal!)
│     ├─ tiny_real_bboxes.csv
│     └─ tiny_real_bboxes_summary.json
├─ session.json                               (40+ keys, "Infinity" present)
├─ idtrackerai.log                            (mocked status lines)
└─ inconsistent_frames.csv                    (3 frame indices)
```

### 8.2 Test classes (all new)

| Test | Asserts |
|---|---|
| `test_detect_priority` | h5 > parquet > npy > pickle > csv_tidy > csv_bundle > legacy |
| `test_format_parity` | Every format reads to the same `Session` field-for-field |
| `test_id_probabilities_squeeze` | `(N, M, 1)` collapses to `(N, M)` |
| `test_json_infinity_handling` | `Infinity` in session.json parses without raising; `IDT_JSON_NONSTRICT` info logged |
| `test_session_json_full_extract` | `roi_list`, `tracking_intervals`, `timers`, `last_validated` all land in `Session.metadata` |
| `test_log_digest` | Success / Error status surfaced from `idtrackerai.log` |
| `test_resource_fork_ignored` | `._*` files in the fixture are filtered out |
| `test_inconsistent_frames_loaded` | `Session.inconsistent_frames == {0, 5, 9}` for the fixture |
| `test_bbox_csv_loaded` | `Session.bbox_table` is a DataFrame; per-(frame, identity) lookup works |
| `test_length_unit_none_no_calibration` | calibration left empty; warning surfaced |
| `test_length_unit_positive_autocalibrates` | `CalibrationConfig.px_per_cm` populated |
| `test_body_length_reliable_default_false` | always False unless user explicitly acknowledges |
| `test_pickle_refused_in_cli` | `--allow-pickle` required |
| `test_legacy_v5_path` | Old reader contract still works on a `tiny_legacy_v5` fixture |
| `test_partial_session_no_traj` | Returns Session with `partial=True`, no crash |
| `test_unknown_version` | Loads as 6.x with warning |
| `test_quality_metrics_propagated` | All 7 quality keys reach `Session.quality` |
| `test_video_path_unreachable` | `Session.video.path is None`; warning emitted |
| `test_real_session_smoke` (opt-in, marked `@pytest.mark.real_data`) | Reads one of the 70 real sessions if available; ignored in CI unless dataset present |

### 8.3 R-parity rebaseline (`tests/fixtures/r_outputs/`)

Re-derive golden CSV against the new `tiny_real/` fixture; tolerances
unchanged from TECHNICAL_SPEC §11.2.

---

## 9. Risks & assumptions

| # | Risk | Mitigation |
|---|---|---|
| R1 | Test suite (75 green) is pinned to a fiction | §6.20: introduce `tiny_real` alongside; flip default once parity reached |
| R2 | `allow_pickle=True` is a remote-code-execution vector | §7.2 surface-specific gates |
| R3 | We cannot install `h5py` in this environment (verified: `ModuleNotFoundError`) | Optional extra `track2data[idtrackerai]`; graceful fallback to NPY when h5py absent |
| R4 | `pyarrow` already required for Feather export — no new dep | — |
| R5 | `Pillow` not yet a dep | Add under same `idtrackerai` extra (small) |
| R6 | Future idtracker.ai versions may **rename** keys | `key_aliases.py` policy; readers degrade to `IDT_DICT_MISSING_KEY` warning, not crash |
| R7 | Future versions may add **new files** at any folder level | reader uses an allow-list of consumed files; everything else logged as info only |
| R8 | Custom post-processing outputs (`*_bboxes.csv`, `inconsistent_frames.csv`) are user-pipeline-specific | Treat as opportunistic — never required, never crash if absent or different schema |
| R9 | macOS `._*` resource forks may carry trailing-NULs that fool simple "exists" checks | filter at discovery layer via `iter_session_files()` |
| R10 | Real `video_paths` are unreachable from the user's analysis machine | path-rebase tool (F14); preview falls back to `background.png` |
| R11 | **Corrected 2026-08**: 26/70 real sessions have a valid `length_unit`, not none — the original assumption was drawn from one uncalibrated sample. The auto-calibration path must be tested against a calibrated real session, not assumed to be a permanent no-op | F6 must work correctly with `length_unit` both present and `None` |
| R12 | `body_length` in idtracker.ai is segmentation-dependent (`reference:100`); users may still use it for calibration | F12 banner + manifest record |
| R13 | `id_probabilities` shape disagrees with reference doc | normalise at the source; document deviation in the analysis doc itself |
| R14 | macOS / Windows / Linux path separators differ | always `Path()`; preserve original strings in `Session.metadata["raw"]` |
| R15 | Legacy v4/v5 outputs may exist on user machines we have not sampled | keep legacy path, but do not block reader release on it |

### 9.1 Working assumptions (require user confirmation)

- A1 — Single unified `IDTrackerAiReader` rather than one reader per
  format.
- A2 — `h5py` and `Pillow` as optional extras (`track2data[idtrackerai]`).
- A3 — Programmatic API loads NPY/pickle by default; GUI/CLI gate
  explicitly.
- A4 — `body_length_reliable` defaults to False until the user
  explicitly acknowledges the segmentation-dependency caveat.
- A5 — `length_unit` auto-applies only with confirmation on Stage 3.
- A6 — `roi_list` from `session.json` is offered as an auto-seed on
  Stage 4 but never overwrites user-drawn ROIs without confirmation.
- A7 — Custom artefacts (`*_bboxes.csv`, `inconsistent_frames.csv`)
  are loaded opportunistically; missing → silent.
- A8 — `idtrackerai.log` parsing is best-effort and never required.
- A9 — Legacy v4/v5 support stays in the codebase but is not
  test-gated on real-data fixtures.

---

## 10. Questions requiring user approval

1. **Reader architecture (A1)** — unified reader, or one per format?
   *Recommendation:* unified.

2. **Extras packaging (A2)** — `h5py` + `Pillow` as
   `track2data[idtrackerai]` extra, or required in core?
   *Recommendation:* extra; the engine should be small.

3. **Pickle policy (A3)** — refuse-by-default in GUI/CLI with prompt,
   or load with non-blocking warning?
   *Recommendation:* refuse-by-default; allow-once-per-project.

4. **Body-length acknowledgement (A4 / F12)** — block bodylength
   calibration until acknowledged, or log a warning?
   *Recommendation:* block + persist acknowledgement.

5. **`length_unit` auto-apply (A5)** — silent or confirmation?
   *Recommendation:* confirmation, since `length_unit=None` is the
   common case and silently calibrating zero would be worse than
   prompting.

6. **`roi_list` auto-seed (A6)** — auto-populate Stage 4 zones from
   `session.json.roi_list`, or only when the user clicks "Import
   from session.json"?
   *Recommendation:* auto-populate as a draft; user confirms.

7. **Custom artefacts (A7)** — load `<session>_bboxes.csv` and
   `inconsistent_frames.csv` by default and surface in diagnostics,
   or behind a "post-processing extras" flag?
   *Recommendation:* default-on; small cost, high diagnostic value.

8. **Legacy v4/v5 scope (A9)** — keep code path, or drop on the
   basis that the 70-session corpus is uniformly 6.x?
   *Recommendation:* keep, since users with older labs may still
   process older outputs; cost is small.

9. **Tracking-log digest depth** — extract only Success/Error +
   durations (cheap), or surface every WARN/ERROR line (richer
   but log-format-coupled)?
   *Recommendation:* both, with the richer detail behind a "Show
   full log" disclosure.

10. **idmatcher.ai `matching_results/`** — first-class support
    (import labels onto `individual_id`), or just list and ignore?
    *Recommendation:* v1.0 list-and-ignore; v1.1 first-class.

11. **`bbox.csv` body length precedence** — when both
    `body_length` (from trajectory dict) and per-row `body_length_px`
    (from `<session>_bboxes.csv`) are present, which wins for the
    Stage 3 BL-calibration table?
    *Recommendation:* per-row bbox value (it is per-individual, not
    a session mean) but show both; if only `body_length` present,
    use it with the unreliability banner.

12. **Real-data smoke test** — add an opt-in `@pytest.mark.real_data`
    test that runs against the 70-session corpus when present?
    *Recommendation:* yes, but skip in CI; useful for local
    regression checks during development.
