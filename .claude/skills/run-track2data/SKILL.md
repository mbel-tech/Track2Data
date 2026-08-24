---
name: run-track2data
description: Run, launch, build, screenshot, or drive the Track2Data desktop GUI, CLI, or engine. Use when asked to start the app, take a screenshot of a wizard screen, smoke-test the UI, reproduce a GUI bug, or invoke the pipeline headlessly.
---

# Running Track2Data

Track2Data is a PySide6 desktop app (`app/` + `ui/`) over a Qt-free Python
engine (`track2data/`), plus a Click CLI. Three surfaces, three ways in:

| Surface | How to drive it |
|---|---|
| **GUI** | `.claude/skills/run-track2data/driver.py` — in-process, headless, screenshots |
| **CLI** | the `track2data` console script |
| **Engine** | plain `import track2data` — no Qt needed |

All paths below are relative to the repo root.

## Prerequisites

```bash
pip install -e ".[dev]"
```

Installs PySide6, the engine, both console scripts, and pytest. No system
packages are needed on Windows. On Linux the Qt platform libraries are
also required — CI installs them like this:

```bash
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libgl1
```

## Run the GUI (agent path)

**Use the driver, not `python -m app.main`.** It runs the real
`MainWindow` in-process under the `offscreen` Qt platform, so it needs no
display and cannot be defeated by window placement (see Gotchas).

```bash
# full smoke: create a project, screenshot all 10 wizard pages, verify state
python .claude/skills/run-track2data/driver.py smoke
```

Writes to `artifacts/gui-smoke/` (gitignored) and exits non-zero if the
window fails to paint or an unexpected modal appears. This is the fastest
way to confirm the GUI is not broken.

```bash
# list wizard page indices
python .claude/skills/run-track2data/driver.py pages

# screenshot one page, by name or index
python .claude/skills/run-track2data/driver.py shot --page export -o /tmp/export.png
python .claude/skills/run-track2data/driver.py shot --page 7 -o /tmp/processing.png
```

The stack has **10** pages even though the sidebar shows 7 numbered
stages — `pages` prints the mapping.

### Interactive driving

For a flow the subcommands don't cover, pipe commands into the REPL:

```bash
printf 'goto processing\nstate\nshot /tmp/p.png\nquit\n' \
  | python .claude/skills/run-track2data/driver.py repl
```

Commands: `goto <page>`, `click <button-label>`, `type <text>`,
`shot <path>`, `state`, `pages`, `quit`. `click` matches button text
case-insensitively as a substring, so `click Create Project` finds
`Create Project` and `click Open` finds `Open Project…`.

**Always look at the screenshot you took.** The driver catches a blank
frame, but not a wrong one.

## Run the GUI (human path)

```bash
python -m app.main
```

Opens a real window. Useless headless, and unhelpful to an agent — it
blocks until the window is closed and gives you nothing to click with.

## Run the CLI

```bash
track2data --help
track2data list-metrics
track2data new my_experiment --out /tmp/my_experiment.t2d.json
track2data validate /tmp/my_experiment.t2d.json   # exit 1 until sessions+metrics exist
track2data run /tmp/my_experiment.t2d.json --out-dir /tmp/out
```

## Direct invocation (engine only)

The engine imports without PySide6 — the fastest path for a change that
doesn't touch the GUI:

```bash
python -c "
from track2data.api import Engine
from track2data import __version__
print('engine OK', __version__)
"
```

## Test

```bash
python -m pytest tests/ -m "not r_parity and not corpus_local" -q
python -m ruff check .
```

`corpus_local` tests need the 70-session idtracker.ai corpus, which is
gitignored and absent on most machines; they skip automatically.

Workflow edits are linted separately — the repo has a pre-commit
`actionlint` hook that degrades to a warning if the binary is missing:

```bash
actionlint .github/workflows/release.yml .github/workflows/ci.yml
```

## Gotchas

Each of these cost real time to find. None is guessable from the source.

- **Qt 6 ships no fonts.** Under `QT_QPA_PLATFORM=offscreen` every glyph
  renders as a tofu box (□□□□) — the layout is pixel-perfect and the text
  is entirely unreadable, which looks like a font-stack bug in the app
  rather than a missing font directory. Fix is `QT_QPA_FONTDIR` pointing
  at the OS font dir; **the driver sets this automatically** per platform.
  Set it yourself if you drive Qt without the driver.

- **A window on a secondary monitor can sit at negative desktop
  coordinates.** Screenshotting the *primary screen* then returns a frame
  with no app in it, which reads as "the app failed to launch" when it
  launched perfectly. Do not capture by screen or by window handle — the
  driver uses `QWidget.grab()`, which renders through Qt's paint system
  and never touches a physical display.

- **A modal `QMessageBox` hangs forever with no traceback.** It spins its
  own event loop waiting for a click that, headless, never comes: no
  output, no error, just a wedged process. The driver installs a guard
  that intercepts `warning`/`critical`/`information`/`question`/`exec`,
  prints `[modal intercepted]`, and returns a default. Keep it if you
  write your own harness.

- **The chosen project directory lives on the `ProjectScreen` widget, not
  on the store.** `_create_project()` validates `screen._selected_dir`
  before it ever touches `ProjectStore`, so setting `store._project_dir`
  leaves validation failing and pops a modal. Set `_selected_dir` — that
  is what the `Browse…` callback assigns.

- **`QPixmap.save()` returns `False` instead of raising** when the parent
  directory doesn't exist — silently producing no file. Qt also resolves a
  Unix-style `/tmp/x.png` to `C:\tmp\x.png` on Windows, which usually
  doesn't exist. Check the return value; the driver does.

- **`QT_QPA_PLATFORM` must be set before PySide6 is imported.** Setting it
  after the first `import PySide6` has no effect.

- **`python -m track2data.cli` prints nothing** — `cli.py` has no
  `__main__` guard. Use the `track2data` console script.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Driver produces no output and never exits | An unexpected modal. The guard should print `[modal intercepted]`; if you bypassed the driver, that's the hang. |
| Screenshot is all boxes (□□□□) | `QT_QPA_FONTDIR` unset or pointing at a missing directory. |
| `SystemExit: ... looks blank (N distinct colours)` | The window never painted. Confirm `.show()` ran and events were pumped. |
| `SystemExit: QPixmap.save() refused to write ...` | Parent directory missing, or a Unix path on Windows. |
| `no button matching 'X'; page has: [...]` | Wrong page, or the label changed — the error lists the real button texts. |
| Qt warns `Cannot find font directory .../PySide6/lib/fonts` | Harmless once `QT_QPA_FONTDIR` is set; Qt logs it regardless. |
