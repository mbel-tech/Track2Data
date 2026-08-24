# Track2Data UI — Design Specification

**Audience:** Frontend implementers.
**Status:** Draft v0.1 (companion to PRD §14; aligned with v1.0 MVP scope).
**Stack:** Python 3.11+, PySide6 (Qt 6.6+), `qasync` for async-Qt bridging,
matplotlib + pyqtgraph for plots.
**Distribution:** packaged with PyInstaller; UI imports `track2data` engine.
**Related:** [`./TECHNICAL_SPEC.md`](./TECHNICAL_SPEC.md) for the system-level view (tech stack, build, distribution, configuration hierarchy).

---

## 1. Overview & responsibilities

The UI is a thin layer over the engine. It owns:

1. Wizard navigation (7 stages, PRD §14).
2. A reactive **project state store** (single source of truth).
3. **Background-task orchestration** so the GUI never blocks.
4. Validation feedback, run-log surfacing, export workflow.

The UI never re-implements engine logic; it calls `track2data.api.Engine`.

---

## 2. Architecture

```
[ ProjectStore (QObject signals) ]
        │  ▲
        ▼  │
[ Wizard pages (QWidget) ]──────► [ Engine facade ]
        │                            (track2data.api.Engine)
        ▼
[ TaskRunner (QThreadPool) ] ─── progress / log signals ─► [ RunLogDock ]
```

- **`ProjectStore`** — a `QObject` holding the in-memory `ProjectManifest`
  and emitting fine-grained Qt signals when fields change. UI widgets
  bind to those signals.
- **Pages** — `QWidget` subclasses, one per stage. Pages read from the
  store, write back via setter methods that emit signals.
- **`TaskRunner`** — wraps engine calls that may take seconds (import,
  preprocess, run metrics, export) and runs them on a `QThreadPool`
  with progress reporting.
- **`RunLogDock`** — a dockable Markdown viewer subscribed to the
  engine's logging callback.

---

## 3. Application shell

```
QMainWindow
├── QMenuBar
│   ├── File: New… / Open… / Save / Duplicate as template / Recent ▸ / Quit
│   ├── Edit: Undo / Redo / Preferences
│   ├── Run: Validate / Run pipeline / Export…
│   ├── View: Toggle Run Log / Toggle Diagnostics / Theme ▸
│   └── Help: About / Open docs / Report issue
├── QToolBar (back / forward / run / export / cancel)
├── Central: QStackedWidget (one page per wizard stage)
├── LeftDock: WizardSidebar (stage list, completion ticks)
├── BottomDock: RunLogDock
└── StatusBar (current project, worker count, cache hit rate)
```

**Command palette** (Ctrl/Cmd-K, PRD §14): a `QDialog` over the main
window with fuzzy-matched actions wired through `QAction`.

---

## 4. Project state model

```python
class ProjectStore(QObject):
    # Signals (one per top-level field; pages connect only to what they need)
    projectChanged       = Signal()
    sessionsChanged      = Signal()
    calibrationChanged   = Signal()
    zonesChanged         = Signal()
    metadataChanged      = Signal()
    preprocessChanged    = Signal()
    metricsChanged       = Signal()
    exportChanged        = Signal()
    runLogAppended       = Signal(str)        # markdown line
    taskProgress         = Signal(str, int)   # task_id, percent
    taskFinished         = Signal(str, object)# task_id, result

    def __init__(self): ...
    def manifest(self) -> ProjectManifest: ...
    def update_calibration(self, cfg: CalibrationConfig): ...
    # ... one setter per field
```

State is **never** mutated in place; setters replace fields and emit
signals. Undo/redo (post-MVP) becomes a `QUndoStack` of manifest diffs.

---

## 5. Wizard pages

Page-by-page contract: **what the user sees**, **engine calls**,
**validation**, **navigation gate**.

> For the user-facing perspective on each page (wireframes, decision
> branches, exact validation message text, save/resume logic) see
> [`USER_WORKFLOW.md`](./USER_WORKFLOW.md).

### 5.1 Page 1 — Project

| Element | Behaviour |
|---|---|
| New / Open / Duplicate buttons | `engine.manifest.new()` / `read()` / `duplicate()` |
| Recent-projects list | from `QSettings` |
| Project name field | binds to `store.manifest.project_name` |
| Project directory picker | required to enable Next |

**Validation:** project name non-empty; directory writable.
**Engine calls:** `manifest.new(name, dir)`, `manifest.read(path)`.

### 5.2 Page 2 — Sessions

| Element | Behaviour |
|---|---|
| Folder picker / drag-drop area | calls `engine.import_session(path)` async |
| Session table (QTableView) | columns: folder, reader, fps, frames, animals, has-video, has-identities, include? |
| Remove / Re-detect buttons | update store |
| Sample-frame thumbnail (right side) | `engine.preview_frame(session_id)` |

**Validation (DV-1):** failed imports stay in the table with a red
status icon and a tooltip carrying `error.remediation`.
**Engine calls:** `Engine.import_sessions(paths) -> list[Session]`.
**Gate:** ≥ 1 session marked include.

### 5.3 Page 3 — Calibration

| Element | Behaviour |
|---|---|
| Radio: scalar vs. body-length | mode selection |
| px-per-cm spinbox + helper "click two points to measure" | scalar mode |
| Min body-length samples spinbox | BL mode |
| Per-session orientation tag dropdown ("FT"/"FD"/custom) | for zone reuse |

**Validation (DV-4):** scalar mode requires px-per-cm > 0;
BL mode validates per session — sessions failing the sample-count
threshold are listed.
**Engine calls:** `Engine.set_calibration(cfg)`.

### 5.4 Page 4 — Zones

Three-pane layout: thumbnail picker (top), polygon canvas (centre),
zone list (right).

| Element | Behaviour |
|---|---|
| Frame thumbnail strip | pick frame from any included session |
| Polygon canvas (`QGraphicsView`) | draw / drag / delete vertices; live area readout |
| Zone list | name, level (main/secondary/custom), area (optional) |
| Import CSV / Export CSV buttons | round-trip `ZoneSet` via `zones.io` |
| Orientation toggle (FT/FD) | swap zone set per orientation tag |

**Validation (DV-3):** ≥ 3 vertices; no self-intersection
(checked via shapely `is_valid` from engine); within frame bounds.
**Engine calls:** `Engine.set_zones(zone_set)`,
`zones.io.read_csv(path)`.

### 5.5 Page 5 — Metadata

| Element | Behaviour |
|---|---|
| File picker (CSV/XLSX) + "Skip metadata" option | `metadata.loader.load` |
| Mapping table | columns × canonical fields with dropdowns; aliases pre-applied (condition→treatment, date→trial_date) |
| Join-key configurator | radio: by session_id / by composite / by regex; regex with named groups |
| Live preview panel | matched (green), unmatched (yellow), conflicts (red) |

**Validation (DV-2):** required canonical fields must resolve. The Next
button stays disabled while any session is unmatched **unless** the
user explicitly ticks "Proceed without metadata for these sessions".
**Engine calls:** `metadata.join.match(sessions, mapping)`.

### 5.6 Page 6 — Preprocessing & Metrics

Split pane.

**Left — preprocessing:** one collapsible group per step
(`gap_fill`, `jump_detect`, `identity_switch`, `smoothing`, `validate`)
with enable toggle + parameter widgets. Defaults shown greyed; "Reset
to defaults" link per group.

**Right — metric catalogue:** three tabs (Individual / Group / Zone)
populated from `metrics.list_for_level(level)`. Each row = checkbox +
id + name + ⓘ icon + ⚙ config icon (stub in v1 — see below).
Identity-aware metrics (`Metric.requires_identity`) greyed-out when
every *probed* session in the project has `has_stable_identities is
False` — sessions not yet probed (or whose probe failed) don't count
toward that "every", so an all-unprobed project greys nothing — with
an explanatory tooltip. Zone tab disabled when no zones are defined.

**Footer:** "Timepoint binning" spinbox (minutes; 0 = whole session).

#### MetricInfoDialog (info-button modal)

Clicking the ⓘ icon next to a metric opens a `MetricInfoDialog`
(`QDialog` subclass, constructed from a `Metric` class — not an id
string) that renders the metric's `documentation:
MetricDocumentation` field:

- Definition · Formula · Inputs · Assumptions / warnings · Reference
- Footer button: **Copy citation** (writes citation + DOI to clipboard)
- Closes on: title-bar ✕ · `Escape` key (QDialog's own default
  behaviour) · click outside the dialog's rect (a QApplication-wide
  event filter installed for the dialog's lifetime, not a separate
  overlay widget)

The ⓘ icon is **hidden** when both `documentation.formula_plain` and
`documentation.citation` are `None` — those metrics fall back to the
existing tooltip-only behaviour. In practice this never currently
hides anything, since `MetricDocumentation.formula_plain` is a
required (non-`None`) `str` field on every built-in metric today; the
check is implemented as specified for forward compatibility. See
[`METRICS_SPEC.md` §6](./METRICS_SPEC.md) for the canonical
architecture and the per-metric content this dialog renders.

**Validation:** PreprocessConfig and MetricSelection are validated
through Pydantic on every change; invalid fields highlight red.
**Engine calls:** `Engine.set_preprocess(cfg)`,
`Engine.set_metric_selection(sel)`.

### 5.7 Page 7.1 — Pipeline Preview & Validation

Read-only summary of entire pipeline configuration; optionally run a dry-run preview.

| Element | Behaviour |
|---|---|
| Summary table (read-only) | rows: Project name, Sessions count, Calibration mode, Zones count, Metadata (file or skipped), Preprocessing steps enabled, Metrics selected (count breakdown) |
| Validate button | calls `Engine.validate_pipeline()` (async); shows ✓ "Ready to run" or ✗ "Error: <reason>" |
| Run preview button | calls `Engine.run_session(selected_session)` via `TaskRunner`; caches result; shows progress bar |
| Preview-log viewer | collapsible; shows live run-log during preview |

**Validation:** All prior stages must be green. Validation must pass before export.
**Engine calls:** `Engine.validate_pipeline()`, `Engine.run_session(session_id)`.

---

### 5.7b Page 7.2 — Export Targets & Configuration

Select export format(s), configure per-exporter options, run export pipeline.

| Element | Behaviour |
|---|---|
| Exporter table (QTableWidget) | columns: enabled (checkbox), format_name, description, output_files; rows from exporters.registry |
| Target directory picker | QLineEdit (editable) + 📂 browse button; default = `<project>/exports/<ISO timestamp>/` |
| Existing files list | collapsible QListWidget (shown if directory non-empty); with `overwrite_confirmed` checkbox |
| CLI snippet disclosure | copyable `track2data run …` command for headless reproduction |
| Progress bar | shown during export; indeterminate if no progress callbacks |
| Export log | collapsible; shows live run-log output |
| Export success receipt | table of written files + SHA-256 hashes; buttons: Copy CLI / Open folder / New export |

**Validation (DV-3 / DV-8):** ≥ 1 exporter selected; target directory exists or creatable; if non-empty, `overwrite_confirmed` must be ticked.
**Engine calls:** `Engine.export(payload, exporters, out_dir)`.
**Gate:** Export button enabled only if validation passes.

---

## 6. Detailed Screen Specifications (14 screens across 7 stages)

This section provides implementation-ready detail for all 14 screens: widget types, data bindings, validation rules, error messages, and navigation logic.

### 6.1 Screen 1.1 — Project Metadata Entry

**Stage:** Stage 1 (Project Setup)  
**Purpose:** Initialize project identity and metadata.

**Widget List:**
- QLabel: "Project name *"
- QLineEdit: `project_name_input` (required; alphanumeric + spaces/dashes; platform-illegal chars detected inline)
- QLabel: "Project directory *"
- QLineEdit: `project_dir_input` (read-only display of selected path)
- QPushButton: `browse_dir_button` (📂 icon; opens native folder picker)
- QLabel: "Created" (section header)
- QLabel: `created_timestamp` (read-only; ISO timestamp from manifest)
- QLabel: "App version" (section header)
- QLabel: `app_version_label` (read-only, e.g. "Track2Data 0.1.0")
- QLabel: "Optional metadata" (collapsible section header)
- QLineEdit: `description_input` (multi-line; placeholder "pH-tolerance choice trials…")
- QLineEdit: `investigator_input` (free text; placeholder "M. Bellio")
- QLineEdit: `tags_input` (comma-separated; placeholder "pilot, zebrafish, temp-stressor")

**Data Bindings:**
- `project_name_input` ↔ `ProjectStore.manifest.project_name` (signal: `projectChanged`)
- `project_dir_input` ← `ProjectStore.manifest.folder` (read-only from store)
- `created_timestamp`, `app_version_label` ← manifest (read-only)
- Optional metadata fields → future `ProjectManifest` extension (not yet in models; coordinate with engine team)

**Validation Rules:**
- `project_name` non-empty (required)
- `project_name` contains no OS-illegal chars (Windows: `< > : " / \ | ? *`; others: `/` only)
- `project_dir` must exist or be user-creatable
- `project_dir` must be writable (`os.access(path, os.W_OK)`)
- If `project_dir` non-empty AND contains `*.t2d.json`: emit error "This directory already holds project '<name>'. Choose a different directory or use **Open** from the Welcome screen."

**Error Messages:**
- "Project name is required." → red border on `project_name_input` field + inline error text
- "Project name contains illegal characters: `<chars>`" → inline red text + suggestion
- "Cannot write to '<path>'. Pick a different directory or check folder permissions." → red banner
- "Directory already contains project '<other>'. Choose a different directory or use **Open** from Welcome." → modal error dialog

**Next Button Logic:**
- Enabled only when: `project_name` non-empty AND `project_dir` writable AND no conflicting project found
- On Next: emit `store.projectChanged`, autosave manifest, advance to Stage 2

**Navigation Context:**
- Back to Welcome always allowed (discard unsaved metadata)
- Sidebar nav to later stages allowed if this stage is valid (manifest autosaved on every field change)

---

### 6.2 Screen 2.1 — Session Folder Import & Reader Detection

**Stage:** Stage 2 (Session Management)  
**Purpose:** Import `idtracker.ai` output folders; preview reader-detected format; select sessions for processing.

**Widget List:**
- QLabel: "Drag-drop session folders here, or click ➕ Add…"
- QDropZone / Custom QWidget: Accepts folder drag-drop; visual feedback (blue border on drag-over)
- QPushButton: `add_folders_button` (➕ icon; opens `QFileDialog.getExistingDirectories()`)
- QTableWidget: `session_table`
  - Columns: `include` (checkbox), `session_id`, `reader_detected`, `fps`, `n_frames`, `n_animals`, `identity_status`, `has_video`, `status` (icon + tooltip on error)
  - Rows: auto-generated from imported sessions; right-click context menu (Remove, Re-detect, Edit session_id)
- QPushButton: `remove_button` (🗑 icon; removes selected row)
- QPushButton: `redetect_button` (🔄 icon; re-runs reader detection on selected rows)
- QLabel: "Preview: <session_id>" (right side, section header)
- QLabel: `preview_folder_path` (read-only; full path of selected session)
- QLabel: `preview_reader_format` (read-only; e.g. "idtrackerai v5.1")
- QLabel: `preview_fps`, `preview_n_frames`, `preview_n_animals` (read-only display)
- QGraphicsView / QLabel: `preview_frame_canvas` (thumbnail image from frame 0; empty if import fails)

**Data Bindings:**
- `session_table` rows ← `ProjectStore.sessions` (list of `SessionRef`) (signal: `sessionsChanged`)
- Table selection → `ProjectStore.selected_session_id` (new optional field; not persisted)
- `include` checkboxes ← → session internal state (extend `SessionRef` with `marked_for_processing: bool = True` OR use a separate dict in `ProjectStore`)
- Preview frame: triggered by `Engine.preview_frame(session_id)` → async via `TaskRunner`, result → `preview_frame_canvas`

**Validation Rules:**
- ≥ 1 session ticked `include` (required to advance)
- Each failed-import row: display error icon + tooltip with `error.remediation` (e.g. "trajectories.npy not found under '<folder>/trajectories'. Re-run idtracker.ai or check the folder layout.")
- If mixed FPS across included sessions: yellow banner "Sessions have different frame rates (30, 60). Each will use its own FPS in metric computation."
- If all included sessions are identity-free: info banner "None of the included sessions have stable identities. Individual-level metrics will not be computed."

**Error Messages:**
- Per-row (on import failure): "'<folder>' is not a recognised tracker output. Supported: idtracker.ai v5, v4." (error icon + tooltip)
- Per-row: "trajectories.npy not found under '<folder>/trajectories'. …" (error icon + tooltip)
- Mixed FPS: yellow banner with "Proceed?" button or auto-proceed
- All identity-free: info banner (no blocking)
- 0 sessions included: Next button disabled, tooltip "Tick at least one session to continue."

**Next Button Logic:**
- Enabled only when ≥ 1 session marked `include`
- On Next: emit `store.sessionsChanged`, call `Engine.import_sessions(selected_paths)` via TaskRunner, save `SessionRef` list to manifest
- On import failure (async): show error modal with remediation; user stays on this page to retry or fix

**Navigation Context:**
- Back to Stage 1 allowed; sessions preserved
- Sidebar nav forward allowed if ≥ 1 session ticked

---

### 6.3 Screen 3.1 — Calibration Method Chooser

**Stage:** Stage 3 (Calibration)  
**Purpose:** Select between scalar px-per-cm vs. body-length calibration modes.

**Widget List:**
- QRadioButton: `radio_scalar` ("Scalar px-per-cm")
- QRadioButton: `radio_bodylength` ("Body length (recommended)") [pre-selected]
- QLabel: Mode explanation text (collapsible)
- QLabel: "Why body-length?" disclosure button + collapsible help text (explaining per-individual calibration)
- QLabel: Sessions compatibility preview
  - Shows which sessions have bbox data available (from `Session.bbox_table`)
  - If 0 sessions have bbox: yellow banner "No session has body-length bounding box data. Scalar mode will be used."

**Data Bindings:**
- `radio_scalar` / `radio_bodylength` ↔ `ProjectStore.calibration.mode` (signal: `calibrationChanged`)
- On mode change: mark calibration as dirty; optionally clear per-session data if switching modes

**Validation Rules:**
- Mode must be selected (always true via radio buttons; default = body-length)

**Error Messages:**
- (None expected; selection is free)

**Next Button Logic:**
- Always enabled (default mode is pre-selected)
- On Next: advance to Screen 3.2 (data entry for chosen mode); emit signal but do NOT yet mutate calibration state

**Navigation Context:**
- Back to Stage 2 allowed
- Changing mode from Screen 3.2 returns here (soft reset of calibration data)

---

### 6.4 Screen 3.2 — Calibration Data Entry

**Stage:** Stage 3 (Calibration)  
**Purpose:** Enter mode-specific calibration parameters.

**Widget List (Scalar Mode):**
- QLabel: "Scale factor (px per cm)"
- QDoubleSpinBox: `px_per_cm_spinbox` (range 0.1–1000, decimals 2, default empty/0)
- QPushButton: `measure_button` ("📏 Measure on frame")
  - On click: opens dialog to pick session + frame, click two points on canvas, compute distance, auto-fill spinbox
- QLabel: "Preview: 1 cm = <value> pixels"

**Widget List (Body-Length Mode):**
- QLabel: "Min body-length samples per session"
- QSpinBox: `bl_min_samples_spinbox` (range 1–100, default 30)
- QLabel: "Per-session BL status:" (section header)
- QTableWidget: `bl_status_table`
  - Columns: `session_id`, `bl_samples_count`, `median_bl_px`, `status` (✓ ready / ⚠ insufficient / × error)
  - Rows auto-populated from included sessions
- QLabel: "Orientation pairing (for zone reuse)"
- QComboBox: `orientation_tag_combo` (dropdown: FT / FD / custom; auto-generated from all included sessions' tags)

**Data Bindings:**
- `px_per_cm_spinbox` ↔ `ProjectStore.calibration.px_per_cm` (scalar mode; signal: `calibrationChanged`)
- `bl_min_samples_spinbox` ↔ `ProjectStore.calibration.bl_min_samples` (BL mode)
- Per-session orientation tags: read from extended `Session` model (add field `orientation_tag: str | None = None`)
- On mode change: clear opposite mode's data from store

**Validation Rules (Scalar Mode):**
- `px_per_cm > 0` (required); if not, show inline error "px/cm must be greater than zero."

**Validation Rules (Body-Length Mode):**
- If ≥ 1 session below threshold: yellow banner "N session(s) have fewer than <min> body-length samples and will be excluded from cm-based metrics."
- If **all** sessions below threshold: red modal "No session has sufficient body-length samples. Choose a lower threshold or use Scalar mode."

**Error Messages:**
- Scalar: "px/cm must be greater than zero." (inline red)
- BL: "<N> session(s) below threshold…" (yellow banner)
- BL: "No session has sufficient samples. Lower threshold or switch mode." (red modal)

**Next Button Logic:**
- Scalar: enabled only if `px_per_cm > 0`
- BL: enabled only if ≥ 1 session meets threshold (red modal blocks if all fail)
- On Next: emit `store.calibrationChanged`, save `CalibrationConfig`, advance to Stage 4

**Navigation Context:**
- Back to Screen 3.1 allowed (returns without losing data entry)
- Back to Stage 2 allowed (soft-resets calibration)

---

### 6.5 Screen 4.1 — ROI Import (Optional)

**Stage:** Stage 4 (Zones/ROIs)  
**Purpose:** Load pre-defined ROIs from CSV or skip to manual drawing.

**Widget List:**
- QLabel: "Load saved ROI set (optional)"
- QPushButton: `import_csv_button` ("📥 Import CSV")
- QLineEdit: `csv_path_input` (read-only; displays selected file)
- QLabel: "Or draw ROIs from scratch on the next screen."
- QTableWidget: `imported_rois_preview`
  - Columns: `roi_name`, `vertex_count`, `area_px²`, `status` (✓ valid / ✗ self-intersecting)
  - Empty if no import

**Data Bindings:**
- Imported `ZoneSet` → `ProjectStore.zones` (signal: `zonesChanged`)

**Validation Rules:**
- CSV import is optional
- If imported: each ROI validated via shapely (≥ 3 vertices, not self-intersecting)

**Error Messages:**
- "Could not read '<file>'. Ensure it is a valid CSV (ROI_index, ROI_name, Vertex_index, X, Y)."
- Per-row: "ROI '<name>' has fewer than 3 vertices."
- Per-row: "ROI '<name>' has crossing edges."

**Next Button Logic:**
- Always enabled (ROI import is optional)
- On Next: save imported zones, advance to Screen 4.2

---

### 6.6 Screen 4.2 — ROI Polygon Editor & Canvas

**Stage:** Stage 4 (Zones/ROIs)  
**Purpose:** Draw or edit ROIs interactively on video frames.

**Widget List (Left Pane — Canvas):**
- QComboBox: `session_picker` (dropdown: select included session)
- QSpinBox: `frame_number_spinbox` (0 to n_frames-1)
- QPushButton: "◄ Prev" / "▶ Next"
- QGraphicsView / Custom: `polygon_canvas`
  - Display: video frame + overlaid zones (semi-transparent fills, vertex circles, edges)
  - Draw mode: click to add vertices, right-click to finalize, ESC to cancel
  - Drag mode: drag vertices, double-click to delete
  - Hover: highlight nearby vertices/edges
- Toolbar: "✏ Draw" / "➖ Delete" / "↺ Reset" / "📥 Import CSV" / "📤 Export CSV"

**Widget List (Right Pane — Zone List & Properties):**
- QLabel: "Zones" (header)
- QListWidget: `zone_list_widget` (rows: `● zone_name`, optional level badge)
  - Right-click context menu: Rename, Delete, Move up/down
- QPushButton: "+ Add zone"
- QLineEdit: `zone_name_edit` (editable when zone selected)
- QComboBox: `zone_level_combo` (dropdown: main / secondary / custom)
- QLabel: "Vertices: <count>" (read-only)
- QLabel: "Orientation"
- QComboBox: `orientation_tag_combo` (dropdown: FT / FD / custom)

**Data Bindings:**
- `session_picker` → triggers frame load
- `frame_number_spinbox` → triggers frame load
- Polygon vertices → real-time update of area via shapely
- `zone_list_widget` ↔ `ProjectStore.zones.rois`

**Validation Rules:**
- Each ROI ≥ 3 vertices
- No self-intersecting ROIs
- No vertex outside frame bounds (warning allowed)
- No duplicate ROI names

**Error Messages:**
- "ROI '<name>' has fewer than 3 vertices." (inline, Next disabled)
- "ROI '<name>' has crossing edges. Move a vertex to fix." (inline, Next disabled)
- "ROI extends beyond frame. It will be clipped during metric computation." (warning banner)

**Next Button Logic:**
- Enabled if all ROIs valid (or no ROIs and user skips zone metrics on Stage 6)
- On Next: emit `store.zonesChanged`, advance to Stage 5

---

### 6.7 Screen 5.1 — Metadata Source Selection

**Stage:** Stage 5 (Metadata & Mapping)  
**Purpose:** Choose metadata file (CSV/XLSX) or skip.

**Widget List:**
- QLabel: "Attach experimental metadata (optional)"
- QPushButton: "📂 Choose file (CSV / XLSX)"
- QLineEdit: `metadata_path_input` (read-only)
- QLabel: "File info: <N> rows, <M> columns"
- QPushButton: "Skip metadata for now"

**Data Bindings:**
- `metadata_path_input` → `ProjectStore.metadata_source.path`

**Validation Rules:**
- File must be readable CSV or XLSX
- File must have ≥ 1 row and ≥ 1 column

**Error Messages:**
- "Could not read '<file>'. Ensure it is a valid CSV or XLSX file."
- "File is empty."

**Next Button Logic:**
- Enabled if: (file loaded) OR ("Skip" clicked)
- On file selection: trigger async load via TaskRunner, then auto-advance or show Next button
- On Skip: emit `metadataChanged(None)`, advance to Stage 6

---

### 6.8 Screen 5.2 — Metadata Mapping & Join Preview

**Stage:** Stage 5 (Metadata & Mapping)  
**Purpose:** Map CSV columns to canonical fields; define join key; preview matches.

**Widget List (Mapping Table):**
- QTableWidget: `mapping_table`
  - Columns: `source_column`, `→`, `canonical_field` (QComboBox dropdown), `sample_value` (read-only)
  - Rows auto-populated from CSV header
- QLabel: "Aliases pre-applied (condition→treatment, date→trial_date, ...)"

**Widget List (Join Key):**
- QRadioButton: `radio_by_session_id` ("by session_id")
- QRadioButton: `radio_by_composite` ("by composite key:")
  - Sub-widget: QMultiSelect dropdown of canonical fields
- QRadioButton: `radio_by_regex` ("by regex pattern:")
  - Sub-widget: QLineEdit regex (e.g. `N(?P<trial>\d+)_T(?P<rep>\d+)`)

**Widget List (Match Preview):**
- QTableWidget: `preview_table`
  - Columns: `session_id`, `status`, `matched_row` / `error`
  - Rows: one per included session
  - Status: ✓ matched / ⚠ unmatched / ✗ conflict / ✗ error
- QLabel: "Unmatched rows in metadata: <list>" (if any)
- QCheckBox: `proceed_without_unmatched` ("Proceed without metadata for the <N> unmatched sessions")

**Data Bindings:**
- `mapping_table` edits → `ProjectStore.mapping.rules`
- `radio_by_*` selections → `ProjectStore.mapping.join_keys` / `join_regex`
- On any change: trigger async `metadata.join.match(...)` → update preview table

**Validation Rules:**
- All required canonical fields must map
- No column mapped to >1 canonical field
- If unmatched sessions: `proceed_without_unmatched` must be checked
- If conflicts (≥2 rows match 1 session): cannot advance

**Error Messages:**
- "Canonical field '<field>' is required; pick a source column."
- "Column '<col>' is assigned to both '<a>' and '<b>'."
- "Some sessions unmatched. Tick 'Proceed' or refine the join key."
- "Session '<id>' matches >1 metadata row. Refine or remove duplicate."

**Next Button Logic:**
- Enabled if: required fields mapped AND (all matched OR `proceed_without_unmatched` checked) AND no conflicts
- On Next: emit `metadataChanged`, save `MetadataSource` + `MappingRule`, advance to Stage 6

---

### 6.9 Screen 6.1 — Preprocessing Configuration

**Stage:** Stage 6 (Preprocessing & Metrics)  
**Purpose:** Configure trajectory cleaning steps.

**Widget List (5 collapsible sections):**

**Gap Filling:**
- QCheckBox: `gap_fill_enabled` (☑, default True)
- QSpinBox: `gap_fill_max_frames` (range 1–1000, default 30)

**Jump Detection:**
- QCheckBox: `jump_enabled` (☑, default True)
- QComboBox: `jump_method` (sd_multiple / percentile, default sd_multiple)
- QDoubleSpinBox: `jump_sd_mult` (shown if sd_multiple; range 1–100, default 10.0)
- QDoubleSpinBox: `jump_percentile` (shown if percentile; range 0–100, default 99.0)
- QDoubleSpinBox: `jump_pct_mult` (shown if percentile; default 2.0)
- QComboBox: `jump_replacement` (nan / linear_interp, default linear_interp)

**Identity Switch Correction:**
- QCheckBox: `id_switch_enabled` (☐, default **False** — re-permutes 17.1% of
  a real recording and injects ~640px single-frame teleports, measured
  against the real corpus; off pending a fragment-boundary-aware
  replacement, see `track2data/core/models.py`'s `IdSwitchCfg`)
- QDoubleSpinBox: `id_switch_tier1_ratio` (range 1–10, default 1.5)
- QCheckBox: `id_switch_tier2_hungarian` (☑, default True)
- QSpinBox: `id_switch_consolidate_window` (range 1–100, default 5)

**Smoothing:**
- QCheckBox: `smoothing_enabled` (☑, default True)
- QComboBox: `smoothing_method` (none / moving_avg / savgol, default savgol)
- QSpinBox: `smoothing_window` (range 3–51, odd only, default 5)
- QSpinBox: `smoothing_polyorder` (range 1–5, default 2; validation: < window)

**Coverage Validation:**
- QCheckBox: `coverage_validation_enabled` (☑, default True)
- QSpinBox: `coverage_min_track_frames` (range 0–N, default 0)
- QDoubleSpinBox: `coverage_max_na_pct` (range 0–1, default 0.10; display as %)

**Global Controls:**
- QPushButton: "Reset all to defaults"

**Data Bindings:**
- All fields ↔ `ProjectStore.preprocess` (PreprocessConfig) (signal: `preprocessChanged`)
- On invalid field: highlight red; disable Next

**Validation Rules:**
- `gap_fill_max_frames > 0`
- `jump_sd_mult > 0`
- `smoothing_window` odd (auto-round if even + warn)
- `smoothing_polyorder < smoothing_window`
- `coverage_max_na_pct ≤ 0.5` (warn if >0.5)

**Error Messages:**
- "Smoothing window must be odd; rounding to <next odd>." (warning, auto-fix)
- "Polynomial order must be < window length." (inline error)

**Next Button Logic:**
- Enabled if all validation passes (preprocessing always valid by default)
- On Next: emit `preprocessChanged`, save `PreprocessConfig`, advance to Screen 6.2

---

### 6.10 Screen 6.2 — Metric Selection (Registry-Driven Tabs)

**Stage:** Stage 6 (Preprocessing & Metrics)  
**Purpose:** Select which metrics to compute.

**Widget List:**
- QTabWidget: `metric_tabs` (3 tabs: Individual / Group / Zone)

**Per-tab structure:**
- QTableWidget: `metric_list`
  - Columns: `include` (checkbox), `metric_id`, `metric_name`, `info` (ⓘ icon), `config` (⚙ icon — **stub in v1**: shows "Not yet implemented"; no Screen 6.3 or config schema exists yet)
  - Rows: auto-populated from `metrics.list_for_level(level)`
  - Greyed rows: metrics where `Metric.requires_identity` is `True`, when every session in the project has `has_stable_identities is False` (with tooltip). Sessions with `has_stable_identities is None` (not yet probed, or probe failed) are treated as unknown, not identity-free — they don't trigger greying.
  - Disabled Zone tab if no zones defined on Stage 4

**MetricInfoDialog (Modal):**
- Opens on ⓘ click, constructed from the row's `Metric` class directly
- Renders `Metric.documentation` fields (definition, formula_plain, formula_latex, inputs, assumptions, warnings, citation, citation_doi)
- Footer button: "Copy citation" (to clipboard)
- Close: title-bar ✕, Escape, or a click outside the dialog's rect (QApplication-wide event filter)

**Data Bindings:**
- Checkboxes ↔ `ProjectStore.metrics.individual` / `.group` / `.zone`
- `SessionRef.has_stable_identities` ↔ populated by a background probe (`read_session` via `TaskRunner`) when a session is added in Stage 2

**Validation Rules:**
- ≥1 metric selected across all tabs (required)
- Identity-free sessions → rows for `requires_identity` metrics greyed when *every* session lacks stable identities (still count if checked; engine skips per-session)
- No zones → Z-* tab disabled

**Error Messages:**
- "Select at least one metric." (Next button disabled + tooltip)

**Next Button Logic:**
- Next is the shared toolbar ◀ Back / Next ▶ action, not a per-screen button — its enabled state depends only on stack position (`page_index < last_page`), not on how many metrics are selected, and it just advances the `QStackedWidget` to the next built stage (the Processing screen). It does not itself save the selection. `MetricSelection` is saved separately by the screen's own **Apply selection** button, which calls `ProjectStore.update_metrics()` (this is what emits `metricsChanged`).
- Screen 6.3 (below) is not implemented — there is no config schema or navigation target for it yet, so Next never routes there.

---

### 6.11 Screen 6.3 — Per-Metric Advanced Configuration (Aspirational — Not Yet Implemented)

> **Status:** This screen does not exist in the shipped app — no config schema, no navigation target, nothing below is built. Kept as a design reference only; everything in this section is proposed, not current behavior.

**Stage:** Stage 6 (Preprocessing & Metrics)  
**Purpose:** Configure metric-specific parameters (e.g., activity threshold).

**Widget List:**
- QTableWidget: `metric_config_table`
  - Columns: `metric_id`, `parameter_name`, `value`, `unit`, `reset`
  - Rows: auto-generated from selected metrics' config schemas
  - Example rows:
    - IL-4 Activity threshold: QDoubleSpinBox (default 1.0) BL/s
    - IL-7 Min freezing bout: QSpinBox (default 5) frames
    - GL-3 Minimum speed: QDoubleSpinBox (default 0.1) BL/s
  - Reset button (↺) per row

- QLabel: "Global parameters" (section header)
- QSpinBox: `timepoint_minutes_spinbox` (range 0–N, 0=whole session, default None)
- QDoubleSpinBox: `quality_threshold_slider` (range 0–1, default 0.0; display as slider or spinner; masks per-frame metrics when `id_probabilities[frame, animal] < threshold`) — **already implemented today**, on the real Screen 6.2 (§6.10) as `_quality_spin`, not gated behind this unbuilt screen

**Data Bindings:**
- `timepoint_minutes_spinbox` ↔ `ProjectStore.metrics.timepoint_minutes`
- `quality_threshold_slider` ↔ `ProjectStore.metrics.quality_threshold`
- Per-metric config → new `MetricSelection.config: dict[str, Any] = {}` field

**Validation Rules:**
- `timepoint_minutes >= 0`
- `quality_threshold` in [0, 1]
- Per-metric validation (e.g., activity threshold < 10 BL/s → warning)

**Error Messages:**
- "Activity threshold > 5 BL/s. Typical cruise is <2 BL/s. Confirm or reset." (warning)

**Next Button Logic:**
- Enabled if all config parameters valid
- On Next: emit `metricsChanged`, advance to Stage 7.1

---

| UI surface | Engine entry point |
|---|---|
| Page 1 New/Open | `Engine.new_project(name, dir)` / `Engine.open_project(path)` |
| Page 2 import | `Engine.import_sessions(paths) -> list[Session]` |
| Page 2 thumbnail | `Engine.preview_frame(session_id) -> QImage-friendly bytes` |
| Page 3 calibration | `Engine.set_calibration(cfg)` |
| Page 4 zones | `Engine.set_zones(zone_set)` / `zones.io.read_csv` |
| Page 5 metadata | `metadata.loader.load` / `metadata.join.match` / `Engine.set_metadata_mapping` |
| Page 6 preprocess | `Engine.set_preprocess(cfg)`, `Engine.set_metric_selection(sel)` |
| Page 7 preview | `Engine.run_session(session_id) -> PreprocessedSession` (cached) |
| Page 7 export | `Engine.export(payload, exporters, out_dir)` |
| Run-log dock | engine logging callback → `store.runLogAppended` signal |

`Engine` is constructed once per project and lives on the main thread;
mutating methods are cheap (they only update the manifest). Heavy
methods (`import_sessions`, `run_session`, `export`) accept an optional
progress callback and are dispatched through `TaskRunner`.

---

## 7. Background tasks & progress UX

```python
class TaskRunner(QObject):
    def submit(self, task_id: str, fn: Callable, *args, **kwargs): ...
    # emits taskProgress(task_id, percent) and taskFinished(task_id, result)
```

- Uses `QThreadPool.globalInstance()` for I/O-bound tasks and
  delegates CPU-heavy work to the engine's `ProcessPoolExecutor` (the
  engine streams `(percent, message)` back to the runner).
- A toolbar **Cancel** action sends a cooperative cancel signal; long
  operations check it between sessions.
- Per-task progress is shown in the status bar; failed tasks raise a
  modal with `error.remediation` plus a "Copy details" button (copies
  full traceback to clipboard).

---

## 8. Error messages & user feedback

### 8.1 Severity → UI affordance

| Severity | UI element |
|---|---|
| `info` | toast in status bar (3 s) |
| `warning` | yellow banner at top of page; persistent until dismissed |
| `error` | modal dialog blocking page advance; includes remediation + Copy details |

### 8.2 Validation feedback per page

Every page exposes `is_valid: bool` and `validation_errors: list[str]`.
The wizard sidebar shows a tick / cross / warning icon per stage. Stage
selection is allowed in either direction; the Run action requires all
stages green.

---

## 9. Theming & accessibility (NFR-7)

- Two themes (light + dark) via Qt stylesheets; system-preference
  detection on startup.
- All controls keyboard-navigable (`Tab` order curated per page).
- Screen-reader labels via `setAccessibleName` / `setAccessibleDescription`.
- Contrast palette validated against WCAG AA at design time.
- All units (`s`, `cm`, `BL/s`) shown in labels and tooltips.

---

## 10. Future UI extension points

| Hook | Use case |
|---|---|
| `WizardRegistry.register(page_cls, after="zones")` | drop in a custom stage (e.g. a stats page for v1.2) |
| `MetricConfigWidgetRegistry` | metric plug-ins ship a per-metric config widget that the metrics tab renders automatically |
| `ExporterRegistry` | exporter plug-ins auto-populate the Export tab |
| Theme plug-ins | additional QSS files discoverable via entry point |

---

## 11. Open questions (UI-specific)

- Plot library: matplotlib (already in scientific deps) vs. pyqtgraph
  (better interactivity). Current pick: matplotlib for static plots,
  pyqtgraph for the trajectory canvas where pan/zoom is wanted.
- Whether the polygon canvas allows arbitrary zone naming or constrains
  to a fixed level list ("main", "secondary") to stay compatible with
  the existing pipeline column names. Current pick: free-text name +
  `level` dropdown with the two defaults + "custom".
- Async strategy: `qasync` integration for first-class `async def`
  engine methods vs. `TaskRunner`-only. Current pick: `TaskRunner`-only
  in MVP to keep the surface simple; `qasync` is a v1.1 enhancement.
