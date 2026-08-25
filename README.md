# Track2Data

Open-source desktop application that turns `idtracker.ai` output folders into analysis-ready behavioural datasets.

See [PRD.md](PRD.md) for the full product requirements. Design and workflow docs live in [docs/](docs/):

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased M1–M5 implementation plan, module build order, and exit criteria.
- [`docs/TECHNICAL_SPEC.md`](docs/TECHNICAL_SPEC.md) — **read first.** System-level technical contract: tech stack, architecture, project file format, build/packaging, testing pyramid, plug-in compatibility policy.
- [`docs/USER_WORKFLOW.md`](docs/USER_WORKFLOW.md) — the end-to-end user journey through the wizard, wireframes, validation messages, and save/resume logic.
- [`docs/UI_DESIGN.md`](docs/UI_DESIGN.md) — PySide6 wizard architecture and engine bindings.
- [`docs/ENGINE_DESIGN.md`](docs/ENGINE_DESIGN.md) — pure-Python `track2data` engine: layout, models, plug-in surface.
- [`docs/IDTRACKERAI_FORMAT_ANALYSIS.md`](docs/IDTRACKERAI_FORMAT_ANALYSIS.md) — gap analysis of the current reader against the official idtracker.ai 6.0.14 docs and a 70-session real-data corpus; cross-version normalisation strategy.
- [`docs/METRICS_SPEC.md`](docs/METRICS_SPEC.md) — canonical, implementation-ready specification for every behavioural metric (formulas, inputs, outputs, units, citations) plus the UI info-button architecture.
- [`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md) — how to enable signed releases on each OS, what it costs, and why the first release is necessarily unsigned.

Contributing: see [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, TDD workflow, branch policy, and how to run tests.

## Installation

**Engine only** (CLI + headless processing, no PySide6):
```bash
pip install -e "."
track2data --help
```

**Desktop GUI** (adds PySide6):
```bash
pip install -e ".[ui]"
track2data-gui
# or: python -m app.main
```

**Pre-built binaries** (no Python install needed): download the latest
release for your OS from the [Releases page](https://github.com/mbel-tech/Track2Data/releases).
These ship unsigned, so your OS will warn before the first run. That is
expected, and it is not a sign of a corrupted download — the free
code-signing programme for open-source projects requires a project to
have already published a release, so the first one cannot be signed.
See [`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md) for the full picture
and the plan for signing later releases.

- **Windows**: SmartScreen shows "Windows protected your PC". Click
  **More info**, then **Run anyway**.
- **macOS**: Gatekeeper blocks the app on first launch. Right-click (or
  Control-click) `Track2Data.app` → **Open** → **Open** again in the
  dialog. (A plain double-click will just say the app is damaged/can't
  be opened — that's Gatekeeper, not a broken download.)
- **Linux**: mark the `.AppImage` executable before running:
  `chmod +x Track2Data-x86_64.AppImage`.

Every release includes a `SHA256SUMS.txt` alongside the binaries —
verify your download with `sha256sum -c SHA256SUMS.txt` (or `shasum -a
256 -c` on macOS) before running past the warning above.

## Development setup

```bash
pip install -e ".[dev]"
pytest                                  # all tests (engine + UI smoke)
pytest tests/ -m "not r_parity" -v     # skip R-parity (no fixture data needed)
pytest tests/test_app_smoke.py -v      # Phase 1 smoke tests only
ruff check .                            # lint
```

## Running the app

```bash
# After pip install -e ".[ui]":
track2data-gui

# Or directly:
python -m app.main
```

Opens the full import → calibrate → zones → metadata → metrics →
process → preview → export wizard, wired end to end to the
`track2data` engine.

## Requesting a metric

Track2Data computes 33 built-in metrics — individual, group, zone, and
tracking-quality diagnostics. Every one carries a scientific reference,
published in [`docs/METRIC_REFERENCES.csv`](docs/METRIC_REFERENCES.csv)
and shown in the app's ⓘ info dialog.

If a measure you need is missing,
[open a metric request](../../issues/new?template=metric_request.yml).
The form asks for three things: the metric's level (individual, group,
zone, or diagnostic), its name, and **a DOI** for the paper defining it.
The DOI is required because it becomes that metric's row in the
references list — a proposal with no citable source can't become one.

For the full definition of every existing metric, see
[`docs/METRICS_SPEC.md`](docs/METRICS_SPEC.md); for how to add one, see
[`CONTRIBUTING.md` §7](CONTRIBUTING.md).
