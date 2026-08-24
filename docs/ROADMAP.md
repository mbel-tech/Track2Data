# Track2Data — Implementation Roadmap

**Status:** M1–M4 complete. M5 (v1.0 release) is the only milestone left.
**Last updated:** 2026-08-21

---

## Current state

The engine, the GUI, and the packaging pipeline are all built and green.

| Area | Status |
|---|---|
| Pydantic data models (`Session`, `ProjectManifest`, `PreprocessConfig`, `MetricSelection`) | ✅ Implemented |
| Full error hierarchy (`core/errors.py`) | ✅ Implemented |
| Manifest read/write + migration (`core/manifest.py`) | ✅ Implemented |
| Unified idtracker.ai reader (`readers/idtrackerai/`) — h5 / npy / csv | ✅ Implemented; 70/70 real corpus sessions import |
| Behavioural metrics | ✅ 33 registered (IL-1..8, GL-1..10, Z-1..6, D-1..9) |
| Exporters | ✅ 5 (`csv_long`, `csv_wide`, `excel`, `feather`, `readme`) |
| Metadata join wired into `Engine` | ✅ Implemented |
| Desktop GUI (`app/` + `ui/`) | ✅ Wizard wired end-to-end to the engine |
| Standalone binaries (Windows / macOS / Linux) | ✅ Built + validated in CI |
| Test suite | ✅ ~1170 passing (plus `r_parity` and `corpus_local` gates) |
| CI workflow | ✅ Green across a 6-cell OS × Python matrix |

Remaining work is release mechanics, not implementation — see **M5** below.

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

## M1 — Engine foundation ✅ complete

**Goal:** `track2data run project.t2d.json` produces a correct CSV for the `tiny_v5` fixture.

**Exit criteria:**
- All M1 modules implemented and TDD-green
- `pytest tests/ -m "not r_parity"` passes with coverage ≥ 70 %
- `pytest tests/test_r_parity/ -m "r_parity and not r_parity_local"` passes
- `ruff check .` clean

The coverage floor was temporarily 70% during M1 and was restored to 80%
in M2; it sits well above that in practice.

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

## M2 — Metadata + remaining metrics ✅ complete

**Goal:** Full metric suite + metadata join; R-parity gate enabled for choice-pipeline fixtures (post-embargo).

| Area | Items | Status |
|---|---|---|
| Metadata pipeline | `metadata/{schema,loader,mapping,join}.py`, wired into `Engine` | ✅ |
| Remaining individual metrics | IL-3..IL-8 | ✅ |
| Remaining group metrics | GL-2, GL-4, GL-6, GL-8, GL-9, GL-10 | ✅ |
| Remaining zone metrics | Z-2, Z-4, Z-5, Z-6 | ✅ |
| Additional exporters | `csv_wide.py`, `feather.py` | ✅ |
| Additional diagnostics | D-6..D-9 (fragment-derived; added alongside the reader realignment) | ✅ |
| Coverage gate | Restored to 80 % | ✅ |
| R-parity gate | Enable `r_parity_local` → `r_parity` after embargo lift | ⏳ blocked on the pre-publication embargo, not on code |

---

## M3 — UI layer (PySide6) ✅ complete

**Goal:** Fully functional desktop wizard, wired end-to-end to the engine.

| Area | Items | Status |
|---|---|---|
| State management | `ui/store/project_store.py`, `ui/store/task_runner.py` | ✅ |
| Shell | `app/main.py`, `app/main_window.py`, `app/navigation.py`, `app/state.py` | ✅ |
| Screens (flat in `ui/`, per D-006) | `project`, `import`, `calibration`, `zones`, `metadata`, `metrics`, `preprocessing`, `processing`, `preview`, `export` | ✅ |
| Dialogs / shared widgets | `ui/dialogs/metric_info_dialog.py`, `ui/widgets/dataframe_table.py` | ✅ |
| Testing | `pytest-qt` integration tests per screen, headless via `QT_QPA_PLATFORM=offscreen` | ✅ |

Background execution is `QThreadPool`/`QRunnable` only — no `qasync`
(D-003). The engine never imports PySide6 (D-001).

---

## M4 — Packaging + cross-OS

| Area | Items |
|---|---|---|
| PyInstaller | `packaging/track2data.spec` — onefile build, macOS `.app` bundle | ✅ |
| Release matrix | `.github/workflows/release.yml` — builds Win / macOS / Linux on `v*` tags, publishes a GitHub Release with SHA-256 sums | ✅ validated via `workflow_dispatch` |
| Per-OS packaging | Inno Setup `.exe`, `hdiutil` `.dmg`, `.AppImage` | ✅ |
| Determinism gate | `packaging/check_determinism.py` — byte-diffs two independent runs | ✅ |
| `track2data[ui]` / `[build]` extras | Declared in `pyproject.toml` | ✅ |
| Signed binaries | macOS notarisation, Windows Authenticode | ⏳ deferred to v1.1 (TECHNICAL_SPEC §10.3); v1.0 ships unsigned with a documented trust path in `README.md` |

---

## M5 — v1.0 release

The only milestone with work left. Nothing here is blocked on
implementation.

- [ ] Cross-check `docs/` against implementation (this pass closed the
      known stale items: ROADMAP status, `qasync`, `ui/pages/`,
      entry-point groups, branch-protection wording)
- [ ] Write release notes from `CHANGELOG.md`
- [ ] Decide the first tag: `v0.1.0` (what `pyproject.toml` declares
      today — an honest "first working release") vs. holding the number
      back for a signed, fully-polished `v1.0.0`
- [ ] Cut the semver tag on `main` — this triggers `release.yml`, which
      builds all three binaries and publishes the GitHub Release
- [ ] Switch the repository to public, and enable branch protection on
      `main` at the same time (both require it to be public or Pro —
      see `CONTRIBUTING.md` §4)
- [ ] Code signing — **not** a v1.0 blocker; explicitly deferred to v1.1

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
- [`docs/UI_DESIGN.md`](UI_DESIGN.md) — 14-screen PySide6 GUI specification
