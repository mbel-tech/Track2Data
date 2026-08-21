# Track2Data — Implementation Roadmap

**Status:** M0 foundation complete; M1 in progress.
**Last updated:** 2026-05-18

---

## Current state

Foundation is in place and tested:

| Area | Status |
|---|---|
| Pydantic data models (`Session`, `ProjectManifest`, `PreprocessConfig`, `MetricSelection`) | ✅ Implemented |
| Full error hierarchy (`core/errors.py`) | ✅ Implemented |
| Manifest read/write + migration (`core/manifest.py`) | ✅ Implemented |
| Unified idtracker.ai reader (`readers/idtrackerai/`) — all v4–v6 formats | ✅ Implemented |
| Legacy readers (`idtrackerai_v5`, `idtrackerai_v4`) | ✅ Kept for back-compat |
| Metric abstract base + `MetricDocumentation` | ✅ Implemented |
| Behavioural metrics specification (`docs/METRICS_SPEC.md`) | ✅ 29 metrics specified |
| GUI specification (`docs/UI_DESIGN.md`) | ✅ Specified — 10 screens / 7 stages shipped (`DECISIONS.md` D-005); doc originally scoped 14 |
| Test suite | ✅ 200+ tests passing |
| CI workflow | ✅ Configured |

All remaining modules below are **stubs** — correct skeleton, no logic yet.

---

## Prerequisites for M1 (P0/P1 items — must be complete first)

- [x] `LICENSE` (MIT)
- [x] `CONTRIBUTING.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `docs/ROADMAP.md` (this file)
- [x] `.github/workflows/ci.yml`
- [x] Unified `idtrackerai` reader entry point in `pyproject.toml`
- [x] `r_parity_local` pytest marker registered
- [x] `ENGINE_DESIGN.md` §4 reconciled with implemented models

---

## Module dependency graph

```
core/{hashing,logging,parallel}   ← no deps; used everywhere
reference/{canonical_columns,default_params}
        ↓
readers/idtrackerai/              ← Session output
        ↓
calibration/{scalar,bodylength}
zones/{geometry,io,orientation}
metadata/{loader,mapping,join,schema}
        ↓
preprocess/{kinematics,gap_fill,jump_detect,identity_switch,smoothing,validate}
preprocess/pipeline               ← orchestrates the above
        ↓
metrics/{individual,group,zone,identity_free,diagnostic}
        ↓
exporters/{csv_long,csv_wide,excel,feather,readme}
cache/store
        ↓
cli.py  api.py                    ← public surface
        ↓
ui/ app/                          ← M3 (PySide6 layer)
```

---

## M1 — Engine foundation

**Goal:** `track2data run project.t2d.json` produces a correct CSV for the `tiny_v5` fixture.

**Exit criteria:**
- All M1 modules implemented and TDD-green
- `pytest tests/ -m "not r_parity"` passes with coverage ≥ 70 %
- `pytest tests/test_r_parity/ -m "r_parity and not r_parity_local"` passes
- `ruff check .` clean

**Build order (TDD — each module fully green before moving on):**

| # | Module | Notes |
|---|---|---|
| 1 | `core/hashing.py` | SHA-256 helpers; zero deps |
| 2 | `core/logging.py` | Structured logger + run-log Markdown writer |
| 3 | `core/parallel.py` | `ProcessPoolExecutor` wrapper, worker-cap policy |
| 4 | `reference/canonical_columns.py` | Frozen column-name registry |
| 5 | `reference/default_params.py` | All default parameter values |
| 6 | `preprocess/kinematics.py` | Speed, acceleration, heading |
| 7 | `preprocess/gap_fill.py` | PP-1 linear interpolation |
| 8 | `preprocess/jump_detect.py` | PP-2 SD-multiple + percentile |
| 9 | `preprocess/identity_switch.py` | PP-3 mutual-NN + Hungarian |
| 10 | `preprocess/smoothing.py` | PP-4 moving-avg + Savitzky-Golay |
| 11 | `preprocess/validate.py` | PP-5 coverage gate |
| 12 | `preprocess/pipeline.py` | Ordered preprocessor chain |
| 13 | `calibration/scalar.py` | px-per-cm scalar mode |
| 14 | `calibration/bodylength.py` | Per-session body-length normalisation |
| 15 | `zones/geometry.py` | Shapely polygon ops, PIP, area |
| 16 | `zones/io.py` | CSV ↔ `ZoneSet` round-trip |
| 17 | `zones/orientation.py` | FT/FD orientation pairing |
| 18 | `metrics/individual.py` | IL-1 path length, IL-2 speed first; others incremental |
| 19 | `metrics/group.py` | GL-1 NND, GL-3 polarisation, GL-5 centroid speed |
| 20 | `metrics/zone.py` | Z-1 time in zone, Z-3 visits |
| 21 | `metrics/identity_free.py` | GL-7 NN-matched speed |
| 22 | `metrics/diagnostic.py` | D-1..D-5 always-on diagnostics |
| 23 | `exporters/csv_long.py` | Primary long-format CSV |
| 24 | `exporters/readme.py` | Human-readable run README |
| 25 | `exporters/excel.py` | Multi-sheet xlsx |
| 26 | `cache/store.py` | Content-addressed Parquet cache |
| 27 | `cli.py` | `track2data run / validate / list-metrics / cache clear / new` |
| 28 | `api.py` | Engine facade wired end-to-end |

---

## M2 — Metadata + remaining metrics

**Goal:** Full metric suite + metadata join; R-parity gate enabled for choice-pipeline fixtures (post-embargo).

| Area | Items |
|---|---|
| Metadata pipeline | `metadata/{schema,loader,mapping,join}.py` |
| Remaining individual metrics | IL-3..IL-8 |
| Remaining group metrics | GL-2, GL-4, GL-6, GL-8, GL-9, GL-10 |
| Remaining zone metrics | Z-2, Z-4, Z-5, Z-6 |
| Additional exporters | `csv_wide.py`, `feather.py` |
| R-parity gate | Enable `r_parity_local` → `r_parity` after embargo lift |
| Coverage gate | Restore to 80 % (from temporary 70 % in M1) |

---

## M3 — UI layer (PySide6)

**Goal:** Fully functional desktop wizard matching the 10-screen/7-stage layout in `docs/UI_DESIGN.md` (`DECISIONS.md` D-005).

| Area | Items |
|---|---|
| State management | `ui/store/project_store.py`, `ui/store/task_runner.py` |
| Shell | `app/main.py`, `app/main_window.py`, `app/navigation.py`, `app/state.py` |
| Pages | `ui/project_screen.py`, `ui/import_screen.py`, `ui/calibration_screen.py`, `ui/zones_screen.py`, `ui/metadata_screen.py`, `ui/metrics_screen.py`, `ui/export_screen.py` |
| Dialogs | `ui/dialogs/metric_info_dialog.py` |
| Testing | `pytest-qt` integration tests for each page |

---

## M4 — Packaging + cross-OS

| Area | Items |
|---|---|
| PyInstaller | `packaging/track2data.spec` + entry-point freeze |
| Release matrix | GitHub Actions build + upload for Win / macOS / Linux |
| Signed binaries | macOS notarisation, Windows Authenticode (deferred if complex) |
| `track2data[ui]` extra | Declared in `pyproject.toml` |

---

## M5 — v1.0 release

- Code signing completed
- Release notes written
- `docs/` finalised and cross-checked against implementation
- Semver tag `v1.0.0` on `main`

---

## Out of MVP (post-v1.0)

| Feature | Rationale for deferral |
|---|---|
| `qasync` / `async def` engine methods | Requires API-shape change; QThreadPool sufficient for v1.0 |
| Statistics module (ANOVA, GLMM, etc.) | Out of scope; separate package |
| Plug-in marketplace / registry UI | Needs stable API surface first |
| GPU acceleration | No user requirement yet |
| Telemetry | Explicitly opted out (no telemetry policy) |
| R runtime integration | Engine is pure-Python by design |

---

## Repository visibility

Private until v1.0 release. Switch to public after M5 tag is cut.

---

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — dev setup, TDD workflow, branch policy
- [`docs/TECHNICAL_SPEC.md`](TECHNICAL_SPEC.md) — system architecture, testing strategy
- [`docs/ENGINE_DESIGN.md`](ENGINE_DESIGN.md) — engine internals and module layout
- [`docs/METRICS_SPEC.md`](METRICS_SPEC.md) — 29 behavioural metrics with formulas and citations
- [`docs/UI_DESIGN.md`](UI_DESIGN.md) — PySide6 GUI specification (10 screens / 7 stages shipped; `DECISIONS.md` D-005)
