# Track2Data — User Workflow Specification

**Status:** Draft v0.1 (companion to PRD §14 and UI_DESIGN §5; aligned with v1.0 MVP scope)
**Audience:** Frontend implementers, UX reviewers, scientific testers writing acceptance scripts
**Related docs:** [`../PRD.md`](../PRD.md), [`./TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md), [`./UI_DESIGN.md`](./UI_DESIGN.md), [`./ENGINE_DESIGN.md`](./ENGINE_DESIGN.md)

This document describes the **user-facing journey** through Track2Data
from launch to export. It complements PRD.md (which states *what* the
app does) and UI_DESIGN.md (which states *how* the app is built) by
spelling out *what the researcher does, in what order, with what
choices, and with what messages*.

---

## 1. Overview

### 1.1 The journey at a glance

```
┌────────────┐    ┌─────────┐    ┌──────────┐    ┌─────────────┐
│  Welcome   │──► │ Project │──► │ Sessions │──► │ Calibration │
└────────────┘    └─────────┘    └──────────┘    └─────────────┘
                                                          │
                                                          ▼
┌─────────────────────┐    ┌──────────┐    ┌────────────────────┐
│ Preview & Export    │◄── │ Metadata │◄── │ Zones              │
│ (preview/diag/exp.) │    │(optional)│    └────────────────────┘
└─────────────────────┘    └──────────┘
        │
        ▼
  Export bundle ── manifest.json ── run_log.md ── project.t2d.json
```

### 1.2 Workflow modes

| Mode | Trigger | What it changes |
|---|---|---|
| **First-time** | Welcome → New project | All stages start empty. User walks the wizard linearly. |
| **Resume** | Welcome → Recent / Open | Project reopens at the **last green stage**, all prior settings restored. |
| **Template** | Welcome → Duplicate as template | A new project inherits calibration, zones, mapping rules, preprocessing, metric selection — but **not** imported sessions. The user lands on Stage 2 (Sessions). |
| **Headless** | `track2data run <project.t2d.json>` | No UI; engine runs the whole pipeline. Exit code 0 on success; non-zero on any DV-* failure. |

### 1.3 Stage gating & navigation rules

- The left **wizard sidebar** lists every stage with a status badge:
  - ◯ empty / not visited
  - ▶ in progress
  - ✓ valid (all required inputs satisfied, no validation errors)
  - ⚠ warnings present but advance-allowed
  - ✗ invalid (cannot advance)
- **Forward** navigation (Next button) requires the current stage to
  be `✓` or `⚠`. The Next button shows a tooltip with the blocking
  reason when disabled.
- **Backward** navigation is always allowed; settings on later stages
  are preserved unless the change invalidates them (e.g. changing
  calibration mode resets per-session calibration check results — a
  yellow banner warns the user before the change is committed).
- A green status on **all** stages enables the toolbar **Run** action;
  Run is available from any stage as a shortcut.

---

## 2. Cross-cutting flows

### 2.1 Save / autosave / resume

| Trigger | Effect |
|---|---|
| Stage advance (Next clicked) | Autosave: `project.t2d.json` rewritten; title bar dirty-marker (`●`) cleared. |
| Any field edit | Title bar shows `●` to indicate unsaved changes. |
| Ctrl/Cmd-S | Force save now. |
| File ▸ Save As… | Write a copy under a new path; current project re-points to the new file. |
| App quit while dirty | Modal: *"Save changes to project '<name>' before quitting?"* with buttons **Save & quit / Quit without saving / Cancel**. |
| Crash recovery | On next launch, the welcome screen shows a banner: *"Recovered draft for project '<name>' last edited <time>"* with **Recover / Discard** actions. The draft is read from `<project_dir>/.t2d_autosave.json`. |

**Resume rule:** opening a saved project jumps to the last green stage
(furthest valid stage); the user can navigate back at any time.

### 2.2 Run log drawer

A bottom dock viewer streams Markdown lines as the engine works:

```
[14:02:11] INFO  Imported session S-001 — 60 fps, 4 animals, identities stable (98 % coverage)
[14:02:13] WARN  Session S-003 — body-length samples = 12 (< 30 required) — calibration disabled for this session
[14:02:14] INFO  Metadata join: 18 matched, 2 unmatched, 0 conflicts
[14:03:02] ERROR Zone polygon "centre" is self-intersecting — fix or remove before continuing
```

The drawer is collapsible; severity-coloured (info=grey, warn=yellow,
error=red) and supports filter + copy-to-clipboard.

### 2.3 Command palette (Ctrl/Cmd-K)

Fuzzy-search of every action and stage. Suggested actions:
*Open recent project*, *Jump to Sessions*, *Reprocess from Calibration*,
*Toggle Run Log*, *Copy CLI snippet*. The palette is the recommended
power-user path; the menu bar mirrors every entry.

### 2.4 Reproducibility receipt

After every successful export the **Export tab** shows a receipt:

```
✓ Export complete — 5 files written to D:/projects/feb-experiment/exports/2026-05-14T1408/
  manifest.json                 sha256 a4f1…3c
  master_fish_by_frame.csv      sha256 e90b…71
  trial_activity_summary.csv    sha256 1d22…f0
  trial_occupancy_long.csv      sha256 7b4e…02
  README.md                     sha256 9aa2…8c

[Copy CLI snippet]   [Open folder]   [Close]
```

The CLI snippet is the headless reproduction command:
`track2data run "D:/projects/feb-experiment/project.t2d.json"`.

---

## 3. Stage-by-stage journey

Each stage section follows the same template:

> **Purpose** — what the user is trying to accomplish.
> **Wireframe** — ASCII sketch of the page.
> **Required inputs** — must be supplied to advance.
> **Optional inputs** — improve output if supplied.
> **Decisions / branches** — choices the user makes here.
> **Validation rules & messages** — exact text shown.
> **Errors & warnings** — concrete strings.
> **Saved at this point** — what hits `project.t2d.json` when the
> user advances.

### Stage 0 — Welcome / Start

**Purpose:** Choose a project to work on (new, recent, opened, or
duplicated template).

**Wireframe:**

```
┌──────────────────────── Track2Data v0.1 ─────────────────────────┐
│                                                                  │
│   Track2Data                                                     │
│   Turn idtracker.ai outputs into analysis-ready datasets.        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │  + New       │  │  📂 Open…    │  │  📑 Duplicate as     │    │
│  │   project    │  │   project    │  │   template…           │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘    │
│                                                                  │
│   Recent projects                                                │
│  ─────────────────────────────────────────────────────────────   │
│   ► feb-experiment            opened 2 hours ago                 │
│   ► pilot-octopus             opened yesterday                   │
│   ► flowdown-2025-Q1          opened 6 days ago                  │
│                                                                  │
│   [Recovered draft for 'feb-experiment' from 2026-05-13 17:42 ▾] │
│        [Recover]  [Discard]                                      │
│                                                                  │
│   Quick start guide ↗   Docs ↗   GitHub ↗   v0.1.0               │
└──────────────────────────────────────────────────────────────────┘
```

**Decisions:**
- **New project** → opens a "New project" dialog (name + directory),
  then advances to Stage 1.
- **Open** → native file picker for `*.t2d.json`, then resume.
- **Duplicate as template** → pick a source project; new project name
  + directory; advances to Stage 2 (sessions empty, all other
  settings inherited).
- **Recent click** → resume directly.
- **Crash-recovery banner** appears only if `.t2d_autosave.json` is
  detected and newer than the last saved `project.t2d.json`.

**Validation:** none; the welcome screen is a launcher.

**Saved at this point:** nothing. The chosen project file becomes the
working project for the rest of the session.

---

### Stage 1 — Project

**Purpose:** Set the project's identity (name, directory) and confirm
metadata that travels with every export.

**Wireframe:**

```
┌─ Stage 1 of 7  •  Project ───────────────────────────────────────┐
│                                                                  │
│   Project name *      [ feb-experiment                       ]   │
│   Project directory * [ D:/projects/feb-experiment      ] [📂]   │
│                                                                  │
│   Created    2026-05-14 14:00                                    │
│   App vers.  Track2Data 0.1.0                                    │
│                                                                  │
│   Optional                                                       │
│   Description  [ pH-tolerance choice trials – Feb cohort     ]   │
│   Investigator [ M. Bellio                                    ]  │
│                                                                  │
│                            [ Cancel ] [ Next: Sessions ▶ ]       │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** project name (non-empty), project directory
(writable).

**Optional inputs:** description, investigator, free-text tags.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Empty name | *"Project name is required."* (inline, red border) | error |
| Directory not writable | *"Cannot write to '<path>'. Pick a different directory or check permissions."* (banner) | error |
| Directory non-empty and contains another `*.t2d.json` | *"This directory already holds project '<other>'. Choose a different directory or use **Open** from Welcome."* (modal) | error |
| Name contains characters illegal on the host OS | *"Project name contains characters not allowed by Windows / macOS / Linux file systems: `<chars>`. Use only letters, digits, dash, underscore, and space."* (inline) | error |

**Saved at advance:** `project_name`, `folder`, timestamps,
`app_version`, optional description/investigator.

---

### Stage 2 — Sessions

**Purpose:** Tell the app which `idtracker.ai` output folders to
process.

**Wireframe:**

```
┌─ Stage 2 of 7  •  Sessions ──────────────────────────────────────┐
│                                                                  │
│   Drag-drop session folders here, or click ➕ Add…               │
│   ┌────────────────────────────────────────────────────────────┐ │
│   │  ☑  session_N1_T1   ✓ v5  60 fps  108 000 fr  4 fish  ident │
│   │  ☑  session_N1_T2   ✓ v5  60 fps  108 000 fr  4 fish  ident │
│   │  ⚠  session_N2_T1   ✓ v5  60 fps   90 000 fr  4 fish  no ID │
│   │  ✗  session_corrupt × trajectories.npy missing              │
│   └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│   [➕ Add folders]  [🗑 Remove]  [🔄 Re-detect]                  │
│                                                                  │
│   Preview (S-N1_T1)            ┌──────────────────────┐          │
│   Folder      session_N1_T1    │                      │          │
│   Reader      idtrackerai_v5   │   [video frame]      │          │
│   FPS         60               │                      │          │
│   Frames      108 000          │                      │          │
│   Animals     4                │                      │          │
│   Identities  stable (96 %)    │                      │          │
│   Video file  ✓ reachable      └──────────────────────┘          │
│                                                                  │
│   ◀ Back                                  Next: Calibration ▶    │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** at least one session ticked Include.

**Optional inputs:** per-session **session_id** override (default =
folder basename).

**Decisions / branches:**
- A session may be **identity-stable** or **identity-free**. The flag
  is auto-detected (≥ 50 % non-NaN per animal). Identity-free sessions
  can still be processed but will only produce group-level metrics.
- A session whose source video is unreachable is allowed; preview
  falls back to a blank canvas.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Folder is not an idtracker.ai output | *"'<folder>' is not a recognised tracker output (no reader detected). Tracked formats: idtracker.ai v5, v4."* | error per-row |
| `trajectories.npy` missing | *"trajectories.npy not found under '<folder>/trajectories'. Re-run idtracker.ai or check the folder layout."* | error per-row |
| Mixed FPS across included sessions | *"Sessions have different frame rates (30, 60). Metrics will use each session's own FPS but cross-session merges may need a manual conversion."* | warning banner |
| All included sessions are identity-free | *"None of the included sessions have stable identities. Individual-level metrics will be unavailable; only group and zone metrics will run."* | info banner |
| 0 sessions ticked include | Next button disabled; tooltip: *"Tick at least one session to continue."* | (disabled state) |

**Saved at advance:** each included `SessionRef` (path + SHA-256 of
the trajectory file), the auto-detected reader, video info, animal
count, identity-stability flag.

---

### Stage 3 — Calibration

**Purpose:** Establish a real-world scale so kinematics report in cm
or body lengths, not pixels.

**Wireframe:**

```
┌─ Stage 3 of 7  •  Calibration ───────────────────────────────────┐
│                                                                  │
│  Mode  ( ) Scalar px-per-cm     (•) Body length (recommended)    │
│  ─────────────────────────────────────────────────────────────   │
│                                                                  │
│   Body-length mode                                               │
│   Min samples per session  [ 30 ]                                │
│   ┌────────────────────────────────────────────────────────────┐ │
│   │ Session       BL samples   median BL (px)   status         │ │
│   │ N1_T1         412          88.2             ✓ ready        │ │
│   │ N1_T2         410          87.6             ✓ ready        │ │
│   │ N2_T1         12           —                ⚠ skipped      │ │
│   └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│   Orientation pairing                                            │
│   ┌────────────────────────────────────────────────────────────┐ │
│   │ Session   orientation tag                                  │ │
│   │ N1_T1     [ FT  ▾ ]                                        │ │
│   │ N1_T2     [ FT  ▾ ]                                        │ │
│   │ N2_T1     [ FD  ▾ ]                                        │ │
│   └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│   ◀ Back                                       Next: Zones ▶     │
└──────────────────────────────────────────────────────────────────┘
```

> **Reality note:** the real screen is simpler than this wireframe
> (no measure-on-frame tool, BL sample-count table, or orientation
> pairing yet) and, as of Part 2 of the post-v0.1.0 GUI fixes, offers
> a **third mode** this wireframe doesn't show: **Session
> calibration**, which uses each session's own `length_unit` (the
> validator's calibration ratio) instead of one project-wide scalar or
> a derived body-length ratio. It adds a unit picker, a required
> confirmation checkbox, and a per-session readiness list so a session
> missing `length_unit` is visible before running.

**Required inputs:** mode (scalar, body-length, or session).

**Optional inputs:** orientation tag per session (only required if
the user wants to reuse one zone set across mirrored videos).

**Decisions / branches:**
- **Scalar mode** swaps the body-length table for a `px_per_cm`
  spinbox + a "Measure on frame" tool that lets the user click two
  points of known real-world distance.
- Sessions failing the BL sample threshold are listed and **skipped
  from cm-based metrics** — their per-frame outputs will still appear
  in px-based metrics.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Scalar mode, `px_per_cm <= 0` | *"px/cm must be greater than zero."* (inline) | error |
| BL mode, ≥ 1 session below sample threshold | *"<N> session(s) have fewer than <min> body-length samples and will be skipped for cm-based metrics. You can lower the threshold or switch to scalar mode."* (banner) | warning |
| BL mode, **all** sessions below threshold | *"No session has enough body-length samples for body-length calibration. Switch to scalar mode or re-run idtracker.ai with longer segmentation."* (modal blocks advance) | error |
| Orientation tag empty | (allowed; defaults to "default") | — |

**Saved at advance:** `CalibrationConfig` (mode, px_per_cm or
min_samples), per-session orientation tag.

---

### Stage 4 — Zones

**Purpose:** Draw or import region-of-interest polygons over a video
frame; assign each ROI a level (main / secondary / custom).

**Wireframe:**

```
┌─ Stage 4 of 7  •  Zones ─────────────────────────────────────────┐
│                                                                  │
│  Pick frame from   [ S-N1_T1  ▾ ]      Orientation   [ FT  ▾ ]   │
│                                                                  │
│ ┌──────────────────────────────────┐ ┌───────────────────────┐   │
│ │                                  │ │ ROIs                  │   │
│ │   [video frame thumbnail]        │ │  ● flow      main  ✓  │   │
│ │   ┌── flow ──┐                   │ │  ● calm      main  ✓  │   │
│ │   │          │                   │ │  ● centre    sec   ✓  │   │
│ │   │          │                   │ │  + Add ROI            │   │
│ │   └──────────┘                   │ │                       │   │
│ │   ┌── calm ──┐                   │ │ Level     [ main  ▾ ] │   │
│ │   │          │                   │ │ Area      [ 12.4 cm² ]│   │
│ │   └──────────┘                   │ │ Vertices  4           │   │
│ │                                  │ │                       │   │
│ └──────────────────────────────────┘ └───────────────────────┘   │
│                                                                  │
│   Tools  [ ✏ Draw ] [ ➖ Delete vertex ] [ ↺ Reset polygon ]     │
│          [ 📥 Import CSV ] [ 📤 Export CSV ]                     │
│                                                                  │
│   ◀ Back                                    Next: Metadata ▶     │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** at least one ROI for any session that will be
used in zone-based metrics. Zones are **optional overall** — if no
ROI is defined, zone-based metrics on Stage 6 are greyed out.

**Optional inputs:** ROI area (for area-corrected occupancy); ROI
level beyond the two defaults.

**Decisions / branches:**
- **Draw new ROIs** with the polygon tool.
- **Import** an existing CSV (`ROI_index, ROI_name, Vertex_index, X,
  Y`) — useful when re-using zones from previous experiments.
- **Reuse via orientation** — once tagged in Stage 3, switching the
  orientation tag re-uses the same ROIs mirrored about the configured
  axis.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| ROI has < 3 vertices | *"ROI '<name>' has fewer than 3 vertices."* (inline) | error |
| ROI is self-intersecting | *"ROI '<name>' has crossing edges. Move a vertex to fix."* (inline) | error |
| ROI vertex outside frame bounds | *"ROI '<name>' extends beyond the frame (1920 × 1080). It will be clipped during metric computation."* | warning |
| ROI names duplicated | *"Two ROIs named '<name>' — rename one or merge."* | error |
| No ROIs at all | (allowed) – next page will gray out zone metrics | info |

**Saved at advance:** `ZoneSet` (rois + orientation_tag +
zone_levels).

---

### Stage 5 — Metadata (optional)

**Purpose:** Attach experimental metadata (treatment, group, date,
timepoint, …) so that every output row carries the right context.

**Wireframe:**

```
┌─ Stage 5 of 7  •  Metadata (optional) ───────────────────────────┐
│                                                                  │
│   [ 📂 Choose file (CSV / XLSX) ]    [ Skip metadata for now ]   │
│   Selected: D:/data/trial_meta.xlsx (24 rows, 7 columns)         │
│                                                                  │
│   Mapping                                                        │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Source column       →  Canonical field           Sample      ││
│  │ video_id            →  [ session_id  ▾ ]         N1_T1       ││
│  │ trial               →  [ trial_id    ▾ ]         1           ││
│  │ condition           →  [ treatment   ▾ ] (alias) low pH      ││
│  │ date                →  [ trial_date  ▾ ] (alias) 2026-02-11  ││
│  │ tank                →  [ —           ▾ ]         A           ││
│  │ density             →  [ group_id    ▾ ]         high        ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│   Join key   (•) session_id   ( ) tank + date   ( ) regex on    │
│              folder name [ N(?P<trial>\d+)_T(?P<rep>\d+) ]      │
│                                                                  │
│   Match preview                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Session    Status                                            ││
│  │ N1_T1      ✓ matched row 1 (treatment=low pH)                ││
│  │ N1_T2      ✓ matched row 2 (treatment=low pH)                ││
│  │ N2_T1      ⚠ unmatched                                       ││
│  │ N2_T2      ⚠ unmatched                                       ││
│  │            (rows 17, 23 unmatched in metadata)               ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│   ☐ Proceed without metadata for the 2 unmatched sessions       │
│                                                                  │
│   ◀ Back                              Next: Preprocessing ▶      │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** none (whole stage is optional).

**Optional inputs:** metadata file, mapping rule, join key.

**Decisions / branches:**

| Path | Consequence |
|---|---|
| Click **Skip metadata for now** | All canonical fields default to derived values: `session_id` = folder name; `trial_id` = 1; `treatment` = "unknown". Treatment-grouped plots and stratified exports become single-level. |
| Map metadata and all sessions match | Standard path — every output row carries the joined fields. |
| Map metadata but some sessions unmatched | The Next button stays disabled until either (a) every session matches, or (b) the user explicitly ticks *"Proceed without metadata for the N unmatched sessions"*. |
| Mapping has conflicts (2 metadata rows → 1 session) | Conflicts highlighted red; user must resolve (de-duplicate the metadata or refine the join key). |

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Required canonical field unmapped | *"Canonical field '<field>' is not mapped. Pick a source column or skip metadata."* | error |
| Same source column mapped to two canonical fields | *"Column '<col>' is assigned to both '<a>' and '<b>'."* | error |
| Unmatched sessions, checkbox not ticked | *"Some sessions did not match a metadata row. Tick 'Proceed without metadata' or refine the join key."* | error |
| Conflict (≥ 2 rows match one session) | *"Session '<id>' matches more than one metadata row. Refine the join key or remove the duplicate row."* | error |
| Date column failed ISO-8601 parse | *"Column 'date' contains values that are not ISO-8601 dates (e.g. '<val>'). They will be exported as strings."* | warning |

**Saved at advance:** `MetadataSource` (file + sha256),
`MappingRule`, the resolved per-session row table.

---

### Stage 6 — Preprocessing & Metrics

**Purpose:** Choose how trajectories are cleaned, then choose which
metrics to compute.

**Wireframe:**

```
┌─ Stage 6 of 7  •  Preprocessing & Metrics ───────────────────────┐
│                                                                  │
│ ┌─ Preprocessing ─────────────┐ ┌─ Metrics ──────────────────┐   │
│ │ ▼ Gap filling      ☑       │ │ [ Individual ][Group][Zone] │   │
│ │   max gap [ 30  ] frames    │ │                            │   │
│ │                             │ │ Individual                 │   │
│ │ ▼ Jump detection   ☑       │ │  ☑ IL-1 Path length        │   │
│ │   method [ sd_mult ▾ ]      │ │  ☑ IL-2 Mean / max speed   │   │
│ │   mult   [ 10.0 ]           │ │  ☐ IL-3 Distance from cent │   │
│ │   repl   [ linear-interp ▾] │ │  ☑ IL-4 Active vs inactive │   │
│ │                             │ │      threshold [ 1.0 ] BL/s│   │
│ │ ▼ Identity switches ☑      │ │  ☐ IL-5 Tortuosity         │   │
│ │   Tier-1 ratio [ 1.5 ]      │ │                            │   │
│ │   Tier-2 Hungarian ☑       │ │ (Greyed for session N2_T1 –│   │
│ │                             │ │  no stable identities.)    │   │
│ │ ▼ Smoothing       ☑        │ │                            │   │
│ │   method [ savgol ▾ ]       │ │                            │   │
│ │   window [ 5 ]  order [ 2 ] │ │                            │   │
│ │                             │ │                            │   │
│ │ ▼ Coverage gate   ☑        │ │                            │   │
│ │   max % NA / indiv [ 10% ]  │ │                            │   │
│ │                             │ │                            │   │
│ │ [ Reset all to defaults ]   │ │                            │   │
│ └─────────────────────────────┘ └────────────────────────────┘   │
│                                                                  │
│   Timepoint binning  [ 20 ] minutes  ( 0 = whole session )       │
│                                                                  │
│   ◀ Back                                  Next: Preview ▶        │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** at least one metric selected.

**Optional inputs:** every preprocessing toggle and parameter
(sensible defaults preselected).

**Decisions / branches:**
- **Identity-free fallback** — when *any* included session is
  identity-free, that session's individual metrics are greyed out
  with tooltip: *"This session does not have stable identities;
  individual-level metrics will be skipped for it."*
- **No zones defined** → zone tab disabled with tooltip: *"Define at
  least one zone on Stage 4 to enable these metrics."*
- **Timepoint binning** — set to 0 to disable and report whole-session
  values only.
- **Metric info ⓘ icon** — each metric row carries an ⓘ icon to the
  right of the name. Click opens a `MetricInfoDialog` showing the
  metric's definition, formula, inputs, assumptions, and reference
  (rendered from `Metric.documentation`). Closes on ✕, `Escape`, or
  outside-click. The icon is hidden for metrics whose
  `MetricDocumentation` carries neither a formula nor a citation
  (those fall back to the existing tooltip). See
  [`METRICS_SPEC.md` §6](./METRICS_SPEC.md) for the full architecture.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| 0 metrics selected | Next disabled; tooltip *"Select at least one metric."* | (disabled) |
| Smoothing window even (e.g. 4) for Savitzky-Golay | *"Savitzky-Golay window must be odd; rounding to 5."* | warning (auto-fix) |
| Polynomial order ≥ window | *"Polynomial order must be smaller than the window length."* | error |
| `max % NA per individual > 0.5` | *"A coverage gate above 50 % NA is very permissive — most published thresholds are 10 % NA. Continue anyway?"* | warning |
| Active-threshold > 5 BL/s | *"Threshold is unusually high — fish typically cruise at <2 BL/s. Confirm or reset to default 1.0."* | warning |

**Saved at advance:** `PreprocessConfig`, `MetricSelection`,
timepoint bin size.

---

### Stage 7 — Preview & Export

The final stage has three tabs that share a session picker on top.

#### 7.1 Tab — Preview

```
┌─ Stage 7  •  Preview ────────────────────────────────────────────┐
│  Session [ S-N1_T1 ▾ ]    [ ▶ Run preview ]                      │
│                                                                  │
│   Layers   ☑ Frame  ☑ Zones  ☑ Raw trajectories                 │
│             ☑ Preprocessed  ☐ Identity-switch events            │
│                                                                  │
│  ┌────────────────────────────────────┐ ┌──────────────────────┐ │
│  │   [interactive trajectory canvas]  │ │ QC                   │ │
│  │                                    │ │ Valid frames  98.4 % │ │
│  │                                    │ │ Jumps removed   12   │ │
│  │                                    │ │ ID switches      3   │ │
│  │                                    │ │ Coverage         ✓   │ │
│  │                                    │ │ Speed PDF [chart]    │ │
│  └────────────────────────────────────┘ └──────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

- **Run preview** computes preprocessing + metrics for the picked
  session (cached after first run, refreshed if parameters change).
- Layers can be toggled live.
- The QC panel mirrors the per-session diagnostics row.

#### 7.2 Tab — Diagnostics

```
┌─ Stage 7  •  Diagnostics ────────────────────────────────────────┐
│  Per-session QC                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Session  valid%  jumps  switches  NA%   speed-spark         │  │
│  │ N1_T1    98.4    12     3         1.6   ▁▃▅▇▅▃▁             │  │
│  │ N1_T2    97.9     8     1         2.1   ▁▂▄▆▄▂▁             │  │
│  │ N2_T1    87.1    45    14        12.9   ▁▃█▅▃▁              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Click any row → coverage histogram, speed PDF, ID-switch timeln │
└──────────────────────────────────────────────────────────────────┘
```

#### 7.3 Tab — Export

```
┌─ Stage 7  •  Export ─────────────────────────────────────────────┐
│                                                                  │
│   Format                                                         │
│    ☑ CSV (long)        master_fish_by_frame.csv  trial_*.csv     │
│    ☑ CSV (wide)        trial_summary_wide.csv                    │
│    ☑ Excel             Track2Data_<project>.xlsx                 │
│    ☐ Feather           master_fish_by_frame.feather              │
│    ☑ Manifest + README manifest.json + README.md                 │
│                                                                  │
│   Target directory  [ D:/projects/feb-experiment/exports/        │
│                       2026-05-14T1410          ] [📂]            │
│   Existing files  none                                           │
│                                                                  │
│   ▾ Show CLI snippet                                             │
│       track2data run "D:/projects/feb-experiment/project.t2d.    │
│       json"                                                      │
│   [ 📋 Copy ]                                                    │
│                                                                  │
│   ◀ Back                                  [ 🚀 Export ]          │
└──────────────────────────────────────────────────────────────────┘
```

**Required inputs:** target directory (default
`<project>/exports/<ISO timestamp>/`), ≥ 1 exporter ticked.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| 0 exporters ticked | Export button disabled; tooltip *"Pick at least one output format."* | (disabled) |
| Target directory non-empty | Modal *"Will overwrite <N> file(s) in '<dir>'. Continue?"* with **Overwrite / Cancel / Use a fresh subfolder**. | confirmation |
| Disk-write fails partway | *"Export aborted after <N> file(s). Restored previous state. See run log for details."* (modal) | error |

After success the **reproducibility receipt** described in §2.4
appears.

**Saved at advance:** `ExportTarget` list, run-log entry, manifest
hash. The user remains on Stage 7 — there is no Stage 8.

---

## 4. Branch summary

```
                       ┌─ identity-free? ─┐
                       │                  │
        Sessions ──────┤                  ├──► Stage 6 hides IL-* for that session
                       │                  │
                       └──────────────────┘

                       ┌─ skip metadata? ─┐
                       │                  │
        Metadata ──────┤                  ├──► canonical fields default to folder name
                       │                  │      → no treatment-stratified outputs
                       └──────────────────┘

                       ┌─ no zones? ──────┐
                       │                  │
        Zones    ──────┤                  ├──► Stage 6 zone tab disabled
                       │                  │
                       └──────────────────┘

                       ┌─ scalar vs. BL? ─┐
                       │                  │
        Calibration ───┤                  ├──► cm-based metrics only when scalar
                       │                  │      or per-session BL valid
                       └──────────────────┘
```

---

## 5. Recommended screen order — rationale

| Order | Stage | Why here |
|---|---|---|
| 0 | Welcome | A launcher must come before any project state. |
| 1 | Project | Identity (name/dir) must exist before anything else can be saved. |
| 2 | Sessions | Every downstream stage needs to know how many animals and what FPS. |
| 3 | Calibration | Depends on `n_animals` and FPS from Stage 2; must precede zones if zone areas use cm. |
| 4 | Zones | Depends on having an extracted video frame from Stage 2 and an orientation tag from Stage 3. |
| 5 | Metadata | Optional; placed late so that the user already knows which sessions are real. |
| 6 | Preprocessing & Metrics | Needs identity status, FPS, BL, zones, and metadata-level options (treatment list) to render correctly. |
| 7 | Preview & Export | The output stage — depends on every previous stage. |

The order is gated but not strictly serial: jumping back to fix
Stage 3 from Stage 6 is fully supported and only invalidates fields
that actually depend on the changed value.

---

## 6. Error / warning catalogue (consolidated)

Each error carries a code that matches `core/errors.py` so the run log
and headless CLI report the same identifier. The full list:

| Code | Stage | Severity | User-facing text |
|---|---|---|---|
| `NO_READER` | 2 | error | "'<folder>' is not a recognised tracker output." |
| `TRAJ_NOT_FOUND` | 2 | error | "trajectories.npy not found under '<folder>/trajectories'." |
| `TRAJ_BAD_NDIM` | 2 | error | "Trajectory file has the wrong shape (expected 3-D)." |
| `TRAJ_BAD_SHAPE` | 2 | error | "Trajectory dimensions could not be interpreted as (n_frames, n_animals, 2)." |
| `MIXED_FPS` | 2 | warning | "Sessions have different frame rates." |
| `IDENT_NONE` | 2 | info | "No included session has stable identities — individual metrics disabled." |
| `BL_SAMPLES_LOW` | 3 | warning | "<N> session(s) have too few body-length samples." |
| `BL_SAMPLES_NONE` | 3 | error | "No session has enough body-length samples — pick scalar mode." |
| `PX_PER_CM_INVALID` | 3 | error | "px/cm must be greater than zero." |
| `ROI_FEW_VERTICES` | 4 | error | "ROI '<name>' has fewer than 3 vertices." |
| `ROI_SELF_INTERSECT` | 4 | error | "ROI '<name>' has crossing edges." |
| `ROI_OUT_OF_BOUNDS` | 4 | warning | "ROI '<name>' extends beyond the frame." |
| `ROI_NAME_DUP` | 4 | error | "Two ROIs named '<name>'." |
| `META_FIELD_UNMAPPED` | 5 | error | "Canonical field '<field>' is not mapped." |
| `META_AMBIGUOUS` | 5 | error | "Session '<id>' matches more than one metadata row." |
| `META_UNMATCHED` | 5 | error | "Some sessions did not match a metadata row." |
| `META_DATE_INVALID` | 5 | warning | "Column 'date' contains non-ISO-8601 values." |
| `SMOOTH_EVEN_WINDOW` | 6 | warning | "Savitzky-Golay window must be odd; rounding to <N>." |
| `SMOOTH_ORDER_GE_WINDOW` | 6 | error | "Polynomial order must be smaller than the window length." |
| `COVERAGE_LOOSE` | 6 | warning | "Coverage gate above 50 % NA is very permissive." |
| `PREPROCESS_STAGE_FAILED` | 6 | error | "Preprocessing succeeded but a later stage failed: <reason>" |
| `EXPORT_OVERWRITE` | 7 | confirmation | "Will overwrite <N> file(s)." |
| `EXPORT_PARTIAL_FAIL` | 7 | error | "Export aborted after <N> file(s)." |
| `IDT_NO_TRAJ` | 2 | error | "No trajectory file found in `<folder>/trajectories/`." |
| `IDT_FORMAT_AMBIGUOUS` | 2 | info | "Multiple trajectory formats present (`<list>`); chose `<best>`." |
| `IDT_PICKLE_REFUSED` | 2 | error | "Loading `<path>` requires explicit consent (`--allow-pickle` / GUI prompt)." |
| `IDT_VERSION_UNKNOWN` | 2 | warning | "idtracker.ai version `<v>` not recognised; using v6.x assumptions." |
| `IDT_PARTIAL_SESSION` | 2 | warning | "Session looks incomplete (no `trajectories/`; log ended in error)." |
| `IDT_BODY_LENGTH_UNRELIABLE` | 3 | warning | "idtracker.ai's `body_length` is computed from blob bounding boxes and varies with segmentation parameters; not a validated biological length." |
| `IDT_DICT_MISSING_KEY` | 2 | warning | "Trajectory dict missing optional key `<k>`; field set to None." |
| `IDT_SHAPE_MISMATCH` | 2 | error | "`id_probabilities` shape `<a>` incompatible with trajectories `<b>`." |
| `IDT_LENGTH_UNIT_INVALID` | 3 | warning | "`length_unit=<v>` invalid; manual calibration required." |
| `IDT_ROI_MASK_UNREADABLE` | 4 | warning | "Could not decode `<path>`." |
| `IDT_JSON_NONSTRICT` | 2 | info | "`session.json` contains non-strict JSON literal (`Infinity`/`NaN`); parsed leniently." |
| `IDT_VIDEO_PATH_UNREACHABLE` | 2 | warning | "`video_paths` `<p>` unreachable on this machine. Use 'Locate video…' to rebase." |
| `IDT_RESOURCE_FORK_IGNORED` | 2 | info | "Ignored `<count>` macOS resource-fork files (`._*`)." |

The `IDT_*` codes are sourced from [`./IDTRACKERAI_FORMAT_ANALYSIS.md`](./IDTRACKERAI_FORMAT_ANALYSIS.md) §7.1 and become live when the reader rewrite lands.

---

## 7. Reproducibility outputs (user perspective)

After Stage 7 the user has, on disk:

```
<project_dir>/
├── project.t2d.json              # the manifest
├── .t2d_autosave.json            # crash-recovery copy
├── run_log.md                    # human-readable trail
├── .t2d_cache/                   # content-addressed feather cache
└── exports/
    └── 2026-05-14T1410/
        ├── manifest.json         # hash + parameters + SHA-256s
        ├── README.md             # one-page summary
        ├── master_fish_by_frame.csv
        ├── trial_activity_summary_long.csv
        ├── trial_occupancy_long.csv
        ├── group_dynamics_summary.csv
        └── Track2Data_feb-experiment.xlsx
```

To reproduce: send a reviewer the `project.t2d.json` plus the
original `session_*` folders. The reviewer runs:

```
track2data run /path/to/project.t2d.json
```

…and obtains the same `exports/<timestamp>/` bundle with byte-identical
data files (only the timestamp inside `manifest.json` differs).

---

## 8. Open questions for UX review

1. Should the Welcome screen be skippable after the first run? Current
   recommendation: shown every launch with a "Skip on next launch"
   checkbox.
2. Should the toolbar Run action attempt a full pipeline even when
   later stages are not yet green, or always require all-green? Current
   recommendation: only enabled when all-green.
3. Should "Reset to defaults" on Stage 6 be per-step or all-or-nothing?
   Current recommendation: both — per-step reset link inside each
   group + a global "Reset all" at the bottom.
4. Crash-recovery banner — auto-recover silently, or always ask?
   Current recommendation: always ask (user trust > convenience).
