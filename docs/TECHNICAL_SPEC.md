# Track2Data — Technical Specification

**Status:** Draft v0.1 (the system-level integration doc)
**Audience:** New engineers, OSS reviewers, packaging maintainers
**Companion docs:**
[`../PRD.md`](../PRD.md) (what & why) ·
[`./USER_WORKFLOW.md`](./USER_WORKFLOW.md) (user journey) ·
[`./ENGINE_DESIGN.md`](./ENGINE_DESIGN.md) (engine internals) ·
[`./UI_DESIGN.md`](./UI_DESIGN.md) (UI internals)

---

## 1. Purpose & scope

This document is the **system-level technical contract** for
Track2Data. It pulls together the four cornerstone areas — UI,
engine, plug-ins, persistence — and adds what is not captured in any
single component doc: tech-stack rationale, whole-system
architecture, the on-disk project format, build and distribution,
and the system-level test pyramid.

### 1.1 What this doc is

- The "read me first" for a new engineer.
- The authoritative answer to: *which libraries, which version,
  which boundary, which file on disk, which CI gate?*
- The migration / versioning policy for plug-ins and the `.t2d.json`
  manifest.

### 1.2 What this doc is **not**

| Question | Where to look |
|---|---|
| What does the product do for users? | [`../PRD.md`](../PRD.md) |
| What does a researcher click, in what order? | [`./USER_WORKFLOW.md`](./USER_WORKFLOW.md) |
| How is module `metrics/group.py` implemented? | [`./ENGINE_DESIGN.md`](./ENGINE_DESIGN.md) §8 |
| How does the idtracker.ai reader handle version / format drift? | [`./IDTRACKERAI_FORMAT_ANALYSIS.md`](./IDTRACKERAI_FORMAT_ANALYSIS.md) |
| What signal does `ProjectStore` emit on calibration change? | [`./UI_DESIGN.md`](./UI_DESIGN.md) §4 |

Where this doc and a component doc disagree, the **component doc
wins** for its own scope; raise an issue to reconcile.

---

## 2. Tech stack & rationale

| Layer | Choice | Version pin | Why this, not the alternative |
|---|---|---|---|
| Language | **Python** | 3.11+ | Already required by `idtracker.ai`; first-class NumPy/SciPy; PEP 604 union types; structural typing via Pydantic v2 |
| Desktop UI toolkit | **PySide6** | 6.6+ | LGPL — allows MIT distribution without GPL entanglement; PyQt6 is GPL and would force project relicensing |
| UI async / threading | **QThreadPool + ProcessPoolExecutor** (`qasync` deferred to v1.1) | stdlib | `qasync` integration adds complexity in MVP; QThreadPool covers UI-side I/O, ProcessPoolExecutor covers CPU work |
| Data models | **Pydantic v2** | 2.0+ | Fast (Rust core), declarative, `arbitrary_types_allowed` for numpy arrays, native JSON round-trip |
| Numerics | **NumPy / SciPy** | numpy 1.26+, scipy 1.11+ | Foundation libraries; deterministic when BLAS threads = 1 |
| Tabular | **Pandas** | 2.0+ | Standard; `to_parquet` / `to_feather` via pyarrow |
| Geometry | **Shapely** | 2.0+ | Industry-standard polygon ops; vectorised in v2 |
| Excel | **openpyxl** | latest | Pure Python; supports multi-sheet `.xlsx` |
| Parquet / Feather | **pyarrow** | latest | R-readable via `arrow::read_feather`; cross-language |
| Video frames | **pyav** | latest | Cross-platform wheels (Win/macOS/Linux); fallback: `imageio-ffmpeg` |
| CLI | **click** | 8.x | Decorator-based, mature; covers headless `track2data run` |
| Plots (static) | **matplotlib** | 3.8+ | Publication-style charts |
| Plots (interactive) | **pyqtgraph** | latest | Fast pan/zoom on the trajectory canvas |
| Logging | **stdlib `logging`** + optional **structlog** in v1.1 | stdlib | Keep deps light at MVP |
| Hashing | **stdlib `hashlib`** | stdlib | SHA-256 only |
| Build backend | **hatchling** | latest | Modern PEP 517 backend; simpler than setuptools |
| Binary packaging | **PyInstaller** | 6.x | Mature, signed-binary support; one-file distribution |
| Tests | **pytest** + **pytest-cov** + **hypothesis** | latest | Coverage gating + property tests for numeric algorithms |
| Lint / format | **ruff** | latest | Single tool replaces flake8 + isort + pyupgrade + bandit-lite |
| Type check | **mypy** (advisory; pydantic enforces at runtime) | latest | Optional CI gate at start, enforced post-v1.0 |

**Headline picks**

1. **PySide6** (LGPL) so the app stays MIT.
2. **Pydantic v2** for all cross-module payloads + JSON serialisation.
3. **PyInstaller** for shippable binaries; `pip install` for advanced
   users.
4. **Plug-in via `importlib.metadata` entry points** — no custom
   loader, no eval, no monkey-patching.

---

## 3. System architecture

### 3.1 Whole-system view

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Track2Data Desktop App                         │
│                                                                      │
│  ┌────────────────────────┐         ┌────────────────────────────┐   │
│  │   PySide6 UI layer     │         │   track2data.api.Engine    │   │
│  │   • QMainWindow        │◀───────▶│   (facade)                 │   │
│  │   • QStackedWidget     │  Pydantic models +                   │   │
│  │   • ProjectStore       │  numpy arrays                        │   │
│  │   • TaskRunner         │         └─────────────┬──────────────┘   │
│  │   • RunLogDock         │                       │                  │
│  └────────────────────────┘                       ▼                  │
│            ▲                          ┌───────────────────────────┐  │
│            │                          │  Engine subsystems        │  │
│            │ Engine                   │  ────────────────────────  │  │
│            │ logging                  │  readers/                  │  │
│  ┌─────────┴────────────┐             │  metadata/                 │  │
│  │  track2data.cli       │───────────▶│  calibration/              │  │
│  │  (headless run path) │             │  zones/                    │  │
│  └──────────────────────┘             │  preprocess/               │  │
│                                       │  metrics/                  │  │
│                                       │  exporters/                │  │
│                                       │  cache/                    │  │
│                                       └─────────────┬─────────────┘   │
│                                                     ▼                 │
│                                       ┌────────────────────────────┐  │
│                                       │  Plug-in entry points      │  │
│                                       │  • track2data.readers      │  │
│                                       │  • track2data.metrics      │  │
│                                       │  • track2data.exporters    │  │
│                                       └────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
            │                                          │
            ▼                                          ▼
    Filesystem persistence                  ProcessPoolExecutor
    • session_*/ (read-only)                (per-session parallelism;
    • <project>.t2d.json                     BLAS pinned to 1 thread)
    • <project>/.t2d_cache/
    • <project>/exports/<timestamp>/
```

### 3.2 Boundary contracts

| Boundary | Types crossing it | Direction |
|---|---|---|
| UI ↔ Engine | Pydantic models (`Session`, `ProjectManifest`, `*Config`); numpy arrays inside `Session.raw_xy` | both |
| Engine ↔ Plug-in | ABCs (`SessionReader`, `Metric`, `Exporter`); plug-ins return Pydantic models or pandas DataFrames | both |
| Engine ↔ Filesystem | `Path` objects; JSON; NumPy `.npy`; Feather; CSV; XLSX | both |
| Engine ↔ Workers | Pickled `Session` + `PreprocessConfig` over `ProcessPoolExecutor`; results returned as Pydantic models | both |
| CLI ↔ Engine | Same as UI ↔ Engine | both |

**Key rule:** the engine never imports from `track2data.api` to call
back into the UI — UI subscribes to engine log callbacks; engine
never knows the UI exists. This keeps the engine usable from CLI
and from notebooks.

### 3.3 Threading & process model

- **UI thread** — owns Qt event loop; ProjectStore lives here.
- **QThreadPool workers** (I/O-bound) — folder enumeration,
  metadata file load, preview-frame extraction.
- **ProcessPoolExecutor workers** (CPU-bound) — preprocessing +
  metric computation per session. Worker cap:
  `min(user_setting, os.cpu_count() - 1, 8)`. Inside each worker:
  `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` for determinism (NFR-6).

---

## 4. Repository layout

```
Track2Data/
├── pyproject.toml              # build, deps, entry points
├── README.md
├── PRD.md
├── LICENSE                     # MIT
├── docs/
│   ├── TECHNICAL_SPEC.md       # this file
│   ├── ENGINE_DESIGN.md
│   ├── UI_DESIGN.md
│   └── USER_WORKFLOW.md
├── track2data/                 # the Python package (pure-Python engine)
│   ├── __init__.py
│   ├── api.py                  # Engine facade
│   ├── cli.py                  # click CLI
│   ├── core/                   # models, errors, hashing, manifest, parallel
│   ├── readers/                # idtracker.ai readers + base ABC
│   ├── metadata/               # load + mapping + join
│   ├── calibration/            # scalar + body-length
│   ├── zones/                  # IO + geometry + orientation pairing
│   ├── preprocess/             # gap-fill, jump, ID-switch, smoothing, gate
│   ├── metrics/                # IL/GL/Z metrics + identity-free
│   ├── exporters/              # CSV long/wide, Excel, Feather, README
│   ├── cache/                  # content-addressed feather cache
│   └── reference/              # canonical column registry, default params
├── ui/                         # PySide6 layer (added in next phase)
│   ├── app.py                  # entry point
│   ├── main_window.py
│   ├── store/                  # ProjectStore + TaskRunner
│   └── pages/                  # one widget per wizard page
├── tests/                      # mirrors track2data/ + ui/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── sessions/tiny_v5/   # synthetic 100-frame, 4-animal session
│   │   └── r_outputs/          # golden CSV for parity tests
│   ├── test_core/
│   ├── test_readers/
│   └── test_r_parity/
└── packaging/                  # PyInstaller specs + installer scripts
    ├── track2data.spec
    └── README.md
```

**`ui/` lives outside `track2data/` deliberately** so that the
engine remains a clean, UI-free `pip install track2data` library.

---

## 5. Module map (cross-reference)

| System concern | Module(s) | Deep-dive |
|---|---|---|
| Project manifest read/write | `track2data/core/manifest.py`, `core/models.py::ProjectManifest` | ENGINE_DESIGN §4 |
| idtracker.ai ingestion | `track2data/readers/idtrackerai_v5.py`, `readers/__init__.py` | ENGINE_DESIGN §5 |
| Metadata load + map + join | `track2data/metadata/` | ENGINE_DESIGN §6 |
| Calibration | `track2data/calibration/` | ENGINE_DESIGN §5 (PRD §5.3) |
| Zones (CSV ↔ geometry ↔ assignment) | `track2data/zones/` | ENGINE_DESIGN §3, §15 |
| Preprocessing pipeline | `track2data/preprocess/` | ENGINE_DESIGN §7 |
| Metrics (IL, GL, Z, identity-free) | `track2data/metrics/` | ENGINE_DESIGN §8 |
| Export (CSV/XLSX/Feather + README) | `track2data/exporters/` | ENGINE_DESIGN §9 |
| Caching | `track2data/cache/` | ENGINE_DESIGN §10 |
| Plug-in discovery | `track2data/{readers,metrics,exporters}/__init__.py` | ENGINE_DESIGN §11 |
| CLI | `track2data/cli.py` | ENGINE_DESIGN §12 |
| Errors | `track2data/core/errors.py` | ENGINE_DESIGN §13 |
| Concurrency | `track2data/core/parallel.py` | ENGINE_DESIGN §14 |
| UI shell & wizard | `ui/main_window.py`, `ui/pages/` | UI_DESIGN §3, §5 |
| UI state + tasks | `ui/store/project_store.py`, `ui/store/task_runner.py` | UI_DESIGN §4, §7 |

---

## 6. End-to-end data flow

A complete run, from user action to byte-on-disk:

```
User clicks "Add folder"  ──►  ui/pages/sessions_page.py
                              │
                              ▼  TaskRunner.submit
                          track2data.api.Engine.import_session(folder)
                              │
                              ▼  readers/__init__.detect_reader
                          IDTrackerAiV5Reader.read(folder)
                              │  numpy.load (.npy) + read .json
                              ▼
                          Session(raw_xy, video, n_animals, …)
                              │
                              ▼  emit log + ProjectStore.sessionsChanged
                          UI updates session table

User clicks Run pipeline   ──►  ui/main_window.run_pipeline()
                              │
                              ▼  TaskRunner submits per-session jobs
                          ProcessPoolExecutor (n=min(cpu-1, 8))
                              │ per-session:
                              ▼
                          preprocess.pipeline.run(session, cfg)
                              │
                              ▼ cache lookup by SHA-256(reader + folder + cfg)
                          metrics.compute_all(preprocessed, selection)
                              │
                              ▼ pandas DataFrames
                          exporters.write_all(payload, out_dir)
                              │
                              ▼ files written with deterministic sort
                          manifest.json + per-file SHA-256 + run_log.md
                              │
                              ▼
                          UI shows reproducibility receipt
```

---

## 7. Project file format — `.t2d.json`

### 7.1 Top-level schema (v1)

```json
{
  "schema_version": 1,
  "app_version": "0.1.0",
  "project_name": "feb-experiment",
  "folder": "D:/projects/feb-experiment",
  "created_at": "2026-05-14T14:00:00Z",
  "updated_at": "2026-05-14T14:08:31Z",
  "sessions": [
    {
      "session_id": "session_N1_T1",
      "folder": "D:/raw/session_N1_T1",
      "trajectory_sha256": "a4f1...3c",
      "reader": "idtrackerai_v5"
    }
  ],
  "calibration": {
    "mode": "bodylength",
    "px_per_cm": null,
    "bl_min_samples": 30
  },
  "zones": {
    "rois": [{"name": "flow", "level": "main", "vertices": [], "area_units": 12.4}],
    "orientation_tag": "FT",
    "zone_levels": {"flow": "main", "calm": "main", "centre": "secondary"}
  },
  "metadata_source": {
    "path": "D:/data/trial_meta.xlsx",
    "sha256": "9aa2...8c"
  },
  "mapping": {
    "rules": [
      {"source": "video_id", "canonical": "session_id"},
      {"source": "condition", "canonical": "treatment", "alias": "condition->treatment"}
    ],
    "join_key": "session_id"
  },
  "preprocess": {
    "gap_fill": {"enabled": true, "max_gap_frames": 30},
    "jump":     {"enabled": true, "method": "sd_multiple", "sd_mult": 10.0, "replacement": "linear_interp"},
    "identity_switch": {"enabled": true, "tier1_ratio": 1.5, "tier2_hungarian": true},
    "smoothing": {"enabled": true, "method": "savgol", "window": 5, "polyorder": 2},
    "coverage":  {"min_track_frames": 0, "max_pct_na_per_individual": 0.10}
  },
  "metrics": {
    "individual": ["IL-1", "IL-2", "IL-4"],
    "group":      ["GL-1", "GL-3"],
    "zone":       ["Z-1", "Z-3"],
    "diagnostic": [],
    "timepoint_minutes": 20,
    "quality_threshold": 0.0
  },
  "export_targets": [
    {"name": "csv_long",  "enabled": true},
    {"name": "csv_wide",  "enabled": true},
    {"name": "excel",     "enabled": true},
    {"name": "feather",   "enabled": false}
  ],
  "run_log_path": "D:/projects/feb-experiment/run_log.md"
}
```

The canonical Pydantic models live in `core/models.py`; the JSON
above is what `ProjectManifest.model_dump_json()` produces.

### 7.2 Versioning policy

- `schema_version` is bumped on **breaking** changes only.
- Minor schema changes (new optional fields) read older files via
  Pydantic field defaults — **no migration needed**.
- A new major version registers a migration in
  `core/manifest.py::MIGRATIONS = {1: migrate_v0_to_v1, …}` and
  records the upgrade in the run log (PRD DV-6).
- Reading a manifest with `schema_version > current` raises
  `ConfigError(code="SCHEMA_TOO_NEW", remediation="Upgrade Track2Data to read this project.")`.

### 7.3 Project hash

`ProjectManifest.project_hash()` returns a 16-char hex SHA-256 of the
model dumped with `created_at` / `updated_at` **excluded**. Identical
parameter sets across machines therefore hash identically — the
project hash is the unique key for reproducibility.

---

## 8. Configuration hierarchy

Resolution order (first hit wins):

| Source | Where | Use |
|---|---|---|
| CLI flag | `track2data run --workers 4 …` | Override anything for a single headless run |
| Project manifest | `<project>.t2d.json` | Per-project settings (calibration, zones, metric selection, …) |
| User settings | `QSettings` (`~/.config/Track2Data` or platform equivalent) | Last-used theme, recent projects, default worker cap |
| Built-in defaults | `track2data/reference/default_params.py` | Fallback values |

**Rule:** the engine never reads `QSettings` directly — the UI is
the only consumer. CLI flags map onto the same `Engine` setter
methods the UI uses, so the same code path is exercised.

---

## 9. Logging & error handling

Full hierarchy lives in `core/errors.py` (ENGINE_DESIGN §13). The
system-level policy:

| Severity | Engine API | UI affordance | Headless exit |
|---|---|---|---|
| `info` | logged at INFO | status-bar toast (3 s) | logged only |
| `warning` | raised as `Track2DataError` w/ severity=warning | yellow banner | logged; exit 0 |
| `error` | raised as `Track2DataError` w/ severity=error | modal w/ remediation | exit 2 |
| programming bug | bare Python exception | modal with "Copy details" + traceback | exit 1 |

Every error carries `code`, `subject`, `remediation`. The
USER_WORKFLOW.md §6 catalogue is the authoritative list of
user-facing codes; new codes added to engine/UI must be appended
there in the same PR.

**Log destinations:**
- stdout (CLI runs) — plain text or JSONL via `--json-logs`.
- `<project>/run_log.md` (Markdown, append-only).
- UI RunLogDock (in-memory, mirrors `run_log.md`).

---

## 10. Build, packaging, distribution

### 10.1 Source distribution

```
pip install track2data           # engine only, no UI
pip install "track2data[ui]"     # adds PySide6, pyav, pyqtgraph
pip install "track2data[dev]"    # adds pytest, ruff, hypothesis
```

`pyproject.toml` declares the extras; the engine is importable
without PySide6 so headless / notebook users have a small install.

### 10.2 Desktop binaries

Built with **PyInstaller**:

- `packaging/track2data.spec` — pinned to PyInstaller 6.x.
- One-file build per OS (`--onefile`):
  - Windows: `Track2Data-setup.exe` (Inno Setup wraps the `.exe`).
  - macOS: `.dmg` containing `Track2Data.app` (v1.1 will notarize).
  - Linux: `.AppImage`.
- Build matrix runs on **CI per release tag** (`v*`):
  - GitHub Actions: `windows-2022`, `macos-13`, `ubuntu-22.04`.
- Artefacts uploaded to a GitHub Release; SHA-256 sums published in
  the release notes for reviewer verification.

### 10.3 Code signing

| OS | v1.0 | v1.1 plan |
|---|---|---|
| Windows | unsigned (SmartScreen warning) | Authenticode (DigiCert / certum) |
| macOS | unsigned + Gatekeeper bypass instructions | Apple Developer ID + notarization |
| Linux | unsigned `.AppImage` | optional GPG-detached sig |

The README documents the unsigned-binary trust path for v1.0.

### 10.4 Update strategy

- v1.0: manual download from GitHub Releases (no in-app updater).
- v1.1: opt-in "Check for updates" command (Help menu) hits the
  GitHub Releases API; no automatic background polling (NFR — no
  telemetry / no background network).

---

## 11. Testing strategy

### 11.1 Test pyramid

```
            ┌─────────────────────┐
            │  E2E (UI + engine)  │   ~5 tests (one per wizard happy path)
            ├─────────────────────┤
            │  Integration        │   ~20 tests (per subsystem)
            ├─────────────────────┤
            │  R-parity           │   ~25 tests (golden CSV)
            ├─────────────────────┤
            │  Unit               │   >= 200 tests (>= 80 % line coverage)
            └─────────────────────┘
```

Tools: `pytest`, `pytest-cov` (gate >= 80 %), `hypothesis` for
property-based numeric tests, `pytest-qt` for UI integration,
`click.testing.CliRunner` for CLI smoke tests.

### 11.2 R-parity tests

Golden CSV fixtures in `tests/fixtures/r_outputs/` capture the
expected reader / metric outputs against a tiny synthetic session.
Tolerances:

| What | Tolerance |
|---|---|
| Reader fields (FPS, frame, shape) | exact |
| Trajectory values | atol = 1e-9 |
| Speed / kinematics | atol = 1e-6 |
| NND, IID, polarisation | atol = 1e-6 |
| Hull area | rtol = 1e-5 (qhull vs R `chull` rounding) |
| Zone counts / transitions | exact |

### 11.3 CI gates

| Stage | Trigger | Must pass |
|---|---|---|
| Lint | every push | `ruff check .` |
| Unit + integration | every push | `pytest tests/ -m "not r_parity"` |
| R-parity | every push | `pytest tests/ -m r_parity` |
| Coverage | every push | `pytest --cov=track2data --cov-fail-under=80` |
| Build matrix | release tags | PyInstaller binaries x 3 OS |
| Determinism | release tags | re-run fixture project, byte-diff outputs |

### 11.4 Determinism gate

A dedicated job runs the same project file twice in fresh temp
directories and asserts byte-identical CSV / Feather output
(timestamps inside `manifest.json` masked). Any drift fails the
release (NFR-6 + PRD DV-5).

---

## 12. Extensibility & plug-in compatibility

### 12.1 Three entry-point groups

| Group | ABC | Discovery |
|---|---|---|
| `track2data.readers` | `SessionReader` | `readers/__init__.py::_load_entry_points()` |
| `track2data.metrics` | `Metric` | `metrics/__init__.py` (planned) |
| `track2data.exporters` | `Exporter` | `exporters/__init__.py` (planned) |

External packages declare entry points in their own `pyproject.toml`:

```toml
[project.entry-points."track2data.metrics"]
my-metric = "my_pkg.my_metric:MyMetric"
```

### 12.2 Compatibility policy (semver-aligned)

| Change | Allowed in minor | Requires major bump |
|---|---|---|
| Add a method to an ABC with a default | yes | — |
| Add a field to a Pydantic model with a default | yes | — |
| Remove a method from an ABC | no | yes |
| Remove / rename a Pydantic field | no | yes |
| Change a method signature | no | yes |
| Tighten a default tolerance | document in release notes | — |

External plug-ins are loaded behind a `try/except` and **never crash
the engine** — failures surface as a warning in the run log
(ENGINE_DESIGN §5.3).

### 12.3 Versioned IDs

Built-in metric IDs (`IL-1..IL-8`, `GL-1..GL-10`, `Z-1..Z-6`, and the
diagnostic series `D-1..D-5`) are reserved. The full canonical
catalogue lives in [`./METRICS_SPEC.md`](./METRICS_SPEC.md) §4 —
adding or renaming a built-in ID requires a corresponding section
there. Plug-ins must use their own namespace (`mypkg/IL-1`); the
registry rejects duplicates and emits
`ConfigError(code="METRIC_ID_CONFLICT")`.

`D-*` diagnostic metrics are auto-computed for every session
regardless of `MetricSelection.diagnostic`, and are emitted as a
sibling `quality.csv` alongside the main metrics CSV (plus a "Quality"
sheet in the Excel export).

---

## 13. Performance & resource limits

Mapping PRD NFRs to enforced behaviour:

| NFR | Where enforced |
|---|---|
| NFR-3 (<= 3 min for 60-min, 8-fish, 30-fps session) | `core/parallel.py` per-session pool + cached preprocess output |
| NFR-4 (<= 4 GB RSS for 60-min, 16-fish) | stream trajectories via NumPy memmap when > 500 MB; chunked metric computation |
| NFR-5 (worker cap) | `worker_count()` in `core/parallel.py` |
| NFR-6 (determinism) | per-worker BLAS pinning, sorted CSV output, fixed numpy rng seeds in any algorithm that uses them |
| NFR-7 (accessibility) | UI_DESIGN §9 — keyboard nav + screen-reader labels |
| NFR-8 (i18n / locale) | force `.` decimal + ISO-8601 dates in exporters |
| NFR-9 (logging) | stdout + run_log.md + RunLogDock |
| NFR-11 (>= 80 % coverage) | CI gate `--cov-fail-under=80` |

---

## 14. Open questions

1. **macOS notarization** — v1.0 ships unsigned; v1.1 plan above.
   Confirm the Apple Developer ID is acquirable for the project
   maintainer.
2. **GPU acceleration** — explicitly out of scope at MVP (NFR C3).
   Re-evaluate when a session exceeds 4 h x 30 fish; CuPy could
   accelerate KD-tree NND.
3. **Plugin marketplace** — deferred to v1.4. v1.0 plug-ins are
   installable only via `pip`.
4. **Schema migrations** — current model is forward-compatible reads
   only. If we change the calibration model in v2, write
   `migrate_v1_to_v2` before bumping.
5. **`qasync` migration** — defer to v1.1; TaskRunner with
   QThreadPool / ProcessPoolExecutor covers MVP. Re-evaluate if any
   metric needs streaming progress at sub-second granularity.
6. **CI Windows** — PyInstaller + Inno Setup on `windows-2022`
   runner; verify path-length and `pyav` wheel availability.
