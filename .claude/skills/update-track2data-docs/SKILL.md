---
name: update-track2data-docs
description: Update Track2Data's front-facing GitHub documentation (README, docs/guide/USER_GUIDE.md, the PDF guide, CHANGELOG-derived content) after code changes. Retakes the guide screenshots whenever a UI feature changed and rebuilds the PDF. Use when asked to refresh/update/sync the docs or user guide, after a UI or behaviour change, or before a release.
---

# Update Track2Data front-facing docs

The public docs must match the app as shipped. This skill finds what changed since the guide was
last updated, rewrites the affected text, **retakes every screenshot a UI change could touch**, and
rebuilds the PDF.

Front-facing files (all paths relative to the repo root):

| File | Role |
|---|---|
| `README.md` | install, links, one-line feature summary |
| `docs/guide/USER_GUIDE.md` | the user guide: single source of truth, one chapter per wizard screen |
| `docs/guide/images/*.png` | screenshots, generated from the real app |
| `docs/guide/Track2Data_User_Guide.pdf` | PDF edition, built from the Markdown |
| `CHANGELOG.md` | input here, not output (only fix it if an entry is missing or wrong) |
| `CONTRIBUTING.md`, `docs/*.md` | touch only if the change makes them wrong |

Copyright and PDF author stay **Martina Bellio, 2026**. Never put a model name in any file or commit.

## Workflow

### 1. Find what changed

```bash
git fetch origin main && git status   # work on the designated branch, from latest main
python .claude/skills/update-track2data-docs/changes.py
```

It prints the baseline (last commit touching `USER_GUIDE.md`), commits since, CHANGELOG lines added,
UI files changed with the **chapter and screenshots they affect**, and engine files changed.
Then read what the script cannot judge:

- `CHANGELOG.md` `[Unreleased]` in full: every Added / Changed / Removed / Fixed line is a candidate
  doc edit. Skip purely internal entries (tests, CI, refactors).
- The diffs of the changed UI files (`git diff <baseline>..HEAD -- ui app`): new buttons, renamed
  labels, new options, moved controls, removed features.
- `docs/METRICS_SPEC.md`, `docs/USER_WORKFLOW.md` and `PRD.md` when metrics, outputs or workflow
  changed, so the guide agrees with them.
- `README.md` for stale install steps, feature lists or links.

Write a short checklist of doc edits before touching files. If nothing user-visible changed, say so
and stop: do not rebuild the PDF or churn images for nothing.

### 2. Run the app and look before you write

Use the `run-track2data` skill's driver to see changed screens
(`python .claude/skills/run-track2data/driver.py shot --page <name> -o <png>`). Open the screenshot
and read it. Quote labels exactly as they appear in the UI (button text, tab names, menu paths).
Do not document from the diff alone.

### 3. Update the Markdown guide

Edit `docs/guide/USER_GUIDE.md` only (never recreate per-page files).

- Keep the chapter structure; chapters are tested to match the wizard pages (`ui/store/stage_status.py`).
- Figures are raw HTML so they render on GitHub and in the PDF:

  ```html
  <figure>
  <img src="images/NAME.png" alt="Short alt text">
  <figcaption><b>Figure N.</b> Caption sentence.</figcaption>
  </figure>
  ```

  Place each figure next to the text it illustrates and refer to it in the prose ("Figure 7 shows…").
  **Renumber all figures** in order if you add or remove one, and fix "Figure N" mentions in prose.
- Keep links to other sections as in-document anchors (`#2-sessions`). Links leaving the guide use
  `../../` relative paths; the PDF build turns them into GitHub URLs.
- Update the contents list, the "How the workflow is organised" table, quick start, output-file
  tables and troubleshooting rows when behaviour changed. Add a troubleshooting row for every new
  user-facing error message.
- Style: plain, second-person, short sentences; bold for UI labels; no marketing words.
- Update `README.md` if install steps, feature summary or doc links changed.

### 4. Retake screenshots

Retake whenever a UI feature changed: a screen's layout, labels, options, default values, colours,
menu or sidebar. The script's mapping tells you which prefixes are affected; **shared widgets,
store/badges and `app/` changes affect every screen, so retake all**.

```bash
pip install -e ".[dev,ui]"     # once
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libgl1   # Linux, if Qt libs are missing
python scripts/generate_guide_screenshots.py
```

The script regenerates all images deterministically, so always run it whole, then look at **every**
changed PNG (`git status docs/guide/images`). Check that the new feature is actually visible. For a
new screen state or option the script does not reach, extend `scripts/generate_guide_screenshots.py`
(add a `shot("NN-name")` call after driving the UI into that state) and reference the new image from
the guide. Every committed image must be used by the guide, and every image the guide shows must be
written by the script (`tests/test_docs/test_guide.py` enforces both).
If an image is unchanged byte-for-byte nothing needs committing; do not hand-edit PNGs.

### 5. Rebuild the PDF

```bash
pip install pypdf              # plus pandoc and Chromium/Chrome on PATH ($CHROME or --chrome)
python scripts/build_user_guide.py
```

Then **look at it**: render a few pages (`pdftoppm -r 50 -png docs/guide/Track2Data_User_Guide.pdf /tmp/p`)
and check figures sit next to their text, no heading is stranded at a page bottom, tables are not
cut, and the front page is right. Confirm metadata:

```bash
python -c "from pypdf import PdfReader as R; print(R('docs/guide/Track2Data_User_Guide.pdf').metadata)"
```

Author must be `Martina Bellio`, Copyright `© 2026 Martina Bellio`.

### 6. Verify, commit, push

```bash
python -m pytest tests/test_docs -q
ruff check .
```

If a user-visible change was documented, make sure `CHANGELOG.md` mentions the doc refresh only when
it is itself notable (usually not). Commit Markdown, images and PDF **together**, so the PDF never
lags the source. Push to the designated branch and open a draft PR following the repo's PR
conventions.

## Rules

- Never document features that are not in the code; verify in the running app.
- Never leave the PDF or screenshots stale relative to `USER_GUIDE.md`.
- Do not edit generated PNGs or the PDF by hand.
- If the app cannot be run (missing Qt libs, no Chromium), say exactly what is missing instead of
  shipping unverified screenshots or an unrebuilt PDF.
