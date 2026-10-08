# Track2Data — User Workflow Specification

**Status:** Draft v0.1 (companion to PRD §14 and UI_DESIGN §5; aligned with v1.0 MVP scope)
**Audience:** Frontend implementers, UX reviewers, scientific testers writing acceptance scripts
**Related docs:** [`../PRD.md`](../docs/dev/PRD.md), [`./TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md), [`./UI_DESIGN.md`](dev/UI_DESIGN.md), [`./ENGINE_DESIGN.md`](./ENGINE_DESIGN.md)

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
┌─ Stage 1 of 9  •  Project ───────────────────────────────────────┐
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

**Purpose:** Tell the app which tracking output to process. You point
at the folder; the app works out which tracking software wrote it,
asks you to confirm (or change it), and only then adds the sessions.

**How adding works:**

1. **Add folders…** (or drag a folder, or a single tracking file, onto
   the screen). A progress row shows while the app looks inside; you
   can cancel it.
2. **Confirm.** A dialog names the software it found and how sure it
   is, and why. You can pick another software from the list, fill in
   anything the files do not record (frame rate, frame size, which
   keypoint stands for the animal), rename sessions, or leave some
   out. *Add N sessions* stays disabled, with a tooltip saying why,
   until nothing is missing. A reader that has not yet been checked
   against real output from that tracker is marked **unverified**.
3. **Add.** The sessions join the project with the software and
   options you confirmed; they are read the same way every time the
   project is opened.

If nothing is recognised the dialog says so, lists the file types it
did see and the software this version can read, and adds nothing.

**Wireframe:**

```
┌─ Stage 2 of 9  •  Sessions ──────────────────────────────────────┐
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
  can still be processed but produce only group metrics and the pure-occupancy zone metrics (Z-1, Z-2, Z-8), pooled over animals.
- A session whose source video is unreachable is allowed; preview
  falls back to a blank canvas.

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Nothing in the folder was recognised | *"No tracking output was recognised in <folder>."* followed by the file types seen and the software this version can read | info, in the confirm dialog |
| The scan itself failed | *"Could not look at that folder: <reason>"* under the table | error, inline |
| A required option is missing (e.g. frame rate) | *Add* disabled; tooltip names the missing option | blocks adding |
| Two sessions would share an id, or one is already in the project | *Add* disabled or the row marked *already in the project*; tooltip says which | blocks adding / info |
| Folder is not an idtracker.ai output (probe of an entry added by an older version) | *"'<folder>' is not a recognised tracker output (no reader detected). Supported: idtracker.ai 6.x output (the legacy v5 layout is also read; v4 is not yet supported)."* | error per-row |
| `trajectories.npy` missing | *"trajectories.npy not found under '<folder>/trajectories'. Re-run idtracker.ai or check the folder layout."* | error per-row |
| Mixed FPS across included sessions | *"Sessions have different frame rates (30, 60). Metrics will use each session's own FPS but cross-session merges may need a manual conversion."* | warning banner |
| All included sessions are identity-free | *"None of the included sessions have stable identities. Individual-level metrics will be unavailable; group metrics and pooled zone-occupancy metrics (Z-1, Z-2, Z-8) will run."* | info banner |
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
┌─ Stage 3 of 9  •  Calibration ───────────────────────────────────┐
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
┌─ Stage 4 of 9  •  Zones ─────────────────────────────────────────┐
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
ROI is defined, zone-based metrics on Stage 7 (Metrics) are greyed out.

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
┌─ Stage 5 of 9  •  Metadata (optional) ───────────────────────────┐
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

### Stage 6 — Preprocessing

**Purpose:** Choose how trajectories are cleaned before any metric is
computed.

Through v0.1.0 this shared a single wizard page with Metrics. They are
now two screens with their own sidebar rows — the combined page made
Metrics reachable only via the toolbar's "Next" button, never from the
sidebar, which read as "the metrics screen is empty" (it wasn't empty;
it was unreachable). See `app/navigation.py`.

**Wireframe (current implementation — a scrollable single column, not
the aspirational two-pane layout of earlier drafts):**

```
┌─ Stage 6  •  Preprocessing ───────────────────────────────────────┐
│  Enable and configure the preprocessing pipeline steps.           │
│                                                                    │
│  ☑ Gap Fill                                                       │
│      ☑ Enabled     Max gap frames  [ 30 ]                         │
│                                                                    │
│  ☑ Jump Detection                                                 │
│      ☑ Enabled     Method  [ Standard-deviation multiple ▾ ]      │
│                     SD multiplier  [ 10.0 ]  Percentile [ 99.0 ]  │
│                                                                    │
│  ☐ Identity Switch Correction                                     │
│      ☐ Enabled  (off by default — see tooltip)                    │
│      Tier-1 ratio [ 1.5 ]   ☑ Tier-2 Hungarian assignment          │
│                                                                    │
│  ☑ Smoothing                                                      │
│      ☑ Enabled     Method  [ None ▾ ]   Window  [ 5 ]             │
│                                                                    │
│  ☑ Coverage Gate                     ▲ (scrolls)                  │
│      Max % missing per individual  [ 10 % ]                       │
│                                                                    │
│  (changes save automatically)                                     │
└────────────────────────────────────────────────────────────────────┘
```

**Optional inputs:** every toggle and parameter (sensible defaults
preselected; Identity Switch Correction defaults **off**).

**Decisions / branches:**
- **Identity Switch Correction is off by default.** Tooltip explains
  why: measured against real idtracker.ai recordings, this corrector
  re-permuted 17% of a session and injected large single-frame
  teleports, because it reasons from raw geometry alone with no
  knowledge of idtracker.ai's own fragment boundaries. Turning it on
  is a deliberate, informed choice, not a default.
- **Reset to defaults** is per-step, not all-or-nothing (each group's
  own "Enabled" checkbox and fields reset independently).

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| Smoothing window even (e.g. 4) for Savitzky-Golay | *"Savitzky-Golay window must be odd; rounding to 5."* | warning (auto-fix) |
| Polynomial order ≥ window | *"Polynomial order must be smaller than the window length."* | error |
| `max % NA per individual > 0.5` | *"A coverage gate above 50 % NA is very permissive — most published thresholds are 10 % NA. Continue anyway?"* | warning |

**Saved at advance:** `PreprocessConfig`.

---

### Stage 7 — Metrics

**Purpose:** Choose which behavioural metrics to extract.

**Wireframe (current implementation):**

```
┌─ Stage 7  •  Metrics ──────────────────────────────────────────────────────┐
│  Choose which behavioural metrics to extract.                              │
│                                                                             │
│  [ Individual ] [ Group ] [ Zone ]                                         │
│  ┌────────┬──────────────────────────────────────────────┬──────┬────────┐ │
│  │Include │Name                                          │ Info │ Config │ │
│  ├────────┼──────────────────────────────────────────────┼──────┼────────┤ │
│  │  ☑     │ Distance Travelled                           │  ⓘ   │   ⚙    │ │
│  │  ☑     │ Speed (mean / median / max)                  │  ⓘ   │   ⚙    │ │
│  │  ☐     │ Distance from Arena Centre                   │  ⓘ   │   ⚙    │ │
│  │  ☑     │ Activity / Freezing Fraction                 │  ⓘ   │   ⚙    │ │
│  │  ☐     │ Tortuosity                                   │  ⓘ   │   ⚙    │ │
│  │  ☐     │ Acceleration (mean abs / RMS / max)          │  ⓘ   │   ⚙    │ │
│  │  ☐     │ Freezing-Bout Count & Duration               │  ⓘ   │   ⚙    │ │
│  │  ☐     │ Turn Rate (Heading Change)                   │  ⓘ   │   ⚙    │ │
│  └────────┴──────────────────────────────────────────────┴──────┴────────┘ │
│  (Greyed for a session with no stable identities.)                        │
│                                                                             │
│  Quality threshold  [ 0.00 ]                                              │
│  (changes save automatically)                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Required inputs:** at least one metric selected.

**Decisions / branches:**
- **Identity-free fallback** — a session counts as identity-free when
  idtracker.ai declared `track_wo_identities` in its `session.json`, or
  when you ticked the Identity-free box for it on Stage 2. When *every*
  session is identity-free, `requires_identity` metric rows are greyed
  out with a tooltip. When only some are, the rows stay selectable and
  the tooltip names the affected sessions — the engine skips those
  metrics for exactly those sessions and lists them under "Metrics
  skipped" in the run README. A session whose probe has not landed does
  not trigger either state.
- **No zones defined** → the Zone tab is disabled.
- **Metric info ⓘ icon** — opens a `MetricInfoDialog` with the
  metric's definition, formula, inputs, assumptions, and reference
  (from `Metric.documentation`). Closes on ✕, `Escape`, or
  outside-click. Hidden for metrics with neither a formula nor a
  citation. See [`METRICS_SPEC.md` §6](./METRICS_SPEC.md).
- **⚙ Config icon** — stub in v1; shows "Not yet implemented."

**Validation messages:**

| Condition | Message | Severity |
|---|---|---|
| 0 metrics selected | Next disabled; tooltip *"Select at least one metric."* | (disabled) |

**Saved automatically:** `MetricSelection` is committed shortly after each
change and again when the page is left; there is no Apply button.

---

### Stage 8 — Processing

**Purpose:** Run preprocessing + metric extraction across every
session, and watch it happen.

Reachable directly from the sidebar, and via the toolbar's **Run**
action from any stage (`app/main_window.py::_action_run`) — both paths
call the same `ProcessingScreen.start_run()`, so there is exactly one
run code path regardless of how the user got here.

**Wireframe (current implementation):**

```
┌─ Stage 8  •  Processing ──────────────────────────────────────────┐
│  Validate the pipeline configuration and run preprocessing +      │
│  metric extraction across all sessions.                           │
│                                                                    │
│  [ Validate pipeline ]  [ Run pipeline ]  [ Cancel ]               │
│                                                                    │
│  ████████████████████████░░░░░░░░░░░░░░  62%                      │
│  Running… writing to <project>/exports/<ISO timestamp>/           │
│                                                                    │
│  ┌────────────┬────────────────┬────────┬──────────┐              │
│  │ Session    │ Status         │ Frames │ Duration │              │
│  ├────────────┼────────────────┼────────┼──────────┤              │
│  │ N1_T1      │ Done           │ —      │ 4.2s     │              │
│  │ N1_T2      │ Computing…     │ —      │ —        │              │
│  │ N2_T1      │ Queued         │ —      │ —        │              │
│  └────────────┴────────────────┴────────┴──────────┘              │
└────────────────────────────────────────────────────────────────────┘
```

**Decisions / branches:**
- **Validate pipeline** runs `Engine.validate()` synchronously and
  shows a summary dialog — it is a pure manifest read, no engine run.
- **Run pipeline** validates first; if issues are found, shows them
  in a warning dialog and does not submit anything.
- A session that fails (import, preprocess, metrics, or export) is
  captured as that session's own error and shown as "Failed" in the
  table — it does not abort the rest of the batch (see issue #7).
- **Frames** is currently always "—": neither the progress event nor
  the per-session result carries a frame count today.

**Saved at advance:** nothing new — this stage produces `RunResult`
(diagnostics + capped metric previews) held in memory for Stage 9's
Preview tab, and the actual output files on disk.

---

### Stage 9 — Preview & Export

> **Doc/reality note (unrelated to the Stage 6/7 split above):** this
> section's three-tab design (Preview / Diagnostics / Export sharing one
> session picker) predates the current implementation. `PreviewScreen`
> (page 8) actually has **Summary / Diagnostics / Metrics** tabs, and
> Export is its own separate screen (`ExportScreen`, page 9) — the two
> share a sidebar row per `PAGE_TO_STAGE`, but they are not tabs of one
> screen. This section's wireframes below are only renumbered here, not
> rewritten to match; that is a separate follow-up.

The final stage has three tabs that share a session picker on top.

#### 9.1 Tab — Preview

```
┌─ Stage 9  •  Preview ────────────────────────────────────────────┐
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

#### 9.2 Tab — Diagnostics

```
┌─ Stage 9  •  Diagnostics ────────────────────────────────────────┐
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

#### 9.3 Tab — Export

```
┌─ Stage 9  •  Export ─────────────────────────────────────────────┐
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
hash. The user remains on Stage 9 — it is the last stage.

---

## 4. Branch summary

```
                       ┌─ identity-free? ─┐
                       │                  │
        Sessions ──────┤                  ├──► Stage 7 (Metrics) hides IL-* for that session
                       │                  │
                       └──────────────────┘

                       ┌─ skip metadata? ─┐
                       │                  │
        Metadata ──────┤                  ├──► canonical fields default to folder name
                       │                  │      → no treatment-stratified outputs
                       └──────────────────┘

                       ┌─ no zones? ──────┐
                       │                  │
        Zones    ──────┤                  ├──► Stage 7 (Metrics) zone tab disabled
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
| 6 | Preprocessing | Needs FPS from Stage 2 and calibration from Stage 3 to render its parameters meaningfully. |
| 7 | Metrics | Needs identity status, zones, and metadata-level options (treatment list) to grey rows correctly. |
| 8 | Processing | Runs the pipeline — depends on every configuration stage above. |
| 9 | Preview & Export | The output stage — depends on every previous stage. |

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
| `EXPORT_OVERWRITE` | 9 | confirmation | "Will overwrite <N> file(s)." |
| `EXPORT_PARTIAL_FAIL` | 9 | error | "Export aborted after <N> file(s)." |
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
| `READER_UNKNOWN` | 2 | error | "No reader named '<name>' is registered." Fix: check the spelling (`track2data list-readers`) or install the plug-in that provides it. |
| `READER_NOT_AVAILABLE` | 2 | error | "Session '<id>' was added with reader '<name>', which is not available here." Fix: install the plug-in that provides it, or remove the session and add it again so a reader is detected afresh. The session is never read by a different reader: another reader could turn the same files into different numbers. |
| `READER_OPTION_MISSING` | 2 | error | "Reader '<reader>' needs option '<name>' (<label>); the files do not record it." Never defaulted: a made-up frame rate would corrupt every speed metric. |
| `READER_OPTION_INVALID` | 2 | error | "Reader '<reader>': option '<name>' <reason>." Raised for an unknown option name, a wrong type, a value outside its range or choices, or any option given to a reader that takes none. A keypoint or animal that is not in the file is the same code, and the fix lists the ones that are. |
| `READER_OUTPUT_INVALID` | 2 | error | "<what is wrong>" (a frame rate or size that cannot be true, no frames, positions of the wrong shape). Raised when a reader's result fails the checks every session must pass; the `subject` names the field. |
| `POSE_NO_POSITIONS` | 2 | error | "No keypoint has any usable position." Fix: lower the likelihood cutoff, or check that the file is the tracker's output. |
| `SESSION_AMBIGUOUS` | 2 | error | "<folder> holds N DeepLabCut files, one per video." Fix: add one of the listed files directly, or scan the folder to add them all. |
| `DLC_NOT_A_PREDICTION_FILE` | 2 | error | "<file> is not a DeepLabCut prediction table." A prediction table starts with a `scorer` row and has `x`, `y` and `likelihood` columns; annotation files (`CollectedData_*`) and 3-D tables are not read. |
| `DLC_NO_FILE` | 2 | error | "Nothing to read at <path>." Fix: point at a DeepLabCut `.csv` file or a folder that holds one. |
| `DLC_UNREADABLE` | 2 | error | "<file> is not valid text / could not be parsed." The file may be damaged; re-export it from DeepLabCut. |
| `DLC_BAD_FRAME_INDEX` | 2 | error | "The first column must hold each frame number once." Raised for a missing, negative, fractional or repeated frame number. |
| `SLEAP_NOT_AN_ANALYSIS_FILE` | 2 | error | "<file> is not a SLEAP analysis file." Fix: in SLEAP choose File > Export Analysis HDF5 and add that `.h5` file; project files (`.slp`) are not read. |
| `SLEAP_NO_FILE` | 2 | error | "Nothing to read at <path>." Fix: point at a SLEAP analysis `.h5` file or a folder that holds one. |
| `SLEAP_UNREADABLE` | 2 | error | "<file> could not be read as HDF5." The file may be damaged or incomplete; export it from SLEAP again. |
| `SLEAP_LAYOUT_AMBIGUOUS` | 2 | error | "<file> does not match the SLEAP analysis layout: <what disagrees>." The occupancy, node names or track names do not agree with `tracks`; the file is refused rather than guessed at. |
| `SLEAP_LAYOUT_UNSUPPORTED` | 2 | error | "<file> declares the axis order <...>." Only the standard order (track, xy, node, frame) is read; export the file again from the SLEAP GUI. |
| `CTRAX_NOT_A_RAW_FILE` | 2 | error | "<file> is not a raw Ctrax .mat file." This reader reads Ctrax's own file (variables `ntargets`, `x_pos`, `y_pos`, `identity`, `timestamps`). A `trx.mat` (a `trx` struct, from Ctrax, FlyTracker or JAABA) is a different format that is not read yet. |
| `CTRAX_NO_FILE` | 2 | error | "Nothing to read at <path>." Fix: point at a Ctrax `.mat` file or a folder that holds one. |
| `CTRAX_UNREADABLE` | 2 | error | "<file> could not be read as a MATLAB file." The file may be damaged or incomplete; save the tracks from Ctrax again. |
| `CTRAX_INCONSISTENT` | 2 | error | "ntargets, the per-detection arrays and the timestamps disagree." The file may be damaged or from a different tool. |
| `CTRAX_BAD_TIMESTAMPS` | 2 | error | "The timestamps give no frame rate (fewer than two frames, or they do not increase)." The frame rate is never guessed. |
| `CTRAX_FRAME_TOO_SHORT` | 2 | error | "Positions reach <y> px from the bottom, more than the frame height you gave." Fix: give the video's real height; Ctrax measures y from the bottom, so it is needed to flip it. |
| `CTRAX_DUPLICATE_TRACK` | 2 | error | "A track id appears twice in the same frame." A raw Ctrax file never does this; it may be damaged. |
| `CTRAX_TOO_LARGE` | 2 | error | "One slot per track id would not fit in memory." Fix: set `top_n` to keep only the longest tracks. |
| `DLC_BAD_VALUE` | 2 | error | "<file> has cells that are not numbers." An empty cell is missing data; a text cell is an error and is never silently turned into a gap. |

The `IDT_*` codes are sourced from [`./IDTRACKERAI_FORMAT_ANALYSIS.md`](./IDTRACKERAI_FORMAT_ANALYSIS.md) §7.1 and become live when the reader rewrite lands.

---

## 7. Reproducibility outputs (user perspective)

After Stage 9 the user has, on disk:

```
<project_dir>/
├── project.t2d.json              # the manifest
├── .t2d_autosave.json            # crash-recovery copy
├── run_log.md                    # human-readable trail
├── .t2d_cache/                   # content-addressed feather cache
└── exports/
    └── 2026-05-14T1410/
        ├── PROJECT_SUMMARY.md    # what ran, what failed, what not to pool
        ├── sessions.csv          # per-session fps, group size, calibration
        ├── codebook.csv          # every column: unit, level, metric, DOI
        ├── session_trial01/      # one directory per session
        │   ├── manifest.json     # hash + parameters + SHA-256s
        │   ├── README.md         # one-page summary for this session
        │   ├── master_fish_by_frame.csv
        │   ├── metrics_long.csv  # one row per value (tidy/long)
        │   ├── trial_activity_summary.csv
        │   ├── group_dynamics_summary.csv
        │   └── Track2Data_feb-experiment.xlsx
        └── session_trial02/
            └── ...
```

The two files at the run root describe the **project**; everything else
describes one session. `sessions.csv` is the machine-readable half — one
row per session with frame rate, frame count, duration, group size, video
resolution, calibration state, and the error for any session that failed.
`PROJECT_SUMMARY.md` is the human half, and leads with anything that makes
the sessions non-interchangeable (mixed frame rates, mixed group sizes,
mixed calibration), because a result pooled across those without
accounting for them will be wrong. A separate "Notes on the readers"
section says what the numbers rest on: a reader that was written from a
format's documentation and never checked against real tracker output, and
body-length calibration chosen for a tracker that reports no body length
(those sessions are exported in pixels only). Neither stops the run, and the
same notes are shown before it starts.

Each session's `README.md` and `manifest.json` say which software produced
its trajectories. For idtracker.ai that is the "idtracker.ai provenance"
section (version, tracking-run status, quality scores). For any other tracker
it is a "Source software provenance" section: the software and reader, whether
the reader was tested against real output, whether it was detected or chosen
by the user (and with what confidence), the options it was given (frame rate,
frame size, which keypoint), and the name of the file it read.

`codebook.csv` documents the schema itself: one row per exported column
with its unit, level, originating metric and DOI. Read it before trusting
a column name to imply its unit — notably, **every `*_pct` column holds a
fraction in [0, 1], not a percentage** (`time_pct = 0.42` means 42 %). The
names are kept for backward compatibility with existing analysis scripts,
so the codebook is where the units are stated truthfully.

`metrics_long.csv` is the tidy/long form —
`session_id, individual_id, zone_name, metric_id, column, value, unit`,
one row per measured value. The three `*_summary.csv` files are *wide*
(one row per session × individual, a column per metric) whatever their
names suggest, and they drop `metric_id` during the merge. Feed the long
table to `lme4`/`glmmTMB`/`statsmodels`; it also joins directly to
`codebook.csv` on `column`.

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
