# Track2Data — Implementation Roadmap

**Status:** M1–M4 complete. M5 (v1.0 release) is the only milestone left.
**Last updated:** 2026-08-21

---

## Completed milestones

M1 (engine foundation), M2 (metadata + remaining metrics) and M3 (the
PySide6 UI layer) are done. Their task lists lived here and are now
redundant three ways over: `CHANGELOG.md` records what shipped, the issue
tracker records what is open, and `docs/dev/DECISIONS.md` records why. Three
places to update meant two went stale — see the git history for the original
breakdowns.

---

## Current state

The engine, the GUI, and the packaging pipeline are all built and green.

| Area | Status |
|---|---|
| Pydantic data models (`Session`, `ProjectManifest`, `PreprocessConfig`, `MetricSelection`) | ✅ Implemented |
| Full error hierarchy (`core/errors.py`) | ✅ Implemented |
| Manifest read/write + migration (`core/manifest.py`) | ✅ Implemented |
| Unified idtracker.ai reader (`readers/idtrackerai/`) — h5 / npy / csv | ✅ Implemented; 70/70 real corpus sessions import |
| Behavioural metrics | ✅ 45 registered (IL-1..11, IL-14, GL-1..11, GL-13, GL-15, Z-1..9, D-1..11) |
| Exporters | ✅ 5 (`csv_long`, `csv_wide`, `excel`, `feather`, `readme`) |
| Metadata join wired into `Engine` | ✅ Implemented |
| Desktop GUI (`app/` + `ui/`) | ✅ Wizard wired end-to-end to the engine |
| Standalone binaries (Windows / macOS / Linux) | ✅ Built + validated in CI |
| Test suite | ✅ ~1170 passing (plus `r_parity` and `corpus_local` gates) |
| CI workflow | ✅ Green across a 6-cell OS × Python matrix |

Remaining work is release mechanics, not implementation — see **M5** below.

---

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
- [x] Switch the repository to public — done; the repository is public
      and MIT-licensed
- [ ] **Enable branch protection on `main`** — now unblocked by the
      repository being public, but not yet applied. `CONTRIBUTING.md` §4
      already describes the intended rules (`CI passed` as the single
      required check, no review requirement, admins exempt) as though
      they were live, so this is a documentation/reality gap until the
      setting is turned on
- [ ] Code signing — **not** a v1.0 blocker, and cannot be done before
      the first release: SignPath Foundation's free OSS signing requires
      an already-published release. Infrastructure is implemented and
      activates on secrets alone — see [`./CODE_SIGNING.md`](../CODE_SIGNING.md)

---

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

### Reserved metric IDs (proposed, not built)

The 2026-08 reference audit proposed 20 new metrics; 11 shipped
(IL-9, IL-10, IL-11, IL-14, GL-11, GL-13, GL-15, Z-7, Z-8, Z-9,
D-10 -- see `docs/METRICS_SPEC.md`). These IDs are reserved against the
proposals below and MUST NOT be reused for something else without
re-reading why each was deferred:

| ID(s) | Proposal | Why deferred |
|---|---|---|
| Z-10 | Vertical-position / novel-tank depth metrics | Assumes side-view video; nothing in the data model records camera view, so on top-down data it would compute "depth" from a meaningless y-axis. Needs a project-level `camera_view` declaration first. |
| GL-17 | Individual consistency / repeatability of social position | Needs repeated trials. `Metric.compute(session, cfg)` is per-session with no cross-session concept -- an architectural change, not a metric. |
| D-11 | Effective sample size / autocorrelation-adjusted N | Viable, medium effort, no blocker -- deferred on scope alone this round. |
| D-12 | Interpolation & gap provenance per metric | `PreprocessedSession.was_interpolated` already exists, but *per-metric* provenance requires every metric to report which frames fed it -- a change to the `Metric` contract, not one new class. |
| IL-12 | Speed autocorrelation / persistence time | Viable, medium effort, no blocker -- deferred on scope alone this round. |
| IL-13 | Bout / kinematic-state segmentation | The proposal's source (Marques et al. 2018) segmented bouts from **tail shape at ~700 fps**; citing it for a centroid-based segmenter would repeat the exact over-claim the audit flagged on IL-5's tortuosity estimator. |
| GL-12 | Neighbour angular distribution / density map | Viable, but its natural output is a 2-D histogram, which doesn't fit the long-format `session_id \| individual_id \| metric_id \| value` schema -- needs summary scalars designed first. |
| GL-14 | Directional correlation delay / leadership ranking | D-7 measured a **median individual-fragment length of 3 frames** on a real corpus session; lag correlation needs identity to hold across seconds, which this corpus does not support. |
| GL-16 | Group spatial correlation length | Cavagna's method is validated on flocks of hundreds; on shoals of 5-20 animals the correlation length is not estimable. |

### Deferred: identity-free zone metrics

`Engine.compute_metrics` refuses every `requires_identity` metric for a
session tracked without identification, and `docs/METRICS_SPEC.md` §4.5
carries the full classification. One inconsistency is knowingly left
open: all nine Z-* metrics declare `requires_identity = False` and so
still run on such a session, yet every one emits an `individual_id`
column and indexes by animal slot `k`.

| Z-4, Z-6, Z-7 | Transitions, latency to first entry, transition matrix / sequence entropy | Genuinely need the animal to be the same throughout; no valid reading on an identity-free session. |
| Z-1, Z-2, Z-3, Z-5, Z-8, Z-9 | Occupancy-style | Correct once summed over individuals, meaningless per row. |

The fix is not to flip the flags -- that would make *all* zone analysis
unavailable for an identity-free session, which is worse than the status
quo. It is to emit pooled rows instead of per-individual rows in that
case, changing the output shape of six metrics. Same family of problem as
GL-14 and GL-17 above: identity is assumed by the output schema, not just
by the arithmetic.

---

---

## Repository visibility

Private until v1.0 release. Switch to public after M5 tag is cut.

---

---
