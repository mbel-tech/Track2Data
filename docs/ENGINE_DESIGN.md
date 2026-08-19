# Track2Data Engine — Design Specification

**Audience:** Backend implementers, contributors writing plug-ins.
**Status:** Draft v0.1 (companion to PRD §5; aligned with v1.0 MVP scope).
**Language / runtime:** Python 3.11+, pure-Python (no R at runtime).
**Distribution unit:** the `track2data` package; the desktop GUI imports it.
**Related:** [`./TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md) for the system-level view (tech stack, build, distribution, plug-in compatibility policy).

> **Caveat (2026-05-14):** §5 (Readers) describes the original reader
> assumptions. A real-data audit against idtracker.ai 6.0.13 outputs
> revealed fundamental mismatches; see
> [`./IDTRACKERAI_FORMAT_ANALYSIS.md`](./IDTRACKERAI_FORMAT_ANALYSIS.md)
> for the gap analysis and the planned normalisation-layer rewrite.

---

## 1. Overview & responsibilities

The engine is a headless library that owns every behaviour mandated by
PRD §5 — import, calibration, zone handling, metadata mapping, preprocessing,
metric extraction, export, caching, and run-log emission. It exposes:

1. A **stable Python API** for the PySide6 UI and external scripts.
2. A **`track2data` CLI** for headless reproduction (`track2data run
   project.t2d.json`).
3. Three **plug-in entry points** so contributors can add readers,
   metrics, and exporters without forking.

The engine is **stateless across runs** in the sense that all state is
captured in the project manifest + cache directory; no globals.

---

## 2. Package layout

```
track2data/
├── __init__.py                  # public API re-exports
├── _version.py
├── cli.py                       # `track2data` console entry point
├── api.py                       # high-level facade (Engine class)
│
├── core/
│   ├── __init__.py
│   ├── models.py                # Pydantic data models (§4)
│   ├── manifest.py              # project manifest read/write + migration
│   ├── hashing.py               # SHA-256 helpers for files & dicts
│   ├── logging.py               # structured logger + run-log Markdown writer
│   ├── parallel.py              # ProcessPoolExecutor wrapper, worker-cap policy
│   └── errors.py                # exception hierarchy (§13)
│
├── readers/
│   ├── __init__.py              # discovery via entry points (§11)
│   ├── base.py                  # SessionReader abstract base
│   ├── idtrackerai_v5.py        # current idtracker.ai format
│   ├── idtrackerai_v4.py        # legacy fallback
│   ├── idtrackerai_detect.py    # version sniffing
│   └── video_meta.py            # extract one frame + fps via ffmpeg or pyav
│
├── metadata/
│   ├── __init__.py
│   ├── loader.py                # CSV/XLSX loader, type coercion
│   ├── mapping.py               # MappingRule, canonical-field resolver
│   ├── join.py                  # session ↔ metadata-row matcher (multi-key + regex)
│   └── schema.py                # canonical-field list, aliases (condition→treatment, date→trial_date)
│
├── calibration/
│   ├── __init__.py
│   ├── scalar.py                # px-per-cm scalar mode
│   └── bodylength.py            # per-session body-length normalisation
│
├── zones/
│   ├── __init__.py
│   ├── io.py                    # CSV ↔ ZoneSet round-trip
│   ├── geometry.py              # shapely-based polygon ops, PIP, area
│   └── orientation.py           # orientation pairing (FT/FD style)
│
├── preprocess/
│   ├── __init__.py
│   ├── pipeline.py              # ordered Preprocessor chain (§7)
│   ├── gap_fill.py              # PP-1
│   ├── jump_detect.py           # PP-2 (sd_multiple + percentile)
│   ├── identity_switch.py       # PP-3 (Tier-1 mutual-NN + Tier-2 Hungarian)
│   ├── smoothing.py             # PP-4 (moving-avg + Savitzky-Golay)
│   ├── validate.py              # PP-5 (coverage gate)
│   └── kinematics.py            # speed, accel, heading recomputation
│
├── metrics/
│   ├── __init__.py              # registry + discovery via entry points
│   ├── base.py                  # Metric abstract base
│   ├── individual.py            # IL-1..IL-5
│   ├── group.py                 # GL-1..GL-7 (NND, polarisation, hull, etc.)
│   ├── zone.py                  # Z-1..Z-5
│   └── identity_free.py         # NN-matched speed + flow↔calm crossings
│
├── exporters/
│   ├── __init__.py              # registry + discovery via entry points
│   ├── base.py                  # Exporter abstract base
│   ├── csv_long.py
│   ├── csv_wide.py
│   ├── excel.py                 # multi-sheet xlsx via openpyxl
│   ├── feather.py               # pyarrow feather/parquet
│   └── readme.py                # human-readable run README.md
│
├── cache/
│   ├── __init__.py
│   └── store.py                 # content-addressed feather cache
│
└── reference/
    ├── canonical_columns.py     # frozen column-name registry (§4)
    └── default_params.py        # all default parameter values
```

Tests mirror the tree under `tests/`. Fixtures live in `tests/fixtures/`.

---

## 3. Module responsibility matrix

| Module | Inputs | Outputs | Side effects |
|---|---|---|---|
| `readers` | session folder path | `Session` object (numpy arrays + metadata) | none |
| `metadata.loader` | CSV/XLSX path | `pandas.DataFrame` | none |
| `metadata.mapping` | DataFrame + `MappingRule` | canonical DataFrame | none |
| `metadata.join` | sessions + mapped metadata | `JoinResult` (matched, unmatched, conflicts) | none |
| `calibration` | `Session` + mode + params | `Calibration` (px↔cm, BL/s factor) | none |
| `zones.io` | CSV path or `ZoneSet` | `ZoneSet` ↔ CSV | writes CSV on export |
| `zones.geometry` | `ZoneSet` + (x,y) frames | per-frame zone labels | none |
| `preprocess.pipeline` | `Session` + `PreprocessConfig` | `PreprocessedSession` + `PreprocessReport` | none |
| `metrics.*` | `PreprocessedSession` + selection | `MetricResult` per metric | none |
| `exporters.*` | merged DataFrames + manifest | files written | filesystem writes |
| `core.manifest` | manifest JSON | `ProjectManifest` model + migration log | reads/writes JSON |
| `cache.store` | content-hash key + DataFrame | cached feather | reads/writes cache |
| `api.Engine` | `ProjectManifest` | orchestration of all of the above | logs + cache + exports |

---

## 4. Data models (Pydantic v2)

All cross-module data uses Pydantic models so payloads are
self-validating and serialisable. Stored in `core/models.py`.

### 4.1 Core records

```python
class FrameRange(BaseModel):
    start: int = 0
    end: int | None = None   # None = end-of-session

class VideoInfo(BaseModel):
    path: Path | None        # may be unreachable; preview falls back
    fps: float
    n_frames: int
    width_px: int
    height_px: int

class Session(BaseModel):
    session_id: str          # = folder basename by default
    folder: Path
    reader: str              # which reader matched
    video: VideoInfo
    n_animals: int
    trajectory_variant: Literal["with_gaps", "wo_gaps"]
    has_stable_identities: bool   # auto-detected (§5.5)
    raw_xy: np.ndarray       # shape (n_frames, n_animals, 2), float32, NaN = gap
    body_length_px: np.ndarray | None = None  # (n_animals,) — median bbox diagonal; None if unavailable
    body_length_reliable: bool = False         # True when derived from bbox_table median diagonal

    class Config:
        arbitrary_types_allowed = True
```

### 4.2 Configuration models

```python
class CalibrationConfig(BaseModel):
    mode: Literal["scalar", "bodylength"]
    px_per_cm: float | None = None         # required when mode == "scalar"
    bl_min_samples: int = 30               # bodylength mode validation

class ZoneSet(BaseModel):
    rois: list[ROI]
    orientation_tag: str | None = None     # e.g. "FT" / "FD"
    zone_levels: dict[str, str]            # roi_name -> "main" | "secondary" | custom

class ROI(BaseModel):
    name: str
    level: str
    vertices: list[tuple[float, float]]    # px coords
    area_units: float | None = None        # optional, for area-corrected metrics

class PreprocessConfig(BaseModel):
    gap_fill: GapFillCfg = GapFillCfg()
    jump: JumpCfg = JumpCfg()
    identity_switch: IdSwitchCfg = IdSwitchCfg()
    smoothing: SmoothCfg = SmoothCfg()
    coverage: ValidateCfg = ValidateCfg()

class GapFillCfg(BaseModel):
    enabled: bool = True
    max_gap_frames: int = 30

class JumpCfg(BaseModel):
    enabled: bool = True
    method: Literal["sd_multiple", "percentile"] = "sd_multiple"
    sd_mult: float = 10.0
    percentile: float = 99
    pct_mult: float = 2.0
    replacement: Literal["nan", "linear_interp"] = "linear_interp"

class IdSwitchCfg(BaseModel):
    enabled: bool = True
    tier1_ratio: float = 1.5
    tier2_hungarian: bool = True
    consolidate_window: int = 5

class SmoothCfg(BaseModel):
    enabled: bool = True
    method: Literal["none", "moving_avg", "savgol"] = "savgol"
    window: int = 5
    polyorder: int = 2

class ValidateCfg(BaseModel):
    min_track_frames: int = 0
    max_pct_na_per_individual: float = 0.1  # = 90 % coverage

class MetricSelection(BaseModel):
    individual: list[str] = []              # IDs like "IL-1"
    group:      list[str] = []
    zone:       list[str] = []
    diagnostic: list[str] = []             # D-* IDs; auto-computed, always exported
    timepoint_minutes: int | None = None   # 20 in the choice-exp pipeline
    quality_threshold: float = 0.0         # mask frames below this id_probability
```

### 4.3 Canonical output column registry

Stored in `reference/canonical_columns.py`; the single source of truth
for export column names so all exporters stay consistent and parity
tests against the R pipeline can pin names exactly.

| Group | Column | Type | Unit |
|---|---|---|---|
| key | `session_id` | str | — |
| key | `trial_id` | int | — |
| key | `timepoint` | int | bin index |
| key | `individual_id` | int | nullable (identity-free) |
| key | `frame` | int | — |
| key | `time_s` | float | seconds since session start |
| kine | `x_px`, `y_px` | float | pixels |
| kine | `x_cm`, `y_cm` | float | cm (only if calibrated) |
| kine | `speed_cm_s`, `speed_bl_s` | float | — |
| kine | `heading_rad` | float | radians |
| zone | `main_zone`, `sec_zone` | str | user-defined labels |
| meta | `treatment`, `group_id`, `trial_date`, … | varies | from metadata mapping |

### 4.4 `ProjectManifest`

```python
class ProjectManifest(BaseModel):
    schema_version: int = 1
    app_version: str
    project_name: str
    created_at: datetime
    updated_at: datetime
    sessions: list[SessionRef]       # path + SHA-256
    calibration: CalibrationConfig
    zones: ZoneSet
    metadata_source: MetadataSource | None
    mapping: MappingRule | None
    preprocess: PreprocessConfig
    metrics: MetricSelection
    export_targets: list[ExportTarget]
    run_log_path: Path
```

`hashing.canonical_hash(manifest)` returns the project hash printed on
every export and cache key.

---

## 5. Reader subsystem

### 5.1 `SessionReader` base

```python
class SessionReader(ABC):
    name: str            # plug-in key
    priority: int = 0    # higher wins on tie

    @classmethod
    @abstractmethod
    def detect(cls, folder: Path) -> bool: ...

    @abstractmethod
    def read(self, folder: Path) -> Session: ...
```

### 5.2 Built-in readers

- **`idtrackerai`** — unified reader (priority 20). Supports all
  idtracker.ai 6.x output formats. Package layout:

  ```
  readers/idtrackerai/
  ├── reader.py            IDTrackerAiReader — wires the full pipeline
  ├── detect.py            file-tree probe; priority: h5>parquet>npy>pickle>csv
  ├── normaliser.py        TrajectoryPayload dict → Session (version-agnostic rules)
  ├── session_json.py      session.json parser with Infinity/NaN hook
  ├── log.py               idtrackerai.log digest extractor
  ├── custom_artefacts.py  inconsistent_frames.csv, *_bboxes.csv, matching_results/
  ├── key_aliases.py       cross-version key rename map
  └── formats/
      ├── npy.py           pickled-dict NPY loader
      ├── csv_bundle.py    trajectories_csv/ loader
      ├── h5.py            h5py loader (optional extra)
      ├── parquet.py       pyarrow loader (optional extra)
      ├── pickle.py        pickle loader (consent-gated)
      ├── csv_tidy.py      tidy CSV loader
      └── legacy.py        pre-6.x video_object.npy path
  ```

  Key normalisation rules applied by `Normaliser`:
  - `id_probabilities` shape `(N, M, 1)` squeezed to `(N, M)`.
  - `length_unit ≤ 0 | None | inf` treated as "not calibrated".
  - `body_length_reliable` always `False` until user acknowledges.
  - macOS resource-fork `._*` files filtered at detection layer.
  - Non-strict JSON literals (`Infinity`, `NaN`) parsed leniently.
  - Unknown trajectory-dict keys preserved in `Session.raw_attrs`.

- **`idtrackerai_v5`** — legacy reader (priority 10). Kept for backwards
  compatibility with pre-6.x data using `video_object.npy`.
- **`idtrackerai_v4`** — legacy fallback (priority 5).

### 5.3 Discovery

Built-ins are registered in `readers/__init__.py`. External readers
register via the `track2data.readers` entry point (§11). On import, the
loader sorts candidates by `priority` (descending) and the first
`detect()` returning `True` wins. The unified `idtrackerai` reader
(priority 20) wins for any folder containing a `trajectories/`
subdirectory. Failures are logged but never raise during discovery.

### 5.4 Video metadata

`readers/video_meta.py` extracts one frame + fps via `pyav` (no native
ffmpeg dependency at install). If the video file is missing, the
session still loads — preview falls back to a blank canvas (FR-VIEW-1).

### 5.5 Identity-free detection

`Session.has_stable_identities = True` iff every animal has ≥ X%
non-NaN frames (default 50%, configurable). When `False`, the engine
disables individual-level metrics and routes through the
`identity_free` path that matches the choice-experiment R logic.

---

## 6. Metadata subsystem

### 6.1 Canonical fields & aliases

`metadata/schema.py` ships the canonical field list and a built-in alias
table:

```python
CANONICAL = ["session_id", "trial_id", "individual_id", "group_id",
             "treatment", "trial_date", "timepoint"]
ALIASES = {"condition": "treatment", "date": "trial_date"}
```

### 6.2 Loader

`metadata.loader.load(path)` returns a `pandas.DataFrame` with stripped
whitespace, lowered string columns where appropriate, and ISO-8601
dates. Excel files: read sheet 0; multi-sheet support is a future
feature.

### 6.3 Mapping & join

`MappingRule` records, for each canonical field, the source column name
and an optional regex transform. `join.match()` returns:

```python
class JoinResult(BaseModel):
    matched:    dict[str, dict[str, Any]]   # session_id -> row dict
    unmatched_sessions: list[str]
    unmatched_metadata_rows: list[int]
    conflicts:  list[ConflictRecord]        # e.g. two metadata rows match one session
```

Match keys can be: exact (`session_id`), composite (`tank + trial_date`),
or regex on folder basename (e.g. `N(\d+)_segment(\d+)` → trial number +
timepoint).

---

## 7. Preprocessing pipeline

### 7.1 Contract

A `Preprocessor` is:

```python
class Preprocessor(Protocol):
    name: str
    def apply(self, xy: np.ndarray, ctx: PPContext) -> PPStepResult: ...

class PPStepResult(BaseModel):
    xy: np.ndarray
    affected_frames: int
    affected_per_individual: list[int]
    notes: str = ""
```

`pipeline.run(session, config) → PreprocessedSession` applies the steps
in a fixed order: `gap_fill → jump_detect → identity_switch → smoothing
→ validate`. Each step writes one row to the `PreprocessReport`.

### 7.2 Algorithm porting notes (R → Python)

| R step | Python module | Library equivalent |
|---|---|---|
| Linear-interp gap fill | `gap_fill.py` | `pandas.Series.interpolate(method="linear", limit=N)` |
| `sd_multiple` jump | `jump_detect.py` | numpy global mean+SD on per-frame displacement, NaN-replace then re-interp |
| `percentile` jump | `jump_detect.py` | `numpy.nanpercentile` × multiplier |
| Tier-1 mutual-NN ratio | `identity_switch.py` | numpy pairwise distances; ratio rule |
| Tier-2 Hungarian | `identity_switch.py` | `scipy.optimize.linear_sum_assignment` |
| Savitzky-Golay smoothing | `smoothing.py` | `scipy.signal.savgol_filter` |
| Heading recomputation | `kinematics.py` | `numpy.arctan2(dy, dx)` |

Determinism (FR-PRE-3, NFR-6): every step uses numpy operations only;
no random seeds; no thread-pool reductions (or seeded BLAS threads = 1
for per-session work).

---

## 8. Metric subsystem

> **Canonical metric spec:** see [`./METRICS_SPEC.md`](./METRICS_SPEC.md)
> for the implementation-ready definition of every metric ID
> (formulas, inputs, outputs, units, edge cases, citations) and the
> UI info-button architecture this subsystem feeds.

### 8.1 `Metric` base class

```python
class Metric(ABC):
    id: str               # e.g. "IL-2"
    name: str
    label: str            # manuscript-friendly label
    level: Literal["individual", "group", "zone", "diagnostic"]
    priority: Literal["primary", "optional", "advanced", "diagnostic"]
    requires_identity: bool
    output_columns: list[str]
    documentation: MetricDocumentation   # rendered by the info-button modal

    @abstractmethod
    def compute(self, session: PreprocessedSession,
                cfg: dict | None = None) -> pd.DataFrame: ...
```

`MetricDocumentation` is a Pydantic model carrying the definition,
formula, inputs, assumptions, warnings, and citation that the UI
`MetricInfoDialog` renders verbatim (see `METRICS_SPEC.md` §5.2 / §6).

The output DataFrame always carries the canonical keys (`session_id`,
`trial_id`, `timepoint`, `individual_id` where applicable) plus the
metric's `output_columns`.

### 8.2 Built-in catalogue

Listed in PRD §5.6 and fully specified in `METRICS_SPEC.md` §4.
Implementation notes:

- **GL-1 NND / GL-2 IID / GL-4 hull area** — port from `swaRm`:
  - NND per frame: `scipy.spatial.cKDTree.query(k=2)` then mean.
  - IID per frame: pairwise distance via `scipy.spatial.distance.pdist`.
  - Hull area: `scipy.spatial.ConvexHull(points).volume` (2-D ⇒ area).
- **GL-3 polarisation** — `P = |sum(unit_heading_vectors)| / n` per frame.
- **GL-5 centroid speed** — frame-to-frame Euclidean on the mean (x,y).
- **GL-6 cohesion** — `1 / mean_NND` (NaN-safe).
- **GL-7 NN-matched speed (identity-free)** — match consecutive frames'
  detections via nearest-neighbour assignment; report the frame-mean
  matched displacement, divided by the per-frame Δt.

### 8.3 Active-classification threshold (FR-MTR-3)

`metrics.individual.active_threshold(session)` returns
`mean(per_fish_median(body_length_cm))` for the trial — matches the R
default. Overridable via metric config.

### 8.4 Zone metrics & area correction

`metrics.zone` consumes `main_zone` / `sec_zone` columns produced by
`zones.geometry.assign(session.xy, zone_set)`. Area-corrected time
divides time-in-zone by `roi.area_units`.

### 8.5 Registration & discovery

Built-ins call `registry.register(MetricClass)` in `metrics/__init__.py`.
External plug-ins use the `track2data.metrics` entry point. The UI
queries `registry.list_for_level("group")` to populate metric menus.

---

## 9. Exporters

### 9.1 `Exporter` base

```python
class Exporter(ABC):
    name: str
    file_extension: str

    @abstractmethod
    def write(self, payload: ExportPayload, out_dir: Path) -> list[Path]: ...
```

`ExportPayload` carries: master_fish_by_frame, trial_activity_summary,
trial_occupancy_long, group_dynamics_summary, qc tables, manifest hash,
app version.

### 9.2 Built-in exporters

| Exporter | Files written |
|---|---|
| `csv_long`  | `master_fish_by_frame.csv`, `trial_activity_summary_long.csv`, `trial_occupancy_long.csv`, `group_dynamics_summary.csv` |
| `csv_wide`  | `trial_summary_wide.csv` |
| `excel`     | `Track2Data_<project>.xlsx` (multi-sheet) |
| `feather`   | `master_fish_by_frame.feather`, `trial_activity_summary.feather` |
| `readme`    | `README.md` + `manifest.json` |

Determinism (FR-EXP-3): CSV writers sort rows by canonical keys before
writing, force `.` decimal separator, force UTF-8 LF, force ISO-8601
dates. SHA-256 of each output is recorded in `manifest.json`.

---

## 10. Caching strategy

`cache/store.py` is a content-addressed Feather store keyed by:
`SHA-256(reader_name + session_folder_hash + preprocess_config_hash)`.
- **Hit** → return cached DataFrame.
- **Miss** → run, write, return.

Cache lives under `.<project>.t2d_cache/`. The CLI exposes
`track2data cache clear --project <p>`.

---

## 11. Plug-in entry points

Defined in `pyproject.toml` for built-ins; external packages declare the
same keys to extend the engine.

```toml
[project.entry-points."track2data.readers"]
idtrackerai_v5 = "track2data.readers.idtrackerai_v5:IDTrackerAiV5Reader"

[project.entry-points."track2data.metrics"]
IL-2_speed   = "track2data.metrics.individual:MeanSpeedMetric"
GL-1_nnd     = "track2data.metrics.group:NNDMetric"

[project.entry-points."track2data.exporters"]
csv_long = "track2data.exporters.csv_long:CsvLongExporter"
```

Discovery uses `importlib.metadata.entry_points(group="track2data.*")`.

---

## 12. CLI surface (`track2data/cli.py`)

| Command | Purpose |
|---|---|
| `track2data run <project.t2d.json>` | Headless run (FR-REP-2). |
| `track2data validate <project.t2d.json>` | Schema + reachability checks only. |
| `track2data list-metrics` | Print all registered metric IDs + descriptions. |
| `track2data cache clear` | Wipe `.t2d_cache/`. |
| `track2data new <name>` | Scaffold an empty project manifest. |

Implemented with `click` (already in scientific-Python deps).

---

## 13. Error handling & validation

### 13.1 Exception hierarchy (`core/errors.py`)

```
Track2DataError                       # base
├── ConfigError                       # bad parameters
├── DataValidationError               # DV-1..DV-8 failures
│   ├── ImportError_                  # readers
│   ├── MetadataValidationError       # mapping/join
│   ├── CalibrationError
│   └── ZoneValidationError
├── ProcessingError                   # runtime in preprocess/metrics
└── ExportError
```

Every exception carries: `code` (machine-readable), `severity`
(`error` / `warning` / `info`), `subject` (file path or session_id),
and `remediation` (one-line user hint shown in UI banners).

### 13.2 Validation rules (mapped to PRD DV-1..DV-8)

| ID | Where | Rule |
|---|---|---|
| DV-1 | `readers` | file presence, shape `(n_frames, n_animals, 2)`, fps > 0 |
| DV-2 | `metadata.mapping` | required canonical cols present after mapping |
| DV-3 | `zones.geometry` | ≥ 3 vertices per ROI, shapely `is_valid`, within frame bounds |
| DV-4 | `calibration` | `px_per_cm > 0`; BL mode rejects < N samples |
| DV-5 | `tests/golden/` | per-release CI fixture parity |
| DV-6 | `core.manifest.migrate` | semver-style migration log entry |
| DV-7 | `tests/r_parity/` | numerical-tolerance comparison vs. R outputs |
| DV-8 | `exporters.csv_long` etc. | SHA-256 of each written file |

### 13.3 Logging

`core.logging.get_logger(__name__)` returns a `structlog`-compatible
logger that emits JSONL events. The same events feed the Markdown
`run_log.md` writer. Log levels: `DEBUG`, `INFO`, `WARN`, `ERROR`. The
UI subscribes via a `QObject`-friendly handler (§4 of UI design).

---

## 14. Concurrency model

- **Per-session parallelism** via `concurrent.futures.ProcessPoolExecutor`
  in `core/parallel.py` (NFR-5).
- Worker cap: `min(user_setting, os.cpu_count() - 1, 8)`.
- BLAS threads pinned to 1 inside workers (`OMP_NUM_THREADS=1`,
  `MKL_NUM_THREADS=1`) so per-session determinism is preserved.
- Within a session, processing is single-threaded.
- Disabled if `n_workers == 1` so debugging shows real tracebacks.

---

## 15. Testing strategy

### 15.1 Layers

| Layer | Coverage target | Tooling |
|---|---|---|
| Unit | ≥ 80 % line | pytest + hypothesis for property tests |
| Integration | per-module happy + sad path | pytest + tmp_path |
| Determinism | bit-exact re-run | pytest + SHA-256 |
| R-parity | numerical-tolerance vs. R outputs | pytest + a frozen R-output fixture set |
| CLI | smoke tests | pytest + `click.testing.CliRunner` |

### 15.2 Fixtures

- `tests/fixtures/sessions/tiny_v5/` — a 200-frame, 4-animal synthetic
  idtracker.ai folder (committed; ≤ 50 KB).
- `tests/fixtures/r_outputs/` — golden CSVs from the user's
  `checked_sessions_choice_exp` pipeline (open question §5 — needs the
  user to confirm a session that may be redistributed).

### 15.3 Reference R-parity matrix

| Metric | Tolerance | Notes |
|---|---|---|
| Speed (cm/s) | abs ≤ 1e-6 | identical interpolation order |
| NND, IID (px) | abs ≤ 1e-6 | identical pairwise distance |
| Polarisation | abs ≤ 1e-6 | identical heading definition |
| Hull area | rel ≤ 1e-5 | qhull vs. R `chull` rounding |
| Zone time | exact (counts) | identical PIP results required |
| Zone transitions | exact | NN-matched logic must match |

---

## 16. Extension points (summary)

| What | How | Where documented |
|---|---|---|
| New reader (different tracker) | Subclass `SessionReader`, register via `track2data.readers` entry point | §5, §11 |
| New metric | Subclass `Metric`, register via `track2data.metrics` | §8, §11 |
| New exporter | Subclass `Exporter`, register via `track2data.exporters` | §9, §11 |
| New preprocessing step | Add a `Preprocessor` implementation + insert in `pipeline.run` (config-driven order is a v1.1 candidate) | §7 |
| Custom canonical metadata field | Append to `metadata.schema.CANONICAL` via plug-in init hook | §6 |

---

## 17. Open questions (engine-specific)

- Exact canonical idtracker.ai trajectory-folder layout for current
  releases (the `01_core_pipeline` GOT reader was not available on
  disk to inspect). Mitigation: write `idtrackerai_v5` against the
  documented format and add `_v4` for older outputs; treat as living
  documentation until parity tests pin it down.
- Whether `pyav` is acceptable on all target OSes (Linux wheels are fine;
  macOS/Windows wheels exist). Fallback: `imageio-ffmpeg` for frame
  extraction only.
- Caching key: should preprocess config hash include or exclude
  smoothing parameters when only metric selection changed? Current
  design: yes, include — simpler invalidation; revisit if performance
  hurts.
