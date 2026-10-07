# Critical issues audit: findings and resolution

An external audit listed 15 issues. Each was checked against the code at commit `0b9b860` before
anything was changed; several claims were stale or wrong. This file records what was true, what was
done, and what is still open. Paths are repo-relative. Details: `CHANGELOG.md` and the decision
numbers below in `DECISIONS.md`.

| ID | Area | Sev | Finding at `0b9b860` | Status | Resolution |
|---|---|:-:|---|---|---|
| SCI-01 | Science | P0 | Audit said "fixed"; it was **not**. Body-length calibration stored pixels in `body_length_cm` and left `px_per_cm` unset, and every `*_bl` output sat under `if px_per_cm is not None`, so it was always NaN. Tests built sessions with both values, which no real path produces. | **Fixed** (D-015) | `*_bl = value_px / body_length_px`, independent of `px_per_cm` and of the calibration mode. New `PreprocessedSession.body_length_px`. |
| SCI-02 | Science | P1 | All nine zone metrics emitted per-slot rows on identity-free sessions. | **Fixed** (D-016) | Z-1, Z-2, Z-8 (pure occupancy) are pooled without `individual_id`; Z-3, Z-4, Z-5, Z-6, Z-7, Z-9 follow a slot across frames and now require identity. |
| SCI-03 | Science | P2 | Metadata join is per session; a per-animal value would be copied onto every animal (D-010). | **Open by design** | Needs a composite `(session_id, individual_id)` join, which reverses D-010. The Metadata screen shows *Individual ID* disabled and the guide says to join per-animal data after export. |
| PERF-01 | Engine | P1 | `Engine.run` forced `n_workers=1`. | **Fixed** (D-020) | Spawn process pool; workers get the manifest JSON, progress returns over a queue. **Not benchmarked on real long sessions**; on tiny test sessions it is slower because start-up dominates. Default stays 1. |
| PERF-02 | Engine | P1 | `CacheStore` stored flat DataFrames and was unused (a documented deferral, not a bug). | **Fixed** (D-019) | Preprocessed sessions cached on disk, keyed by a folder fingerprint and the preprocessing/calibration/zone settings. |
| PERF-03 | Engine | P2 | Importing a session ran a full `read_session`. | **Partly fixed** (D-018) | `SessionReader.probe()` skips bbox tables, matching results, fragments and the log; reopening a project re-probes. The trajectory payload is still read (identity status needs it). Probes still share the single-thread task pool. |
| PERF-04 | Engine | P2 | Per-frame CSV copied and re-sorted the table, then wrote it in one go. | **Fixed** | Chunked write, no copy; traced peak memory halves (133 MB to 67 MB on 2.16 M rows), output byte-identical. Excel splits the table across sheets past its row limit. |
| GUI-01 | UX | P1 | Calibration, Preprocessing, Metadata and Metrics needed an Apply click; navigating away dropped edits. | **Fixed** (D-017) | Debounced auto-commit and a flush when leaving a screen. |
| GUI-02 | UX | P1 | No screen drew a trajectory. | **Fixed** (D-022) | Preview ▸ Trajectories: scrub/play, trails, raw vs processed, zones, occupancy heatmap. Built on Qt graphics items, not pyqtgraph. |
| GUI-03 | UX | P2 | `WizardSidebar.mark_complete` was never called; Next was ungated; creating a project did not advance. (The audit named `ui/widgets/wizard_nav.py`, which does not exist; the sidebar is `app/navigation.py`.) | **Fixed** (D-021) | ✓/⚠/✗/○ badges with tooltips; Next gated with a reason; create/open moves to Sessions. |
| GUI-04 | UX | P2 | Zone canvas had no edges, fill, saved-zone display, zoom/pan or undo. (There was no right-click-to-finish handling to fix.) | **Fixed** | Edges and fill, saved zones shown, wheel zoom, middle-drag pan, Fit, Undo/Ctrl+Z, Rectangle and Circle tools, draggable vertices. |
| GUI-05 | UX | P2 | Cancel was only noticed at stage-boundary events. | **Fixed** (D-020) | `Engine.run(cancel_check=...)` is polled between sessions, preprocessing steps and metrics. A single numpy/shapely call still cannot be interrupted. |
| ENG-01 | Engine/GUI | P2 | The Preprocessing screen had no identity-switch controls and rebuilt `PreprocessConfig` on every apply, resetting `identity_switch`, `jump.pct_mult`, `smoothing.polyorder`, `coverage.min_track_frames`. | **Fixed** | Controls added (default off, with a risk warning); updates use `model_copy`; the velocity-threshold jump method is selectable. |
| ENG-02 | Engine | P2 | The v4 reader is a stub (documented, D-012) but docs advertised v4 support. | **Resolved by documentation** | Docs say v4 is not supported yet. Implementing it needs sample data. |
| DIST-01 | Distribution | P2 | Binaries are unsigned. | **Open, blocked** | Signing is wired in `release.yml` but needs certificates and a published release (`docs/CODE_SIGNING.md`). |

## Also fixed along the way

- Metadata screen: only four fields, no alias matching, no match feedback, blank after reopening a
  project. Now all canonical fields, aliases, "N of M sessions matched", and it repopulates.
- Metrics screen: search, presets, a selection counter, a note that diagnostics always run.
- Calibration screen: two-point "Measure on frame" ruler; body-length summary.
- Export screen: R and Python code to load the files; the page scrolls instead of clipping.
- The status bar did not update its session count when sessions were added.
- Screens built after a project was loaded did not read the store, so their first auto-commit could
  overwrite stored values with widget defaults.
- Help ▸ Open user guide (previously a placeholder).
- New: user guide with screenshots in `docs/guide/`.

## Still open

- Per-animal metadata (SCI-03).
- `MetricSelection.timepoint_minutes` is stored but never used by the engine, so no binning control is offered.
- Benchmark parallel runs on real data (PERF-01).
- Give session probes their own thread pool (PERF-03).
- idtracker.ai v4 reader (ENG-02) and signed binaries (DIST-01).
